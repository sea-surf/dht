"""
BitTorrent Metadata Fetcher (BEP 09 ut_metadata and BEP 10 Extension Protocol).
Connects to peers via TCP, negotiates metadata exchange, downloads the full info dictionary,
verifies SHA-1 checksum, and extracts torrent metadata and file structures.
"""

import asyncio
import hashlib
import math
import os
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

from .bencode import bdecode, bdecode_with_index, bencode

BT_PROTOCOL = b"BitTorrent protocol"
BT_RESERVED = b"\x00\x00\x00\x00\x00\x10\x00\x00"  # Bit 20 enables BEP 10 Extension Protocol
PIECE_SIZE = 16384  # 16KB per BEP 09 standard
MAX_METADATA_SIZE = 30 * 1024 * 1024  # 30 MB limit for safety


def clean_string(data: Any) -> str:
    """Decodes string bytes safely with multiple fallbacks."""
    if isinstance(data, str):
        return data
    if not isinstance(data, bytes):
        return str(data)
    for encoding in ("utf-8", "gbk", "big5", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_torrent_info(info_dict: dict) -> Tuple[str, int, List[Dict[str, Any]]]:
    """
    Parses bencoded info dict into (torrent_name, total_size_bytes, files_list).
    Supports both single-file and multi-file torrents.
    """
    raw_name = info_dict.get(b'name.utf-8') or info_dict.get(b'name') or b'Unknown'
    name = clean_string(raw_name)

    files_list: List[Dict[str, Any]] = []
    total_size = 0

    if b'files' in info_dict and isinstance(info_dict[b'files'], list):
        # Multi-file torrent
        for f in info_dict[b'files']:
            if not isinstance(f, dict):
                continue
            length = f.get(b'length', 0)
            if not isinstance(length, int) or length < 0:
                continue

            path_components = f.get(b'path.utf-8') or f.get(b'path', [])
            if isinstance(path_components, list):
                parts = [clean_string(p) for p in path_components if p]
                file_path = "/".join(parts)
            else:
                file_path = clean_string(path_components)

            files_list.append({"path": file_path, "length": length})
            total_size += length
    else:
        # Single-file torrent
        length = info_dict.get(b'length', 0)
        if isinstance(length, int) and length >= 0:
            total_size = length
            files_list.append({"path": name, "length": length})

    return name, total_size, files_list


class MetadataFetcher:
    def __init__(
        self,
        info_hash_hex: str,
        peer_addr: Tuple[str, int],
        timeout: float = 6.0
    ):
        self.info_hash_hex = info_hash_hex.lower()
        self.info_hash_bytes = bytes.fromhex(self.info_hash_hex)
        self.peer_addr = peer_addr
        self.timeout = timeout
        self.peer_id = b"-PY0001-" + os.urandom(12)

    async def fetch(self) -> Optional[Dict[str, Any]]:
        """
        Attempts to connect to the peer and retrieve the torrent info dictionary.
        Returns parsed torrent data dict or None on failure/timeout.
        """
        try:
            return await asyncio.wait_for(self._do_fetch(), timeout=self.timeout)
        except Exception:
            return None

    async def _do_fetch(self) -> Optional[Dict[str, Any]]:
        host, port = self.peer_addr
        reader, writer = await asyncio.open_connection(host, port)

        try:
            # 1. Send BitTorrent Handshake
            handshake = (
                bytes([len(BT_PROTOCOL)])
                + BT_PROTOCOL
                + BT_RESERVED
                + self.info_hash_bytes
                + self.peer_id
            )
            writer.write(handshake)
            await writer.drain()

            # 2. Read Peer Handshake (68 bytes)
            peer_handshake = await reader.readexactly(68)
            if peer_handshake[:20] != bytes([len(BT_PROTOCOL)]) + BT_PROTOCOL:
                return None

            # Verify peer supports BEP 10 extension protocol (byte 25, bit 0x10)
            if not (peer_handshake[25] & 0x10):
                return None

            # 3. Send Extended Handshake announcing ut_metadata support
            ext_handshake_dict = {
                b'm': {
                    b'ut_metadata': 1
                }
            }
            ext_payload = bencode(ext_handshake_dict)
            ext_msg = struct.pack('!IBB', len(ext_payload) + 2, 20, 0) + ext_payload
            writer.write(ext_msg)
            await writer.drain()

            peer_ut_metadata_id: Optional[int] = None
            metadata_size: Optional[int] = None

            # 4. Wait for peer extended handshake
            while peer_ut_metadata_id is None or metadata_size is None:
                header = await reader.readexactly(4)
                msg_len = struct.unpack('!I', header)[0]
                if msg_len == 0:
                    continue  # Keep-alive

                msg_data = await reader.readexactly(msg_len)
                msg_id = msg_data[0]

                if msg_id == 20:  # Extended message
                    ext_id = msg_data[1]
                    ext_payload = msg_data[2:]

                    if ext_id == 0:  # Extended handshake
                        peer_dict = bdecode(ext_payload)
                        if isinstance(peer_dict, dict):
                            m_dict = peer_dict.get(b'm', {})
                            if isinstance(m_dict, dict):
                                peer_ut_metadata_id = m_dict.get(b'ut_metadata')
                            metadata_size = peer_dict.get(b'metadata_size')
                            if not peer_ut_metadata_id or not metadata_size:
                                return None
                            if metadata_size <= 0 or metadata_size > MAX_METADATA_SIZE:
                                return None
                            break

            # 5. Request all metadata pieces
            total_pieces = math.ceil(metadata_size / PIECE_SIZE)
            pieces: Dict[int, bytes] = {}

            for piece_idx in range(total_pieces):
                req_dict = {
                    b'msg_type': 0,  # 0 = request
                    b'piece': piece_idx
                }
                req_payload = bencode(req_dict)
                req_msg = struct.pack('!IBB', len(req_payload) + 2, 20, peer_ut_metadata_id) + req_payload
                writer.write(req_msg)
            await writer.drain()

            # 6. Receive pieces
            while len(pieces) < total_pieces:
                header = await reader.readexactly(4)
                msg_len = struct.unpack('!I', header)[0]
                if msg_len == 0:
                    continue

                msg_data = await reader.readexactly(msg_len)
                msg_id = msg_data[0]

                if msg_id == 20:
                    ext_id = msg_data[1]
                    if ext_id == 1:  # Our ut_metadata ID was 1
                        payload = msg_data[2:]
                        piece_dict, data_offset = bdecode_with_index(payload)

                        if isinstance(piece_dict, dict) and piece_dict.get(b'msg_type') == 1:  # 1 = data
                            piece_idx = piece_dict.get(b'piece')
                            if piece_idx is not None and 0 <= piece_idx < total_pieces:
                                piece_bytes = payload[data_offset:]
                                pieces[piece_idx] = piece_bytes

            # 7. Assemble and verify SHA-1 hash
            full_metadata = b"".join(pieces[i] for i in range(total_pieces))
            if hashlib.sha1(full_metadata).digest() != self.info_hash_bytes:
                return None

            # 8. Parse bencoded info dictionary
            info_dict = bdecode(full_metadata)
            if not isinstance(info_dict, dict):
                return None

            name, total_size, files = parse_torrent_info(info_dict)

            return {
                "info_hash": self.info_hash_hex,
                "name": name,
                "total_size": total_size,
                "files": files,
                "raw_info": full_metadata
            }

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


class MetadataManager:
    """
    Manages concurrent workers for downloading torrent metadata from discovered peers.
    """
    def __init__(
        self,
        db_has_torrent: Callable[[str], bool],
        on_metadata_saved: Callable[[Dict[str, Any]], None],
        max_concurrent: int = 50,
        stats_dict: Optional[Dict[str, int]] = None
    ):
        self.db_has_torrent = db_has_torrent
        self.on_metadata_saved = on_metadata_saved
        self.max_concurrent = max_concurrent
        self.stats = stats_dict if stats_dict is not None else {}
        self.queue: asyncio.Queue[Tuple[str, Tuple[str, int]]] = asyncio.Queue(maxsize=10000)
        self.seen_hashes: set = set()
        self.workers: List[asyncio.Task] = []
        self._running = False

    def enqueue(self, info_hash: str, peer_addr: Tuple[str, int]):
        """Adds an info_hash and announcing peer to the download queue."""
        info_hash = info_hash.lower()
        if info_hash in self.seen_hashes:
            return
        if self.db_has_torrent(info_hash):
            self.seen_hashes.add(info_hash)
            return

        if len(self.seen_hashes) > 100000:
            self.seen_hashes.clear()

        try:
            self.queue.put_nowait((info_hash, peer_addr))
            self.stats["queue_size"] = self.queue.qsize()
        except asyncio.QueueFull:
            pass

    async def start(self):
        self._running = True
        for _ in range(self.max_concurrent):
            worker_task = asyncio.create_task(self._worker())
            self.workers.append(worker_task)

    async def _worker(self):
        while self._running:
            try:
                info_hash, peer_addr = await self.queue.get()
                self.stats["queue_size"] = self.queue.qsize()
            except asyncio.CancelledError:
                break

            if self.db_has_torrent(info_hash):
                self.seen_hashes.add(info_hash)
                self.queue.task_done()
                continue

            fetcher = MetadataFetcher(info_hash, peer_addr, timeout=5.0)
            self.stats["fetch_attempts"] = self.stats.get("fetch_attempts", 0) + 1

            result = await fetcher.fetch()
            if result:
                self.stats["fetch_success"] = self.stats.get("fetch_success", 0) + 1
                self.seen_hashes.add(info_hash)
                self.on_metadata_saved(result)

            self.queue.task_done()

    def stop(self):
        self._running = False
        for w in self.workers:
            w.cancel()
