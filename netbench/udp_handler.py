"""
netbench.udp_handler
~~~~~~~~~~~~~~~~~~~~
UDP datagram benchmark client and receiver session handlers.
Implements sequence-numbered datagram bursts, out-of-order and packet loss
accounting, RFC 3550 interarrival jitter measurement, and RTT echo tests.

Viva / Networking Principles:
1. Datagram Framing: UDP preserves message boundaries natively (`SOCK_DGRAM`).
   Each `recvfrom()` call returns a complete datagram or raises an error.
   The 20-byte NetBench header is prepended to every datagram.
2. Unreliable Transport: UDP does not provide ACKs, retransmissions, or flow
   control. Datagrams may be dropped, duplicated, or reordered by kernel buffer
   overflows or network congestion.
3. Measurement Window & Bounded Drain: When the client signals `CONTROL_END`,
   the receiver enters a bounded drain window (e.g., 200ms) to capture any
   in-flight datagrams before finalizing loss calculations.
"""

import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from netbench.metrics import (
    BenchmarkMetric,
    calculate_rfc3550_jitter,
    calculate_throughput,
    create_benchmark_metric,
)
from netbench.protocol import (
    DEFAULT_UDP_PORT,
    HEADER_SIZE,
    MAX_UDP_PAYLOAD_SIZE,
    PacketHeader,
    PacketType,
    ProtocolError,
    SequenceTracker,
    pack_packet,
    unpack_header,
    unpack_packet,
)

logger = logging.getLogger(__name__)


class UDPReceiverSession:
    """
    Server-side listener for receiving UDP benchmark bursts and calculating
    empirical loss, delivery rate, out-of-order count, and RFC 3550 jitter.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_UDP_PORT):
        self.host = host
        self._requested_port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Enable port reuse for clean restarts
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self._requested_port))
        # Store the actual bound port (crucial when port=0 is used for ephemeral test ports)
        self.port = self.sock.getsockname()[1]
        self.tracker = SequenceTracker()

    def receive_burst(
        self,
        expected_count: int,
        idle_timeout: float = 2.0,
        drain_timeout: float = 0.3,
    ) -> Tuple[SequenceTracker, Dict[str, Any]]:
        """
        Listen for a burst of `expected_count` datagrams until CONTROL_END or timeout.

        :param expected_count: Total datagrams expected from sender
        :param idle_timeout: Maximum time to wait for initial datagrams (seconds)
        :param drain_timeout: Bounded wait time to collect in-flight packets after CONTROL_END
        :return: Tuple of (SequenceTracker instance, summary dictionary)
        """
        self.tracker.reset()
        self.sock.settimeout(idle_timeout)

        payload_bytes_received = 0
        t_first: Optional[float] = None
        t_last: Optional[float] = None
        control_end_received = False

        start_listen_time = time.perf_counter()

        while True:
            try:
                raw_data, client_addr = self.sock.recvfrom(65536)
            except (socket.timeout, TimeoutError):
                # Idle timeout expired or drain period ended
                break
            except (ConnectionResetError, ConnectionError):
                # On Windows, ICMP Port Unreachable causes WSAECONNRESET; non-fatal
                continue
            except OSError as e:
                logger.warning("UDP socket read error: %s", e)
                break

            now = time.perf_counter()

            if len(raw_data) < HEADER_SIZE:
                logger.debug("Ignoring truncated datagram of %d bytes", len(raw_data))
                continue

            try:
                header = unpack_header(raw_data[:HEADER_SIZE])
            except ProtocolError as e:
                logger.debug("Ignoring malformed UDP datagram header: %s", e)
                continue

            payload = raw_data[HEADER_SIZE:HEADER_SIZE + header.payload_length]

            if header.packet_type == PacketType.CONTROL_START:
                self.tracker.reset()
                payload_bytes_received = 0
                t_first = now
                t_last = now

            elif header.packet_type == PacketType.DATA:
                if t_first is None:
                    t_first = now
                t_last = now

                is_unique = self.tracker.record_packet(
                    sequence_number=header.sequence_number,
                    send_time=header.timestamp,
                    arrival_time=now,
                )
                if is_unique:
                    payload_bytes_received += len(payload)

            elif header.packet_type == PacketType.CONTROL_END:
                control_end_received = True
                # Sender declared dispatch finished; switch to short drain timeout
                self.sock.settimeout(drain_timeout)

            elif header.packet_type == PacketType.ECHO_REQUEST:
                # Echo back to sender
                reply = pack_packet(
                    packet_type=PacketType.ECHO_REPLY,
                    sequence_number=header.sequence_number,
                    payload=payload,
                    timestamp=header.timestamp,
                )
                try:
                    self.sock.sendto(reply, client_addr)
                except OSError:
                    pass

        # Calculate transfer duration
        if t_first is not None and t_last is not None and t_last > t_first:
            duration = t_last - t_first
        elif t_first is not None:
            duration = max(0.0001, time.perf_counter() - t_first)
        else:
            duration = 0.0

        # Calculate RFC 3550 jitter from arrival history
        history = self.tracker.arrival_history
        if len(history) >= 2:
            send_times = [item[1] for item in history]
            arrival_times = [item[2] for item in history]
            jitter_ms = calculate_rfc3550_jitter(send_times, arrival_times)
        else:
            jitter_ms = 0.0

        loss_count = self.tracker.loss_count(expected_count)
        loss_rate = self.tracker.loss_rate_percent(expected_count)
        delivery_rate = self.tracker.delivery_rate_percent(expected_count)
        throughput_bps, throughput_mbps = calculate_throughput(payload_bytes_received, duration)

        summary = {
            "expected_count": expected_count,
            "packets_received": self.tracker.unique_received,
            "total_datagrams_received": self.tracker.total_received,
            "duplicate_count": self.tracker.duplicate_count,
            "out_of_order_count": self.tracker.out_of_order_count,
            "missing_sequences": self.tracker.missing_sequences(expected_count),
            "loss_count": loss_count,
            "loss_rate_percent": loss_rate,
            "delivery_rate_percent": delivery_rate,
            "payload_bytes_received": payload_bytes_received,
            "duration_seconds": duration,
            "throughput_mbps": throughput_mbps,
            "jitter_ms": jitter_ms,
            "control_end_received": control_end_received,
        }

        return self.tracker, summary

    def serve_echo(self, stop_event: threading.Event, timeout: float = 0.2) -> None:
        """
        Continuously listen for ECHO_REQUEST datagrams and echo them back as ECHO_REPLY.
        Runs until `stop_event` is signaled.

        :param stop_event: Threading event to terminate the echo listener cleanly
        :param timeout: Internal socket timeout to check stop_event periodically
        """
        self.sock.settimeout(timeout)
        while not stop_event.is_set():
            try:
                raw_data, client_addr = self.sock.recvfrom(65536)
            except (socket.timeout, TimeoutError):
                continue
            except (ConnectionResetError, ConnectionError):
                continue
            except OSError:
                break

            if len(raw_data) < HEADER_SIZE:
                continue

            try:
                header = unpack_header(raw_data[:HEADER_SIZE])
            except ProtocolError:
                continue

            if header.packet_type == PacketType.ECHO_REQUEST:
                payload = raw_data[HEADER_SIZE:HEADER_SIZE + header.payload_length]
                reply = pack_packet(
                    packet_type=PacketType.ECHO_REPLY,
                    sequence_number=header.sequence_number,
                    payload=payload,
                    timestamp=header.timestamp,
                )
                try:
                    self.sock.sendto(reply, client_addr)
                except OSError:
                    pass

    def close(self) -> None:
        """Cleanly close the underlying UDP socket."""
        try:
            self.sock.close()
        except OSError:
            pass


class UDPBenchmarkClient:
    """
    Client for transmitting UDP datagram bursts and measuring RTT ping-pong latency.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_UDP_PORT, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def run_burst_test(
        self,
        payload_size: int,
        packet_count: int,
        delay_between_packets: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Transmit `packet_count` sequence-numbered datagrams to the UDP receiver.

        :param payload_size: Byte size of payload per datagram (must be <= MAX_UDP_PAYLOAD_SIZE)
        :param packet_count: Total datagrams to transmit
        :param delay_between_packets: Optional throttling delay between datagrams (seconds)
        :return: Client dispatch statistics dictionary
        :raises ValueError: if payload_size exceeds IPv4 UDP limit or is negative
        """
        if payload_size < 0 or payload_size > MAX_UDP_PAYLOAD_SIZE:
            raise ValueError(
                f"Payload size {payload_size} must be between 0 and {MAX_UDP_PAYLOAD_SIZE} bytes"
            )
        if packet_count < 0:
            raise ValueError(f"Packet count cannot be negative: {packet_count}")
        if packet_count == 0:
            return {
                "packets_sent": 0,
                "payload_bytes_sent": 0,
                "send_duration_seconds": 0.0,
            }

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = b"U" * payload_size
        packets_sent = 0

        try:
            t_start = time.perf_counter()

            # Transmit CONTROL_START frame to signal beginning of burst
            start_packet = pack_packet(
                packet_type=PacketType.CONTROL_START,
                sequence_number=0,
                payload=b"",
                timestamp=t_start,
            )
            sock.sendto(start_packet, (self.host, self.port))

            for seq in range(packet_count):
                t_send = time.perf_counter()
                packet = pack_packet(
                    packet_type=PacketType.DATA,
                    sequence_number=seq,
                    payload=payload,
                    timestamp=t_send,
                )
                sock.sendto(packet, (self.host, self.port))
                packets_sent += 1

                if delay_between_packets > 0:
                    time.sleep(delay_between_packets)

            # Transmit CONTROL_END frame (duplicated to protect against single-packet drop)
            end_packet = pack_packet(
                packet_type=PacketType.CONTROL_END,
                sequence_number=packet_count,
                payload=b"",
                timestamp=time.perf_counter(),
            )
            for _ in range(2):
                sock.sendto(end_packet, (self.host, self.port))

            t_end = time.perf_counter()

        finally:
            sock.close()

        send_duration = max(0.0, t_end - t_start)
        return {
            "packets_sent": packets_sent,
            "payload_bytes_sent": packets_sent * payload_size,
            "send_duration_seconds": send_duration,
        }

    def run_latency_test(
        self,
        payload_size: int = 64,
        ping_count: int = 50,
        timeout: float = 1.0,
    ) -> BenchmarkMetric:
        """
        Execute request-response round-trip ping-pong over UDP to measure RTT statistics.

        Viva Note:
        Unacknowledged or dropped UDP pings time out and are accounted as lost,
        directly demonstrating UDP's lack of delivery guarantees.

        :param payload_size: Size of echo payload (bytes)
        :param ping_count: Number of ping iterations
        :param timeout: Timeout per ping iteration (seconds)
        :return: BenchmarkMetric instance with RTT statistics
        """
        if ping_count <= 0:
            return create_benchmark_metric(
                protocol="UDP",
                payload_size_bytes=payload_size,
                packet_count=0,
                packets_sent=0,
                packets_received=0,
                duration_seconds=0.0,
                rtt_samples_ms=[],
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        payload = b"P" * payload_size
        rtt_samples_ms: List[float] = []
        packets_sent = 0
        packets_received = 0

        try:
            t_test_start = time.perf_counter()

            for seq in range(ping_count):
                t_send = time.perf_counter()
                packet = pack_packet(
                    packet_type=PacketType.ECHO_REQUEST,
                    sequence_number=seq,
                    payload=payload,
                    timestamp=t_send,
                )
                sock.sendto(packet, (self.host, self.port))
                packets_sent += 1

                deadline = time.perf_counter() + timeout
                while True:
                    remaining = max(0.001, deadline - time.perf_counter())
                    sock.settimeout(remaining)
                    try:
                        raw_reply, _ = sock.recvfrom(65536)
                        t_recv = time.perf_counter()
                    except (socket.timeout, TimeoutError):
                        break
                    except (ConnectionResetError, ConnectionError):
                        continue

                    if len(raw_reply) >= HEADER_SIZE:
                        try:
                            header = unpack_header(raw_reply[:HEADER_SIZE])
                            if (
                                header.packet_type == PacketType.ECHO_REPLY
                                and header.sequence_number == seq
                            ):
                                rtt_ms = (t_recv - t_send) * 1000.0
                                rtt_samples_ms.append(rtt_ms)
                                packets_received += 1
                                break
                        except ProtocolError:
                            continue

            t_test_end = time.perf_counter()

        finally:
            sock.close()

        total_duration = max(0.0, t_test_end - t_test_start)

        return create_benchmark_metric(
            protocol="UDP",
            payload_size_bytes=payload_size,
            packet_count=ping_count,
            packets_sent=packets_sent,
            packets_received=packets_received,
            duration_seconds=total_duration,
            rtt_samples_ms=rtt_samples_ms,
        )


def build_udp_metric_from_summary(
    client_stats: Dict[str, Any],
    receiver_summary: Dict[str, Any],
    payload_size: int,
) -> BenchmarkMetric:
    """
    Combine client-side send statistics with receiver-side sequence tracking
    results to construct a unified BenchmarkMetric.

    :param client_stats: Output from UDPBenchmarkClient.run_burst_test()
    :param receiver_summary: Output from UDPReceiverSession.receive_burst()
    :param payload_size: Configured per-packet payload size in bytes
    :return: BenchmarkMetric record
    """
    packets_sent = client_stats.get("packets_sent", 0)
    packets_received = receiver_summary.get("packets_received", 0)
    duration = receiver_summary.get("duration_seconds", client_stats.get("send_duration_seconds", 0.0))
    jitter_ms = receiver_summary.get("jitter_ms")

    return create_benchmark_metric(
        protocol="UDP",
        payload_size_bytes=payload_size,
        packet_count=packets_sent,
        packets_sent=packets_sent,
        packets_received=packets_received,
        duration_seconds=duration,
        jitter_ms=jitter_ms,
    )
