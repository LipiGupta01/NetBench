"""
netbench.metrics
~~~~~~~~~~~~~~~~
Mathematical formulations and data structures for network benchmark evaluation:
- Throughput and Goodput (bps, Mbps)
- Packet Loss & Delivery Rate (%)
- Round-Trip Latency (Min, Mean, Median, Max in milliseconds)
- Interarrival Jitter (RFC 3550 standard in milliseconds)

Viva / Theory Note on Protocol Metrics:
1. TCP (Transmission Control Protocol):
   - Reliable, byte-stream oriented.
   - Packet loss at the network layer is automatically retransmitted by the OS kernel
     via TCP sliding-window flow control and congestion control (e.g., CUBIC).
   - At the socket application layer, loss is 0.0% unless the connection breaks.
   - Latency is measured using request-response (ping-pong echo) Round-Trip Time (RTT).
2. UDP (User Datagram Protocol):
   - Unreliable, message/datagram oriented.
   - No kernel acknowledgments, retransmissions, or congestion throttling.
   - Empirical packet loss rate = (sent - received) / sent * 100%.
   - Interarrival Jitter measures the statistical variance in packet delivery spacing
     according to the RTP standard RFC 3550.
"""

from dataclasses import asdict, dataclass
import datetime
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LatencyStats:
    """
    Statistical distribution of Round-Trip Time (RTT) samples.
    All latency metrics are expressed in milliseconds (ms).
    """
    sample_count: int
    min_ms: Optional[float]
    mean_ms: Optional[float]
    median_ms: Optional[float]
    max_ms: Optional[float]
    std_dev_ms: Optional[float]

    @classmethod
    def empty(cls) -> "LatencyStats":
        """Factory for trials where no valid latency samples exist."""
        return cls(
            sample_count=0,
            min_ms=None,
            mean_ms=None,
            median_ms=None,
            max_ms=None,
            std_dev_ms=None,
        )


@dataclass
class BenchmarkMetric:
    """
    Consolidated performance metric record for a completed benchmark trial.
    Suitable for serialization to CSV, JSON, and conversion to Pandas DataFrame.
    """
    protocol: str                  # "TCP" or "UDP"
    payload_size_bytes: int        # Payload size per packet (bytes)
    packet_count: int              # Configured/target packet count (N)
    packets_sent: int              # Number of packets actually dispatched
    packets_received: int          # Unique packets successfully received
    duration_seconds: float        # Total trial duration (seconds)
    throughput_mbps: float         # Goodput in Megabits per second (Mbps)
    throughput_bps: float          # Goodput in bits per second (bps)
    loss_rate_percent: float       # Lost packet percentage [0.0..100.0]
    delivery_rate_percent: float   # Delivered packet percentage [0.0..100.0]
    avg_latency_ms: Optional[float]    # Mean RTT in ms (None if not measured)
    min_latency_ms: Optional[float]    # Min RTT in ms (None if not measured)
    median_latency_ms: Optional[float] # Median RTT in ms (None if not measured)
    max_latency_ms: Optional[float]    # Max RTT in ms (None if not measured)
    jitter_ms: Optional[float]         # RFC 3550 jitter in ms (None if not measured)
    timestamp: str                 # ISO 8601 formatted timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert metric instance into dictionary representation for tabular display."""
        return asdict(self)


def calculate_throughput(
    payload_bytes_received: int,
    duration_seconds: float,
) -> Tuple[float, float]:
    """
    Calculate application goodput in bits per second and Megabits per second.

    Formula:
      throughput_bps = (payload_bytes_received * 8) / duration_seconds
      throughput_mbps = throughput_bps / 1,000,000

    :param payload_bytes_received: Total payload data received (excluding headers)
    :param duration_seconds: Duration of the benchmark transfer in seconds
    :return: Tuple of (throughput_bps, throughput_mbps)
    :raises ValueError: if payload_bytes_received is negative
    """
    if payload_bytes_received < 0:
        raise ValueError(f"Payload bytes cannot be negative: {payload_bytes_received}")

    if duration_seconds <= 0.0:
        # Avoid division by zero on instantaneous or aborted trials
        return 0.0, 0.0

    total_bits = payload_bytes_received * 8.0
    throughput_bps = total_bits / duration_seconds
    throughput_mbps = throughput_bps / 1_000_000.0
    return throughput_bps, throughput_mbps


def calculate_loss_and_delivery(
    packets_sent: int,
    packets_received: int,
) -> Tuple[int, float, float]:
    """
    Calculate packet loss count, loss percentage, and delivery percentage.

    Formulas:
      loss_count = max(0, packets_sent - packets_received)
      loss_rate_percent = (loss_count / packets_sent) * 100.0
      delivery_rate_percent = (min(packets_received, packets_sent) / packets_sent) * 100.0

    :param packets_sent: Total datagrams/packets dispatched by client
    :param packets_received: Total unique datagrams/packets acknowledged by receiver
    :return: Tuple of (loss_count, loss_rate_percent, delivery_rate_percent)
    :raises ValueError: if packets_sent or packets_received is negative
    """
    if packets_sent < 0 or packets_received < 0:
        raise ValueError(
            f"Packet counts cannot be negative: sent={packets_sent}, received={packets_received}"
        )

    if packets_sent == 0:
        return 0, 0.0, 0.0

    loss_count = max(0, packets_sent - packets_received)
    loss_rate = (loss_count / packets_sent) * 100.0
    delivered = min(packets_received, packets_sent)
    delivery_rate = (delivered / packets_sent) * 100.0

    return loss_count, loss_rate, delivery_rate


def calculate_latency_stats(rtt_samples_ms: List[float]) -> LatencyStats:
    """
    Compute statistical distribution of Round-Trip Time (RTT) samples.

    :param rtt_samples_ms: List of RTT measurements in milliseconds
    :return: LatencyStats dataclass with min, mean, median, max, std_dev
    :raises ValueError: if any sample is negative or non-finite
    """
    if not rtt_samples_ms:
        return LatencyStats.empty()

    for s in rtt_samples_ms:
        if s < 0.0 or math.isnan(s) or math.isinf(s):
            raise ValueError(f"Invalid latency sample: {s} ms (must be non-negative and finite)")

    sample_count = len(rtt_samples_ms)
    min_ms = float(min(rtt_samples_ms))
    max_ms = float(max(rtt_samples_ms))
    mean_ms = float(statistics.mean(rtt_samples_ms))
    median_ms = float(statistics.median(rtt_samples_ms))
    std_dev_ms = float(statistics.stdev(rtt_samples_ms)) if sample_count >= 2 else 0.0

    return LatencyStats(
        sample_count=sample_count,
        min_ms=min_ms,
        mean_ms=mean_ms,
        median_ms=median_ms,
        max_ms=max_ms,
        std_dev_ms=std_dev_ms,
    )


def calculate_rfc3550_jitter(
    send_times_s: List[float],
    arrival_times_s: List[float],
) -> float:
    """
    Calculate interarrival jitter according to RFC 3550 (RTP specification, Section 6.4.1).

    Viva / Mathematical Principle:
    Let S_i be the transmission timestamp of packet i, and R_i be the arrival timestamp.
    For consecutive packets i and j:
      D(i, j) = (R_j - R_i) - (S_j - S_i) = (R_j - S_j) - (R_i - S_i)
    Notice that any constant clock offset between sender and receiver cancels out
    completely: (R_j - S_j) - (R_i - S_i) = (R_j - R_i) - (S_j - S_i).
    The smoothed jitter is updated using an exponentially weighted moving average:
      J_new = J_old + (|D(i, j)| - J_old) / 16

    :param send_times_s: Monotonic transmission times of consecutive packets (in seconds)
    :param arrival_times_s: Monotonic arrival times of consecutive packets (in seconds)
    :return: Smoothed interarrival jitter in milliseconds (ms)
    :raises ValueError: if list lengths mismatch
    """
    if len(send_times_s) != len(arrival_times_s):
        raise ValueError(
            f"Mismatched sample counts: send_times ({len(send_times_s)}) != arrival_times ({len(arrival_times_s)})"
        )

    if len(send_times_s) < 2:
        return 0.0

    jitter_s = 0.0
    for idx in range(1, len(send_times_s)):
        s_prev, s_curr = send_times_s[idx - 1], send_times_s[idx]
        r_prev, r_curr = arrival_times_s[idx - 1], arrival_times_s[idx]

        # Transit time difference
        transit_diff = (r_curr - r_prev) - (s_curr - s_prev)
        abs_diff = abs(transit_diff)

        # RFC 3550 recursive filter: J = J + (|D| - J) / 16
        jitter_s += (abs_diff - jitter_s) / 16.0

    # Convert seconds to milliseconds for display and comparison
    return jitter_s * 1000.0


def create_benchmark_metric(
    protocol: str,
    payload_size_bytes: int,
    packet_count: int,
    packets_sent: int,
    packets_received: int,
    duration_seconds: float,
    rtt_samples_ms: Optional[List[float]] = None,
    jitter_ms: Optional[float] = None,
    timestamp: Optional[str] = None,
) -> BenchmarkMetric:
    """
    Factory helper to assemble a fully populated BenchmarkMetric instance
    from raw experiment measurements.

    :param protocol: "TCP" or "UDP"
    :param payload_size_bytes: Per-packet payload size in bytes
    :param packet_count: Target packet count
    :param packets_sent: Total packets dispatched
    :param packets_received: Unique packets delivered
    :param duration_seconds: Elapsed duration in seconds
    :param rtt_samples_ms: Optional list of RTT measurements in ms
    :param jitter_ms: Optional calculated jitter in ms
    :param timestamp: Optional ISO timestamp (defaults to current UTC time)
    :return: BenchmarkMetric record
    """
    total_payload = packets_received * payload_size_bytes
    throughput_bps, throughput_mbps = calculate_throughput(total_payload, duration_seconds)
    _, loss_rate, delivery_rate = calculate_loss_and_delivery(packets_sent, packets_received)

    if rtt_samples_ms:
        stats = calculate_latency_stats(rtt_samples_ms)
        min_lat = stats.min_ms
        mean_lat = stats.mean_ms
        med_lat = stats.median_ms
        max_lat = stats.max_ms
    else:
        min_lat = mean_lat = med_lat = max_lat = None

    if timestamp is None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return BenchmarkMetric(
        protocol=protocol.upper(),
        payload_size_bytes=payload_size_bytes,
        packet_count=packet_count,
        packets_sent=packets_sent,
        packets_received=packets_received,
        duration_seconds=duration_seconds,
        throughput_mbps=throughput_mbps,
        throughput_bps=throughput_bps,
        loss_rate_percent=loss_rate,
        delivery_rate_percent=delivery_rate,
        avg_latency_ms=mean_lat,
        min_latency_ms=min_lat,
        median_latency_ms=med_lat,
        max_latency_ms=max_lat,
        jitter_ms=jitter_ms,
        timestamp=timestamp,
    )
