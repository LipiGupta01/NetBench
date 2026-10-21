"""
netbench.storage
~~~~~~~~~~~~~~~~
Persistence and data conversion utilities for NetBench benchmark runs:
- Converts BenchmarkMetric objects to Pandas DataFrame
- Generates CSV string representations for Streamlit download
- Persists experimental logs to the results/ directory
"""

import csv
import datetime
import io
import os
from typing import Any, Dict, List, Optional
import pandas as pd

from netbench.metrics import BenchmarkMetric


def metrics_to_dataframe(metrics: List[BenchmarkMetric]) -> pd.DataFrame:
    """
    Convert a list of BenchmarkMetric instances into a Pandas DataFrame.

    :param metrics: List of BenchmarkMetric records
    :return: Formatted DataFrame
    """
    if not metrics:
        return pd.DataFrame()

    records = [m.to_dict() for m in metrics]
    df = pd.DataFrame(records)

    # Reorder columns logically for clean display
    column_order = [
        "timestamp",
        "protocol",
        "payload_size_bytes",
        "packet_count",
        "packets_sent",
        "packets_received",
        "throughput_mbps",
        "loss_rate_percent",
        "delivery_rate_percent",
        "avg_latency_ms",
        "min_latency_ms",
        "median_latency_ms",
        "max_latency_ms",
        "jitter_ms",
        "duration_seconds",
    ]
    existing_cols = [c for c in column_order if c in df.columns]
    extra_cols = [c for c in df.columns if c not in column_order]
    return df[existing_cols + extra_cols]


def metrics_to_csv_string(metrics: List[BenchmarkMetric]) -> str:
    """
    Serialize a list of BenchmarkMetric instances to a CSV string.

    :param metrics: List of BenchmarkMetric records
    :return: CSV formatted text
    """
    if not metrics:
        return ""

    df = metrics_to_dataframe(metrics)
    return df.to_csv(index=False)


def save_metrics_to_csv(
    metrics: List[BenchmarkMetric],
    directory: str = "results",
    filename_prefix: str = "netbench_results",
) -> Optional[str]:
    """
    Save a list of BenchmarkMetric records to a CSV file in the specified directory.

    :param metrics: List of BenchmarkMetric records
    :param directory: Output folder (defaults to 'results')
    :param filename_prefix: Prefix for the generated filename
    :return: Path of saved file, or None if list is empty
    """
    if not metrics:
        return None

    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(directory, f"{filename_prefix}_{timestamp}.csv")

    df = metrics_to_dataframe(metrics)
    df.to_csv(filepath, index=False)
    return filepath
