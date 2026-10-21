# NetBench: TCP vs UDP Performance Analysis Tool

A college-level Computer Networks project developed in Python to evaluate and compare **TCP** and **UDP** transport-layer protocols under identical, empirical network conditions.

---

## 🎯 Project Objectives

- **Empirical Measurement:** Exchange real socket data over localhost (or LAN) without simulated or fabricated values.
- **Side-by-Side Comparison:** Measure and compare:
  - **Throughput / Goodput** (Mbps)
  - **Latency / Round-Trip Time (RTT)** (Min, Mean, Median, Max in ms)
  - **Packet Loss Rate** & **Delivery Rate** (%)
  - **Interarrival Jitter** (RFC 3550 Standard in ms)
  - **Reliability & Ordering**
- **Viva-Ready Modular Architecture:** Clean separation of network socket logic from the Streamlit analytical dashboard, complete with clear explanations of socket options (`SO_REUSEADDR`, `TCP_NODELAY`, buffering) and framing mechanisms.

---

## 🏗️ Project Structure

```text
NetBench/
├── .venv/                      # Isolated virtual environment
├── .gitignore                  # Git ignore rules
├── requirements.txt            # Direct dependencies (streamlit, pandas, plotly)
├── README.md                   # Project documentation & setup instructions
├── app.py                      # Streamlit interactive benchmark dashboard
├── server_cli.py               # Standalone command-line server manager
│
├── netbench/                   # Pure networking engine
│   ├── __init__.py             # Package marker
│   ├── protocol.py             # Binary packet framing, sequence numbers, headers
│   ├── metrics.py              # Mathematical calculation of throughput, latency, loss, jitter
│   ├── tcp_handler.py          # TCP benchmark client and server session handlers
│   ├── udp_handler.py          # UDP benchmark client and datagram receiver
│   ├── server.py               # Unified background server manager with graceful shutdown
│   ├── runner.py               # Benchmark execution coordinator & validation
│   └── storage.py              # Experiment history serialization & CSV export
│
├── tests/                      # Automated unit and integration tests (74 tests)
│   ├── __init__.py
│   ├── test_protocol.py        # Protocol packing and unpacking tests
│   ├── test_metrics.py         # Metrics calculations verification
│   ├── test_tcp_integration.py # Real TCP socket integration tests
│   ├── test_udp_integration.py # Real UDP socket integration tests
│   ├── test_server.py          # Server lifecycle and CLI tests
│   └── test_dashboard_helpers.py # Dashboard parameter validation, serialization & trial execution
│
└── results/                    # CSV output folder for test results
    └── .gitkeep
```

---

## ⚙️ Prerequisites & Environment Setup

### Prerequisites
- Python 3.10+ (tested with Python 3.14.6)
- Windows / macOS / Linux

### Setup Instructions

1. **Navigate to the project directory:**
   ```powershell
   cd NetBench
   ```

2. **Activate the virtual environment & verify packages:**
   ```powershell
   .\.venv\Scripts\python.exe -c "import streamlit, pandas, plotly; print('Environment OK!')"
   ```

3. **Run Automated Test Suite:**
   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   ```

4. **Launch the Streamlit Dashboard:**
   ```powershell
   .\.venv\Scripts\streamlit.exe run app.py
   ```

5. **(Optional) Run Standalone Server CLI:**
   ```powershell
   .\.venv\Scripts\python.exe server_cli.py --tcp-port 5000 --udp-port 5001
   ```

---

## 🗺️ Project Milestones

- **Phase 1: Environment & Project Scaffolding** *(Completed & Verified)*
- **Phase 2: Protocol Framing & Metrics Engine** *(Completed & Verified - 41 tests)*
- **Phase 3: TCP & UDP Benchmark Handlers** *(Completed & Verified - 53 tests)*
- **Phase 4: Unified Server Manager & Standalone CLI** *(Completed & Verified - 65 tests)*
- **Phase 5: Streamlit Web Dashboard & Integration** *(Completed & Verified - 74 tests)*
  - 5-section UI: Overview, Run Benchmark, Compare Protocols, Experiment History, About & Viva Guide
  - Real socket communication, session history, Plotly comparison charts, CSV export, and Viva guide.
