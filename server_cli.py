"""
server_cli.py
~~~~~~~~~~~~~
Command-line interface to launch and manage the NetBench TCP & UDP benchmark server.

Usage:
    python server_cli.py [--host HOST] [--tcp-port PORT] [--udp-port PORT]

Examples:
    python server_cli.py
    python server_cli.py --host 127.0.0.1 --tcp-port 5001 --udp-port 5002
    python server_cli.py --tcp-port 0 --udp-port 0   # Ephemeral test ports
"""

import argparse
import ipaddress
import logging
import signal
import sys
import time

from netbench.protocol import DEFAULT_TCP_PORT, DEFAULT_UDP_PORT
from netbench.server import NetBenchServer, ServerStartupError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("netbench.cli")


def validate_host(host_str: str) -> str:
    """Validate that the bind host is a valid IP address or 'localhost'."""
    if host_str.lower() == "localhost":
        return "127.0.0.1"
    try:
        ipaddress.ip_address(host_str)
        return host_str
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Invalid bind IP address '{host_str}': {e}"
        ) from e


def validate_port(port_str: str) -> int:
    """Validate that the port is within the valid port range [0, 65535]."""
    try:
        port = int(port_str)
        if not (0 <= port <= 65535):
            raise ValueError()
        return port
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Invalid port number '{port_str}'. Must be an integer between 0 and 65535."
        ) from e


def parse_arguments(args=None) -> argparse.Namespace:
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(
        description="NetBench - TCP vs UDP Performance Analysis Benchmark Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=validate_host,
        default="127.0.0.1",
        help="Local network interface address to bind (e.g. 127.0.0.1 or 0.0.0.0)",
    )
    parser.add_argument(
        "--tcp-port",
        type=validate_port,
        default=DEFAULT_TCP_PORT,
        help="TCP port to listen on (0 for automatic ephemeral port)",
    )
    parser.add_argument(
        "--udp-port",
        type=validate_port,
        default=DEFAULT_UDP_PORT,
        help="UDP port to listen on (0 for automatic ephemeral port)",
    )
    return parser.parse_args(args)


def print_banner(server: NetBenchServer) -> None:
    """Display startup confirmation banner with active listening addresses."""
    status = server.get_status()
    banner = f"""
============================================================
        NetBench - Benchmark Server (Active)
============================================================
  Host Address : {status['host']}
  TCP Port     : {status['tcp_port']} (Streaming & RTT Ping-Pong)
  UDP Port     : {status['udp_port']} (Datagram Bursts & Jitter)
  Active State : READY FOR CLIENTS
============================================================
  Ready for benchmark trials.
  Press Ctrl+C to terminate the server gracefully.
============================================================
"""
    print(banner, flush=True)


def main(args=None) -> int:
    """Main CLI entry point."""
    try:
        parsed_args = parse_arguments(args)
    except SystemExit as e:
        return e.code

    server = NetBenchServer(
        host=parsed_args.host,
        tcp_port=parsed_args.tcp_port,
        udp_port=parsed_args.udp_port,
    )

    shutdown_event = [False]

    def signal_handler(signum, frame):
        if not shutdown_event[0]:
            shutdown_event[0] = True
            print("\nShutting down NetBench server listeners...", flush=True)
            server.stop()
            print("Server stopped cleanly. Goodbye!", flush=True)

    # Register OS signal handlers for graceful Ctrl+C and termination
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    try:
        server.start()
    except ServerStartupError as err:
        print(f"\n[ERROR] Server startup failed: {err}", file=sys.stderr, flush=True)
        return 1

    print_banner(server)

    try:
        while not shutdown_event[0]:
            time.sleep(0.5)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
