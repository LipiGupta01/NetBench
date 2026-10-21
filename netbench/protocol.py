"""
netbench.protocol
~~~~~~~~~~~~~~~~~
Binary packet framing, header serialization/deserialization, and sequence tracking
for the NetBench TCP vs UDP Performance Analysis Tool.

Header Specification (20 bytes fixed, Big-Endian / Network Byte Order '!2sBB IId'):
+-----------------------------+-----------------------------+
| Field                       | Type / Size / Format        |
+=============================+=============================+
| Magic Bytes ("NB")          | 2 bytes, ascii ('!2s')      |
| Protocol Version            | 1 byte, uint8 ('!B')        |
| Packet Type                 | 1 byte, uint8 ('!B')        |
| Sequence Number             | 4 bytes, uint32 ('!I')      |
| Payload Length              | 4 bytes, uint32 ('!I')      |
| Monotonic Sender Timestamp  | 8 bytes, double ('!d')      |
+-----------------------------+-----------------------------+
Total Fixed Header Size: 20 bytes

Viva / Theory Note on Timestamps:
`time.perf_counter()` provides high-resolution monotonic timing, but its clock
epoch origin is process/system-dependent and uncalibrated across machines.
Therefore, receiver monotonic clock - sender monotonic clock is NOT a valid
one-way delay measurement.
Valid latency measurements are:
1. RTT Echo (Round-Trip Time): Sender records t_send, receiver echoes packet
   with the identical t_send, and sender computes RTT = (t_recv - t_send)
   entirely on its own monotonic clock.
2. Interarrival Jitter (RFC 3550): Uses differences (R_j - R_i) - (S_j - S_i),
   where any constant sender-receiver clock offset cancels out mathematically.
"""

from dataclasses import dataclass
import struct
from typing import List, Optional, Set, Tuple

# Protocol Constants
MAGIC_BYTES: bytes = b"\x4e\x42"  # 'NB' in ASCII (0x4E, 0x42)
CURRENT_VERSION: int = 1
HEADER_FORMAT: str = "!2sBB IId"
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 20 bytes

# Default Benchmark Listening Ports
DEFAULT_TCP_PORT: int = 5001
DEFAULT_UDP_PORT: int = 5002

# Limits for safety against malformed / corrupted packets
MAX_UDP_PAYLOAD_SIZE: int = 65507   # Maximum IPv4 UDP payload (65535 - 20 IP - 8 UDP)
MAX_TCP_PAYLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB per frame safety limit
MAX_UINT32: int = 0xFFFFFFFF


class PacketType:
    """Enumeration of recognized NetBench packet types."""
    DATA: int = 1            # Standard benchmark payload
    CONTROL_START: int = 2   # Handshake / start of test session
    CONTROL_END: int = 3     # Sender signals all datagrams have been dispatched
    ACK_REPORT: int = 4      # Receiver summary report / acknowledgment
    ECHO_REQUEST: int = 5    # Ping request for RTT measurement
    ECHO_REPLY: int = 6      # Pong response for RTT measurement

    _VALID_TYPES = {DATA, CONTROL_START, CONTROL_END, ACK_REPORT, ECHO_REQUEST, ECHO_REPLY}

    @classmethod
    def is_valid(cls, ptype: int) -> bool:
        return ptype in cls._VALID_TYPES


# Exception Hierarchy
class ProtocolError(Exception):
    """Base exception for all NetBench protocol encoding/decoding errors."""
    pass


class InvalidMagicError(ProtocolError):
    """Raised when the packet header does not begin with expected magic bytes."""
    pass


class UnsupportedVersionError(ProtocolError):
    """Raised when the protocol version in the header is not supported."""
    pass


class InvalidPacketTypeError(ProtocolError):
    """Raised when the packet type is unknown or invalid."""
    pass


class TruncatedHeaderError(ProtocolError):
    """Raised when the incoming buffer has fewer bytes than the required header size."""
    pass


class TruncatedPayloadError(ProtocolError):
    """Raised when the available payload bytes are less than declared in the header."""
    pass


class InvalidPayloadLengthError(ProtocolError):
    """Raised when payload length is negative or exceeds protocol safety limits."""
    pass


class InvalidFieldError(ProtocolError):
    """Raised when a header field value is outside valid integer ranges."""
    pass


@dataclass(frozen=True)
class PacketHeader:
    """Structured representation of a decoded NetBench packet header."""
    magic: bytes
    version: int
    packet_type: int
    sequence_number: int
    payload_length: int
    timestamp: float

    def __post_init__(self):
        # Validate ranges upon creation
        if self.magic != MAGIC_BYTES:
            raise InvalidMagicError(f"Invalid magic bytes: {self.magic!r}, expected {MAGIC_BYTES!r}")
        if self.version != CURRENT_VERSION:
            raise UnsupportedVersionError(f"Unsupported protocol version: {self.version}, expected {CURRENT_VERSION}")
        if not PacketType.is_valid(self.packet_type):
            raise InvalidPacketTypeError(f"Invalid packet type: {self.packet_type}")
        if not (0 <= self.sequence_number <= MAX_UINT32):
            raise InvalidFieldError(f"Sequence number {self.sequence_number} out of uint32 range [0, {MAX_UINT32}]")
        if self.payload_length < 0:
            raise InvalidPayloadLengthError(f"Negative payload length: {self.payload_length}")


def pack_header(
    packet_type: int,
    sequence_number: int,
    payload_length: int,
    timestamp: float,
    version: int = CURRENT_VERSION,
    magic: bytes = MAGIC_BYTES,
) -> bytes:
    """
    Pack a NetBench packet header into 20 bytes of big-endian binary data.

    :param packet_type: PacketType enum value (1..6)
    :param sequence_number: 32-bit unsigned integer (0..2^32-1)
    :param payload_length: 32-bit unsigned integer payload size in bytes
    :param timestamp: 64-bit float monotonic timestamp (seconds)
    :param version: Protocol version (defaults to CURRENT_VERSION)
    :param magic: Magic bytes (defaults to MAGIC_BYTES)
    :return: 20 bytes packed header
    :raises InvalidFieldError: if any field exceeds range or is invalid
    """
    if magic != MAGIC_BYTES:
        raise InvalidMagicError(f"Cannot pack invalid magic bytes: {magic!r}")
    if version != CURRENT_VERSION:
        raise UnsupportedVersionError(f"Cannot pack unsupported version: {version}")
    if not PacketType.is_valid(packet_type):
        raise InvalidPacketTypeError(f"Cannot pack invalid packet type: {packet_type}")
    if not (0 <= sequence_number <= MAX_UINT32):
        raise InvalidFieldError(f"Sequence number {sequence_number} out of uint32 range [0, {MAX_UINT32}]")
    if not (0 <= payload_length <= MAX_UINT32):
        raise InvalidPayloadLengthError(f"Payload length {payload_length} out of uint32 range [0, {MAX_UINT32}]")

    return struct.pack(
        HEADER_FORMAT,
        magic,
        version,
        packet_type,
        sequence_number,
        payload_length,
        float(timestamp),
    )


def unpack_header(buffer: bytes) -> PacketHeader:
    """
    Unpack a 20-byte NetBench packet header from binary data.

    :param buffer: Byte sequence of at least HEADER_SIZE (20 bytes)
    :return: PacketHeader instance
    :raises TruncatedHeaderError: if buffer is shorter than 20 bytes
    :raises InvalidMagicError: if magic bytes mismatch
    :raises UnsupportedVersionError: if version is unrecognized
    :raises InvalidPacketTypeError: if packet type is invalid
    """
    if len(buffer) < HEADER_SIZE:
        raise TruncatedHeaderError(
            f"Buffer length ({len(buffer)} bytes) is less than required header size ({HEADER_SIZE} bytes)"
        )

    magic, version, packet_type, seq_num, payload_len, timestamp = struct.unpack_from(
        HEADER_FORMAT, buffer, 0
    )

    if magic != MAGIC_BYTES:
        raise InvalidMagicError(f"Invalid magic bytes: {magic!r}, expected {MAGIC_BYTES!r}")
    if version != CURRENT_VERSION:
        raise UnsupportedVersionError(f"Unsupported protocol version: {version}, expected {CURRENT_VERSION}")
    if not PacketType.is_valid(packet_type):
        raise InvalidPacketTypeError(f"Invalid packet type: {packet_type}")

    return PacketHeader(
        magic=magic,
        version=version,
        packet_type=packet_type,
        sequence_number=seq_num,
        payload_length=payload_len,
        timestamp=timestamp,
    )


def pack_packet(
    packet_type: int,
    sequence_number: int,
    payload: bytes = b"",
    timestamp: float = 0.0,
) -> bytes:
    """
    Pack a complete NetBench packet (header + payload).

    :param packet_type: PacketType value
    :param sequence_number: 32-bit sequence number
    :param payload: Binary payload content
    :param timestamp: Monotonic timestamp (seconds)
    :return: Serialized bytes (HEADER_SIZE + len(payload))
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError(f"Payload must be bytes or bytearray, got {type(payload).__name__}")

    header = pack_header(
        packet_type=packet_type,
        sequence_number=sequence_number,
        payload_length=len(payload),
        timestamp=timestamp,
    )
    return header + bytes(payload)


def unpack_packet(buffer: bytes) -> Tuple[PacketHeader, bytes]:
    """
    Unpack a complete NetBench packet from a buffer.

    :param buffer: Binary data containing header and full payload
    :return: Tuple of (PacketHeader, payload_bytes)
    :raises TruncatedHeaderError: if buffer is shorter than HEADER_SIZE
    :raises TruncatedPayloadError: if buffer has fewer bytes than declared in payload_length
    """
    header = unpack_header(buffer)
    total_expected = HEADER_SIZE + header.payload_length

    if len(buffer) < total_expected:
        raise TruncatedPayloadError(
            f"Expected {header.payload_length} payload bytes, but buffer only has {len(buffer) - HEADER_SIZE} bytes"
        )

    payload = buffer[HEADER_SIZE:total_expected]
    return header, payload


class SequenceTracker:
    """
    Receiver-side accounting class for sequence numbers and packet delivery.

    Tracks received sequence numbers, detects missing datagrams, duplicates,
    out-of-order deliveries, and preserves arrival timestamps for jitter analysis.

    Viva / Theory Note:
    In UDP, packet loss is not signaled by the network layer; the receiver
    must infer loss by tracking transmitted sequence numbers [0, 1, 2, ... N-1].
    Any sequence number not received by the time the test terminates is classified
    as lost.
    Late arrivals: A packet arriving after the receiver finalizes the test report
    is treated as lost during that benchmark window.
    """

    def __init__(self):
        self._received_sequences: Set[int] = set()
        self._received_count: int = 0
        self._duplicate_count: int = 0
        self._out_of_order_count: int = 0
        self._highest_seq_seen: int = -1
        self._arrival_history: List[Tuple[int, float, float]] = []  # (seq, send_time, arrival_time)

    def record_packet(
        self,
        sequence_number: int,
        send_time: float = 0.0,
        arrival_time: float = 0.0,
    ) -> bool:
        """
        Record the arrival of a packet.

        :param sequence_number: Sequence number from packet header
        :param send_time: Sender's timestamp from packet header
        :param arrival_time: Receiver's local monotonic timestamp upon receipt
        :return: True if this was a new (first-time) sequence number, False if duplicate
        """
        self._received_count += 1
        self._arrival_history.append((sequence_number, send_time, arrival_time))

        if sequence_number in self._received_sequences:
            self._duplicate_count += 1
            return False

        # Out-of-order detection:
        # If we see a sequence number smaller than the highest sequence number
        # we have already observed, this datagram arrived out of sequence.
        if self._highest_seq_seen != -1 and sequence_number < self._highest_seq_seen:
            self._out_of_order_count += 1

        if sequence_number > self._highest_seq_seen:
            self._highest_seq_seen = sequence_number

        self._received_sequences.add(sequence_number)
        return True

    @property
    def total_received(self) -> int:
        """Total datagrams received, including duplicates."""
        return self._received_count

    @property
    def unique_received(self) -> int:
        """Count of distinct sequence numbers received."""
        return len(self._received_sequences)

    @property
    def duplicate_count(self) -> int:
        """Number of duplicate datagrams received."""
        return self._duplicate_count

    @property
    def out_of_order_count(self) -> int:
        """Number of datagrams that arrived with seq < max_seq_seen."""
        return self._out_of_order_count

    @property
    def highest_seq_seen(self) -> int:
        """Highest sequence number seen (-1 if no packets received)."""
        return self._highest_seq_seen

    @property
    def arrival_history(self) -> List[Tuple[int, float, float]]:
        """History of received packets: list of (seq, send_time, arrival_time)."""
        return list(self._arrival_history)

    def missing_sequences(self, expected_count: int) -> List[int]:
        """
        Compute the list of sequence numbers that were expected [0..expected_count-1]
        but never received.

        :param expected_count: Total packets the sender intended to send (N)
        :return: Sorted list of missing sequence numbers
        """
        if expected_count <= 0:
            return []
        expected_set = set(range(expected_count))
        missing = expected_set - self._received_sequences
        return sorted(missing)

    def loss_count(self, expected_count: int) -> int:
        """
        Calculate total missing packets based on expected count.

        :param expected_count: Total packets sent (N)
        :return: Number of lost datagrams (clamped to >= 0)
        """
        if expected_count <= 0:
            return 0
        return max(0, expected_count - self.unique_received)

    def loss_rate_percent(self, expected_count: int) -> float:
        """
        Calculate packet loss rate as a percentage [0.0..100.0].

        :param expected_count: Total packets sent (N)
        :return: Loss rate percentage
        """
        if expected_count <= 0:
            return 0.0
        lost = self.loss_count(expected_count)
        return (lost / expected_count) * 100.0

    def delivery_rate_percent(self, expected_count: int) -> float:
        """
        Calculate packet delivery rate as a percentage [0.0..100.0].

        :param expected_count: Total packets sent (N)
        :return: Delivery rate percentage
        """
        if expected_count <= 0:
            return 0.0
        delivered = min(self.unique_received, expected_count)
        return (delivered / expected_count) * 100.0

    def reset(self) -> None:
        """Reset all tracking counters for a new benchmark run."""
        self._received_sequences.clear()
        self._received_count = 0
        self._duplicate_count = 0
        self._out_of_order_count = 0
        self._highest_seq_seen = -1
        self._arrival_history.clear()
