"""
tests.test_dashboard_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for dashboard helper logic, validation functions,
CSV serialization, and storage persistence.
"""

import os
import unittest

from netbench.metrics import create_benchmark_metric
from netbench.runner import (
    check_configuration_mismatch,
    execute_benchmark_trial,
    validate_trial_parameters,
)
from netbench.server import NetBenchServer
from netbench.storage import (
    metrics_to_csv_string,
    metrics_to_dataframe,
    save_metrics_to_csv,
)


class TestDashboardHelpers(unittest.TestCase):
    """Test suite for validation, formatting, and serialization helpers."""

    def test_parameter_validation_success(self):
        """Valid parameters must pass validation."""
        valid, msg = validate_trial_parameters(
            protocol="TCP",
            test_type="throughput",
            payload_size=1024,
            packet_count=100,
            delay_between_packets=0.0,
            timeout=5.0,
        )
        self.assertTrue(valid)
        self.assertIsNone(msg)

        valid_udp, msg_udp = validate_trial_parameters(
            protocol="UDP",
            test_type="latency",
            payload_size=64,
            packet_count=20,
            delay_between_packets=0.01,
            timeout=3.0,
        )
        self.assertTrue(valid_udp)
        self.assertIsNone(msg_udp)

    def test_parameter_validation_errors(self):
        """Invalid inputs must be rejected with helpful error messages."""
        # Bad protocol
        v, m = validate_trial_parameters("SCTP", "throughput", 1024, 100)
        self.assertFalse(v)
        self.assertIn("Unsupported protocol", m)

        # Bad test type
        v, m = validate_trial_parameters("TCP", "invalid_type", 1024, 100)
        self.assertFalse(v)
        self.assertIn("Unsupported test type", m)

        # Negative payload
        v, m = validate_trial_parameters("TCP", "throughput", -1, 100)
        self.assertFalse(v)

        # UDP payload too large (> 65507)
        v, m = validate_trial_parameters("UDP", "throughput", 70000, 100)
        self.assertFalse(v)
        self.assertIn("Payload size must be between", m)

        # Zero packet count
        v, m = validate_trial_parameters("TCP", "throughput", 1024, 0)
        self.assertFalse(v)

        # Negative delay
        v, m = validate_trial_parameters("UDP", "throughput", 512, 50, delay_between_packets=-0.1)
        self.assertFalse(v)

        # Zero timeout
        v, m = validate_trial_parameters("TCP", "throughput", 512, 50, timeout=0.0)
        self.assertFalse(v)

    def test_configuration_mismatch_detection(self):
        """Warns when comparing trials with mismatched parameters."""
        metric1 = create_benchmark_metric(
            protocol="TCP",
            payload_size_bytes=1024,
            packet_count=100,
            packets_sent=100,
            packets_received=100,
            duration_seconds=0.1,
        )
        metric2 = create_benchmark_metric(
            protocol="UDP",
            payload_size_bytes=1024,
            packet_count=100,
            packets_sent=100,
            packets_received=95,
            duration_seconds=0.08,
        )
        # Matching configs: no warnings
        warnings = check_configuration_mismatch(metric1, metric2)
        self.assertEqual(len(warnings), 0)

        # Mismatched payload size and packet count
        metric3 = create_benchmark_metric(
            protocol="UDP",
            payload_size_bytes=64,
            packet_count=50,
            packets_sent=50,
            packets_received=50,
            duration_seconds=0.02,
        )
        warnings_mismatch = check_configuration_mismatch(metric1, metric3)
        self.assertEqual(len(warnings_mismatch), 2)
        self.assertTrue(any("Payload sizes differ" in w for w in warnings_mismatch))
        self.assertTrue(any("Packet counts differ" in w for w in warnings_mismatch))

    def test_metrics_dataframe_and_csv_serialization(self):
        """Tests DataFrame conversion and CSV string export."""
        metric = create_benchmark_metric(
            protocol="TCP",
            payload_size_bytes=1024,
            packet_count=50,
            packets_sent=50,
            packets_received=50,
            duration_seconds=0.05,
            rtt_samples_ms=[0.5, 0.8],
        )

        # Empty serialization
        self.assertTrue(metrics_to_dataframe([]).empty)
        self.assertEqual(metrics_to_csv_string([]), "")

        # Valid serialization
        df = metrics_to_dataframe([metric])
        self.assertEqual(len(df), 1)
        self.assertEqual(df["protocol"].iloc[0], "TCP")
        self.assertEqual(df["payload_size_bytes"].iloc[0], 1024)

        csv_str = metrics_to_csv_string([metric])
        self.assertIn("TCP", csv_str)
        self.assertIn("throughput_mbps", csv_str)
        self.assertIn("1024", csv_str)

    def test_save_metrics_to_csv_file(self):
        """Tests saving results to the results/ folder."""
        metric = create_benchmark_metric(
            protocol="UDP",
            payload_size_bytes=512,
            packet_count=20,
            packets_sent=20,
            packets_received=18,
            duration_seconds=0.02,
            jitter_ms=0.15,
        )
        test_dir = "results"
        saved_file = save_metrics_to_csv([metric], directory=test_dir, filename_prefix="unit_test_run")
        self.assertIsNotNone(saved_file)
        self.assertTrue(os.path.exists(saved_file))

        # Clean up temporary test file
        try:
            os.remove(saved_file)
        except OSError:
            pass


class TestBenchmarkTrialExecution(unittest.TestCase):
    """Integration test verifying execute_benchmark_trial runs actual socket communication."""

    @classmethod
    def setUpClass(cls):
        cls.server = NetBenchServer(host="127.0.0.1", tcp_port=0, udp_port=0)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop(timeout=2.0)

    def test_tcp_throughput_trial(self):
        metric = execute_benchmark_trial(
            protocol="TCP",
            test_type="throughput",
            payload_size=1024,
            packet_count=50,
            server=self.server,
        )
        self.assertEqual(metric.protocol, "TCP")
        self.assertEqual(metric.packets_sent, 50)
        self.assertEqual(metric.packets_received, 50)
        self.assertEqual(metric.payload_size_bytes, 1024)
        self.assertGreater(metric.throughput_mbps, 0.0)
        self.assertEqual(metric.loss_rate_percent, 0.0)

    def test_tcp_latency_trial(self):
        metric = execute_benchmark_trial(
            protocol="TCP",
            test_type="latency",
            payload_size=64,
            packet_count=10,
            server=self.server,
        )
        self.assertEqual(metric.protocol, "TCP")
        self.assertEqual(metric.packets_sent, 10)
        self.assertEqual(metric.packets_received, 10)
        self.assertIsNotNone(metric.avg_latency_ms)
        self.assertGreater(metric.avg_latency_ms, 0.0)

    def test_udp_burst_trial(self):
        metric = execute_benchmark_trial(
            protocol="UDP",
            test_type="throughput",
            payload_size=512,
            packet_count=30,
            server=self.server,
        )
        self.assertEqual(metric.protocol, "UDP")
        self.assertEqual(metric.packets_sent, 30)
        self.assertGreater(metric.packets_received, 0)
        self.assertEqual(metric.payload_size_bytes, 512)
        self.assertGreater(metric.throughput_mbps, 0.0)

    def test_udp_latency_trial(self):
        metric = execute_benchmark_trial(
            protocol="UDP",
            test_type="latency",
            payload_size=64,
            packet_count=10,
            server=self.server,
        )
        self.assertEqual(metric.protocol, "UDP")
        self.assertEqual(metric.packets_sent, 10)
        self.assertEqual(metric.packets_received, 10)
        self.assertIsNotNone(metric.avg_latency_ms)
        self.assertGreater(metric.avg_latency_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
