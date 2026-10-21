"""
app.py
~~~~~~
NetBench — TCP vs UDP Performance Analysis Tool
Interactive Engineering Dashboard for Computer Networks Laboratory

Evaluates and compares transport layer protocols (TCP vs UDP) under identical
socket conditions over localhost (127.0.0.1).
"""

import datetime
import os
import time
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from netbench.metrics import BenchmarkMetric
from netbench.protocol import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT
from netbench.runner import (
    check_configuration_mismatch,
    execute_benchmark_trial,
    validate_trial_parameters,
)
from netbench.server import NetBenchServer, ServerStartupError
from netbench.storage import metrics_to_csv_string, metrics_to_dataframe, save_metrics_to_csv

# Page Configuration
st.set_page_config(
    page_title="NetBench | TCP vs UDP Analysis",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Human-Designed Engineering Interface Stylesheet
st.markdown(
    """
    <style>
    /* Global App Container */
    .stApp {
        background-color: #f8fafc;
        color: #0f172a;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }

    /* Application Header */
    .app-header {
        padding: 4px 0 14px 0;
        margin-bottom: 16px;
        border-bottom: 1px solid #e2e8f0;
    }
    .app-title {
        font-size: 1.55rem;
        font-weight: 600;
        color: #0f172a;
        letter-spacing: -0.01em;
        line-height: 1.2;
        margin: 0;
    }
    .app-subtitle {
        font-size: 0.95rem;
        color: #475569;
        margin-top: 3px;
        font-weight: 500;
    }
    .app-context {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 2px;
    }

    /* Technical Metric Cards */
    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }
    .metric-card-label {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748b;
        margin-bottom: 4px;
    }
    .metric-card-value {
        font-size: 1.35rem;
        font-weight: 600;
        color: #0f172a;
        line-height: 1.2;
    }
    .metric-card-sub {
        font-size: 0.75rem;
        color: #64748b;
        margin-top: 4px;
    }

    /* Server Status Badges */
    .status-pill-active {
        display: inline-block;
        padding: 3px 8px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #166534;
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-radius: 3px;
        margin-bottom: 8px;
    }
    .status-pill-inactive {
        display: inline-block;
        padding: 3px 8px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #991b1b;
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 3px;
        margin-bottom: 8px;
    }

    /* Engineering Note Boxes */
    .tech-note {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-left: 3px solid #2563eb;
        border-radius: 4px;
        padding: 10px 14px;
        font-size: 0.85rem;
        color: #334155;
        margin: 12px 0;
        line-height: 1.45;
    }
    .tech-warning {
        background: #ffffff;
        border: 1px solid #fecaca;
        border-left: 3px solid #dc2626;
        border-radius: 4px;
        padding: 10px 14px;
        font-size: 0.85rem;
        color: #7f1d1d;
        margin: 12px 0;
        line-height: 1.45;
    /* Sidebar Navigation Radio */
    div[data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 3px;
        margin-bottom: 8px;
    }
    div[data-testid="stSidebar"] div[role="radiogroup"] label {
        padding: 5px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 500;
        color: #334155;
        cursor: pointer;
    }
    div[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background-color: #f1f5f9;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    """Initialize persistent variables in Streamlit session state."""
    if "history" not in st.session_state:
        st.session_state.history: List[BenchmarkMetric] = []
    if "server" not in st.session_state:
        st.session_state.server: Optional[NetBenchServer] = None
    if "preset_payload" not in st.session_state:
        st.session_state.preset_payload: int = 1460
    if "preset_count" not in st.session_state:
        st.session_state.preset_count: int = 100
    if "nav_section" not in st.session_state:
        st.session_state.nav_section: str = "Overview"


def get_or_start_server() -> NetBenchServer:
    """Retrieve the active server instance or initialize and start one."""
    server = st.session_state.server
    if server is None or not server.is_running:
        server = NetBenchServer(host="127.0.0.1", tcp_port=DEFAULT_TCP_PORT, udp_port=DEFAULT_UDP_PORT)
        try:
            server.start()
            st.session_state.server = server
        except ServerStartupError as e:
            st.error(f"Server startup error: {e}")
            raise
    return server


def format_val(val: Optional[float], unit: str = "", precision: int = 2) -> str:
    """Format floating-point metrics with explicit units or em dash if unavailable."""
    if val is None:
        return "—"
    if unit:
        return f"{val:.{precision}f} {unit}"
    return f"{val:.{precision}f}"


def render_metric_card(label: str, value: str, subtext: str = "") -> str:
    """Generate HTML for a compact technical metric card."""
    sub_html = f'<div class="metric-card-sub">{subtext}</div>' if subtext else ""
    return f"""
    <div class="metric-card">
        <div class="metric-card-label">{label}</div>
        <div class="metric-card-value">{value}</div>
        {sub_html}
    </div>
    """


def apply_chart_theme(fig: go.Figure, title: str, yaxis_title: str) -> None:
    """Apply restrained technical styling to Plotly figures."""
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=13, color="#1e293b", family="sans-serif"),
            x=0.01,
            xanchor="left",
        ),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        margin=dict(l=45, r=20, t=35, b=35),
        font=dict(family="sans-serif", size=11, color="#334155"),
        xaxis=dict(
            showline=True,
            linecolor="#cbd5e1",
            linewidth=1,
            gridcolor="#f1f5f9",
            tickfont=dict(size=11, color="#475569"),
        ),
        yaxis=dict(
            title=dict(text=yaxis_title, font=dict(size=11, color="#475569")),
            showline=True,
            linecolor="#cbd5e1",
            linewidth=1,
            gridcolor="#f1f5f9",
            tickfont=dict(size=11, color="#475569"),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        bargap=0.35,
    )


def render_sidebar() -> str:
    """Render navigation menu, server status, and test presets in sidebar."""
    with st.sidebar:
        st.markdown("### Navigation")
        nav_options = [
            "Overview",
            "Run Benchmark",
            "Compare Protocols",
            "Experiment History",
            "About & Viva Guide",
        ]
        selected_section = st.radio(
            "Section Navigation",
            nav_options,
            key="nav_section",
            label_visibility="collapsed",
        )

        st.divider()
        st.markdown("### Server Manager")

        server = st.session_state.server
        is_running = server is not None and server.is_running

        if is_running:
            st.markdown(
                f'<span class="status-pill-active">● Active · 127.0.0.1</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"TCP Port: `{server.tcp_port}` · UDP Port: `{server.udp_port}`")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Stop Server", use_container_width=True):
                    server.stop()
                    st.session_state.server = None
                    st.rerun()
            with col2:
                if st.button("Restart", use_container_width=True):
                    server.stop()
                    time.sleep(0.1)
                    new_server = NetBenchServer(host="127.0.0.1", tcp_port=DEFAULT_TCP_PORT, udp_port=DEFAULT_UDP_PORT)
                    new_server.start()
                    st.session_state.server = new_server
                    st.rerun()
        else:
            st.markdown(
                '<span class="status-pill-inactive">○ Server Inactive</span>',
                unsafe_allow_html=True,
            )
            st.caption("Start listener to accept socket benchmark connections.")
            if st.button("Start Server", type="primary", use_container_width=True):
                try:
                    srv = NetBenchServer(host="127.0.0.1", tcp_port=DEFAULT_TCP_PORT, udp_port=DEFAULT_UDP_PORT)
                    srv.start()
                    st.session_state.server = srv
                    st.rerun()
                except ServerStartupError as e:
                    st.error(f"Startup failed: {e}")

        st.divider()
        def _apply_preset(payload: int, count: int) -> None:
            st.session_state.preset_payload = payload
            st.session_state.preset_count = count
            st.session_state.nav_section = "Run Benchmark"

        st.markdown("### Parameter Presets")
        st.button(
            "64 B · Control / RTT Ping",
            on_click=_apply_preset,
            args=(64, 100),
            use_container_width=True,
        )
        st.button(
            "1,460 B · Standard MTU Frame",
            on_click=_apply_preset,
            args=(1460, 100),
            use_container_width=True,
        )
        st.button(
            "16,384 B · Bulk Transfer",
            on_click=_apply_preset,
            args=(16384, 50),
            use_container_width=True,
        )

        st.divider()
        st.caption("NetBench v1.0 • Computer Networks Laboratory")

    return selected_section


def render_header() -> None:
    """Render permanent top header across all views."""
    st.markdown(
        """
        <div class="app-header">
            <div class="app-title">NetBench</div>
            <div class="app-subtitle">TCP vs UDP Performance Analysis Tool</div>
            <div class="app-context">Computer Networks Laboratory Project • Socket Benchmarking Workbench</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview() -> None:
    """Render introductory project architecture and key metrics summary."""

    st.markdown(
        """
        NetBench measures and compares the empirical behavior of **Transmission Control Protocol (TCP)**
        and **User Datagram Protocol (UDP)** over socket interfaces using a custom 20-byte binary packet format.
        All measurements reflect live socket communication over `127.0.0.1`.
        """
    )

    # Key Statistics Cards
    col1, col2, col3, col4 = st.columns(4)
    total_runs = len(st.session_state.history)
    tcp_runs = sum(1 for m in st.session_state.history if m.protocol == "TCP")
    udp_runs = sum(1 for m in st.session_state.history if m.protocol == "UDP")
    max_throughput = max((m.throughput_mbps for m in st.session_state.history), default=0.0)

    with col1:
        st.markdown(render_metric_card("Total Trials", str(total_runs)), unsafe_allow_html=True)
    with col2:
        st.markdown(render_metric_card("TCP Runs", str(tcp_runs)), unsafe_allow_html=True)
    with col3:
        st.markdown(render_metric_card("UDP Runs", str(udp_runs)), unsafe_allow_html=True)
    with col4:
        tp_str = f"{max_throughput:.2f} Mbps" if max_throughput > 0 else "—"
        st.markdown(render_metric_card("Peak Goodput", tp_str), unsafe_allow_html=True)

    st.markdown("### Protocol Specifications")
    st.markdown(
        """
        | Dimension | TCP (`SOCK_STREAM`) | UDP (`SOCK_DGRAM`) |
        | :--- | :--- | :--- |
        | **Transport Model** | Connection-oriented (3-way handshake) | Stateless datagram dispatch |
        | **Delivery Guarantee** | 100% kernel ARQ (automatic retransmission) | Best-effort; unacknowledged |
        | **Framing** | Continuous byte-stream; requires framing header | Message boundaries preserved natively |
        | **Flow & Congestion** | Dynamic sliding window, ACK pacing, Nagle's algorithm | None; unbounded transmission rate |
        | **Header Overhead** | 20–60 bytes IP/TCP + 20-byte NetBench header | 8 bytes UDP + 20-byte NetBench header |
        | **Target Metrics** | Application Goodput (Mbps), RTT Ping Echo (ms) | Packet Loss Rate (%), Delivery Rate (%), RFC 3550 Jitter (ms) |
        """
    )

    st.markdown(
        """
        <div class="tech-note">
            <strong>Localhost Socket Behavior:</strong> Loopback benchmarking (<code>127.0.0.1</code>) bypasses
            physical network interface cards and transmission media. Packet loss in UDP only occurs when client
            burst transmission exceeds kernel socket buffer queue drain rates. RTT values reflect OS context
            switching and process scheduling rather than propagation delay.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_run_benchmark() -> None:
    """Render benchmark configuration form and execute live socket tests."""
    st.markdown("### Run Benchmark Trial")
    st.caption("Configure parameters to exchange structured binary packets over local sockets.")

    default_payload = st.session_state.preset_payload
    default_count = st.session_state.preset_count

    with st.form("benchmark_config_form"):
        col1, col2 = st.columns(2)

        with col1:
            protocol_choice = st.selectbox(
                "Protocol Mode",
                ["TCP", "UDP", "Comparative (Both TCP & UDP)"],
                help="Select individual protocol or execute sequential runs under identical parameters.",
            )
            test_type = st.selectbox(
                "Measurement Mode",
                ["Throughput (Bulk Transfer)", "Latency (RTT Echo Ping-Pong)"],
                help="Throughput measures sustained delivery rate; Latency measures round-trip time.",
            )

        with col2:
            payload_size = st.number_input(
                "Payload Size per Packet (Bytes)",
                min_value=16,
                max_value=65507,
                value=int(default_payload),
                step=128,
                help="User payload size per packet (excluding 20-byte NetBench binary header).",
            )
            packet_count = st.number_input(
                "Packet Count (N)",
                min_value=5,
                max_value=10000,
                value=int(default_count),
                step=10,
                help="Total number of packets or ping iterations to transmit.",
            )

        with st.expander("Advanced Network Parameters"):
            adv_col1, adv_col2 = st.columns(2)
            with adv_col1:
                delay_between_packets = st.slider(
                    "UDP Inter-Packet Delay (seconds)",
                    min_value=0.0,
                    max_value=0.05,
                    value=0.0,
                    step=0.001,
                    format="%.3f s",
                    help="Client-side inter-packet pause to regulate datagram transmission rate.",
                )
            with adv_col2:
                timeout_s = st.slider(
                    "Socket Timeout (seconds)",
                    min_value=1.0,
                    max_value=15.0,
                    value=5.0,
                    step=1.0,
                    help="Maximum wait time for connection establishment, replies, or socket drain.",
                )

        submit_btn = st.form_submit_button("Run Benchmark Trial", type="primary", use_container_width=True)

    if submit_btn:
        t_type = "throughput" if "Throughput" in test_type else "latency"

        # Verify or start server before running
        try:
            server = get_or_start_server()
        except Exception as e:
            st.error(f"Cannot run benchmark: Server listener unavailable ({e})")
            return

        protocols_to_run = ["TCP", "UDP"] if "Comparative" in protocol_choice else [protocol_choice]
        progress_bar = st.progress(0.0)
        status_box = st.empty()

        for idx, proto in enumerate(protocols_to_run):
            status_box.info(
                f"Executing {proto} {t_type.capitalize()} trial "
                f"({packet_count} packets × {payload_size} B)..."
            )
            try:
                metric = execute_benchmark_trial(
                    protocol=proto,
                    test_type=t_type,
                    payload_size=int(payload_size),
                    packet_count=int(packet_count),
                    server=server,
                    delay_between_packets=delay_between_packets,
                    timeout=timeout_s,
                )
                st.session_state.history.append(metric)
                progress_bar.progress((idx + 1) / len(protocols_to_run))
            except Exception as e:
                status_box.empty()
                st.error(f"Trial execution error for {proto}: {e}")
                return

        time_now = datetime.datetime.now().strftime("%H:%M:%S")
        status_box.success(f"Benchmark execution completed at {time_now}.")
        time.sleep(0.2)

        # Render recent trial metrics
        recent_metrics = st.session_state.history[-len(protocols_to_run):]
        st.markdown("### Trial Results")

        for m in recent_metrics:
            delivered_bytes = m.payload_size_bytes * m.packets_received
            st.markdown(f"**{m.protocol} {t_type.capitalize()}** — `{m.timestamp[:19]}`")

            r_col1, r_col2, r_col3, r_col4 = st.columns(4)

            with r_col1:
                st.markdown(
                    render_metric_card(
                        "Goodput",
                        f"{m.throughput_mbps:.2f} Mbps",
                        f"Delivered: {delivered_bytes:,} B",
                    ),
                    unsafe_allow_html=True,
                )

            with r_col2:
                if m.protocol == "TCP":
                    loss_sub = "0% (Kernel ARQ guaranteed)"
                else:
                    lost = m.packets_sent - m.packets_received
                    loss_sub = f"Lost: {lost} ({m.loss_rate_percent:.1f}%)"
                st.markdown(
                    render_metric_card(
                        "Delivery Rate",
                        f"{m.delivery_rate_percent:.1f}%",
                        loss_sub,
                    ),
                    unsafe_allow_html=True,
                )

            with r_col3:
                rtt_val = format_val(m.avg_latency_ms, "ms", 3)
                if m.min_latency_ms is not None and m.max_latency_ms is not None:
                    rtt_sub = f"Min: {m.min_latency_ms:.2f} ms | Max: {m.max_latency_ms:.2f} ms"
                else:
                    rtt_sub = "Not measured in bulk mode"
                st.markdown(
                    render_metric_card("Mean RTT", rtt_val, rtt_sub),
                    unsafe_allow_html=True,
                )

            with r_col4:
                jitter_val = format_val(m.jitter_ms, "ms", 3)
                dur_sub = f"Elapsed: {m.duration_seconds:.4f} s"
                st.markdown(
                    render_metric_card("RFC 3550 Jitter", jitter_val, dur_sub),
                    unsafe_allow_html=True,
                )

            st.divider()


def render_compare() -> None:
    """Render side-by-side protocol comparison and Plotly engineering charts."""
    st.markdown("### Protocol Comparison")

    history = st.session_state.history
    if len(history) < 2:
        st.info("At least two benchmark trials are required for comparison. Execute trials in the 'Run Benchmark' tab.")
        return

    run_options = [
        f"#{idx+1}: [{m.protocol}] {m.payload_size_bytes}B × {m.packet_count} pkts "
        f"— Goodput: {m.throughput_mbps:.1f} Mbps — {m.timestamp[11:19]}"
        for idx, m in enumerate(history)
    ]

    col1, col2 = st.columns(2)
    with col1:
        idx_a = st.selectbox(
            "Trial A",
            range(len(history)),
            index=max(0, len(history) - 2),
            format_func=lambda i: run_options[i],
        )
    with col2:
        idx_b = st.selectbox(
            "Trial B",
            range(len(history)),
            index=len(history) - 1,
            format_func=lambda i: run_options[i],
        )

    metric_a = history[idx_a]
    metric_b = history[idx_b]

    # Check for configuration mismatch
    mismatch_warnings = check_configuration_mismatch(metric_a, metric_b)
    if mismatch_warnings:
        for w in mismatch_warnings:
            st.markdown(
                f'<div class="tech-warning"><strong>Experimental Validity Warning:</strong> {w}</div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        """
        <div class="tech-note">
            <strong>Environment Context:</strong> Benchmark results reflect socket operations over loopback (<code>127.0.0.1</code>).
            Performance varies with host CPU frequency, operating system process scheduling, and socket buffer queue depths.
            These results do not simulate wide-area network propagation delay.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Comparative Metrics Table
    comp_df = pd.DataFrame([
        {"Parameter / Metric": "Protocol", "Trial A": metric_a.protocol, "Trial B": metric_b.protocol},
        {"Parameter / Metric": "Payload Size (Bytes)", "Trial A": str(metric_a.payload_size_bytes), "Trial B": str(metric_b.payload_size_bytes)},
        {"Parameter / Metric": "Packet Count (N)", "Trial A": str(metric_a.packet_count), "Trial B": str(metric_b.packet_count)},
        {"Parameter / Metric": "Packets Sent", "Trial A": str(metric_a.packets_sent), "Trial B": str(metric_b.packets_sent)},
        {"Parameter / Metric": "Packets Received", "Trial A": str(metric_a.packets_received), "Trial B": str(metric_b.packets_received)},
        {"Parameter / Metric": "Goodput (Mbps)", "Trial A": f"{metric_a.throughput_mbps:.2f}", "Trial B": f"{metric_b.throughput_mbps:.2f}"},
        {"Parameter / Metric": "Packet Loss Rate (%)", "Trial A": f"{metric_a.loss_rate_percent:.1f}%", "Trial B": f"{metric_b.loss_rate_percent:.1f}%"},
        {"Parameter / Metric": "Delivery Rate (%)", "Trial A": f"{metric_a.delivery_rate_percent:.1f}%", "Trial B": f"{metric_b.delivery_rate_percent:.1f}%"},
        {"Parameter / Metric": "Mean RTT Latency", "Trial A": format_val(metric_a.avg_latency_ms, "ms", 3), "Trial B": format_val(metric_b.avg_latency_ms, "ms", 3)},
        {"Parameter / Metric": "RFC 3550 Jitter", "Trial A": format_val(metric_a.jitter_ms, "ms", 3), "Trial B": format_val(metric_b.jitter_ms, "ms", 3)},
        {"Parameter / Metric": "Duration (s)", "Trial A": f"{metric_a.duration_seconds:.4f}", "Trial B": f"{metric_b.duration_seconds:.4f}"},
    ])
    st.table(comp_df)

    # Plotly Charts
    st.markdown("### Comparative Performance Charts")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        # Goodput Comparison Bar Chart
        tp_fig = go.Figure(data=[
            go.Bar(
                x=[f"Trial A ({metric_a.protocol})", f"Trial B ({metric_b.protocol})"],
                y=[metric_a.throughput_mbps, metric_b.throughput_mbps],
                marker_color=[
                    "#2563eb" if metric_a.protocol == "TCP" else "#475569",
                    "#2563eb" if metric_b.protocol == "TCP" else "#475569",
                ],
                text=[f"{metric_a.throughput_mbps:.2f} Mbps", f"{metric_b.throughput_mbps:.2f} Mbps"],
                textposition="auto",
            )
        ])
        apply_chart_theme(tp_fig, "Goodput Comparison", "Goodput (Mbps)")
        st.plotly_chart(tp_fig, use_container_width=True)

    with chart_col2:
        # Delivery & Loss Breakdown Stacked Bar Chart
        deliv_fig = go.Figure(data=[
            go.Bar(
                name="Delivered %",
                x=[f"Trial A ({metric_a.protocol})", f"Trial B ({metric_b.protocol})"],
                y=[metric_a.delivery_rate_percent, metric_b.delivery_rate_percent],
                marker_color="#16a34a",
                text=[f"{metric_a.delivery_rate_percent:.1f}%", f"{metric_b.delivery_rate_percent:.1f}%"],
                textposition="auto",
            ),
            go.Bar(
                name="Lost %",
                x=[f"Trial A ({metric_a.protocol})", f"Trial B ({metric_b.protocol})"],
                y=[metric_a.loss_rate_percent, metric_b.loss_rate_percent],
                marker_color="#dc2626",
                text=[f"{metric_a.loss_rate_percent:.1f}%", f"{metric_b.loss_rate_percent:.1f}%"],
                textposition="auto",
            ),
        ])
        deliv_fig.update_layout(barmode="stack", yaxis_range=[0, 105])
        apply_chart_theme(deliv_fig, "Delivery vs Loss Breakdown", "Percentage (%)")
        st.plotly_chart(deliv_fig, use_container_width=True)

    # RTT Latency comparison if latency was measured in either run
    if metric_a.avg_latency_ms is not None or metric_b.avg_latency_ms is not None:
        lat_fig = go.Figure()
        for label, m in [("Trial A", metric_a), ("Trial B", metric_b)]:
            if m.avg_latency_ms is not None:
                lat_fig.add_trace(go.Bar(
                    x=[f"{label} ({m.protocol})"],
                    y=[m.avg_latency_ms],
                    name=f"{m.protocol} Mean RTT",
                    marker_color="#2563eb" if m.protocol == "TCP" else "#475569",
                    error_y=dict(
                        type="data",
                        symmetric=False,
                        array=[(m.max_latency_ms - m.avg_latency_ms) if m.max_latency_ms else 0],
                        arrayminus=[(m.avg_latency_ms - m.min_latency_ms) if m.min_latency_ms else 0],
                    ) if m.min_latency_ms and m.max_latency_ms else None,
                    text=[f"{m.avg_latency_ms:.3f} ms"],
                    textposition="auto",
                ))
        apply_chart_theme(lat_fig, "Round-Trip Latency (RTT) with Min/Max Spread", "Latency (ms)")
        st.plotly_chart(lat_fig, use_container_width=True)


def render_history() -> None:
    """Render session experiment history, filtering, and CSV export controls."""
    st.markdown("### Experiment History & Data Export")
    st.caption("Experiment history is held in-memory for the active session. Use CSV export to retain data.")

    history = st.session_state.history
    if not history:
        st.info("No benchmark trials recorded in this session. Execute runs under 'Run Benchmark'.")
        return

    # Filter controls
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        proto_filter = st.selectbox("Protocol Filter", ["All", "TCP", "UDP"])
    with f_col2:
        test_type_filter = st.selectbox("Measurement Type Filter", ["All", "Throughput", "Latency"])
    with f_col3:
        st.markdown(render_metric_card("Total Recorded Trials", str(len(history))), unsafe_allow_html=True)

    filtered_history = history
    if proto_filter != "All":
        filtered_history = [m for m in filtered_history if m.protocol == proto_filter]
    if test_type_filter == "Throughput":
        filtered_history = [m for m in filtered_history if m.avg_latency_ms is None]
    elif test_type_filter == "Latency":
        filtered_history = [m for m in filtered_history if m.avg_latency_ms is not None]

    if not filtered_history:
        st.warning("No records match the active filter criteria.")
        return

    df = metrics_to_dataframe(filtered_history)
    # Format table for clean engineering display
    display_df = df.copy()
    display_df = display_df.fillna("—")
    st.dataframe(display_df, use_container_width=True)

    # Export & Persistence Actions
    act_col1, act_col2, act_col3 = st.columns(3)

    with act_col1:
        csv_data = metrics_to_csv_string(filtered_history)
        st.download_button(
            label="Download CSV Log",
            data=csv_data,
            file_name=f"netbench_experiments_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with act_col2:
        if st.button("Save to results/ Directory", use_container_width=True):
            saved_path = save_metrics_to_csv(filtered_history, directory="results")
            if saved_path:
                st.success(f"Persisted: `{os.path.basename(saved_path)}`")

    with act_col3:
        confirm_clear = st.checkbox("Confirm Clear History")
        if st.button("Clear Session History", disabled=not confirm_clear, use_container_width=True):
            st.session_state.history.clear()
            st.rerun()


def render_viva_guide() -> None:
    """Educational reference for Computer Networks laboratory viva examination."""
    st.markdown("### Computer Networks Viva & Theoretical Reference")

    with st.expander("1. Transport Layer Fundamentals: TCP vs UDP", expanded=True):
        st.markdown(
            """
            | Characteristic | TCP (`SOCK_STREAM`) | UDP (`SOCK_DGRAM`) |
            | :--- | :--- | :--- |
            | **Connection State** | Connection-oriented (3-way handshake) | Connectionless (Stateless) |
            | **Reliability** | Guaranteed delivery via ARQ retransmission | Best-effort; unacknowledged |
            | **Stream Ordering** | Strictly in-order stream reconstruction | No ordering guarantee |
            | **Header Size** | 20–60 bytes (flags, seq, ack, window) | 8 bytes (ports, length, checksum) |
            | **Flow & Congestion** | Sliding window, Nagle's algorithm, CUBIC/Reno | None (application regulated) |
            | **Primary Use Cases** | HTTP/HTTPS, SSH, File Transfer | DNS, VoIP, Video Streaming, Gaming |
            """
        )

    with st.expander("2. Stream Framing & NetBench 20-Byte Header Format"):
        st.markdown(
            """
            **Theoretical Context:**
            TCP is a **byte-stream protocol**, not a message-oriented protocol. Sockets treat outgoing data
            as a continuous sequence of bytes. Multiple `sendall()` calls may be coalesced into a single segment,
            or a large buffer may be segmented across multiple packets.
            
            To reliably reconstruct individual application messages, NetBench implements a fixed 20-byte binary header:
            
            ```text
            +-------------------+-------------------+-------------------+
            | Magic: "NB" (2B)  | Version: 0x01 (1B)| Type: Enum (1B)   |
            +-------------------+-------------------+-------------------+
            | Sequence Number: uint32 (4B)          | Payload Len (4B)  |
            +---------------------------------------+-------------------+
            | Monotonic Send Timestamp: float64 / double (8B)           |
            +-----------------------------------------------------------+
            ```
            NetBench's `recv_exact()` reads exactly 20 bytes to parse `payload_length`, then reads precisely that many payload bytes.
            """
        )

    with st.expander("3. Goodput vs Throughput Calculation"):
        st.markdown(
            """
            $$\\text{Goodput (Mbps)} = \\frac{\\text{Total Payload Bytes Delivered} \\times 8}{\\text{Transfer Duration (seconds)} \\times 10^6}$$
            - **Wire Throughput:** Measures total raw bits across the physical link, including Ethernet, IP, TCP/UDP headers, and framing.
            - **Application Goodput:** Measures actual user data payload successfully received by the target socket. NetBench measures Goodput.
            """
        )

    with st.expander("4. UDP Packet Loss Accounting & Sequence Tracking"):
        st.markdown(
            """
            **Mechanism:**
            Because UDP does not send ACKs, each datagram carries an unsigned 32-bit sequence number $i \\in [0, N-1]$.
            The server's `SequenceTracker` records observed sequence numbers into a set.
            When the client signals test completion (`CONTROL_END`), the receiver evaluates:
            $$\\text{Lost Packets} = N_{\\text{sent}} - |\\text{Unique Sequences Received}|$$
            $$\\text{Loss Rate (\\%)} = \\left( \\frac{\\text{Lost Packets}}{N_{\\text{sent}}} \\right) \\times 100.0$$
            """
        )

    with st.expander("5. RTT Echo Ping-Pong & Monotonic Clock Epochs"):
        st.markdown(
            """
            **Viva Question:** *Why can't we compute one-way latency by subtracting send timestamp from receive timestamp?*
            
            **Answer:**
            Python's `time.perf_counter()` uses a monotonic clock whose reference point (epoch) is arbitrary
            (typically system uptime). Separate processes or hosts have independent clock epochs and un-synchronized clocks.
            
            NetBench resolves this by measuring **Round-Trip Time (RTT)**:
            1. Sender records $t_0 = \\text{perf\\_counter()}$ and sends an `ECHO_REQUEST`.
            2. Server immediately reflects back an `ECHO_REPLY` with the same sequence and payload.
            3. Sender receives reply at $t_1 = \\text{perf\\_counter()}$.
            4. $\\text{RTT} = t_1 - t_0$, computed entirely on the sender's own local clock.
            """
        )

    with st.expander("6. RFC 3550 Interarrival Jitter Formulation"):
        st.markdown(
            """
            According to RTP standard **RFC 3550 (Section 6.4.1)**:
            For consecutive datagrams $i$ and $j$, where $S$ is sender dispatch time and $R$ is receiver arrival time:
            $$D(i, j) = (R_j - R_i) - (S_j - S_i) = (R_j - S_j) - (R_i - S_i)$$
            Any static clock offset between sender and receiver cancels out algebraically in this difference.
            The smoothed statistical variance is updated iteratively:
            $$J = J + \\frac{|D(i, j)| - J}{16}$$
            """
        )

    with st.expander("7. Socket Options: TCP_NODELAY & Address Reusability"):
        st.markdown(
            """
            - **`TCP_NODELAY` (Disabling Nagle's Algorithm):** Nagle's algorithm buffers small segments
              to coalesce them into full MSS packets. In RTT ping-pong benchmarks, `TCP_NODELAY = 1` prevents
              unwanted 40ms buffering delays.
            - **`SO_REUSEADDR` & `SO_EXCLUSIVEADDRUSE`:** Prevents socket bind failures when restarting the
              server while previous sockets linger in `TIME_WAIT` state, while protecting against unauthorized
              port hijacking.
            """
        )


def main() -> None:
    """Main dashboard layout and navigation router."""
    init_session_state()
    selected_section = render_sidebar()

    render_header()

    if selected_section == "Overview":
        render_overview()
    elif selected_section == "Run Benchmark":
        render_run_benchmark()
    elif selected_section == "Compare Protocols":
        render_compare()
    elif selected_section == "Experiment History":
        render_history()
    elif selected_section == "About & Viva Guide":
        render_viva_guide()


if __name__ == "__main__":
    main()
