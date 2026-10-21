"""
tests.test_server
~~~~~~~~~~~~~~~~~
Unit and integration tests for NetBenchServer lifecycle and server_cli:
- Starting listeners on ephemeral ports
- Exposing actual bound ports
- Client communication with running server over TCP and UDP
- Detecting port-binding and startup errors
- Double-start rejection
- Idempotent and repeated shutdown
- Shutdown while idle and while client is connected
- Thread termination verification
- Clean server restart behavior
- CLI argument parsing and validation
"""

import socket
import threading
import time
import unittest

from netbench.protocol import PacketType, pack_packet
from netbench.server import NetBenchServer, ServerStartupError
from netbench.tcp_handler import TCPBenchmarkClient
from netbench.udp_handler import UDPBenchmarkClient
from server_cli import parse_arguments, validate_host, validate_port


class TestNetBenchServerLifecycle(unittest.TestCase):
    """Lifecycle and thread-safety tests for NetBenchServer."""

    def test_start_ephemeral_ports(self):
        """Starting with port 0 must assign and expose real positive ports."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        self.assertFalse(server.is_running)

        server.start()
        try:
            self.assertTrue(server.is_running)
            self.assertGreater(server.tcp_port, 0)
            self.assertGreater(server.udp_port, 0)
            self.assertNotEqual(server.tcp_port, server.udp_port)

            status = server.get_status()
            self.assertTrue(status["is_running"])
            self.assertEqual(status["tcp_port"], server.tcp_port)
            self.assertEqual(status["udp_port"], server.udp_port)
            self.assertGreaterEqual(status["uptime_seconds"], 0.0)

            # Threads must be active
            self.assertIsNotNone(server.tcp_thread)
            self.assertIsNotNone(server.udp_thread)
            self.assertTrue(server.tcp_thread.is_alive())
            self.assertTrue(server.udp_thread.is_alive())
        finally:
            server.stop()

        self.assertFalse(server.is_running)
        self.assertFalse(server.tcp_thread.is_alive())
        self.assertFalse(server.udp_thread.is_alive())

    def test_client_communication_with_server(self):
        """Clients must be able to perform benchmarks against a running NetBenchServer."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        server.start()
        try:
            # 1. TCP Throughput test against server
            tcp_client = TCPBenchmarkClient(host="127.0.0.1", port=server.tcp_port)
            tcp_metric = tcp_client.run_throughput_test(payload_size=512, packet_count=10)
            self.assertEqual(tcp_metric.protocol, "TCP")
            self.assertEqual(tcp_metric.packets_sent, 10)
            self.assertEqual(tcp_metric.packets_received, 10)
            self.assertGreater(tcp_metric.throughput_mbps, 0.0)

            # 2. TCP Latency test against server
            tcp_lat_metric = tcp_client.run_latency_test(payload_size=64, ping_count=5)
            self.assertEqual(tcp_lat_metric.packets_sent, 5)
            self.assertEqual(tcp_lat_metric.packets_received, 5)
            self.assertIsNotNone(tcp_lat_metric.avg_latency_ms)

            # 3. UDP Latency test against server
            udp_client = UDPBenchmarkClient(host="127.0.0.1", port=server.udp_port)
            udp_lat_metric = udp_client.run_latency_test(payload_size=64, ping_count=5)
            self.assertEqual(udp_lat_metric.packets_sent, 5)
            self.assertEqual(udp_lat_metric.packets_received, 5)
            self.assertIsNotNone(udp_lat_metric.avg_latency_ms)

            # 4. UDP Burst test against server
            udp_client.run_burst_test(payload_size=256, packet_count=10)
            time.sleep(0.05)
            status = server.get_status()
            self.assertIsNotNone(status["latest_udp_summary"])
            self.assertEqual(status["latest_udp_summary"]["expected_count"], 10)
            self.assertEqual(status["latest_udp_summary"]["packets_received"], 10)

        finally:
            server.stop()

    def test_double_start_raises(self):
        """Calling start() when already running must raise RuntimeError."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        server.start()
        try:
            with self.assertRaises(RuntimeError):
                server.start()
        finally:
            server.stop()

    def test_idempotent_stop(self):
        """Calling stop() multiple times or when not started must be safe."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        # Stop before start
        server.stop()
        self.assertFalse(server.is_running)

        server.start()
        server.stop()
        # Repeated stop
        server.stop()
        server.stop()
        self.assertFalse(server.is_running)

    def test_clean_restart_behavior(self):
        """Server can be stopped and restarted cleanly without port conflicts."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        server.start()
        first_tcp_port = server.tcp_port
        server.stop()
        self.assertFalse(server.is_running)

        # Restart
        server.start()
        try:
            self.assertTrue(server.is_running)
            self.assertTrue(server.tcp_thread.is_alive())
            self.assertTrue(server.udp_thread.is_alive())
        finally:
            server.stop()

    def test_shutdown_with_connected_client(self):
        """Stopping the server while a client connection is open must terminate cleanly."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        server.start()

        # Connect a long-lived client socket
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", server.tcp_port))

        try:
            # Trigger server stop while client is still holding connection
            t_start = time.perf_counter()
            server.stop(timeout=1.0)
            t_duration = time.perf_counter() - t_start

            self.assertFalse(server.is_running)
            self.assertLess(t_duration, 2.5)  # Must finish within bounded timeout
            self.assertFalse(server.tcp_thread.is_alive())
            self.assertFalse(server.udp_thread.is_alive())
        finally:
            client_sock.close()

    def test_port_binding_failure_detected(self):
        """ServerStartupError must be raised when attempting to bind to an occupied port."""
        # Occupy a port with an active socket
        conflict_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            conflict_sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        conflict_sock.bind(("127.0.0.1", 0))
        occupied_port = conflict_sock.getsockname()[1]
        conflict_sock.listen(1)

        try:
            conflicting_server = NetBenchServer(host="127.0.0.1", tcp_port=occupied_port, udp_port=0)
            with self.assertRaises(ServerStartupError):
                conflicting_server.start()
            self.assertFalse(conflicting_server.is_running)
        finally:
            conflict_sock.close()

    def test_context_manager(self):
        """Using server as a context manager starts and stops it cleanly."""
        server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        with server as s:
            self.assertTrue(s.is_running)
            self.assertGreater(s.tcp_port, 0)
        self.assertFalse(server.is_running)


class TestServerCLIArguments(unittest.TestCase):
    """Unit tests for CLI argument parsing and validation."""

    def test_validate_host(self):
        self.assertEqual(validate_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_host("localhost"), "127.0.0.1")
        self.assertEqual(validate_host("0.0.0.0"), "0.0.0.0")
        with self.assertRaises(Exception):
            validate_host("not.an.ip.address")

    def test_validate_port(self):
        self.assertEqual(validate_port("5001"), 5001)
        self.assertEqual(validate_port("0"), 0)
        self.assertEqual(validate_port("65535"), 65535)
        with self.assertRaises(Exception):
            validate_port("-1")
        with self.assertRaises(Exception):
            validate_port("70000")
        with self.assertRaises(Exception):
            validate_port("not_a_number")

    def test_parse_arguments_defaults(self):
        args = parse_arguments([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.tcp_port, 5001)
        self.assertEqual(args.udp_port, 5002)

    def test_parse_arguments_custom(self):
        args = parse_arguments(["--host", "127.0.0.1", "--tcp-port", "8001", "--udp-port", "8002"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.tcp_port, 8001)
        self.assertEqual(args.udp_port, 8002)


if __name__ == "__main__":
    unittest.main()
