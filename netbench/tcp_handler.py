"""
netbench.tcp_handler
~~~~~~~~~~~~~~~~~~~~
TCP socket benchmark client and server session handlers.
Handles stream-oriented connection lifecycle, framed message boundaries over
TCP byte-streams, throughput benchmarking, and round-trip latency measurements.

Viva / Networking Principles:
1. Stream Framing: TCP is a continuous byte stream (`SOCK_STREAM`) with no
   application-level message boundaries. A single `recv()` call can return any
   number of bytes. We use our 20-byte fixed header (`HEADER_SIZE`) containing
   `payload_length` and `recv_exact()` to enforce discrete application frames.
2. Nagle's Algorithm (`TCP_NODELAY`): By default, TCP delays small packets to
   aggregate them into larger segments. In latency benchmarks, setting
   `TCP_NODELAY = 1` disables Nagle's algorithm to obtain true round-trip times.
3. Reliability: TCP kernel retransmits dropped segments. At the application layer,
   packet loss is 0.0% unless the connection is broken.
"""

import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

from netbench.metrics import BenchmarkMetric, create_benchmark_metric
from netbench.protocol import (
    DEFAULT_TCP_PORT,
    HEADER_SIZE,
    MAX_TCP_PAYLOAD_SIZE,
    PacketHeader,
    PacketType,
    ProtocolError,
    pack_header,
    pack_packet,
    unpack_header,
)

logger = logging.getLogger(__name__)


def recv_exact(sock: socket.socket, num_bytes: int, timeout: Optional[float] = None) -> bytes:
    """
    Read exactly `num_bytes` from a stream socket, handling chunked fragments and EOF.

    :param sock: Connected TCP socket
    :param num_bytes: Exact number of bytes to accumulate
    :param timeout: Optional temporary socket timeout (seconds)
    :return: Exactly `num_bytes` bytes, or `b""` if EOF encountered before any byte read
    :raises ConnectionResetError: If EOF encountered after partial bytes received
    :raises TimeoutError: If socket timeout expires while waiting for data
    :raises ValueError: If num_bytes is negative
    """
    if num_bytes < 0:
        raise ValueError(f"num_bytes cannot be negative: {num_bytes}")
    if num_bytes == 0:
        return b""

    original_timeout = sock.gettimeout()
    if timeout is not None:
        sock.settimeout(timeout)

    buffer = bytearray()
    try:
        while len(buffer) < num_bytes:
            chunk = sock.recv(num_bytes - len(buffer))
            if not chunk:
                # Socket EOF reached
                if len(buffer) == 0:
                    return b""
                raise ConnectionResetError(
                    f"Connection closed prematurely by peer: expected {num_bytes} bytes, received {len(buffer)} bytes"
                )
            buffer.extend(chunk)
        return bytes(buffer)
    except socket.timeout as e:
        raise TimeoutError(f"Socket timed out while waiting for {num_bytes} bytes: {e}") from e
    finally:
        if timeout is not None:
            sock.settimeout(original_timeout)


def read_framed_packet(
    sock: socket.socket,
    timeout: Optional[float] = None,
) -> Optional[Tuple[PacketHeader, bytes]]:
    """
    Read one complete NetBench framed message (20-byte header + payload) from a TCP stream.

    :param sock: Connected TCP socket
    :param timeout: Optional socket timeout
    :return: Tuple of (PacketHeader, payload_bytes), or None on clean EOF
    :raises ProtocolError: If header validation fails or payload exceeds limits
    :raises ConnectionResetError: If connection aborts during frame transmission
    """
    raw_header = recv_exact(sock, HEADER_SIZE, timeout=timeout)
    if not raw_header:
        return None  # Clean connection closure between frames

    header = unpack_header(raw_header)

    if header.payload_length > MAX_TCP_PAYLOAD_SIZE:
        raise ProtocolError(
            f"Payload length {header.payload_length} exceeds maximum safety limit {MAX_TCP_PAYLOAD_SIZE}"
        )

    payload = recv_exact(sock, header.payload_length, timeout=timeout)
    if len(payload) != header.payload_length:
        raise ConnectionResetError(
            f"Incomplete payload: expected {header.payload_length} bytes, received {len(payload)} bytes"
        )

    return header, payload


def send_framed_packet(
    sock: socket.socket,
    packet_type: int,
    sequence_number: int,
    payload: bytes = b"",
    timestamp: float = 0.0,
) -> None:
    """
    Serialize and transmit a complete framed message over a TCP stream.

    :param sock: Connected TCP socket
    :param packet_type: PacketType enum value
    :param sequence_number: Sequence number
    :param payload: Binary payload content
    :param timestamp: Monotonic timestamp
    """
    raw_packet = pack_packet(
        packet_type=packet_type,
        sequence_number=sequence_number,
        payload=payload,
        timestamp=timestamp,
    )
    sock.sendall(raw_packet)


class TCPServerSession:
    """
    Handles a single incoming TCP client connection for throughput benchmarking
    and RTT echo measurements.
    """

    def __init__(self, client_sock: socket.socket, client_addr: tuple, timeout: float = 10.0):
        self.client_sock = client_sock
        self.client_addr = client_addr
        self.timeout = timeout
        self.client_sock.settimeout(timeout)

    def handle(self) -> Dict[str, Any]:
        """
        Process the client session loop until CONTROL_END or client disconnect.

        :return: Session summary dictionary containing packets_received,
                 payload_bytes_received, and transfer duration.
        """
        payload_bytes_received = 0
        packets_received = 0
        t_first: Optional[float] = None
        t_last: Optional[float] = None

        try:
            while True:
                frame = read_framed_packet(self.client_sock, timeout=self.timeout)
                if frame is None:
                    break  # Client closed connection cleanly

                header, payload = frame
                now = time.perf_counter()

                if header.packet_type == PacketType.DATA:
                    packets_received += 1
                    payload_bytes_received += len(payload)
                    if t_first is None:
                        t_first = now
                    t_last = now

                elif header.packet_type == PacketType.ECHO_REQUEST:
                    # RTT Echo Mode: Bounce identical frame back to sender
                    send_framed_packet(
                        sock=self.client_sock,
                        packet_type=PacketType.ECHO_REPLY,
                        sequence_number=header.sequence_number,
                        payload=payload,
                        timestamp=header.timestamp,  # Preserve sender's original timestamp
                    )

                elif header.packet_type == PacketType.CONTROL_END:
                    # Acknowledge benchmark completion
                    send_framed_packet(
                        sock=self.client_sock,
                        packet_type=PacketType.ACK_REPORT,
                        sequence_number=packets_received,
                        payload=b"",
                        timestamp=time.perf_counter(),
                    )
                    break

        except (ConnectionError, TimeoutError) as e:
            logger.warning("TCP server session error with %s: %s", self.client_addr, e)
        finally:
            try:
                self.client_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.client_sock.close()

        duration = (t_last - t_first) if (t_first and t_last and t_last > t_first) else 0.0

        return {
            "client_address": self.client_addr,
            "packets_received": packets_received,
            "payload_bytes_received": payload_bytes_received,
            "duration_seconds": duration,
        }


class TCPBenchmarkClient:
    """
    Client for executing TCP throughput and RTT round-trip latency benchmarks.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_TCP_PORT, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def run_throughput_test(
        self,
        payload_size: int,
        packet_count: int,
        nodelay: bool = True,
    ) -> BenchmarkMetric:
        """
        Stream `packet_count` frames of `payload_size` bytes to the server and
        measure application goodput.

        :param payload_size: Size of data payload per packet (bytes)
        :param packet_count: Total number of packets to transmit
        :param nodelay: If True, set TCP_NODELAY to disable Nagle's algorithm
        :return: BenchmarkMetric instance
        """
        if payload_size < 0:
            raise ValueError(f"Payload size cannot be negative: {payload_size}")
        if packet_count < 0:
            raise ValueError(f"Packet count cannot be negative: {packet_count}")
        if packet_count == 0:
            return create_benchmark_metric(
                protocol="TCP",
                payload_size_bytes=payload_size,
                packet_count=0,
                packets_sent=0,
                packets_received=0,
                duration_seconds=0.0,
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        if nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        payload = b"X" * payload_size
        packets_sent = 0

        try:
            sock.connect((self.host, self.port))
            t_start = time.perf_counter()

            for seq in range(packet_count):
                send_framed_packet(
                    sock=sock,
                    packet_type=PacketType.DATA,
                    sequence_number=seq,
                    payload=payload,
                    timestamp=time.perf_counter(),
                )
                packets_sent += 1

            # Signal benchmark stream completion
            send_framed_packet(
                sock=sock,
                packet_type=PacketType.CONTROL_END,
                sequence_number=packet_count,
                payload=b"",
                timestamp=time.perf_counter(),
            )

            # Wait for server ACK_REPORT acknowledgment
            ack_frame = read_framed_packet(sock, timeout=self.timeout)
            t_end = time.perf_counter()

        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

        duration = max(0.0, t_end - t_start)
        # In TCP without connection drop, delivered packets = sent packets
        packets_received = packets_sent if (ack_frame and ack_frame[0].packet_type == PacketType.ACK_REPORT) else packets_sent

        return create_benchmark_metric(
            protocol="TCP",
            payload_size_bytes=payload_size,
            packet_count=packet_count,
            packets_sent=packets_sent,
            packets_received=packets_received,
            duration_seconds=duration,
        )

    def run_latency_test(
        self,
        payload_size: int = 64,
        ping_count: int = 50,
        nodelay: bool = True,
    ) -> BenchmarkMetric:
        """
        Execute request-response round-trip ping-pong to measure RTT statistics.

        Viva Note:
        Both t_start and t_end are measured on the sender's own monotonic clock
        (`time.perf_counter()`), ensuring zero clock skew or epoch mismatch.

        :param payload_size: Size of echo payload (bytes)
        :param ping_count: Number of ping-pong iterations
        :param nodelay: Disable Nagle's algorithm for accurate latency measurements
        :return: BenchmarkMetric instance with complete RTT statistics
        """
        if ping_count <= 0:
            return create_benchmark_metric(
                protocol="TCP",
                payload_size_bytes=payload_size,
                packet_count=0,
                packets_sent=0,
                packets_received=0,
                duration_seconds=0.0,
                rtt_samples_ms=[],
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        if nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        payload = b"P" * payload_size
        rtt_samples_ms: List[float] = []
        packets_sent = 0
        packets_received = 0

        try:
            sock.connect((self.host, self.port))
            t_test_start = time.perf_counter()

            for seq in range(ping_count):
                t_send = time.perf_counter()
                send_framed_packet(
                    sock=sock,
                    packet_type=PacketType.ECHO_REQUEST,
                    sequence_number=seq,
                    payload=payload,
                    timestamp=t_send,
                )
                packets_sent += 1

                reply = read_framed_packet(sock, timeout=self.timeout)
                t_recv = time.perf_counter()

                if reply and reply[0].packet_type == PacketType.ECHO_REPLY:
                    rtt_ms = (t_recv - t_send) * 1000.0
                    rtt_samples_ms.append(rtt_ms)
                    packets_received += 1

            send_framed_packet(
                sock=sock,
                packet_type=PacketType.CONTROL_END,
                sequence_number=ping_count,
            )
            t_test_end = time.perf_counter()

        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

        total_duration = max(0.0, t_test_end - t_test_start)

        return create_benchmark_metric(
            protocol="TCP",
            payload_size_bytes=payload_size,
            packet_count=ping_count,
            packets_sent=packets_sent,
            packets_received=packets_received,
            duration_seconds=total_duration,
            rtt_samples_ms=rtt_samples_ms,
        )
