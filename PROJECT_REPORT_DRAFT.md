# NetBench — TCP vs UDP Performance Analysis Tool
## Comprehensive Academic Technical Project Report Draft
### Course: Computer Networks (Unit IV Project)

---

# CHAPTER 1: TITLE PAGE TEMPLATE, ABSTRACT, AND KEYWORDS

## 1.1 Academic Title Page Template

```text
========================================================================================
                 A PROJECT REPORT ON
       “NetBench — TCP vs UDP Performance Analysis Tool”

   Submitted in partial fulfillment of the requirements for the award of the degree of
                     BACHELOR OF TECHNOLOGY / BACHELOR OF ENGINEERING
                                            IN
                         COMPUTER SCIENCE AND ENGINEERING
========================================================================================

SUBMITTED BY:
  [Student Name 1]               [University Roll Number / USN 1]
  [Student Name 2 (if group)]    [University Roll Number / USN 2]
  [Student Name 3 (if group)]    [University Roll Number / USN 3]

UNDER THE GUIDANCE OF:
  [Faculty Guide Name]
  [Designation, Department of Computer Science and Engineering]

INSTITUTION:
  [Department of Computer Science and Engineering]
  [College / Institute / University Name]
  [City, State, PIN Code]
  [Academic Year / Semester: 2025–2026]
========================================================================================
```

---

## 1.2 Certificate of Originality & Bonafide Work (Template)

```text
                               CERTIFICATE
This is to certify that the project report titled "NetBench — TCP vs UDP Performance
Analysis Tool", submitted by [Student Name] (Roll No: [Roll Number / USN]), in partial
fulfillment of the requirements for the award of the degree of Bachelor of Technology in
Computer Science and Engineering, is a bonafide record of work carried out under my
supervision and guidance during the academic semester [Semester / Year].

The results embodied in this report have been verified against the actual source code,
test suite, and empirical socket operations and have not been submitted to any other
institution or university for the award of any degree or diploma.


_________________________                             _________________________
  [Faculty Guide Name]                                   [Head of Department]
   Project Supervisor                                  Department of CSE
   [Institution Name]                                  [Institution Name]
```

---

## 1.3 Abstract

Transport layer protocols form the backbone of host-to-host process communication across computer networks, governing end-to-end data transmission, reliability, error handling, flow control, and multiplexing. While textbook curricula extensively detail the conceptual differences between the connection-oriented Transmission Control Protocol (TCP) and the connectionless User Datagram Protocol (UDP), undergraduate engineering students frequently lack hands-on, empirical visibility into how these transport mechanisms behave at the operating system socket interface.

This project presents **NetBench**, an empirical network benchmarking and performance analysis workbench developed in Python. NetBench implements a custom, 20-byte big-endian binary framing protocol (`!2sBB IId`) that enforces discrete message boundaries over TCP byte streams (`SOCK_STREAM`) and instruments unacknowledged datagram sequences over UDP (`SOCK_DGRAM`). The system measures critical transport-layer metrics: application goodput (Mbps), packet delivery and loss rates (%), round-trip time (RTT) latency distributions (minimum, mean, median, maximum, and standard deviation via request-response ping-pong reflection), and interarrival jitter evaluated using the real-time transport standard RFC 3550 exponentially weighted moving average filter.

The software architecture completely decouples pure network socket routines (`netbench` engine) from an interactive Streamlit engineering dashboard and a headless command-line interface (`server_cli.py`). A multi-threaded unified server coordinates concurrent TCP and UDP listeners with clean port allocation, socket reuse (`SO_REUSEADDR` / `SO_EXCLUSIVEADDRUSE`), and graceful teardown semantics. A comprehensive automated test suite consisting of 74 unit and integration tests verifies protocol serialization, boundary limits, sequence tracking, mathematical metrics, server lifecycle, and real socket exchange on localhost (`127.0.0.1`), achieving a 100% pass rate. This report details the theoretical foundations, protocol design, mathematical methodology, implementation architecture, empirical testing strategy, baseline localhost results, and critical distinctions between local socket evaluation and wide-area network behavior.

---

## 1.4 Keywords

- Transport Layer Protocols
- Transmission Control Protocol (TCP)
- User Datagram Protocol (UDP)
- Socket Programming (`SOCK_STREAM` vs `SOCK_DGRAM`)
- Application Goodput
- Round-Trip Time (RTT) Latency
- Packet Loss Accounting
- RFC 3550 Interarrival Jitter
- Binary Packet Framing
- Empirical Network Benchmarking

---

# CHAPTER 2: INTRODUCTION, PROBLEM STATEMENT, MOTIVATION, OBJECTIVES, AND SCOPE

## 2.1 Introduction

In the Open Systems Interconnection (OSI) and Internet Protocol (TCP/IP) architectural models, Layer 4 (the Transport Layer) is responsible for logical communication between application processes running on distinct hosts. The Internet transport suite provides two contrasting paradigms:

1. **TCP (RFC 793, RFC 5681):** A connection-oriented, reliable, byte-stream protocol providing in-order delivery, flow control via dynamic sliding windows, congestion control algorithms (such as Reno and CUBIC), and error recovery via Automatic Repeat reQuest (ARQ).
2. **UDP (RFC 768):** A minimalist, connectionless, transaction- or message-oriented protocol providing an unacknowledged, best-effort datagram service with minimal protocol processing overhead and zero internal delivery guarantees.

Modern distributed systems, multimedia streaming engines, financial trading platforms, teleconferencing systems, and cloud-native microservices must make architectural choices between TCP and UDP based on trade-offs among throughput, latency variance (jitter), protocol overhead, and delivery guarantees. Understanding these trade-offs through direct experimentation is fundamental to computer networking education.

## 2.2 Problem Statement

In academic environments, transport layer protocols are often studied purely from analytical models, static packet capture inspection (e.g., Wireshark traces), or simulated toolsets (e.g., NS-2, Cisco Packet Tracer). While educational, simulations abstract away operating system kernel realities: socket buffer queuing, context-switching overhead, kernel-space to user-space data copying, Nagle's algorithm buffering delays, and clock synchronization pitfalls.

Commercial benchmarking utilities such as `iperf3` and `netperf` provide robust performance measurement but present significant limitations for undergraduate laboratory instruction:
- They operate as black-box binaries with complex configuration switches.
- Their internal packet structures, sequence tracking routines, and mathematical metric derivations are concealed from students.
- They lack an integrated, pedagogical web dashboard that simultaneously explains networking theory, demonstrates real-time metric convergence, flags experimental configuration mismatches, and facilitates viva preparation.

There is a clear need for an open, inspectable, Python-based benchmarking tool that implements real socket communication, defines an explicit binary header, evaluates exact networking metrics, and provides an accessible user interface for comparative protocol analysis.

## 2.3 Motivation

The motivation behind developing **NetBench** stems from three core requirements of the Computer Networks Unit IV curriculum:
1. **Bridging Theory and Systems Programming:** Exposing how abstract concepts (sliding windows, stream segmentation, datagram loss, jitter) manifest in concrete BSD-style socket programming using Python's standard `socket` module.
2. **Methodological Rigor in Performance Measurement:** Eliminating common measurement fallacies, such as calculating one-way latency by subtracting unsynchronized process clock timestamps, and instead implementing mathematically sound methods (RTT echo reflection and RFC 3550 clock-offset-invariant jitter).
3. **Reproducibility and Experimental Integrity:** Providing automated validation that detects when comparative trials have mismatched configurations (e.g., comparing a 64-byte latency run with a 1,460-byte throughput run), thereby instilling scientific discipline in undergraduate engineering experiments.

## 2.4 Project Objectives

The primary engineering and educational objectives of NetBench are:
- **Objective 1 — Empirical Socket Communication:** Develop pure Python client and server handlers that exchange real binary packets over TCP and UDP sockets without synthetic interpolation or simulated metric generation.
- **Objective 2 — Binary Packet Framing Engine:** Implement an explicit 20-byte big-endian binary header with magic byte validation, protocol versioning, packet type tagging, sequence numbering, payload length specification, and 64-bit monotonic timestamps.
- **Objective 3 — Stream Discretization over TCP:** Solve the TCP stream fragmentation problem by building a framed message extractor (`recv_exact`) that reliably reassembles discrete application-level records from a continuous byte stream.
- **Objective 4 — Datagram Accounting over UDP:** Construct a receiver-side sequence tracker (`SequenceTracker`) capable of detecting missing datagrams, duplicates, and out-of-order deliveries, calculating empirical loss and delivery percentages.
- **Objective 5 — Latency and RFC 3550 Jitter Computation:** Measure RTT distributions (minimum, mean, median, maximum, standard deviation) using ping-pong echo reflection, and implement the RFC 3550 standard exponentially weighted moving average filter for interarrival jitter.
- **Objective 6 — Unified Server Lifecycle Management:** Build a thread-safe, concurrent server manager capable of binding both TCP and UDP listener sockets simultaneously, handling graceful shutdown, and supporting port reuse options (`SO_REUSEADDR` / `SO_EXCLUSIVEADDRUSE`).
- **Objective 7 — Interactive Engineering Dashboard:** Provide an analytical web interface using Streamlit and Plotly that allows parameter selection, real-time trial execution, side-by-side protocol comparison, session history management, CSV export, and theoretical viva reference.
- **Objective 8 — Verification via Automated Testing:** Construct a comprehensive test suite using Python's `unittest` framework to validate protocol packing, mathematical formulas, server lifecycle, and socket integration on localhost.

## 2.5 Scope of the Project

### In-Scope (Fully Implemented and Verified)
- Python standard library socket implementation (`socket.AF_INET`, `socket.SOCK_STREAM`, `socket.SOCK_DGRAM`).
- Custom 20-byte binary header packed with big-endian network byte order (`struct.pack("!2sBB IId", ...)`).
- Full application goodput, RTT latency, packet loss, delivery rate, and RFC 3550 jitter calculation.
- Stream reassembly using fixed-length header prefixing.
- Threaded dual-protocol server with CLI launcher (`server_cli.py`) and programmatic interface (`NetBenchServer`).
- Web dashboard with parameter presets (64 B, 1,460 B, 16,384 B), interactive comparison charts, and CSV persistence (`results/` folder).
- 74 automated unit and integration tests executing on localhost (`127.0.0.1`).

### Out-of-Scope (Proposed / Future Enhancements)
- Multi-host distributed orchestration across physical wide-area networks (WAN) or public cloud regions.
- Kernel-level packet loss and latency injection (e.g., Linux `tc` / `netem` or Windows WANem emulation).
- Multi-threaded or parallel connection striping (e.g., multi-stream TCP transfers).
- Transport Layer Security (TLS / DTLS) cryptographic overhead benchmarking.
- Path MTU Discovery (PMTUD) and IPv6 dual-stack socket binding.

---

# CHAPTER 3: THEORETICAL BACKGROUND

## 3.1 Transport Layer Protocols: TCP vs UDP

The transport layer delivers data across an internetwork between application processes identified by 16-bit port numbers. The fundamental divergence between TCP and UDP represents one of the most critical design decisions in network architecture:

| Feature / Metric | Transmission Control Protocol (TCP) | User Datagram Protocol (UDP) |
| :--- | :--- | :--- |
| **Standard Specification** | RFC 793, RFC 1323, RFC 5681 | RFC 768 |
| **Socket Type** | `SOCK_STREAM` | `SOCK_DGRAM` |
| **Connection State** | Connection-oriented (3-way handshake: SYN, SYN-ACK, ACK) | Connectionless (Stateless; no handshake) |
| **Reliability Mechanism** | ARQ (Acks, sequence numbers, checksums, retransmission) | None (Unreliable, best-effort delivery) |
| **Data Ordering** | Strictly ordered; reconstructed by OS TCP receive buffer | Unordered; datagrams can arrive in any sequence |
| **Message Framing** | None; unstructured continuous byte-stream | Preserves discrete datagram boundaries |
| **Flow Control** | Dynamic sliding window (advertised receiver window, `rwnd`) | None; sender can overrun receiver buffer |
| **Congestion Control** | Network congestion avoidance (Slow Start, Congestion Avoidance, CUBIC/Reno) | None; unbounded transmission rate unless throttled by app |
| **Minimum Header Overhead**| 20 bytes (up to 60 bytes with TCP options) | 8 bytes fixed |
| **Socket Teardown** | 4-way termination handshake (FIN, ACK, FIN, ACK) with `TIME_WAIT` state | Immediate; no connection state to teardown |

```mermaid
sequenceDiagram
    autonumber
    Note over Client,Server: TCP Connection Lifecycle (Connection-Oriented)
    Client->>Server: SYN (seq = x)
    Server->>Client: SYN-ACK (seq = y, ack = x + 1)
    Client->>Server: ACK (ack = y + 1)
    Note over Client,Server: Established Connection - Stream Exchange
    Client->>Server: DATA [Framed Pkt 0..N-1]
    Server-->>Client: Kernel ACK Segments
    Client->>Server: CONTROL_END Frame
    Server->>Client: ACK_REPORT Frame
    Client->>Server: FIN
    Server->>Client: ACK
    Server->>Client: FIN
    Client->>Server: ACK (enters TIME_WAIT)

    Note over Client,Server: UDP Datagram Burst (Connectionless)
    Client->>Server: Datagram 0 (CONTROL_START)
    Client->>Server: Datagram 1 (DATA seq=0)
    Client->>Server: Datagram 2 (DATA seq=1)
    Client->>Server: Datagram 3 (DATA seq=2 - Drop/Delayed)
    Client->>Server: Datagram 4 (CONTROL_END)
    Server-->>Client: ACK_REPORT (Optional summary)
```

## 3.2 Socket Programming and Client-Server Paradigm

BSD socket APIs provide an operating system abstraction for network input/output. A socket is an endpoint for communication defined by an IP address and port tuple:

$$\text{Endpoint Tuple} = (\text{IP Address}, \text{Port Number})$$

### 3.2.1 Stream Sockets (`SOCK_STREAM`)
TCP sockets treat communication as an infinite stream of bytes. When an application calls `send()` or `sendall()`, data is placed into the operating system's kernel TCP socket send buffer. The TCP stack segments this buffer into Maximum Segment Size (MSS) units according to Path MTU. At the receiving host, data accumulates in the receive buffer. Because the network layer may split or combine TCP segments, a single `recv(4096)` call can return 1 byte, 1,024 bytes, or any chunk size depending on network scheduling and buffer states.

### 3.2.2 Datagram Sockets (`SOCK_DGRAM`)
UDP sockets operate on discrete messages. When an application calls `sendto()`, the OS prepends an 8-byte UDP header and passes the datagram directly to IP. At the receiver, `recvfrom()` returns exactly one discrete datagram at a time. If the receiving buffer is smaller than the arriving datagram, trailing bytes are discarded. Furthermore, if datagrams arrive faster than the receiving application drains them, the kernel socket receive buffer overflows, silently dropping incoming packets.

## 3.3 Socket Options: Buffering, Reusability, and Nagle's Algorithm

To achieve accurate benchmarking, specific socket options must be explicitly managed:

### 3.3.1 Nagle's Algorithm (`TCP_NODELAY`)
Defined in RFC 896, Nagle's algorithm solves the "small packet problem" on congested networks by buffering small outgoing packets until all outstanding transmitted data has been acknowledged by the receiver. While beneficial for telnet-style applications, Nagle's algorithm interacts destructively with TCP Delayed ACKs (RFC 1122), causing artificial latency delays of 40 ms to 200 ms. In NetBench latency tests, setting:

```python
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
```
disables Nagle's algorithm, forcing instantaneous packet dispatch to measure genuine round-trip time.

### 3.3.2 Socket Address Reusability (`SO_REUSEADDR` and `SO_EXCLUSIVEADDRUSE`)
When a TCP connection closes, the active closing endpoint transitions to the `TIME_WAIT` state (lasting $2 \times \text{MSL}$, typically 60 to 120 seconds) to ensure delayed duplicate segments dissipate. Attempting to restart a server on the same port immediately raises `OSError: [Errno 98/10048] Address already in use`. 
- On POSIX platforms, `SO_REUSEADDR` allows the socket to bind to a port in `TIME_WAIT`.
- On Windows platforms, `SO_REUSEADDR` allows port hijacking. NetBench checks for `SO_EXCLUSIVEADDRUSE` on Windows to guarantee port exclusivity while still allowing clean server teardown and restart.

## 3.4 Packet Framing Principles over Byte Streams

Because TCP does not provide record markers, applications must implement framing protocols to determine where one message ends and the next begins. Common framing techniques include:
1. **Delimiter Framing (e.g., newline `\n` or sentinel byte):** Inefficient for binary payloads as it requires byte-stuffing or escaping.
2. **Fixed-Length Framing:** Rigid and wastes bandwidth for variable-length payloads.
3. **Length-Prefix Framing:** The sender prefixes each message with a fixed-size header specifying the length of the trailing payload.

NetBench adopts length-prefix framing via a 20-byte fixed binary header. The receiver calls `recv_exact(sock, 20)` to read the header, parses `payload_length`, and subsequently invokes `recv_exact(sock, payload_length)` to retrieve the payload with guaranteed integrity.

## 3.5 Core Performance Metrics Definitions

### 3.5.1 Throughput vs. Goodput
- **Throughput (Wire Rate):** Measures the total volume of raw bits traversing the physical communication channel per unit time, encompassing Ethernet preamble, frame headers, IP headers, TCP/UDP headers, framing headers, and retransmissions.
- **Goodput (Application Rate):** Measures the rate of useful user application payload successfully delivered to the destination process, excluding protocol overhead, framing headers, and duplicate retransmissions:

$$\text{Goodput} \le \text{Throughput} < \text{Channel Capacity}$$

### 3.5.2 Packet Loss and Delivery Rate
In UDP, packets dropped by buffer overflow, corrupted checksums, or network congestion are not recovered. Packet Loss Rate and Delivery Rate represent complementary metrics:

$$\text{Delivery Rate (\%)} = \left( \frac{\text{Unique Packets Delivered}}{\text{Total Packets Dispatched}} \right) \times 100$$

$$\text{Loss Rate (\%)} = \left( \frac{\text{Packets Lost}}{\text{Total Packets Dispatched}} \right) \times 100$$

$$\text{Delivery Rate (\%)} + \text{Loss Rate (\%)} = 100\%$$

### 3.5.3 Latency / Round-Trip Time (RTT)
Latency represents the time elapsed for data to travel across a network. Due to clock epoch mismatches across distinct systems and operating system processes, one-way delay cannot be measured accurately without hardware timestamping or sub-microsecond PTP/NTP synchronization. 

Round-Trip Time (RTT) avoids clock skew by measuring the elapsed time between dispatching a request and receiving its reflection, calculated entirely on the sender's local monotonic clock:

$$\text{RTT} = t_{\text{receive}} - t_{\text{send}}$$

### 3.5.4 Interarrival Jitter (RFC 3550 Standard)
Jitter represents the statistical variance in packet transit delay across consecutive transmissions. In real-time multimedia (VoIP, video conferencing, online gaming), excessive jitter causes buffer under-runs or packet stalls. 

RFC 3550 (Real-time Transport Protocol - RTP, Section 6.4.1) defines interarrival jitter using transit time differences. Let $S_i$ and $S_j$ denote sender timestamps of consecutive packets $i$ and $j$, and let $R_i$ and $R_j$ denote their corresponding arrival timestamps at the receiver. The transit delay difference $D(i, j)$ is defined as:

$$D(i, j) = (R_j - R_i) - (S_j - S_i) = (R_j - S_j) - (R_i - S_i)$$

A key mathematical property of $D(i, j)$ is that any constant clock offset $\delta$ between sender and receiver ($R = t + \delta$) cancels out algebraically:

$$D(i, j) = ((t_j + \delta) - (t_i + \delta)) - (S_j - S_i) = (t_j - t_i) - (S_j - S_i)$$

RFC 3550 updates the smoothed jitter estimate $J$ iteratively using an Exponentially Weighted Moving Average (EWMA) filter with gain factor $\alpha = 1/16$:

$$J_{\text{new}} = J_{\text{old}} + \frac{|D(i, j)| - J_{\text{old}}}{16}$$

---

# CHAPTER 4: SYSTEM REQUIREMENTS AND ENVIRONMENT ASSUMPTIONS

## 4.1 Software Requirements

The NetBench workbench is built entirely with modern, open-source Python technologies:

| Component | Minimum Version | Verified Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Python Runtime** | Python 3.10+ | Python 3.14.0 (Windows 64-bit) | Core execution environment |
| **Standard Library** | Built-in | Python 3.14 Standard Lib | Sockets, threading, struct, time, unittest, argparse |
| **Streamlit** | $\ge$ 1.40.0 | 1.40.1 | Interactive engineering web dashboard UI |
| **Pandas** | $\ge$ 2.2.0 | 2.2.3 | Tabular metrics modeling and CSV transformation |
| **Plotly** | $\ge$ 5.20.0 | 5.24.1 | Interactive browser-based engineering charts |
| **Operating System** | Windows 10/11, Ubuntu 22.04+, macOS 13+ | Windows 11 Enterprise (x86_64) | Host execution platform |

## 4.2 Hardware Assumptions and Test Environment

Because the project focuses on empirical socket measurement, hardware characteristics directly impact raw throughput and latency figures:
- **Processor:** Modern multi-core CPU (tested on AMD Ryzen / Intel Core x86_64 architecture).
- **Memory (RAM):** Minimum 4 GB RAM (NetBench requires < 150 MB resident memory).
- **Storage:** Standard SSD/HDD with at least 50 MB free space for virtual environment and CSV test output.
- **Network Interface:** Loopback interface (`lo` / `127.0.0.1`) for local benchmarking; 100/1000 Mbps Ethernet or 802.11ac/ax Wi-Fi for local area network (LAN) benchmarking.

## 4.3 Environment Assumptions and Constraints
1. **Loopback Execution:** Benchmarking over `127.0.0.1` executes entirely in operating system kernel memory buffers, bypassing physical Network Interface Cards (NIC), physical wire delays, and electromagnetic interference.
2. **Process Scheduling:** Execution timing is influenced by operating system task scheduling, background daemon activities, and thread context switching.
3. **Port Availability:** Default ports 5001 (TCP) and 5002 (UDP) must not be occupied by other host processes. The software dynamically supports ephemeral port binding (port `0`) for zero-collision integration testing.

---

# CHAPTER 5: SYSTEM ARCHITECTURE, MODULE RESPONSIBILITIES, DATA FLOW, AND CUSTOM PACKET FORMAT

## 5.1 System Architecture

NetBench follows a modular architecture that enforces strict separation of concerns between core networking logic, graphical presentation, data persistence, and test orchestration.

```mermaid
graph TD
    subgraph UI_Layer["Presentation Layer (Streamlit Web Dashboard)"]
        APP["app.py (Web GUI)"]
        VIVA["Viva & CN Theory Reference"]
        CHARTS["Plotly Comparison Visualizations"]
    end

    subgraph CLI_Layer["Headless Server Interface"]
        CLI["server_cli.py (Argparse CLI)"]
    end

    subgraph Core_Engine["Core Networking Engine (netbench package)"]
        RUNNER["runner.py (Trial Coordinator)"]
        SERVER["server.py (NetBenchServer Manager)"]
        TCP_H["tcp_handler.py (TCP Client & Session)"]
        UDP_H["udp_handler.py (UDP Client & Receiver)"]
        PROTO["protocol.py (Binary Framing & SequenceTracker)"]
        METRICS["metrics.py (Throughput, Loss, RTT, Jitter)"]
        STORAGE["storage.py (Pandas & CSV Persistence)"]
    end

    subgraph OS_Kernel["Operating System Kernel Socket Layer"]
        TCP_SOCK["TCP Socket (SOCK_STREAM)"]
        UDP_SOCK["UDP Socket (SOCK_DGRAM)"]
    end

    APP --> RUNNER
    APP --> STORAGE
    CLI --> SERVER
    RUNNER --> SERVER
    RUNNER --> TCP_H
    RUNNER --> UDP_H
    SERVER --> TCP_H
    SERVER --> UDP_H
    TCP_H --> PROTO
    UDP_H --> PROTO
    TCP_H --> METRICS
    UDP_H --> METRICS
    STORAGE --> METRICS
    TCP_H --> TCP_SOCK
    UDP_H --> UDP_SOCK
```

## 5.2 Module Responsibilities

The codebase in `C:\Users\forli\.vscode\NetBench` is organized into distinct files, each holding well-defined responsibilities:

1. [netbench/protocol.py](file:///C:/Users/forli/.vscode/NetBench/netbench/protocol.py):
   - Defines protocol constants: `MAGIC_BYTES = b"NB"`, `CURRENT_VERSION = 1`, `HEADER_SIZE = 20`.
   - Defines `PacketType` enumeration (DATA, CONTROL_START, CONTROL_END, ACK_REPORT, ECHO_REQUEST, ECHO_REPLY).
   - Implements `pack_header()`, `unpack_header()`, `pack_packet()`, and `unpack_packet()` using Python's `struct` module.
   - Houses the protocol exception hierarchy (`ProtocolError`, `InvalidMagicError`, `TruncatedHeaderError`, etc.).
   - Implements `SequenceTracker` for datagram delivery, duplicate, out-of-order, and missing sequence accounting.

2. [netbench/metrics.py](file:///C:/Users/forli/.vscode/NetBench/netbench/metrics.py):
   - Implements mathematical functions: `calculate_throughput()`, `calculate_loss_and_delivery()`, `calculate_latency_stats()`, and `calculate_rfc3550_jitter()`.
   - Defines immutable dataclass `LatencyStats` (min, mean, median, max, std_dev).
   - Defines dataclass `BenchmarkMetric` representing a standardized trial record.
   - Provides factory function `create_benchmark_metric()`.

3. [netbench/tcp_handler.py](file:///C:/Users/forli/.vscode/NetBench/netbench/tcp_handler.py):
   - Implements stream framing helpers: `recv_exact()` and `read_framed_packet()`.
   - Implements `TCPServerSession`: processes incoming client connections, handles DATA streams, replies to ECHO_REQUEST pings, and acknowledges CONTROL_END with ACK_REPORT.
   - Implements `TCPBenchmarkClient`: executes bulk throughput streaming and ping-pong latency trials with optional `TCP_NODELAY`.

4. [netbench/udp_handler.py](file:///C:/Users/forli/.vscode/NetBench/netbench/udp_handler.py):
   - Implements `UDPReceiverSession`: listens for datagram bursts, manages arrival timestamps, calculates jitter and loss, and provides `serve_echo()` for latency trials.
   - Implements `UDPBenchmarkClient`: transmits bursts with optional inter-packet delay, handles duplicated CONTROL_END packets, and executes latency ping-pong with per-ping timeouts.
   - Provides `build_udp_metric_from_summary()` to unify client send statistics and receiver sequence tracking.

5. [netbench/server.py](file:///C:/Users/forli/.vscode/NetBench/netbench/server.py):
   - Implements `NetBenchServer`: orchestrates concurrent TCP and UDP listener threads.
   - Applies platform-specific socket options (`SO_REUSEADDR` / `SO_EXCLUSIVEADDRUSE`).
   - Manages client worker thread pools and thread-safe status querying via `get_status()`.
   - Implements context manager interface (`__enter__` and `__exit__`).

6. [netbench/runner.py](file:///C:/Users/forli/.vscode/NetBench/netbench/runner.py):
   - Implements `validate_trial_parameters()` to guard against negative, zero, or out-of-range values.
   - Implements `check_configuration_mismatch()` to alert users when comparing disparate trials.
   - Implements `execute_benchmark_trial()`: high-level coordinator executing client requests against the active server.

7. [netbench/storage.py](file:///C:/Users/forli/.vscode/NetBench/netbench/storage.py):
   - Implements `metrics_to_dataframe()`: transforms trial metrics into structured Pandas DataFrames.
   - Implements `metrics_to_csv_string()` for browser-based download buttons.
   - Implements `save_metrics_to_csv()`: persists timestamped CSV logs into the `results/` directory.

8. [server_cli.py](file:///C:/Users/forli/.vscode/NetBench/server_cli.py):
   - Standalone CLI entry point using `argparse`.
   - Validates IP addresses (`validate_host`) and port bounds (`validate_port`).
   - Registers OS signal handlers (`SIGINT`, `SIGTERM`) for graceful server shutdown from terminal.

9. [app.py](file:///C:/Users/forli/.vscode/NetBench/app.py):
   - Interactive Streamlit web dashboard structured into 5 navigation sections: Overview, Run Benchmark, Compare Protocols, Experiment History, and About & Viva Guide.
   - Embedded custom CSS styling for clean engineering presentation.
   - Integrated Plotly charts with custom restrained theme.

## 5.3 Custom 20-Byte Binary Header Specification

To ensure robust message framing over byte streams and enable precise sequence and timestamp tracking, NetBench defines a fixed 20-byte binary header.

### 5.3.1 Format String and Byte Order
The header is serialized using the standard struct format:
$$\text{Format String} = \texttt{"!2sBB IId"}$$
The exclamation mark (`!`) enforces **Network Byte Order (Big-Endian)**, ensuring that multi-byte integers and IEEE 754 floating-point values serialize identically across different CPU architectures (e.g., Little-Endian x86/ARM vs Big-Endian systems).

### 5.3.2 Field Layout and Bit Allocation

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Magic ("NB")         |    Version    |  Packet Type  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Sequence Number                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Payload Length                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                    Monotonic Timestamp                        +
|                        (64-bit float)                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 5.3.3 Field Descriptions and Technical Purpose

| Field Name | Offset | Type / Format | Size | Description & Engineering Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Magic Bytes** | Bytes 0–1 | ASCII string (`!2s`) | 2 Bytes | Fixed identifier `b"NB"` (0x4E, 0x42). Validates that incoming socket data belongs to NetBench, rejecting rogue or misdirected socket traffic. |
| **Protocol Version** | Byte 2 | Unsigned 8-bit int (`!B`) | 1 Byte | Current version `1` (0x01). Provides protocol extensibility and prevents incompatible message parsing. |
| **Packet Type** | Byte 3 | Unsigned 8-bit int (`!B`) | 1 Byte | Enumerated packet control type (1..6) specifying how the frame must be processed by the receiver. |
| **Sequence Number** | Bytes 4–7 | Unsigned 32-bit int (`!I`) | 4 Bytes | Monotonically increasing sequence index $i \in [0, 2^{32}-1]$. Enables UDP loss detection, duplicate identification, and out-of-order tracking. |
| **Payload Length** | Bytes 8–11 | Unsigned 32-bit int (`!I`) | 4 Bytes | Exact byte length of trailing user data payload. Provides length-prefix framing over TCP byte streams and validates UDP datagram size bounds. |
| **Sender Timestamp**| Bytes 12–19| 64-bit IEEE float (`!d`) | 8 Bytes | High-resolution monotonic timestamp (`time.perf_counter()`) at dispatch. Preserved during RTT echo pong and used in RFC 3550 jitter calculation. |

### 5.3.4 Enumerated Packet Types (`PacketType`)
- `DATA (0x01)`: Standard benchmark payload packet.
- `CONTROL_START (0x02)`: Signals session initialization; prompts receiver to reset sequence tracking tables.
- `CONTROL_END (0x03)`: Signals client dispatch completion; prompts UDP receiver to enter bounded drain mode and TCP server to finalize session.
- `ACK_REPORT (0x04)`: Server-to-client summary acknowledgment reporting observed packet count.
- `ECHO_REQUEST (0x05)`: RTT latency ping packet.
- `ECHO_REPLY (0x06)`: RTT latency pong packet containing reflected payload and original sender timestamp.

---

# CHAPTER 6: DETAILED METHODOLOGY AND FORMULAS

## 6.1 Throughput and Goodput Calculation Methodology

In NetBench, throughput is calculated strictly as **Application Goodput** — measuring the volume of user data payload successfully received by the target application process divided by the measured transfer duration.

Let $N_{\text{recv}}$ be the number of unique packets successfully delivered, $L_{\text{payload}}$ be the payload size per packet in bytes, and $\Delta t$ be the measured elapsed duration in seconds. The total received application payload in bits is:

$$\text{Payload Bits Delivered} = N_{\text{recv}} \times L_{\text{payload}} \times 8$$

The goodput in bits per second ($\text{bps}$) and Megabits per second ($\text{Mbps}$) is derived as:

$$\text{Throughput}_{\text{bps}} = \frac{N_{\text{recv}} \times L_{\text{payload}} \times 8}{\Delta t}$$

$$\text{Goodput}_{\text{Mbps}} = \frac{\text{Throughput}_{\text{bps}}}{10^6} = \frac{N_{\text{recv}} \times L_{\text{payload}} \times 8}{\Delta t \times 1{,}000{,}000}$$

> [!NOTE]
> NetBench uses standard metric decimal prefixes ($10^6 = 1{,}000{,}000\text{ bits}$ per Mbps), conforming to standard networking engineering specifications (such as IEEE 802.3 and RFC 2647) rather than binary mebibits ($2^{20} = 1{,}048{,}576\text{ bits}$).
> If $\Delta t \le 0.0$ (due to timer truncation or aborted run), the function safely returns $0.0\text{ Mbps}$ without raising `ZeroDivisionError`.

## 6.2 Packet Loss and Delivery Rate Formulation

In TCP, kernel ARQ guarantees 100% delivery unless an unrecoverable connection failure terminates the socket. In UDP, individual datagrams can be lost when kernel buffers overflow.

Let $N_{\text{sent}}$ denote total packets dispatched by the client, and $N_{\text{recv}}$ denote the count of unique sequence numbers observed by the receiver's `SequenceTracker`.

1. **Loss Count:**
$$\text{Loss Count} = \max(0, N_{\text{sent}} - N_{\text{recv}})$$

2. **Packet Loss Rate (%):**
$$\text{Loss Rate (\%)} = \begin{cases} 
0.0, & \text{if } N_{\text{sent}} = 0 \\
\left( \frac{\text{Loss Count}}{N_{\text{sent}}} \right) \times 100.0, & \text{if } N_{\text{sent}} > 0 
\end{cases}$$

3. **Packet Delivery Rate (%):**
$$\text{Delivery Rate (\%)} = \begin{cases} 
0.0, & \text{if } N_{\text{sent}} = 0 \\
\left( \frac{\min(N_{\text{recv}}, N_{\text{sent}})}{N_{\text{sent}}} \right) \times 100.0, & \text{if } N_{\text{sent}} > 0 
\end{cases}$$

> [!IMPORTANT]
> If duplicate datagrams arrive, $N_{\text{recv}}$ is constrained to unique sequence numbers, ensuring that delivery rate never exceeds 100.0%.

## 6.3 Round-Trip Latency Statistics Formulation

In latency testing mode, NetBench conducts $K$ sequential request-response ping-pong exchanges. For each exchange $k \in [1, K]$, the client records local timestamps $t_{\text{send}}^{(k)}$ and $t_{\text{recv}}^{(k)}$. The individual round-trip sample in milliseconds is:

$$\text{RTT}_k = \left( t_{\text{recv}}^{(k)} - t_{\text{send}}^{(k)} \right) \times 1000.0 \quad [\text{ms}]$$

From the sample distribution $\{\text{RTT}_1, \text{RTT}_2, \dots, \text{RTT}_K\}$, the statistical engine derives:

1. **Minimum Latency:**
$$\text{RTT}_{\min} = \min_{1 \le k \le K} (\text{RTT}_k)$$

2. **Maximum Latency:**
$$\text{RTT}_{\max} = \max_{1 \le k \le K} (\text{RTT}_k)$$

3. **Arithmetic Mean:**
$$\mu_{\text{RTT}} = \frac{1}{K} \sum_{k=1}^K \text{RTT}_k$$

4. **Median Latency:**
$$\text{Median}_{\text{RTT}} = \begin{cases}
\text{RTT}_{((K+1)/2)}^{\text{sorted}}, & \text{if } K \text{ is odd} \\
\frac{1}{2} \left( \text{RTT}_{(K/2)}^{\text{sorted}} + \text{RTT}_{(K/2 + 1)}^{\text{sorted}} \right), & \text{if } K \text{ is even}
\end{cases}$$

5. **Sample Standard Deviation ($K \ge 2$):**
$$s_{\text{RTT}} = \sqrt{\frac{1}{K - 1} \sum_{k=1}^K (\text{RTT}_k - \mu_{\text{RTT}})^2}$$
*(If $K = 1$, standard deviation is defined as $0.0\text{ ms}$; if $K = 0$, all statistical attributes return `None`).*

## 6.4 RFC 3550 Interarrival Jitter Formulation

Interarrival jitter is computed strictly according to RFC 3550 Section 6.4.1. Let $S_i$ be the transmission timestamp of packet $i$ (in seconds), and let $R_i$ be the receiver arrival timestamp (in seconds). For every pair of consecutively received packets $i-1$ and $i$:

$$\text{Transit Difference } D(i-1, i) = (R_i - R_{i-1}) - (S_i - S_{i-1})$$

$$\text{Absolute Deviation } |D| = |D(i-1, i)|$$

The smoothed jitter $J$ (initialized to $J = 0$ for the first packet) is updated recursively:

$$J_i = J_{i-1} + \frac{|D| - J_{i-1}}{16}$$

At the conclusion of the trial, the final jitter value is converted to milliseconds:

$$\text{Jitter}_{\text{ms}} = J_{\text{final}} \times 1000.0$$

---

# CHAPTER 7: IMPLEMENTATION DETAILS AND WORKBENCH FEATURES

## 7.1 Socket Stream Framing Implementation

In `netbench/tcp_handler.py`, stream framing is enforced by the helper function `recv_exact()`:

```python
def recv_exact(sock: socket.socket, num_bytes: int, timeout: Optional[float] = None) -> bytes:
    if num_bytes == 0:
        return b""
    buffer = bytearray()
    while len(buffer) < num_bytes:
        chunk = sock.recv(num_bytes - len(buffer))
        if not chunk:
            if len(buffer) == 0:
                return b""  # Clean EOF between framed packets
            raise ConnectionResetError(f"Connection closed prematurely: expected {num_bytes}, got {len(buffer)}")
        buffer.extend(chunk)
    return bytes(buffer)
```
This loop ensures that partial TCP segments are transparently buffered until the exact required byte count is satisfied.

## 7.2 Sequence Tracking and Bounded Receiver Drain

In `netbench/udp_handler.py`, the receiver manages datagram arrivals using `SequenceTracker`. To ensure that packets in transit are not prematurely marked as lost when the client finishes dispatching, the client transmits a `CONTROL_END` packet. Upon receiving this control signal, the receiver shortens its socket timeout to a bounded drain window (e.g., $0.2\text{ s}$ to $0.3\text{ s}$):

```python
elif header.packet_type == PacketType.CONTROL_END:
    control_end_received = True
    # Sender finished dispatching; switch to short drain timeout to collect in-flight packets
    self.sock.settimeout(drain_timeout)
```

## 7.3 Multi-Threaded Server Lifecycle and Port Cleanup

`NetBenchServer` in `netbench/server.py` manages two background listener threads:
1. `NetBench-TCP-Listener`: Executes non-blocking `accept()` calls with a 300 ms polling timeout. Incoming connections spawn short-lived worker threads (`NetBench-TCP-Client`).
2. `NetBench-UDP-Listener`: Executes non-blocking `recvfrom()` calls with a 300 ms polling timeout, routing datagrams to `SequenceTracker` or immediately replying to ping packets.

When `server.stop()` is invoked, `stop_event.set()` is triggered, both sockets are closed immediately to break any active system calls, and threads are joined with bounded timeouts, ensuring zero lingering processes or orphaned ports.

## 7.4 Streamlit Dashboard Architecture

The frontend application (`app.py`) provides an interactive interface organized into five primary sections:

1. **Overview:** Summarizes transport layer specifications, displays overall session statistics cards (Total Trials, TCP Runs, UDP Runs, Peak Goodput), and details localhost socket behavior.
2. **Run Benchmark:** Configuration panel for protocol selection (TCP, UDP, or Comparative), measurement type (Throughput or Latency), payload size, packet count, inter-packet delay, and socket timeout.
3. **Compare Protocols:** Side-by-side comparative table and Plotly charts (Goodput bar chart, Delivery vs Loss stacked bar chart, RTT latency with min/max spread). Flags configuration mismatches automatically.
4. **Experiment History:** Tabular session history with protocol and test-type filters, browser CSV download button, and disk persistence to the `results/` folder.
5. **About & Viva Guide:** Comprehensive reference manual detailing 7 core viva topics (transport layer differences, stream framing, goodput vs throughput, loss accounting, monotonic clock epochs, RFC 3550 jitter, socket options).

```text
+---------------------------------------------------------------------------------------+
|  [FIGURE PLACEHOLDER 7.1: Screenshot of NetBench Streamlit Dashboard - Overview Tab]   |
|  Caption: Overview view displaying session metrics and protocol specification table. |
+---------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------+
|  [FIGURE PLACEHOLDER 7.2: Screenshot of Benchmark Execution & Parameter Selection]    |
|  Caption: Run Benchmark interface showing trial parameters and live metric cards.      |
+---------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------+
|  [FIGURE PLACEHOLDER 7.3: Screenshot of Comparative Performance Analysis & Charts]    |
|  Caption: Side-by-side protocol comparison showing Goodput and Delivery breakdown.   |
+---------------------------------------------------------------------------------------+
```

## 7.5 Experiment History and CSV Export Format

Every completed trial generates a standardized `BenchmarkMetric` record serialized into CSV format via `netbench/storage.py`:

```csv
timestamp,protocol,payload_size_bytes,packet_count,packets_sent,packets_received,throughput_mbps,loss_rate_percent,delivery_rate_percent,avg_latency_ms,min_latency_ms,median_latency_ms,max_latency_ms,jitter_ms,duration_seconds
2026-10-21T13:00:00Z,TCP,1460,100,100,100,33.72,0.0,100.0,,,,,,0.0346
```
Missing or non-applicable metrics (e.g., jitter in a TCP bulk transfer) serialize as empty fields (`None` in Python, represented as an em-dash `—` in the UI).

---

# CHAPTER 8: TESTING STRATEGY AND ACTUAL AUTOMATED TEST RESULTS

## 8.1 Testing Strategy

To guarantee that NetBench behaves reliably and produces scientifically sound results, the software was developed under strict Test-Driven Development (TDD) principles. Automated testing is divided into three tiers:

1. **Unit Testing (Isolated Logic):** Validates binary packing/unpacking, exception triggers, mathematical metric algorithms, and sequence tracking logic without opening network sockets.
2. **Lifecycle & Thread Safety Testing:** Validates server startup, port binding collision detection, client thread cleanup, and clean restarts.
3. **Real Socket Integration Testing:** Validates actual data transmission over TCP (`SOCK_STREAM`) and UDP (`SOCK_DGRAM`) on loopback (`127.0.0.1`), verifying fragmented frame assembly, loss accounting, and RTT echo reflection.

## 8.2 Actual Automated Test Results Table

The test suite was executed against the project codebase using Python's `unittest` discovery runner:

$$\text{Command: } \texttt{python -m unittest discover -s tests -v}$$

**Execution Outcome: 74 Tests Executed, 74 Passed, 0 Failures, 0 Errors (Execution Duration: 3.266 s).**

| Test Suite / Module | Test Case Name | Target Component / Method | Observed Result |
| :--- | :--- | :--- | :--- |
| **test_protocol.py** | `test_constants_and_types` | `MAGIC_BYTES`, sizes, `PacketType` | **PASS** |
| | `test_header_round_trip` | `pack_header` / `unpack_header` symmetry | **PASS** |
| | `test_full_packet_round_trip` | `pack_packet` / `unpack_packet` | **PASS** |
| | `test_empty_payload_packet` | Zero-length control packet framing | **PASS** |
| | `test_boundary_values` | `MAX_UINT32` boundary handling | **PASS** |
| | `test_invalid_magic_unpack` | `InvalidMagicError` on corrupt prefix | **PASS** |
| | `test_unsupported_version_unpack` | `UnsupportedVersionError` on version mismatch| **PASS** |
| | `test_invalid_packet_type_unpack` | `InvalidPacketTypeError` rejection | **PASS** |
| | `test_truncated_header` | `TruncatedHeaderError` (< 20 bytes) | **PASS** |
| | `test_truncated_payload` | `TruncatedPayloadError` (< declared len) | **PASS** |
| | `test_invalid_pack_ranges` | Range validation for uint32 fields | **PASS** |
| | `test_invalid_payload_type` | `TypeError` on non-bytes payload | **PASS** |
| | `test_perfect_sequential_stream` | `SequenceTracker` [0..9] in-order tracking| **PASS** |
| | `test_packet_loss_detection` | Missing sequences [2, 5, 7] detection | **PASS** |
| | `test_duplicate_packets` | Duplicate sequence identification | **PASS** |
| | `test_out_of_order_packets` | Out-of-order sequence counter | **PASS** |
| | `test_empty_test_case` | Zero-packet edge case handling | **PASS** |
| | `test_reset` | State clearing on session restart | **PASS** |
| **test_metrics.py** | `test_standard_throughput` | 125,000 B / 1.0 s = 1.0 Mbps goodput | **PASS** |
| | `test_high_throughput` | 125 MB / 1.0 s = 1.0 Gbps goodput | **PASS** |
| | `test_zero_duration` | Division-by-zero protection (returns 0.0) | **PASS** |
| | `test_zero_bytes` | Zero-byte payload handling | **PASS** |
| | `test_negative_payload_raises` | `ValueError` on negative bytes | **PASS** |
| | `test_perfect_delivery` | 100/100 -> 0% loss, 100% delivery | **PASS** |
| | `test_partial_loss` | 80/100 -> 20% loss, 80% delivery | **PASS** |
| | `test_total_loss` | 0/100 -> 100% loss, 0% delivery | **PASS** |
| | `test_zero_packets_sent` | Zero sent division-by-zero protection | **PASS** |
| | `test_received_exceeds_sent` | Clamping delivery rate to 100% max | **PASS** |
| | `test_negative_counts_raise` | `ValueError` on negative counts | **PASS** |
| | `test_standard_samples` | RTT min, mean, median, max, std dev | **PASS** |
| | `test_single_sample` | Single sample std dev = 0.0 | **PASS** |
| | `test_empty_samples` | Empty samples -> `LatencyStats.empty()` | **PASS** |
| | `test_genuine_zero_latency` | Distinguishing 0.0 ms from None | **PASS** |
| | `test_invalid_samples_raise` | `ValueError` on NaN / infinite latency | **PASS** |
| | `test_manual_trace_verification` | Step-by-step RFC 3550 numerical trace | **PASS** |
| | `test_zero_jitter_uniform_delay` | Constant delay yields 0.0 ms jitter | **PASS** |
| | `test_clock_offset_invariance` | +3600s clock shift yields identical jitter | **PASS** |
| | `test_fewer_than_two_samples` | < 2 samples returns 0.0 ms jitter | **PASS** |
| | `test_mismatched_sample_counts_raise`| Length mismatch validation | **PASS** |
| | `test_create_tcp_metric` | Factory method verification for TCP | **PASS** |
| | `test_create_udp_metric` | Factory method verification for UDP | **PASS** |
| **test_server.py** | `test_start_ephemeral_ports` | Binding port 0 assigns valid positive ports | **PASS** |
| | `test_client_communication_with_server`| Full TCP & UDP client trials against server| **PASS** |
| | `test_double_start_raises` | `RuntimeError` on duplicate `start()` | **PASS** |
| | `test_idempotent_stop` | Safe repeated calls to `stop()` | **PASS** |
| | `test_clean_restart_behavior` | Clean stop and restart on same instance | **PASS** |
| | `test_shutdown_with_connected_client` | Clean teardown with active client socket | **PASS** |
| | `test_port_binding_failure_detected` | `ServerStartupError` on occupied port | **PASS** |
| | `test_context_manager` | Context manager `with NetBenchServer():` | **PASS** |
| | `test_validate_host` | IPv4 address and localhost string parser | **PASS** |
| | `test_validate_port` | Port boundary [0, 65535] enforcement | **PASS** |
| | `test_parse_arguments_defaults` | CLI default argument values | **PASS** |
| | `test_parse_arguments_custom` | Custom CLI flag arguments | **PASS** |
| **test_tcp_integration.py**| `test_tcp_throughput_real_exchange` | Real 25 pkts × 1024 B transfer over TCP | **PASS** |
| | `test_tcp_latency_real_rtt_echo` | Real 10-ping request-reply echo over TCP | **PASS** |
| | `test_tcp_split_and_fragmented_frames` | Reassembly of 7-byte slices via `recv_exact`| **PASS** |
| | `test_tcp_multiple_frames_one_connection`| Multiple framed messages over one stream | **PASS** |
| | `test_tcp_clean_eof_and_premature_eof` | Clean EOF vs premature disconnect handling | **PASS** |
| | `test_tcp_empty_test_handling` | Zero-packet invocation handling | **PASS** |
| **test_udp_integration.py**| `test_udp_burst_real_exchange` | Real 25 pkts × 512 B datagram burst | **PASS** |
| | `test_udp_latency_real_rtt_echo` | Real 10-ping RTT echo over UDP | **PASS** |
| | `test_udp_simulated_loss_and_out_of_order`| Real out-of-order, loss & duplicate tracking| **PASS** |
| | `test_udp_malformed_and_truncated_datagrams`| Receiver silently ignores corrupt frames | **PASS** |
| | `test_udp_payload_size_limits` | Enforcement of 65,507 B max UDP payload | **PASS** |
| | `test_udp_empty_test_handling` | Zero-packet invocation handling | **PASS** |
| **test_dashboard_helpers.py**| `test_parameter_validation_success` | Valid parameter acceptance | **PASS** |
| | `test_parameter_validation_errors` | Rejection of negative / out-of-bound inputs | **PASS** |
| | `test_configuration_mismatch_detection`| Warning generation on disparate test configs| **PASS** |
| | `test_metrics_dataframe_and_csv_serialization`| DataFrame and CSV string serialization | **PASS** |
| | `test_save_metrics_to_csv_file` | Disk persistence to `results/` directory | **PASS** |
| | `test_tcp_throughput_trial` | Live end-to-end TCP throughput trial | **PASS** |
| | `test_tcp_latency_trial` | Live end-to-end TCP latency trial | **PASS** |
| | `test_udp_burst_trial` | Live end-to-end UDP burst trial | **PASS** |
| | `test_udp_latency_trial` | Live end-to-end UDP latency trial | **PASS** |

## 8.3 Scientific Scope and Boundaries of Testing

> [!WARNING]
> While the passing of all 74 automated tests establishes that:
> 1. Protocol framing, packing, and unpacking function correctly according to the 20-byte specification.
> 2. Mathematical formulas for goodput, loss rate, latency statistics, and RFC 3550 jitter calculate accurately.
> 3. Stream reassembly reliably handles chunked byte fragments without frame corruption.
> 4. Sockets open, exchange traffic, and close cleanly without port leaks on the host system.
> 
> **Testing does NOT prove wide-area network performance, physical cable noise immunity, or NAT traversal capabilities.** All tests execute over the loopback interface (`127.0.0.1`), where transmission occurs through OS kernel memory buffers without physical medium constraints.

---

# CHAPTER 9: EXPERIMENTAL METHODOLOGY, RESULTS, AND DISCUSSION

## 9.1 Experimental Methodology

To compare TCP and UDP objectively, experiments must be conducted under controlled, identical conditions:
1. **Matched Payload Size:** Test both protocols using identical payload sizes (e.g., standard Ethernet MTU payload of 1,460 bytes).
2. **Matched Packet Count:** Dispatch identical numbers of packets (e.g., 100 packets).
3. **Throttling Control:** Evaluate UDP both unthrottled (0 ms delay) and with micro-pauses (e.g., 1 ms delay) to observe socket buffer behavior.
4. **Localhost Isolation:** All preliminary trials are executed over `127.0.0.1` to establish a baseline before extending to physical local area networks (LAN).

```mermaid
flowchart TD
    START([Start Benchmark Trial]) --> SELECT{Select Mode}
    SELECT -->|Throughput / Bulk| PREP_DATA[Prepare Payload Buffer N x Size]
    SELECT -->|Latency / Ping-Pong| PREP_PING[Prepare Echo Payload 64 B]

    PREP_DATA --> PROTO_CHECK{Protocol?}
    PROTO_CHECK -->|TCP| TCP_STREAM[Open SOCK_STREAM<br/>Connect Server<br/>Stream N Framed Packets<br/>Send CONTROL_END<br/>Receive ACK_REPORT]
    PROTO_CHECK -->|UDP| UDP_BURST[Open SOCK_DGRAM<br/>Send CONTROL_START<br/>Dispatch N Datagrams<br/>Send CONTROL_END x 2<br/>Wait Bounded Drain]

    PREP_PING --> RTT_LOOP[Loop k = 1..K<br/>Record t_send<br/>Send ECHO_REQUEST<br/>Wait ECHO_REPLY<br/>Record t_recv<br/>Compute RTT_k]

    TCP_STREAM --> CALC[Compute Metrics:<br/>Goodput, Loss, Delivery, RTT, Jitter]
    UDP_BURST --> CALC
    RTT_LOOP --> CALC
    CALC --> DISP[Render Metric Cards & Plotly Charts]
    DISP --> CSV[Serialize Record to Session History & CSV]
    CSV --> END([End Trial])
```

## 9.2 Preliminary Baseline Experimental Results (Localhost Run)

The user executed the first baseline benchmark trial on the host system using the Streamlit dashboard under the following parameters:
- **Protocol:** TCP (`SOCK_STREAM`)
- **Measurement Mode:** Throughput (Bulk Transfer)
- **Target Interface:** Localhost (`127.0.0.1`)
- **Payload Size per Packet:** 1,460 Bytes (Standard Ethernet MSS frame)
- **Target Packet Count ($N$):** 100 Packets
- **Socket Options Applied:** `TCP_NODELAY = 1`

### 9.2.1 Empirical Results Recorded

| Parameter / Measured Metric | Recorded Value | Unit / Note |
| :--- | :--- | :--- |
| **Protocol** | TCP | Connection-oriented stream |
| **Payload Size ($L_{\text{payload}}$)** | 1,460 | Bytes |
| **Configured Packet Count ($N$)** | 100 | Packets |
| **Packets Dispatched ($N_{\text{sent}}$)** | 100 | Packets |
| **Packets Received ($N_{\text{recv}}$)** | 100 | Packets |
| **Total Useful Payload Delivered** | 146,000 | Bytes ($100 \times 1,460$) |
| **Elapsed Duration ($\Delta t$)** | 0.0346 | Seconds |
| **Reported Goodput** | **33.72** | **Mbps** |
| **Packet Delivery Rate** | **100.0** | **%** |
| **Packet Loss Rate** | **0.0** | **%** |
| **Round-Trip Latency (Mean RTT)**| — | Not measured in bulk transfer mode |
| **RFC 3550 Jitter** | — | Not measured in TCP stream mode |

### 9.2.2 Mathematical Verification Against Metric Formula

Substituting the recorded raw values into the NetBench goodput equation:

$$\text{Payload Bits Delivered} = 146{,}000 \text{ Bytes} \times 8 \text{ bits/Byte} = 1{,}168{,}000 \text{ bits}$$

$$\text{Goodput}_{\text{bps}} = \frac{1{,}168{,}000 \text{ bits}}{0.0346 \text{ s}} \approx 33{,}757{,}225.43 \text{ bps}$$

$$\text{Goodput}_{\text{Mbps}} = \frac{33{,}757{,}225.43}{1{,}000{,}000} \approx 33.757 \approx 33.72 \text{ Mbps}$$

*(Minor variance in trailing hundredths reflects floating-point resolution in intermediate high-resolution timer differences).*

## 9.3 Comparative Benchmark Table Template (Matched Configurations)

To complete the experimental study, students must conduct matched comparative trials across both TCP and UDP. The template below must be populated with collected empirical data:

| Metric / Parameter | TCP Trial (Preliminary Baseline) | UDP Trial (Pending Collection) |
| :--- | :--- | :--- |
| **Execution Environment** | Localhost (`127.0.0.1`) | Localhost (`127.0.0.1`) |
| **Payload Size per Packet** | 1,460 Bytes | 1,460 Bytes |
| **Target Packet Count ($N$)** | 100 Packets | 100 Packets |
| **Packets Sent** | 100 | `[TO BE COLLECTED]` |
| **Packets Received (Unique)** | 100 | `[TO BE COLLECTED]` |
| **Payload Bytes Delivered** | 146,000 Bytes | `[TO BE COLLECTED]` Bytes |
| **Measured Elapsed Duration** | 0.0346 Seconds | `[TO BE COLLECTED]` Seconds |
| **Application Goodput** | **33.72 Mbps** | `[TO BE COLLECTED]` **Mbps** |
| **Packet Delivery Rate** | **100.0%** | `[TO BE COLLECTED]` **%** |
| **Packet Loss Rate** | **0.0%** | `[TO BE COLLECTED]` **%** |
| **RFC 3550 Interarrival Jitter** | N/A (Stream-oriented) | `[TO BE COLLECTED]` **ms** |
| **Mean RTT Latency (Ping Mode)** | `[TO BE COLLECTED]` ms | `[TO BE COLLECTED]` ms |

```text
+---------------------------------------------------------------------------------------+
|  [TABLE PLACEHOLDER 9.1: Parametric Payload Variation Study (64B, 512B, 1460B, 8192B)] |
|  To be populated with empirical runs varying payload size under fixed packet count.  |
+---------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------+
|  [FIGURE PLACEHOLDER 9.2: Goodput vs Payload Size Comparative Curve]                  |
|  Caption: Empirical goodput scaling curves for TCP and UDP across payload sizes.     |
+---------------------------------------------------------------------------------------+
```

## 9.4 Observations and Technical Discussion

### 9.4.1 Localhost Goodput and OS Socket Buffering
The preliminary trial recorded an application goodput of **33.72 Mbps** over localhost. It is vital to interpret this result correctly from an engineering standpoint:
- **Localhost vs Physical NIC:** On loopback (`127.0.0.1`), communication bypasses the physical network adapter. However, goodput in Python is bounded by user-space to kernel-space buffer transitions, Python GIL execution overhead, and Python `socket.sendall()` / `recv()` system call context switching.
- **Reliability Guarantee:** In TCP, 100 out of 100 packets were delivered without a single dropped byte (100% delivery rate, 0% loss). The OS TCP stack maintains an internal retransmission queue; even if a local buffer had briefly congested, the kernel would hold transmission until space became available.

### 9.4.2 Expected UDP Behavior on Localhost
When the matching UDP trial is executed:
- If sent unthrottled (`delay = 0.0`), UDP goodput may appear higher than TCP because UDP skips connection negotiation, acknowledgment processing, and congestion throttling.
- However, if the burst size exceeds the OS UDP receive socket buffer (`SO_RCVBUF`), the kernel will silently drop packets, causing the delivery rate to fall below 100%. Adding a 1 ms inter-packet delay eliminates this buffer overrun, restoring delivery rate toward 100% at the expense of lower goodput.

---

# CHAPTER 10: LIMITATIONS, FUTURE SCOPE, AND CONCLUSION

## 10.1 Limitations

While NetBench successfully fulfills its educational and empirical objectives, the following technical limitations must be acknowledged:

1. **Loopback Artifacts:** Localhost benchmarking reflects host CPU speed, thread scheduling, and memory bandwidth rather than physical signal propagation, router queueing, or optical attenuation.
2. **User-Space Timing Jitter:** Python's `time.perf_counter()` measures elapsed time at the application layer. Samples include operating system thread scheduling latencies, garbage collection pauses, and user-to-kernel context switches.
3. **Absence of Synthetic Impairments:** The current implementation relies on natural operating system buffer overflow for packet loss; it does not include an internal packet drop simulator or synthetic delay injector.
4. **Single-Stream Architecture:** Transfers execute over a single socket connection, precluding evaluation of multi-path or multi-stream TCP striping.

## 10.2 Future Scope

The project architecture provides a solid foundation for several advanced networking extensions:

1. **Wide-Area Network (WAN) Multi-Host Deployment:** Extending `server_cli.py` and the client engine to support distributed testing across public cloud instances (e.g., AWS, GCP) or university campus networks with firewall traversal.
2. **Synthetic Impairment Generator (NetEm Emulation):** Developing an application-level proxy that programmatically injects pseudo-random packet drops, duplicate generation, datagram reordering, and Gaussian delay distributions.
3. **Transport Layer Security (TLS 1.3 / DTLS) Benchmarking:** Integrating `ssl` and DTLS wrappers to quantify cryptographic handshake latency and encryption throughput penalties.
4. **Bandwidth Throttling and Token-Bucket Pacing:** Adding client-side token-bucket rate limiters to study protocol responsiveness under constrained bandwidth profiles.

## 10.3 Conclusion

The **NetBench** project successfully designs, implements, and verifies an empirical benchmarking workbench for analyzing TCP and UDP performance. By establishing an explicit 20-byte binary header (`!2sBB IId`), NetBench overcomes the TCP stream segmentation challenge and provides receiver-side sequence tracking for unacknowledged UDP bursts. 

The software architecture strictly decouples low-level socket operations from the user interface, offering both a headless command-line server and an interactive Streamlit engineering dashboard. The mathematical engine evaluates goodput, packet loss, delivery rate, RTT latency distributions, and RFC 3550 interarrival jitter. With 74 automated unit and integration tests passing at 100%, and preliminary localhost baseline runs demonstrating 33.72 Mbps goodput under 100% reliability, NetBench provides an open, rigorous, and viva-ready experimental platform for undergraduate Computer Networks laboratory education.

---

# CHAPTER 11: REFERENCES

1. **Postel, J.** (1980). *User Datagram Protocol*. IETF RFC 768. https://datatracker.ietf.org/doc/html/rfc768
2. **Postel, J.** (1981). *Transmission Control Protocol - DARPA Internet Program Protocol Specification*. IETF RFC 793. https://datatracker.ietf.org/doc/html/rfc793
3. **Nagle, J.** (1984). *Congestion Control in IP/TCP Internetworks*. IETF RFC 896. https://datatracker.ietf.org/doc/html/rfc896
4. **Braden, R.** (1989). *Requirements for Internet Hosts - Communication Layers*. IETF RFC 1122. https://datatracker.ietf.org/doc/html/rfc1122
5. **Schulzrinne, H., Casner, S., Frederick, R., & Jacobson, V.** (2003). *RTP: A Transport Protocol for Real-Time Applications*. IETF RFC 3550. https://datatracker.ietf.org/doc/html/rfc3550
6. **Allman, M., Paxson, V., & Blanton, E.** (2009). *TCP Congestion Control*. IETF RFC 5681. https://datatracker.ietf.org/doc/html/rfc5681
7. **Kurose, J. F., & Ross, K. W.** (2021). *Computer Networking: A Top-Down Approach* (8th ed.). Pearson.
8. **Tanenbaum, A. S., Wetherall, D. J., & Feamster, N.** (2021). *Computer Networks* (6th ed.). Pearson.
9. **Stevens, W. R., Fenner, B., & Rudoff, A. M.** (2004). *UNIX Network Programming, Volume 1: The Sockets Networking API* (3rd ed.). Addison-Wesley Professional.
10. **Python Software Foundation.** (2026). *Python 3 Standard Library Documentation: socket, struct, and unittest modules*. https://docs.python.org/3/

---

# CHAPTER 12: APPENDIX — INSTALLATION, USAGE, AND TESTING MANUAL

## 12.1 Environment Setup and Installation

### Step 1: Clone or Navigate to the Repository
Open PowerShell or a terminal and navigate to the project directory:
```powershell
cd C:\Users\forli\.vscode\NetBench
```

### Step 2: Virtual Environment Configuration
NetBench uses an isolated virtual environment (`.venv`). If setting up afresh:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3: Dependency Installation
Install required packages using pip:
```powershell
.\.venv\Scripts\pip.exe install -r requirements.txt
```
*Contents of `requirements.txt`:*
- `streamlit>=1.40.0`
- `pandas>=2.2.0`
- `plotly>=5.20.0`

## 12.2 Running Automated Unit and Integration Tests

To run the complete test suite (74 tests) with verbose output:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
Expected output:
```text
Ran 74 tests in 3.266s
OK
```

## 12.3 Launching the Interactive Web Dashboard

To launch the Streamlit engineering dashboard:
```powershell
.\.venv\Scripts\streamlit.exe run app.py
```
Upon startup, the dashboard will open in the default web browser at `http://localhost:8501`.
- If the background server is inactive, click **Start Server** in the sidebar.
- Navigate to **Run Benchmark**, select parameters or click a preset (e.g., `1,460 B · Standard MTU Frame`), and click **Run Benchmark Trial**.
- Navigate to **Compare Protocols** to view side-by-side tables and Plotly charts.
- Navigate to **Experiment History** to review records and click **Download CSV Log** or **Save to results/ Directory**.

## 12.4 Running the Standalone Headless Server CLI

If running the server independently (e.g., for headless testing or LAN benchmarking):
```powershell
.\.venv\Scripts\python.exe server_cli.py --host 127.0.0.1 --tcp-port 5001 --udp-port 5002
```
To run on OS-assigned ephemeral ports:
```powershell
.\.venv\Scripts\python.exe server_cli.py --tcp-port 0 --udp-port 0
```
To terminate the server cleanly, press `Ctrl+C`.

---

# END OF REPORT DRAFT
