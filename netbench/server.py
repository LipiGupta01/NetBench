"""
netbench.server
~~~~~~~~~~~~~~~
Unified background server manager that coordinates concurrent TCP and UDP
benchmark listener sockets with thread-safe lifecycle controls and port cleanup.

Viva / Architecture Principles:
1. Multi-protocol Concurrency: TCP and UDP operate independently on separate
   threads, allowing simultaneous or alternating benchmarks without cross-talk.
2. Graceful Shutdown & Socket Cleanup: Uses non-blocking socket timeouts and
   explicit socket closure to immediately release ports without lingering
   in TIME_WAIT or hanging background threads.
3. Decoupled Lifecycle: Benchmark tests are triggered on-demand by clients;
   the server remains purely passive until stimulated by client frames.
"""

import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from netbench.protocol import (
    DEFAULT_TCP_PORT,
    DEFAULT_UDP_PORT,
    HEADER_SIZE,
    PacketHeader,
    PacketType,
    ProtocolError,
    SequenceTracker,
    pack_packet,
    unpack_header,
)
from netbench.tcp_handler import TCPServerSession

logger = logging.getLogger(__name__)


class ServerError(Exception):
    """Base exception for NetBench server errors."""
    pass


class ServerStartupError(ServerError):
    """Raised when the server fails to bind or initialize listener sockets."""
    pass


def _configure_server_socket(sock: socket.socket) -> None:
    """
    Apply OS-appropriate address reuse / exclusivity options.
    On Windows, SO_EXCLUSIVEADDRUSE prevents port hijacking while reliably
    detecting active port collisions. On POSIX, SO_REUSEADDR allows clean restarts.
    """
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            return
        except OSError:
            pass

    if hasattr(socket, "SO_REUSEADDR"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


class NetBenchServer:
    """
    Unified manager orchestrating concurrent TCP and UDP benchmark listeners.
    Exposes thread-safe start, stop, and status querying interfaces.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        tcp_port: int = DEFAULT_TCP_PORT,
        udp_port: int = DEFAULT_UDP_PORT,
    ):
        """
        Initialize the NetBench server configuration.

        :param host: IP address to bind (defaults to '127.0.0.1' for localhost security)
        :param tcp_port: TCP port to listen on (0 for OS-assigned ephemeral port)
        :param udp_port: UDP port to listen on (0 for OS-assigned ephemeral port)
        """
        self.host = host
        self._requested_tcp_port = tcp_port
        self._requested_udp_port = udp_port

        # Actual bound ports (populated once start() succeeds)
        self.tcp_port: int = tcp_port
        self.udp_port: int = udp_port

        self.stop_event = threading.Event()
        self.is_running: bool = False
        self._start_time: Optional[float] = None

        self._tcp_sock: Optional[socket.socket] = None
        self._udp_sock: Optional[socket.socket] = None

        self.tcp_thread: Optional[threading.Thread] = None
        self.udp_thread: Optional[threading.Thread] = None
        self._client_threads: List[threading.Thread] = []

        self._lock = threading.Lock()
        self._latest_tcp_session: Optional[Dict[str, Any]] = None
        self._latest_udp_summary: Optional[Dict[str, Any]] = None
        self._udp_tracker = SequenceTracker()
        self._udp_payload_bytes = 0
        self._udp_first_arrival: Optional[float] = None
        self._udp_last_arrival: Optional[float] = None

    def start(self) -> None:
        """
        Bind listener sockets and launch background listener threads.
        Non-blocking: returns immediately once sockets are bound and listening.

        :raises RuntimeError: If start() is called while already running
        :raises ServerStartupError: If socket binding or listener startup fails
        """
        with self._lock:
            if self.is_running:
                raise RuntimeError("NetBenchServer is already running")

            # 1. Bind and configure TCP listening socket
            try:
                tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _configure_server_socket(tcp_sock)
                tcp_sock.bind((self.host, self._requested_tcp_port))
                tcp_sock.listen(128)
                tcp_sock.settimeout(0.3)  # Short timeout for responsive stop_event checks
                self.tcp_port = tcp_sock.getsockname()[1]
                self._tcp_sock = tcp_sock
            except OSError as e:
                if "tcp_sock" in locals() and tcp_sock:
                    tcp_sock.close()
                raise ServerStartupError(
                    f"Failed to bind TCP listener on {self.host}:{self._requested_tcp_port}: {e}"
                ) from e

            # 2. Bind and configure UDP listening socket
            try:
                udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _configure_server_socket(udp_sock)
                udp_sock.bind((self.host, self._requested_udp_port))
                udp_sock.settimeout(0.3)  # Short timeout for responsive stop_event checks
                self.udp_port = udp_sock.getsockname()[1]
                self._udp_sock = udp_sock
            except OSError as e:
                # Clean up already opened TCP socket before raising
                if self._tcp_sock:
                    self._tcp_sock.close()
                    self._tcp_sock = None
                if "udp_sock" in locals() and udp_sock:
                    udp_sock.close()
                raise ServerStartupError(
                    f"Failed to bind UDP listener on {self.host}:{self._requested_udp_port}: {e}"
                ) from e

            # 3. Launch background threads
            self.stop_event.clear()
            self._start_time = time.time()
            self.is_running = True

            self.tcp_thread = threading.Thread(
                target=self._run_tcp_listener,
                name="NetBench-TCP-Listener",
                daemon=True,
            )
            self.udp_thread = threading.Thread(
                target=self._run_udp_listener,
                name="NetBench-UDP-Listener",
                daemon=True,
            )

            self.tcp_thread.start()
            self.udp_thread.start()

        logger.info(
            "NetBenchServer started on %s (TCP: %d, UDP: %d)",
            self.host,
            self.tcp_port,
            self.udp_port,
        )

    def stop(self, timeout: float = 2.0) -> None:
        """
        Signal listener threads to terminate and cleanly release all sockets.
        Idempotent: safe to call multiple times or when already stopped.

        :param timeout: Maximum time (seconds) to wait for each listener thread to exit
        """
        with self._lock:
            if not self.is_running and not self.stop_event.is_set():
                return

            self.stop_event.set()
            self.is_running = False

            # Close listener sockets immediately to unblock accept() and recvfrom()
            if self._tcp_sock:
                try:
                    self._tcp_sock.close()
                except OSError:
                    pass
                self._tcp_sock = None

            if self._udp_sock:
                try:
                    self._udp_sock.close()
                except OSError:
                    pass
                self._udp_sock = None

        # Join listener threads outside lock to prevent deadlocks
        if self.tcp_thread and self.tcp_thread.is_alive():
            self.tcp_thread.join(timeout=timeout)

        if self.udp_thread and self.udp_thread.is_alive():
            self.udp_thread.join(timeout=timeout)

        # Join client worker threads with bounded timeout
        with self._lock:
            for thread in self._client_threads:
                if thread.is_alive():
                    thread.join(timeout=0.5)
            self._client_threads.clear()

        logger.info("NetBenchServer stopped cleanly.")

    def _run_tcp_listener(self) -> None:
        """TCP accept loop: dispatches incoming connections to session handlers."""
        while not self.stop_event.is_set():
            try:
                if not self._tcp_sock:
                    break
                client_sock, client_addr = self._tcp_sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                # Socket closed during shutdown
                break

            # Handle connection in a dedicated worker thread
            worker = threading.Thread(
                target=self._handle_tcp_client,
                args=(client_sock, client_addr),
                name=f"NetBench-TCP-Client-{client_addr}",
                daemon=True,
            )
            with self._lock:
                # Clean up terminated threads from list
                self._client_threads = [t for t in self._client_threads if t.is_alive()]
                self._client_threads.append(worker)
            worker.start()

    def _handle_tcp_client(self, client_sock: socket.socket, client_addr: tuple) -> None:
        """Process a single TCP benchmark client connection."""
        try:
            session = TCPServerSession(client_sock, client_addr, timeout=5.0)
            summary = session.handle()
            with self._lock:
                self._latest_tcp_session = summary
        except Exception as e:
            logger.debug("TCP client session error (%s): %s", client_addr, e)

    def _run_udp_listener(self) -> None:
        """UDP datagram loop: handles ping echo, data burst reception, and control signals."""
        while not self.stop_event.is_set():
            try:
                if not self._udp_sock:
                    break
                raw_data, client_addr = self._udp_sock.recvfrom(65536)
            except (socket.timeout, TimeoutError):
                continue
            except (ConnectionResetError, ConnectionError):
                # On Windows, ICMP Port Unreachable from a previous sendto causes
                # WSAECONNRESET on next recvfrom(). Non-fatal for UDP server.
                continue
            except OSError:
                break

            now = time.perf_counter()

            if len(raw_data) < HEADER_SIZE:
                continue

            try:
                header = unpack_header(raw_data[:HEADER_SIZE])
            except ProtocolError:
                continue

            payload = raw_data[HEADER_SIZE:HEADER_SIZE + header.payload_length]

            if header.packet_type == PacketType.ECHO_REQUEST:
                # Immediate RTT Pong Response
                reply = pack_packet(
                    packet_type=PacketType.ECHO_REPLY,
                    sequence_number=header.sequence_number,
                    payload=payload,
                    timestamp=header.timestamp,
                )
                try:
                    if self._udp_sock:
                        self._udp_sock.sendto(reply, client_addr)
                except OSError:
                    pass

            elif header.packet_type == PacketType.CONTROL_START:
                # Reset sequence tracker for a new burst
                with self._lock:
                    self._udp_tracker.reset()
                    self._udp_payload_bytes = 0
                    self._udp_first_arrival = now
                    self._udp_last_arrival = now

            elif header.packet_type == PacketType.DATA:
                with self._lock:
                    if self._udp_first_arrival is None:
                        self._udp_first_arrival = now
                    self._udp_last_arrival = now

                    is_unique = self._udp_tracker.record_packet(
                        sequence_number=header.sequence_number,
                        send_time=header.timestamp,
                        arrival_time=now,
                    )
                    if is_unique:
                        self._udp_payload_bytes += len(payload)

            elif header.packet_type == PacketType.CONTROL_END:
                # Finalize UDP burst summary
                with self._lock:
                    expected = header.sequence_number
                    duration = 0.0
                    if self._udp_first_arrival and self._udp_last_arrival:
                        duration = max(0.0001, self._udp_last_arrival - self._udp_first_arrival)

                    summary = {
                        "expected_count": expected,
                        "packets_received": self._udp_tracker.unique_received,
                        "total_received": self._udp_tracker.total_received,
                        "duplicate_count": self._udp_tracker.duplicate_count,
                        "out_of_order_count": self._udp_tracker.out_of_order_count,
                        "missing_sequences": self._udp_tracker.missing_sequences(expected),
                        "loss_count": self._udp_tracker.loss_count(expected),
                        "loss_rate_percent": self._udp_tracker.loss_rate_percent(expected),
                        "delivery_rate_percent": self._udp_tracker.delivery_rate_percent(expected),
                        "payload_bytes": self._udp_payload_bytes,
                        "duration_seconds": duration,
                    }
                    self._latest_udp_summary = summary

                # Send ACK_REPORT back to client
                reply = pack_packet(
                    packet_type=PacketType.ACK_REPORT,
                    sequence_number=self._udp_tracker.unique_received,
                    payload=b"",
                    timestamp=time.perf_counter(),
                )
                try:
                    if self._udp_sock:
                        self._udp_sock.sendto(reply, client_addr)
                except OSError:
                    pass

    def get_status(self) -> Dict[str, Any]:
        """
        Return snapshot of server state, suitable for Streamlit UI status displays.

        :return: Dictionary containing running status, bound ports, uptime, and latest metrics
        """
        with self._lock:
            uptime = (time.time() - self._start_time) if (self.is_running and self._start_time) else 0.0
            active_clients = sum(1 for t in self._client_threads if t.is_alive())

            return {
                "is_running": self.is_running,
                "host": self.host,
                "tcp_port": self.tcp_port,
                "udp_port": self.udp_port,
                "uptime_seconds": round(uptime, 2),
                "active_tcp_clients": active_clients,
                "latest_tcp_session": self._latest_tcp_session.copy() if self._latest_tcp_session else None,
                "latest_udp_summary": self._latest_udp_summary.copy() if self._latest_udp_summary else None,
            }

    def __enter__(self) -> "NetBenchServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()
