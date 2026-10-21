"""
tests.test_udp_integration
~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for real UDP datagram communication on localhost:
- Real datagram burst transmission and receiver sequence tracking
- UDP RTT echo latency ping-pong measurement
- Packet loss, duplicate, and out-of-order accounting under real socket conditions
- Handling malformed and truncated UDP frames
- Maximum datagram size enforcement
- Empty tests and clean socket teardown
"""

import socket
import threading
import time
import unittest

from netbench.protocol import (
    HEADER_SIZE,
    MAX_UDP_PAYLOAD_SIZE,
    PacketType,
    pack_packet,
)
from netbench.udp_handler import (
    UDPBenchmarkClient,
    UDPReceiverSession,
    build_udp_metric_from_summary,
)


class TestUDPIntegration(unittest.TestCase):
    """Integration test suite executing actual UDP socket datagram traffic on localhost."""

    def test_udp_burst_real_exchange(self):
        """Test full UDP datagram burst exchange on localhost."""
        receiver = UDPReceiverSession(host="127.0.0.1", port=0)
        port = receiver.port
        receiver_data = {}

        def run_receiver():
            tracker, summary = receiver.receive_burst(
                expected_count=25,
                idle_timeout=2.0,
                drain_timeout=0.2,
            )
            receiver_data["tracker"] = tracker
            receiver_data["summary"] = summary

        rx_thread = threading.Thread(target=run_receiver, daemon=True)
        rx_thread.start()

        # Let receiver thread bind and enter listen loop
        time.sleep(0.02)

        client = UDPBenchmarkClient(host="127.0.0.1", port=port)
        client_stats = client.run_burst_test(
            payload_size=512,
            packet_count=25,
            delay_between_packets=0.001,
        )

        rx_thread.join(timeout=3.0)
        self.assertFalse(rx_thread.is_alive())
        receiver.close()

        summary = receiver_data["summary"]
        self.assertEqual(summary["expected_count"], 25)
        self.assertEqual(summary["packets_received"], 25)
        self.assertEqual(summary["loss_count"], 0)
        self.assertEqual(summary["loss_rate_percent"], 0.0)
        self.assertEqual(summary["delivery_rate_percent"], 100.0)
        self.assertEqual(summary["payload_bytes_received"], 25 * 512)
        self.assertGreater(summary["throughput_mbps"], 0.0)

        # Verify combined BenchmarkMetric construction
        metric = build_udp_metric_from_summary(client_stats, summary, payload_size=512)
        self.assertEqual(metric.protocol, "UDP")
        self.assertEqual(metric.packets_sent, 25)
        self.assertEqual(metric.packets_received, 25)
        self.assertEqual(metric.loss_rate_percent, 0.0)
        self.assertEqual(metric.delivery_rate_percent, 100.0)

    def test_udp_latency_real_rtt_echo(self):
        """Test request-response RTT latency ping-pong over UDP."""
        receiver = UDPReceiverSession(host="127.0.0.1", port=0)
        port = receiver.port
        stop_event = threading.Event()

        echo_thread = threading.Thread(
            target=receiver.serve_echo,
            args=(stop_event,),
            daemon=True,
        )
        echo_thread.start()
        time.sleep(0.02)

        try:
            client = UDPBenchmarkClient(host="127.0.0.1", port=port, timeout=1.0)
            metric = client.run_latency_test(payload_size=64, ping_count=10)
        finally:
            stop_event.set()
            echo_thread.join(timeout=1.0)
            receiver.close()

        self.assertEqual(metric.protocol, "UDP")
        self.assertEqual(metric.packets_sent, 10)
        self.assertEqual(metric.packets_received, 10)
        self.assertEqual(metric.loss_rate_percent, 0.0)
        self.assertIsNotNone(metric.avg_latency_ms)
        self.assertIsNotNone(metric.min_latency_ms)
        self.assertIsNotNone(metric.max_latency_ms)
        self.assertGreaterEqual(metric.avg_latency_ms, 0.0)

    def test_udp_simulated_loss_and_out_of_order(self):
        """
        Verify sequence accounting when packets arrive out-of-order,
        with duplicates, and with missing sequence numbers.
        """
        receiver = UDPReceiverSession(host="127.0.0.1", port=0)
        port = receiver.port
        receiver_data = {}

        def run_receiver():
            tracker, summary = receiver.receive_burst(
                expected_count=6,
                idle_timeout=2.0,
                drain_timeout=0.2,
            )
            receiver_data["summary"] = summary

        rx_thread = threading.Thread(target=run_receiver, daemon=True)
        rx_thread.start()
        time.sleep(0.02)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Send sequence: 0, 1, 4, 3, 5, 3
        # Expected: 6 packets (0..5)
        # Missing: [2]
        # Duplicate: 3 sent twice
        # Out-of-order: 3 arrives after 4
        send_sequence = [0, 1, 4, 3, 5, 3]
        for seq in send_sequence:
            pkt = pack_packet(PacketType.DATA, sequence_number=seq, payload=b"DATA")
            sock.sendto(pkt, ("127.0.0.1", port))
            time.sleep(0.005)

        # Send CONTROL_END
        end_pkt = pack_packet(PacketType.CONTROL_END, sequence_number=6, payload=b"")
        sock.sendto(end_pkt, ("127.0.0.1", port))
        sock.close()

        rx_thread.join(timeout=2.0)
        receiver.close()

        summary = receiver_data["summary"]
        self.assertEqual(summary["expected_count"], 6)
        self.assertEqual(summary["packets_received"], 5)  # unique: 0, 1, 3, 4, 5
        self.assertEqual(summary["duplicate_count"], 1)
        self.assertEqual(summary["out_of_order_count"], 1)
        self.assertEqual(summary["missing_sequences"], [2])
        self.assertEqual(summary["loss_count"], 1)
        self.assertAlmostEqual(summary["loss_rate_percent"], (1 / 6) * 100.0)
        self.assertAlmostEqual(summary["delivery_rate_percent"], (5 / 6) * 100.0)

    def test_udp_malformed_and_truncated_datagrams(self):
        """Verify receiver gracefully ignores malformed, truncated, or corrupt frames."""
        receiver = UDPReceiverSession(host="127.0.0.1", port=0)
        port = receiver.port
        receiver_data = {}

        def run_receiver():
            tracker, summary = receiver.receive_burst(
                expected_count=1,
                idle_timeout=1.5,
                drain_timeout=0.2,
            )
            receiver_data["summary"] = summary

        rx_thread = threading.Thread(target=run_receiver, daemon=True)
        rx_thread.start()
        time.sleep(0.02)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 1. Truncated packet (< 20 bytes)
        sock.sendto(b"12345", ("127.0.0.1", port))
        # 2. Corrupt magic bytes
        corrupt_magic = b"XX" + b"\x00" * (HEADER_SIZE - 2)
        sock.sendto(corrupt_magic, ("127.0.0.1", port))
        time.sleep(0.01)

        # 3. Valid datagram
        valid_packet = pack_packet(PacketType.DATA, sequence_number=0, payload=b"Valid")
        sock.sendto(valid_packet, ("127.0.0.1", port))

        # End test
        end_pkt = pack_packet(PacketType.CONTROL_END, sequence_number=1, payload=b"")
        sock.sendto(end_pkt, ("127.0.0.1", port))
        sock.close()

        rx_thread.join(timeout=2.0)
        receiver.close()

        summary = receiver_data["summary"]
        self.assertEqual(summary["packets_received"], 1)
        self.assertEqual(summary["loss_count"], 0)

    def test_udp_payload_size_limits(self):
        """Enforce maximum allowable UDP payload size limits."""
        client = UDPBenchmarkClient(host="127.0.0.1", port=5002)

        # Payload exceeding MAX_UDP_PAYLOAD_SIZE (65507 bytes) must raise ValueError
        with self.assertRaises(ValueError):
            client.run_burst_test(payload_size=MAX_UDP_PAYLOAD_SIZE + 1, packet_count=1)

        # Negative payload size must raise ValueError
        with self.assertRaises(ValueError):
            client.run_burst_test(payload_size=-10, packet_count=1)

        # Negative packet count must raise ValueError
        with self.assertRaises(ValueError):
            client.run_burst_test(payload_size=64, packet_count=-5)

    def test_udp_empty_test_handling(self):
        """Test zero-packet test invocations for UDP."""
        client = UDPBenchmarkClient(host="127.0.0.1", port=5002)
        burst_stats = client.run_burst_test(payload_size=64, packet_count=0)
        self.assertEqual(burst_stats["packets_sent"], 0)
        self.assertEqual(burst_stats["payload_bytes_sent"], 0)

        metric = client.run_latency_test(payload_size=64, ping_count=0)
        self.assertEqual(metric.packet_count, 0)
        self.assertEqual(metric.packets_sent, 0)
        self.assertEqual(metric.packets_received, 0)
        self.assertIsNone(metric.avg_latency_ms)


if __name__ == "__main__":
    unittest.main()
