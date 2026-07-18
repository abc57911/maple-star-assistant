from __future__ import annotations

import unittest

from maple_star.ipc.preview_transport import PreviewFrame, SerializedPreviewTransport


class PreviewTransportTests(unittest.TestCase):
    def test_latest_frame_replaces_older_frame_for_same_producer(self) -> None:
        transport = SerializedPreviewTransport(max_producers=2)
        first = PreviewFrame("potion", 1, 2, 1, 4, "BGRA", b"12345678", 1.0)
        second = PreviewFrame("potion", 2, 2, 1, 4, "BGRA", b"abcdefgh", 2.0)

        transport.publish(first)
        transport.publish(second)

        self.assertEqual(transport.drain_latest(), [second])

    def test_payload_is_copied_at_publish_boundary(self) -> None:
        transport = SerializedPreviewTransport(max_producers=1)
        payload = bytearray(b"1234")
        frame = PreviewFrame("potion", 1, 1, 1, 4, "BGRA", payload, 1.0)

        transport.publish(frame)
        payload[:] = b"xxxx"

        self.assertEqual(transport.drain_latest()[0].payload, b"1234")

    def test_invalid_frame_shape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PreviewFrame("potion", 1, 2, 2, 4, "BGRA", b"short", 1.0)


if __name__ == "__main__":
    unittest.main()
