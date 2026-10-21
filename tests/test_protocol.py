"""
tests.test_protocol
~~~~~~~~~~~~~~~~~~~
Comprehensive unit test suite for NetBench binary packet framing,
header serialization/deserialization, error conditions, and sequence tracking.
"""

import unittest
from netbench.protocol import (
    CURRENT_VERSION,
    HEADER_SIZE,
    MAGIC_BYTES,
    MAX_UINT32,
    InvalidFieldError,
    InvalidMagicError,
    InvalidPacketTypeError,
    InvalidPayloadLengthError,
    PacketHeader,
    PacketType,
    ProtocolError,
    SequenceTracker,
    TruncatedHeaderError,
    TruncatedPayloadError,
    UnsupportedVersionError,
    pack_header,
    pack_packet,
    unpack_header,
    unpack_packet,
)


class TestProtocolConstants(unittest.TestCase):
    """Sanity checks for protocol definitions and sizes."""

    def test_constants_and_types(self):
        self.assertEqual(MAGIC_BYTES, b"\x4e\x42")
        self.assertEqual(CURRENT_VERSION, 1)
        self.assertEqual(HEADER_SIZE, 20)
        self.assertTrue(PacketType.is_valid(PacketType.DATA))
        self.assertTrue(PacketType.is_valid(PacketType.CONTROL_START))
        self.assertTrue(PacketType.is_valid(PacketType.CONTROL_END))
        self.assertTrue(PacketType.is_valid(PacketType.ACK_REPORT))
        self.assertTrue(PacketType.is_valid(PacketType.ECHO_REQUEST))
        self.assertTrue(PacketType.is_valid(PacketType.ECHO_REPLY))
        self.assertFalse(PacketType.is_valid(999))


class TestPacketFraming(unittest.TestCase):
    """Tests for header and packet serialization and deserialization."""

    def test_header_round_trip(self):
        """Header packed and unpacked should retain all field values."""
        seq = 42
        payload_len = 1024
        ts = 12345.6789
        raw = pack_header(
            packet_type=PacketType.DATA,
            sequence_number=seq,
            payload_length=payload_len,
            timestamp=ts,
        )
        self.assertEqual(len(raw), HEADER_SIZE)

        decoded = unpack_header(raw)
        self.assertEqual(decoded.magic, MAGIC_BYTES)
        self.assertEqual(decoded.version, CURRENT_VERSION)
        self.assertEqual(decoded.packet_type, PacketType.DATA)
        self.assertEqual(decoded.sequence_number, seq)
        self.assertEqual(decoded.payload_length, payload_len)
        self.assertAlmostEqual(decoded.timestamp, ts, places=4)

    def test_full_packet_round_trip(self):
        """Complete packet (header + payload) packed and unpacked."""
        payload = b"Hello, NetBench Socket Benchmark!"
        raw = pack_packet(
            packet_type=PacketType.DATA,
            sequence_number=100,
            payload=payload,
            timestamp=999.123,
        )
        self.assertEqual(len(raw), HEADER_SIZE + len(payload))

        header, extracted_payload = unpack_packet(raw)
        self.assertEqual(header.packet_type, PacketType.DATA)
        self.assertEqual(header.sequence_number, 100)
        self.assertEqual(header.payload_length, len(payload))
        self.assertEqual(extracted_payload, payload)

    def test_empty_payload_packet(self):
        """Packets with zero-length payload (e.g. control signals)."""
        raw = pack_packet(packet_type=PacketType.CONTROL_END, sequence_number=0, payload=b"")
        self.assertEqual(len(raw), HEADER_SIZE)
        header, payload = unpack_packet(raw)
        self.assertEqual(header.packet_type, PacketType.CONTROL_END)
        self.assertEqual(header.payload_length, 0)
        self.assertEqual(payload, b"")

    def test_boundary_values(self):
        """Test boundary limits for sequence numbers and payload lengths."""
        raw = pack_header(
            packet_type=PacketType.DATA,
            sequence_number=MAX_UINT32,
            payload_length=MAX_UINT32,
            timestamp=0.0,
        )
        header = unpack_header(raw)
        self.assertEqual(header.sequence_number, MAX_UINT32)
        self.assertEqual(header.payload_length, MAX_UINT32)


class TestProtocolValidationAndErrors(unittest.TestCase):
    """Tests that malformed, corrupted, or unsupported packets raise clear exceptions."""

    def test_invalid_magic_unpack(self):
        """Corrupt magic bytes must raise InvalidMagicError."""
        bad_buffer = b"XX" + b"\x00" * (HEADER_SIZE - 2)
        with self.assertRaises(InvalidMagicError):
            unpack_header(bad_buffer)

    def test_unsupported_version_unpack(self):
        """Unsupported version must raise UnsupportedVersionError."""
        # Valid magic 'NB', version=99
        bad_buffer = MAGIC_BYTES + bytes([99]) + b"\x00" * (HEADER_SIZE - 3)
        with self.assertRaises(UnsupportedVersionError):
            unpack_header(bad_buffer)

    def test_invalid_packet_type_unpack(self):
        """Invalid packet type must raise InvalidPacketTypeError."""
        # Valid magic 'NB', version=1, packet_type=255
        bad_buffer = MAGIC_BYTES + bytes([CURRENT_VERSION, 255]) + b"\x00" * (HEADER_SIZE - 4)
        with self.assertRaises(InvalidPacketTypeError):
            unpack_header(bad_buffer)

    def test_truncated_header(self):
        """Buffer with fewer than HEADER_SIZE bytes must raise TruncatedHeaderError."""
        with self.assertRaises(TruncatedHeaderError):
            unpack_header(b"\x4e\x42\x01\x01")  # only 4 bytes

    def test_truncated_payload(self):
        """Buffer with fewer bytes than declared payload_length must raise TruncatedPayloadError."""
        raw_header = pack_header(
            packet_type=PacketType.DATA,
            sequence_number=1,
            payload_length=50,  # claims 50 bytes
            timestamp=0.0,
        )
        # Supply only 10 payload bytes instead of 50
        incomplete_packet = raw_header + b"1234567890"
        with self.assertRaises(TruncatedPayloadError):
            unpack_packet(incomplete_packet)

    def test_invalid_pack_ranges(self):
        """Packing out-of-range fields must raise appropriate exceptions."""
        with self.assertRaises(InvalidFieldError):
            pack_header(packet_type=PacketType.DATA, sequence_number=-1, payload_length=10, timestamp=0.0)

        with self.assertRaises(InvalidFieldError):
            pack_header(packet_type=PacketType.DATA, sequence_number=MAX_UINT32 + 1, payload_length=10, timestamp=0.0)

        with self.assertRaises(InvalidPayloadLengthError):
            pack_header(packet_type=PacketType.DATA, sequence_number=0, payload_length=-5, timestamp=0.0)

        with self.assertRaises(InvalidPacketTypeError):
            pack_header(packet_type=999, sequence_number=0, payload_length=10, timestamp=0.0)

    def test_invalid_payload_type(self):
        """Passing non-bytes payload to pack_packet must raise TypeError."""
        with self.assertRaises(TypeError):
            pack_packet(packet_type=PacketType.DATA, sequence_number=0, payload="not bytes")  # type: ignore


class TestSequenceTracker(unittest.TestCase):
    """Tests for sequence number tracking, loss detection, duplicate, and out-of-order accounting."""

    def setUp(self):
        self.tracker = SequenceTracker()

    def test_perfect_sequential_stream(self):
        """Test ideal in-order sequence [0..9]."""
        for i in range(10):
            is_new = self.tracker.record_packet(i, send_time=i * 0.01, arrival_time=i * 0.01 + 0.002)
            self.assertTrue(is_new)

        self.assertEqual(self.tracker.total_received, 10)
        self.assertEqual(self.tracker.unique_received, 10)
        self.assertEqual(self.tracker.duplicate_count, 0)
        self.assertEqual(self.tracker.out_of_order_count, 0)
        self.assertEqual(self.tracker.highest_seq_seen, 9)
        self.assertEqual(self.tracker.missing_sequences(expected_count=10), [])
        self.assertEqual(self.tracker.loss_count(expected_count=10), 0)
        self.assertEqual(self.tracker.loss_rate_percent(expected_count=10), 0.0)
        self.assertEqual(self.tracker.delivery_rate_percent(expected_count=10), 100.0)

    def test_packet_loss_detection(self):
        """Test stream missing specific datagrams [missing 2, 5, 7 out of 10]."""
        received = [0, 1, 3, 4, 6, 8, 9]
        for seq in received:
            self.tracker.record_packet(seq)

        self.assertEqual(self.tracker.unique_received, 7)
        self.assertEqual(self.tracker.missing_sequences(expected_count=10), [2, 5, 7])
        self.assertEqual(self.tracker.loss_count(expected_count=10), 3)
        self.assertAlmostEqual(self.tracker.loss_rate_percent(expected_count=10), 30.0)
        self.assertAlmostEqual(self.tracker.delivery_rate_percent(expected_count=10), 70.0)

    def test_duplicate_packets(self):
        """Test stream with duplicate datagrams."""
        # Seq 1 and 2 received twice
        stream = [0, 1, 2, 1, 2, 3]
        for seq in stream:
            self.tracker.record_packet(seq)

        self.assertEqual(self.tracker.total_received, 6)
        self.assertEqual(self.tracker.unique_received, 4)
        self.assertEqual(self.tracker.duplicate_count, 2)
        # Expected 4 packets [0, 1, 2, 3] -> zero loss of unique packets
        self.assertEqual(self.tracker.loss_count(expected_count=4), 0)

    def test_out_of_order_packets(self):
        """Test out-of-order packet arrivals."""
        # Packet 2 arrives before 1; packet 4 arrives before 3
        stream = [0, 2, 1, 4, 3]
        for seq in stream:
            self.tracker.record_packet(seq)

        self.assertEqual(self.tracker.total_received, 5)
        self.assertEqual(self.tracker.unique_received, 5)
        # '1' arrived after '2' (out of order), '3' arrived after '4' (out of order)
        self.assertEqual(self.tracker.out_of_order_count, 2)
        self.assertEqual(self.tracker.missing_sequences(expected_count=5), [])

    def test_empty_test_case(self):
        """Test behavior when no packets were sent or received."""
        self.assertEqual(self.tracker.total_received, 0)
        self.assertEqual(self.tracker.unique_received, 0)
        self.assertEqual(self.tracker.missing_sequences(expected_count=0), [])
        self.assertEqual(self.tracker.loss_count(expected_count=0), 0)
        self.assertEqual(self.tracker.loss_rate_percent(expected_count=0), 0.0)
        self.assertEqual(self.tracker.delivery_rate_percent(expected_count=0), 0.0)

    def test_reset(self):
        """Test that reset clears all state cleanly."""
        self.tracker.record_packet(0)
        self.tracker.record_packet(1)
        self.tracker.reset()
        self.assertEqual(self.tracker.total_received, 0)
        self.assertEqual(self.tracker.highest_seq_seen, -1)


if __name__ == "__main__":
    unittest.main()
