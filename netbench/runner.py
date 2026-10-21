"""
netbench.runner
~~~~~~~~~~~~~~~
Orchestrates benchmark executions, validates test parameters, and detects
configuration discrepancies between comparative runs.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from netbench.metrics import BenchmarkMetric, create_benchmark_metric
from netbench.protocol import MAX_TCP_PAYLOAD_SIZE, MAX_UDP_PAYLOAD_SIZE
from netbench.server import NetBenchServer
from netbench.tcp_handler import TCPBenchmarkClient
from netbench.udp_handler import UDPBenchmarkClient, build_udp_metric_from_summary


def validate_trial_parameters(
    protocol: str,
    test_type: str,
    payload_size: int,
    packet_count: int,
    delay_between_packets: float = 0.0,
    timeout: float = 5.0,
) -> Tuple[bool, Optional[str]]:
    """
    Validate benchmark parameters before initiating socket operations.

    :return: (is_valid, error_message)
    """
    if protocol.upper() not in ("TCP", "UDP"):
        return False, f"Unsupported protocol '{protocol}'. Must be 'TCP' or 'UDP'."

    if test_type.lower() not in ("throughput", "latency"):
        return False, f"Unsupported test type '{test_type}'. Must be 'throughput' or 'latency'."

    max_payload = MAX_UDP_PAYLOAD_SIZE if protocol.upper() == "UDP" else MAX_TCP_PAYLOAD_SIZE
    if payload_size < 1 or payload_size > max_payload:
        return False, f"Payload size must be between 1 and {max_payload} bytes for {protocol}."

    if packet_count < 1 or packet_count > 50000:
        return False, "Packet count must be between 1 and 50,000."

    if delay_between_packets < 0.0 or delay_between_packets > 1.0:
        return False, "Inter-packet delay must be between 0.0 and 1.0 seconds."

    if timeout < 0.1 or timeout > 60.0:
        return False, "Timeout must be between 0.1 and 60.0 seconds."

    return True, None


def check_configuration_mismatch(
    metric_a: BenchmarkMetric,
    metric_b: BenchmarkMetric,
) -> List[str]:
    """
    Check if two benchmark runs have differing experimental parameters,
    which would undermine fair scientific comparison.

    :return: List of warning strings
    """
    warnings = []

    type_a = "Latency" if metric_a.avg_latency_ms is not None else "Throughput"
    type_b = "Latency" if metric_b.avg_latency_ms is not None else "Throughput"
    if type_a != type_b:
        warnings.append(
            f"Test types differ ({metric_a.protocol}: {type_a} test vs "
            f"{metric_b.protocol}: {type_b} test). Comparing throughput against latency ping-pong is invalid."
        )

    if metric_a.payload_size_bytes != metric_b.payload_size_bytes:
        warnings.append(
            f"Payload sizes differ ({metric_a.protocol}: {metric_a.payload_size_bytes} B vs "
            f"{metric_b.protocol}: {metric_b.payload_size_bytes} B). Fair comparison requires identical payload sizes."
        )

    if metric_a.packet_count != metric_b.packet_count:
        warnings.append(
            f"Packet counts differ ({metric_a.protocol}: {metric_a.packet_count} packets vs "
            f"{metric_b.protocol}: {metric_b.packet_count} packets)."
        )

    return warnings


def execute_benchmark_trial(
    protocol: str,
    test_type: str,
    payload_size: int,
    packet_count: int,
    server: NetBenchServer,
    delay_between_packets: float = 0.0,
    timeout: float = 5.0,
) -> BenchmarkMetric:
    """
    Execute a real network benchmark trial against the running NetBenchServer.

    :param protocol: "TCP" or "UDP"
    :param test_type: "throughput" or "latency"
    :param payload_size: Size per packet in bytes
    :param packet_count: Number of packets / pings
    :param server: Active NetBenchServer instance
    :param delay_between_packets: Inter-packet throttling (UDP only)
    :param timeout: Socket timeout (seconds)
    :return: Completed BenchmarkMetric record
    :raises RuntimeError: If server is not running or parameters are invalid
    """
    is_valid, err_msg = validate_trial_parameters(
        protocol=protocol,
        test_type=test_type,
        payload_size=payload_size,
        packet_count=packet_count,
        delay_between_packets=delay_between_packets,
        timeout=timeout,
    )
    if not is_valid:
        raise ValueError(err_msg)

    if not server.is_running:
        raise RuntimeError(
            "NetBenchServer is not currently running. Please start the server before launching benchmarks."
        )

    proto = protocol.upper()
    ttype = test_type.lower()

    if proto == "TCP":
        client = TCPBenchmarkClient(host=server.host, port=server.tcp_port, timeout=timeout)
        if ttype == "throughput":
            return client.run_throughput_test(payload_size=payload_size, packet_count=packet_count)
        else:
            return client.run_latency_test(payload_size=payload_size, ping_count=packet_count)

    elif proto == "UDP":
        client = UDPBenchmarkClient(host=server.host, port=server.udp_port, timeout=timeout)
        if ttype == "throughput":
            with server._lock:
                server._latest_udp_summary = None

            client_stats = client.run_burst_test(
                payload_size=payload_size,
                packet_count=packet_count,
                delay_between_packets=delay_between_packets,
            )
            # Bounded poll for server listener to finalize sequence accounting from CONTROL_END
            deadline = time.perf_counter() + 0.5
            summary = None
            while time.perf_counter() < deadline:
                status = server.get_status()
                summary = status.get("latest_udp_summary")
                if summary:
                    break
                time.sleep(0.02)

            if summary:
                return build_udp_metric_from_summary(client_stats, summary, payload_size=payload_size)
            else:
                # Fallback if server summary was not populated
                return create_benchmark_metric(
                    protocol="UDP",
                    payload_size_bytes=payload_size,
                    packet_count=packet_count,
                    packets_sent=client_stats["packets_sent"],
                    packets_received=client_stats["packets_sent"],
                    duration_seconds=client_stats["send_duration_seconds"],
                )
        else:
            return client.run_latency_test(
                payload_size=payload_size,
                ping_count=packet_count,
                timeout=timeout,
            )

    raise ValueError(f"Unknown combination: {protocol} / {test_type}")
