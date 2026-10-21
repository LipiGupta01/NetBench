"""
tests.test_metrics
~~~~~~~~~~~~~~~~~~
Comprehensive unit test suite for NetBench metrics engine:
- Throughput and Goodput calculations
- Packet loss and delivery rate calculations
- Latency statistics (min, mean, median, max, std dev)
- RFC 3550 interarrival jitter
- BenchmarkMetric dataclass and factory helper
"""

import math
import unittest
from netbench.metrics import (
    BenchmarkMetric,
    LatencyStats,
    calculate_latency_stats,
    calculate_loss_and_delivery,
    calculate_rfc3550_jitter,
    calculate_throughput,
    create_benchmark_metric,
)


class TestThroughputCalculations(unittest.TestCase):
    """Tests for bits-per-second and Megabits-per-second goodput calculations."""

    def test_standard_throughput(self):
        """125,000 bytes transferred in 1.0 second = 1,000,000 bps = 1.0 Mbps."""
        bps, mbps = calculate_throughput(payload_bytes_received=125_000, duration_seconds=1.0)
        self.assertAlmostEqual(bps, 1_000_000.0)
        self.assertAlmostEqual(mbps, 1.0)

    def test_high_throughput(self):
        """125,000,000 bytes in 1.0 second = 1,000 Mbps = 1 Gbps."""
        bps, mbps = calculate_throughput(payload_bytes_received=125_000_000, duration_seconds=1.0)
        self.assertAlmostEqual(bps, 1_000_000_000.0)
        self.assertAlmostEqual(mbps, 1000.0)

    def test_zero_duration(self):
        """Zero or negative duration must return 0.0 without ZeroDivisionError."""
        bps, mbps = calculate_throughput(payload_bytes_received=1000, duration_seconds=0.0)
        self.assertEqual(bps, 0.0)
        self.assertEqual(mbps, 0.0)

        bps_neg, mbps_neg = calculate_throughput(payload_bytes_received=1000, duration_seconds=-0.5)
        self.assertEqual(bps_neg, 0.0)
        self.assertEqual(mbps_neg, 0.0)

    def test_zero_bytes(self):
        """Zero bytes received yields 0 bps."""
        bps, mbps = calculate_throughput(payload_bytes_received=0, duration_seconds=2.0)
        self.assertEqual(bps, 0.0)
        self.assertEqual(mbps, 0.0)

    def test_negative_payload_raises(self):
        """Negative payload bytes must raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_throughput(payload_bytes_received=-100, duration_seconds=1.0)


class TestLossAndDelivery(unittest.TestCase):
    """Tests for packet loss count, loss percentage, and delivery rate."""

    def test_perfect_delivery(self):
        """100 sent, 100 received -> 0 loss, 0% loss rate, 100% delivery rate."""
        lost, loss_pct, delivery_pct = calculate_loss_and_delivery(packets_sent=100, packets_received=100)
        self.assertEqual(lost, 0)
        self.assertAlmostEqual(loss_pct, 0.0)
        self.assertAlmostEqual(delivery_pct, 100.0)

    def test_partial_loss(self):
        """100 sent, 80 received -> 20 lost, 20% loss rate, 80% delivery rate."""
        lost, loss_pct, delivery_pct = calculate_loss_and_delivery(packets_sent=100, packets_received=80)
        self.assertEqual(lost, 20)
        self.assertAlmostEqual(loss_pct, 20.0)
        self.assertAlmostEqual(delivery_pct, 80.0)

    def test_total_loss(self):
        """100 sent, 0 received -> 100 lost, 100% loss rate, 0% delivery rate."""
        lost, loss_pct, delivery_pct = calculate_loss_and_delivery(packets_sent=100, packets_received=0)
        self.assertEqual(lost, 100)
        self.assertAlmostEqual(loss_pct, 100.0)
        self.assertAlmostEqual(delivery_pct, 0.0)

    def test_zero_packets_sent(self):
        """Zero sent case must not raise ZeroDivisionError."""
        lost, loss_pct, delivery_pct = calculate_loss_and_delivery(packets_sent=0, packets_received=0)
        self.assertEqual(lost, 0)
        self.assertEqual(loss_pct, 0.0)
        self.assertEqual(delivery_pct, 0.0)

    def test_received_exceeds_sent(self):
        """If duplicate or retransmitted packets arrive, delivery rate is capped at 100%."""
        lost, loss_pct, delivery_pct = calculate_loss_and_delivery(packets_sent=100, packets_received=120)
        self.assertEqual(lost, 0)
        self.assertEqual(loss_pct, 0.0)
        self.assertAlmostEqual(delivery_pct, 100.0)

    def test_negative_counts_raise(self):
        """Negative packet counts must raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_loss_and_delivery(packets_sent=-10, packets_received=5)
        with self.assertRaises(ValueError):
            calculate_loss_and_delivery(packets_sent=10, packets_received=-1)


class TestLatencyStatistics(unittest.TestCase):
    """Tests for RTT latency distribution calculations."""

    def test_standard_samples(self):
        """Samples [2.0, 4.0, 4.0, 4.0, 6.0] ms."""
        samples = [2.0, 4.0, 4.0, 4.0, 6.0]
        stats = calculate_latency_stats(samples)
        self.assertEqual(stats.sample_count, 5)
        self.assertAlmostEqual(stats.min_ms, 2.0)
        self.assertAlmostEqual(stats.mean_ms, 4.0)
        self.assertAlmostEqual(stats.median_ms, 4.0)
        self.assertAlmostEqual(stats.max_ms, 6.0)
        self.assertAlmostEqual(stats.std_dev_ms, math.sqrt(2.0), places=4)

    def test_single_sample(self):
        """Single sample has std_dev = 0.0."""
        stats = calculate_latency_stats([3.5])
        self.assertEqual(stats.sample_count, 1)
        self.assertEqual(stats.min_ms, 3.5)
        self.assertEqual(stats.mean_ms, 3.5)
        self.assertEqual(stats.median_ms, 3.5)
        self.assertEqual(stats.max_ms, 3.5)
        self.assertEqual(stats.std_dev_ms, 0.0)

    def test_empty_samples(self):
        """Empty samples must return LatencyStats.empty() with None for stats."""
        stats = calculate_latency_stats([])
        self.assertEqual(stats.sample_count, 0)
        self.assertIsNone(stats.min_ms)
        self.assertIsNone(stats.mean_ms)
        self.assertIsNone(stats.median_ms)
        self.assertIsNone(stats.max_ms)
        self.assertIsNone(stats.std_dev_ms)

    def test_genuine_zero_latency(self):
        """Distinguish genuine 0.0 ms from None/missing data."""
        stats = calculate_latency_stats([0.0, 0.0])
        self.assertIsNotNone(stats.min_ms)
        self.assertEqual(stats.min_ms, 0.0)
        self.assertEqual(stats.mean_ms, 0.0)

    def test_invalid_samples_raise(self):
        """Negative, NaN, or infinite latency samples must raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_latency_stats([1.0, -0.5, 2.0])
        with self.assertRaises(ValueError):
            calculate_latency_stats([1.0, float("nan")])
        with self.assertRaises(ValueError):
            calculate_latency_stats([1.0, float("inf")])


class TestRFC3550Jitter(unittest.TestCase):
    """Tests for RFC 3550 standard interarrival jitter calculation."""

    def test_manual_trace_verification(self):
        """
        Manually verified step-by-step trace:
        4 packets spaced by 20ms at sender:
          send_times = [0.0, 0.020, 0.040, 0.060] seconds
        Arrival times at receiver:
          arrival_times = [0.100, 0.125, 0.140, 0.170] seconds
        Transit delays:
          T_0 = 0.100 - 0.0 = 0.100 s
          T_1 = 0.125 - 0.020 = 0.105 s -> diff |0.105 - 0.100| = 0.005 s
          J_1 = 0 + (0.005 - 0)/16 = 0.0003125 s
          T_2 = 0.140 - 0.040 = 0.100 s -> diff |0.100 - 0.105| = 0.005 s
          J_2 = 0.0003125 + (0.005 - 0.0003125)/16 = 0.00060546875 s
          T_3 = 0.170 - 0.060 = 0.110 s -> diff |0.110 - 0.100| = 0.010 s
          J_3 = 0.00060546875 + (0.010 - 0.00060546875)/16 = 0.001192626953125 s
        In milliseconds: 1.192626953125 ms.
        """
        send_times = [0.0, 0.020, 0.040, 0.060]
        arrival_times = [0.100, 0.125, 0.140, 0.170]
        jitter_ms = calculate_rfc3550_jitter(send_times, arrival_times)
        expected_ms = 1.192626953125
        self.assertAlmostEqual(jitter_ms, expected_ms, places=5)

    def test_zero_jitter_uniform_delay(self):
        """Constant propagation delay yields exactly 0.0 jitter."""
        send_times = [0.0, 0.010, 0.020, 0.030]
        # Exactly 5ms transit time for every packet
        arrival_times = [0.005, 0.015, 0.025, 0.035]
        jitter_ms = calculate_rfc3550_jitter(send_times, arrival_times)
        self.assertAlmostEqual(jitter_ms, 0.0)

    def test_clock_offset_invariance(self):
        """
        Adding an arbitrary constant offset (e.g. unsynchronized clocks)
        to arrival times MUST NOT change the computed jitter.
        """
        send_times = [0.0, 0.020, 0.040, 0.060]
        arrival_times_1 = [0.100, 0.125, 0.140, 0.170]
        # Shift arrival times by 3600 seconds (1 hour)
        arrival_times_2 = [t + 3600.0 for t in arrival_times_1]

        j1 = calculate_rfc3550_jitter(send_times, arrival_times_1)
        j2 = calculate_rfc3550_jitter(send_times, arrival_times_2)
        self.assertAlmostEqual(j1, j2)

    def test_fewer_than_two_samples(self):
        """Fewer than 2 packets cannot yield jitter; returns 0.0."""
        self.assertEqual(calculate_rfc3550_jitter([], []), 0.0)
        self.assertEqual(calculate_rfc3550_jitter([1.0], [2.0]), 0.0)

    def test_mismatched_sample_counts_raise(self):
        """Mismatched send and arrival sample lists must raise ValueError."""
        with self.assertRaises(ValueError):
            calculate_rfc3550_jitter([0.1, 0.2], [0.3])


class TestBenchmarkMetricFactory(unittest.TestCase):
    """Tests for create_benchmark_metric and BenchmarkMetric data model."""

    def test_create_tcp_metric(self):
        metric = create_benchmark_metric(
            protocol="TCP",
            payload_size_bytes=1024,
            packet_count=1000,
            packets_sent=1000,
            packets_received=1000,
            duration_seconds=0.1,
            rtt_samples_ms=[0.5, 0.8, 1.2],
        )
        self.assertEqual(metric.protocol, "TCP")
        self.assertEqual(metric.loss_rate_percent, 0.0)
        self.assertEqual(metric.delivery_rate_percent, 100.0)
        self.assertAlmostEqual(metric.throughput_mbps, (1000 * 1024 * 8) / (0.1 * 1_000_000))
        self.assertAlmostEqual(metric.min_latency_ms, 0.5)
        self.assertAlmostEqual(metric.max_latency_ms, 1.2)
        self.assertIsNone(metric.jitter_ms)

        # Ensure dictionary representation contains all expected keys
        d = metric.to_dict()
        self.assertEqual(d["protocol"], "TCP")
        self.assertIn("throughput_mbps", d)
        self.assertIn("timestamp", d)

    def test_create_udp_metric(self):
        metric = create_benchmark_metric(
            protocol="UDP",
            payload_size_bytes=512,
            packet_count=500,
            packets_sent=500,
            packets_received=450,
            duration_seconds=0.05,
            jitter_ms=0.35,
        )
        self.assertEqual(metric.protocol, "UDP")
        self.assertAlmostEqual(metric.loss_rate_percent, 10.0)
        self.assertAlmostEqual(metric.delivery_rate_percent, 90.0)
        self.assertEqual(metric.jitter_ms, 0.35)
        self.assertIsNone(metric.avg_latency_ms)


if __name__ == "__main__":
    unittest.main()
