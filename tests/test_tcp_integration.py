"""
tests.test_tcp_integration
~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for real TCP socket communication on localhost:
- Real throughput transfer and framed packet assembly
- Fragmented/split packet reads across chunk boundaries
- Multiple frames over a single TCP stream connection
- Premature EOF, truncated frames, and timeouts
- RTT echo ping-pong latency measurement
- Empty test cases and clean socket teardown
"""

import socket
import threading
import time
import unittest

from netbench.protocol import (
    HEADER_SIZE,
    PacketType,
    pack_header,
    pack_packet,
    unpack_header,
)
from netbench.tcp_handler import (
    TCPBenchmarkClient,
    TCPServerSession,
    read_framed_packet,
    recv_exact,
    send_framed_packet,
)


class TestTCPIntegration(unittest.TestCase):
    """Integration test suite executing actual TCP socket traffic on localhost."""

    def setUp(self):
        # Bind server socket to ephemeral port (port=0) to guarantee zero collisions
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.server_sock.listen(5)
        self.port = self.server_sock.getsockname()[1]

    def tearDown(self):
        try:
            self.server_sock.close()
        except OSError:
            pass

    def test_tcp_throughput_real_exchange(self):
        """Test full throughput benchmark run with 25 packets of 1024 bytes."""
        server_result = {}

        def run_server():
            client_sock, client_addr = self.server_sock.accept()
            session = TCPServerSession(client_sock, client_addr, timeout=3.0)
            server_result.update(session.handle())

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        client = TCPBenchmarkClient(host="127.0.0.1", port=self.port, timeout=3.0)
        metric = client.run_throughput_test(payload_size=1024, packet_count=25)

        server_thread.join(timeout=2.0)
        self.assertFalse(server_thread.is_alive())

        # Verify client metric
        self.assertEqual(metric.protocol, "TCP")
        self.assertEqual(metric.packets_sent, 25)
        self.assertEqual(metric.packets_received, 25)
        self.assertEqual(metric.loss_rate_percent, 0.0)
        self.assertEqual(metric.delivery_rate_percent, 100.0)
        self.assertGreater(metric.throughput_mbps, 0.0)

        # Verify server accounting
        self.assertEqual(server_result["packets_received"], 25)
        self.assertEqual(server_result["payload_bytes_received"], 25 * 1024)

    def test_tcp_latency_real_rtt_echo(self):
        """Test round-trip ping-pong echo over TCP."""
        def run_server():
            client_sock, client_addr = self.server_sock.accept()
            session = TCPServerSession(client_sock, client_addr, timeout=3.0)
            session.handle()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        client = TCPBenchmarkClient(host="127.0.0.1", port=self.port, timeout=3.0)
        metric = client.run_latency_test(payload_size=64, ping_count=10)

        server_thread.join(timeout=2.0)
        self.assertFalse(server_thread.is_alive())

        self.assertEqual(metric.protocol, "TCP")
        self.assertEqual(metric.packets_sent, 10)
        self.assertEqual(metric.packets_received, 10)
        self.assertIsNotNone(metric.avg_latency_ms)
        self.assertIsNotNone(metric.min_latency_ms)
        self.assertIsNotNone(metric.max_latency_ms)
        self.assertGreaterEqual(metric.avg_latency_ms, 0.0)

    def test_tcp_split_and_fragmented_frames(self):
        """
        Verify that recv_exact and read_framed_packet correctly assemble frames
        when the network delivers fragmented chunks (e.g. 5 bytes per chunk).
        """
        received_frame = {}

        def run_server():
            client_sock, _ = self.server_sock.accept()
            try:
                frame = read_framed_packet(client_sock, timeout=3.0)
                if frame:
                    received_frame["header"] = frame[0]
                    received_frame["payload"] = frame[1]
            finally:
                client_sock.close()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Connect client and send a 50-byte payload in 7-byte fragmented chunks
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", self.port))
        test_payload = b"NetBench Fragmented Stream Frame Assembly Verification!"
        full_packet = pack_packet(PacketType.DATA, sequence_number=42, payload=test_payload)

        # Transmit in small 7-byte slices with micro-pauses
        chunk_size = 7
        for offset in range(0, len(full_packet), chunk_size):
            client_sock.sendall(full_packet[offset:offset + chunk_size])
            time.sleep(0.005)

        client_sock.close()
        server_thread.join(timeout=2.0)

        self.assertIn("header", received_frame)
        self.assertEqual(received_frame["header"].sequence_number, 42)
        self.assertEqual(received_frame["payload"], test_payload)

    def test_tcp_multiple_frames_one_connection(self):
        """Verify multiple framed messages sent over a single continuous stream."""
        received_payloads = []

        def run_server():
            client_sock, _ = self.server_sock.accept()
            try:
                while True:
                    frame = read_framed_packet(client_sock, timeout=2.0)
                    if frame is None:
                        break
                    received_payloads.append(frame[1])
            finally:
                client_sock.close()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", self.port))

        for idx in range(5):
            send_framed_packet(
                client_sock,
                packet_type=PacketType.DATA,
                sequence_number=idx,
                payload=f"Frame #{idx}".encode("ascii"),
            )
        client_sock.close()
        server_thread.join(timeout=2.0)

        self.assertEqual(len(received_payloads), 5)
        self.assertEqual(received_payloads[0], b"Frame #0")
        self.assertEqual(received_payloads[4], b"Frame #4")

    def test_tcp_clean_eof_and_premature_eof(self):
        """Verify clean EOF returns None and premature EOF raises ConnectionResetError."""
        # 1. Clean EOF test
        def run_clean_eof_server():
            client_sock, _ = self.server_sock.accept()
            frame = read_framed_packet(client_sock, timeout=2.0)
            self.assertIsNone(frame)
            client_sock.close()

        t1 = threading.Thread(target=run_clean_eof_server, daemon=True)
        t1.start()

        c1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c1.connect(("127.0.0.1", self.port))
        # Immediately close without sending any bytes
        c1.close()
        t1.join(timeout=2.0)

        # 2. Premature EOF test (client disconnects halfway through header)
        server_raised = []

        def run_premature_eof_server():
            client_sock, _ = self.server_sock.accept()
            try:
                recv_exact(client_sock, HEADER_SIZE, timeout=2.0)
            except ConnectionResetError as e:
                server_raised.append(e)
            finally:
                client_sock.close()

        t2 = threading.Thread(target=run_premature_eof_server, daemon=True)
        t2.start()

        c2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c2.connect(("127.0.0.1", self.port))
        # Send only 8 bytes out of 20, then abruptly close
        c2.sendall(b"12345678")
        c2.close()
        t2.join(timeout=2.0)

        self.assertEqual(len(server_raised), 1)

    def test_tcp_empty_test_handling(self):
        """Test zero-packet test invocations."""
        client = TCPBenchmarkClient(host="127.0.0.1", port=self.port)
        metric_t = client.run_throughput_test(payload_size=1024, packet_count=0)
        self.assertEqual(metric_t.packet_count, 0)
        self.assertEqual(metric_t.throughput_mbps, 0.0)

        metric_l = client.run_latency_test(payload_size=64, ping_count=0)
        self.assertEqual(metric_l.packet_count, 0)
        self.assertIsNone(metric_l.avg_latency_ms)


if __name__ == "__main__":
    unittest.main()
