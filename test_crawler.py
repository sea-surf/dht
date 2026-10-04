"""
Unit tests to verify bencode, database, and metadata logic.
"""

import os
import unittest
from dhtcrawler_py.bencode import bdecode, bdecode_with_index, bencode
from dhtcrawler_py.database import TorrentDatabase
from dhtcrawler_py.metadata import parse_torrent_info


class TestDHTCrawler(unittest.TestCase):
    def test_bencode(self):
        data = {
            b"int": 42,
            b"str": b"hello world",
            b"list": [1, b"two", 3],
            b"nested": {b"a": b"b"}
        }
        encoded = bencode(data)
        decoded = bdecode(encoded)
        self.assertEqual(decoded[b"int"], 42)
        self.assertEqual(decoded[b"str"], b"hello world")
        self.assertEqual(decoded[b"list"], [1, b"two", 3])
        self.assertEqual(decoded[b"nested"][b"a"], b"b")

    def test_bencode_stream(self):
        payload = bencode({b"msg_type": 1, b"piece": 0}) + b"EXTRA_RAW_BINARY_DATA"
        obj, end_idx = bdecode_with_index(payload)
        self.assertEqual(obj[b"msg_type"], 1)
        self.assertEqual(obj[b"piece"], 0)
        self.assertEqual(payload[end_idx:], b"EXTRA_RAW_BINARY_DATA")

    def test_database(self):
        test_db_path = "test_torrents.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

        db = TorrentDatabase(db_path=test_db_path)
        sample_hash = "abcdef0123456789abcdef0123456789abcdef01"

        inserted = db.save_torrent(
            info_hash=sample_hash,
            name="Ubuntu 24.04 Desktop AMD64 ISO",
            total_size=5_000_000_000,
            files=[{"path": "ubuntu-24.04-desktop-amd64.iso", "length": 5_000_000_000}]
        )
        self.assertTrue(inserted)
        self.assertTrue(db.has_torrent(sample_hash))

        # Search
        results, count = db.search("Ubuntu")
        self.assertEqual(count, 1)
        self.assertEqual(results[0]["name"], "Ubuntu 24.04 Desktop AMD64 ISO")

        # Full info
        torrent = db.get_torrent(sample_hash)
        self.assertIsNotNone(torrent)
        self.assertEqual(len(torrent["files"]), 1)

        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

    def test_metadata_parser(self):
        single_file_dict = {
            b"name": b"SingleFile.mkv",
            b"length": 1048576
        }
        name, total_size, files = parse_torrent_info(single_file_dict)
        self.assertEqual(name, "SingleFile.mkv")
        self.assertEqual(total_size, 1048576)
        self.assertEqual(len(files), 1)

        multi_file_dict = {
            b"name": b"Album",
            b"files": [
                {b"length": 500000, b"path": [b"Disc 1", b"01.mp3"]},
                {b"length": 600000, b"path": [b"Disc 1", b"02.mp3"]}
            ]
        }
        name, total_size, files = parse_torrent_info(multi_file_dict)
        self.assertEqual(name, "Album")
        self.assertEqual(total_size, 1100000)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["path"], "Disc 1/01.mp3")


if __name__ == "__main__":
    unittest.main()
