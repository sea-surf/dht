"""
BitTorrent DHT Crawler / Sniffer (BEP 05 Mainline DHT).
Captures info_hashes from get_peers and announce_peer KRPC queries.
Uses asynchronous UDP DatagramProtocol for high throughput and rapid node discovery.
"""

import asyncio
import os
import random
import socket
import struct
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from .bencode import bdecode, bencode

# Working, high-reliability bootstrap nodes and IP fallbacks
BOOTSTRAP_NODES = [
    ("dht.libtorrent.org", 25401),
    ("185.157.221.247", 25401),
    ("87.98.162.88", 6881),
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.aelitis.com", 6881),
]

def random_node_id() -> bytes:
    """Generates a random 20-byte Kademlia node ID."""
    return os.urandom(20)

def neighbor_node_id(target_id: Optional[bytes]) -> bytes:
    """Generates a node ID with matching prefix to appear close in XOR metric."""
    if target_id and len(target_id) >= 15:
        return target_id[:15] + os.urandom(5)
    return random_node_id()


class DHTProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        node_id: bytes,
        on_info_hash: Callable[[str, Tuple[str, int]], None],
        crawler_stats: Dict[str, int]
    ):
        self.node_id = node_id
        self.on_info_hash = on_info_hash
        self.stats = crawler_stats
        self.transport: Optional[asyncio.DatagramTransport] = None
        # Stores tuples of (remote_node_id, (ip, port))
        self.nodes_pool: List[Tuple[bytes, Tuple[str, int]]] = []
        self.seen_nodes: Set[Tuple[str, int]] = set()

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        self.stats["packets_received"] = self.stats.get("packets_received", 0) + 1
        try:
            msg = bdecode(data)
        except Exception:
            return

        if not isinstance(msg, dict):
            return

        msg_type = msg.get(b'y')
        tid = msg.get(b't', b'')

        if msg_type == b'q':
            self.handle_query(msg, tid, addr)
        elif msg_type == b'r':
            self.handle_response(msg, addr)

    def handle_query(self, msg: dict, tid: bytes, addr: Tuple[str, int]):
        q = msg.get(b'q')
        a = msg.get(b'a', {})
        if not isinstance(a, dict):
            return

        if q == b'get_peers':
            self.stats["get_peers_queries"] = self.stats.get("get_peers_queries", 0) + 1
            info_hash_bytes = a.get(b'info_hash')
            if isinstance(info_hash_bytes, bytes) and len(info_hash_bytes) == 20:
                hex_hash = info_hash_bytes.hex()
                self.on_info_hash(hex_hash, addr)

                # Honeypot response: return token + empty nodes list
                fake_id = neighbor_node_id(info_hash_bytes)
                reply = {
                    b't': tid,
                    b'y': b'r',
                    b'r': {
                        b'id': fake_id,
                        b'token': info_hash_bytes[:8],
                        b'nodes': b''
                    }
                }
                self.send_datagram(bencode(reply), addr)

        elif q == b'announce_peer':
            self.stats["announce_queries"] = self.stats.get("announce_queries", 0) + 1
            info_hash_bytes = a.get(b'info_hash')
            if isinstance(info_hash_bytes, bytes) and len(info_hash_bytes) == 20:
                hex_hash = info_hash_bytes.hex()
                implied = a.get(b'implied_port', 0)
                peer_port = addr[1] if implied else a.get(b'port', addr[1])
                self.on_info_hash(hex_hash, (addr[0], peer_port))

                reply = {
                    b't': tid,
                    b'y': b'r',
                    b'r': {
                        b'id': neighbor_node_id(info_hash_bytes)
                    }
                }
                self.send_datagram(bencode(reply), addr)

        elif q == b'find_node':
            target = a.get(b'target', self.node_id)
            reply = {
                b't': tid,
                b'y': b'r',
                b'r': {
                    b'id': neighbor_node_id(target),
                    b'nodes': b''
                }
            }
            self.send_datagram(bencode(reply), addr)

        elif q == b'ping':
            reply = {
                b't': tid,
                b'y': b'r',
                b'r': {
                    b'id': self.node_id
                }
            }
            self.send_datagram(bencode(reply), addr)

    def handle_response(self, msg: dict, addr: Tuple[str, int]):
        r = msg.get(b'r', {})
        if not isinstance(r, dict):
            return

        nodes = r.get(b'nodes')
        if isinstance(nodes, bytes):
            self.parse_and_add_nodes(nodes)

    def parse_and_add_nodes(self, nodes_data: bytes):
        """Parses compact 26-byte node info chunks."""
        length = len(nodes_data)
        if length % 26 != 0:
            return

        for offset in range(0, length, 26):
            chunk = nodes_data[offset:offset + 26]
            node_id = chunk[:20]
            ip_bytes = chunk[20:24]
            port = struct.unpack('!H', chunk[24:26])[0]
            try:
                ip = socket.inet_ntoa(ip_bytes)
                if port > 0 and (ip, port) not in self.seen_nodes:
                    if len(self.seen_nodes) > 50000:
                        self.seen_nodes.clear()
                    self.seen_nodes.add((ip, port))
                    self.nodes_pool.append((node_id, (ip, port)))
            except Exception:
                continue

        self.stats["active_nodes"] = len(self.nodes_pool)

    def send_datagram(self, data: bytes, addr: Tuple[str, int]):
        if self.transport and not self.transport.is_closing():
            try:
                self.transport.sendto(data, addr)
                self.stats["packets_sent"] = self.stats.get("packets_sent", 0) + 1
            except Exception:
                pass

    def send_find_node(
        self,
        addr: Tuple[str, int],
        remote_node_id: Optional[bytes] = None,
        target_id: Optional[bytes] = None
    ):
        """Sends a KRPC find_node query to explore the DHT with neighbor emulation."""
        tid = os.urandom(2)
        if target_id is None:
            target_id = random_node_id()

        # If we know the remote node's ID, emulate a close neighbor so it places us in its closest bucket
        sender_id = neighbor_node_id(remote_node_id) if remote_node_id else self.node_id

        query = {
            b't': tid,
            b'y': b'q',
            b'q': b'find_node',
            b'a': {
                b'id': sender_id,
                b'target': target_id
            }
        }
        self.send_datagram(bencode(query), addr)


class DHTCrawler:
    def __init__(
        self,
        port: int = 6881,
        on_info_hash: Optional[Callable[[str, Tuple[str, int]], None]] = None
    ):
        self.port = port
        self.node_id = random_node_id()
        self.stats = {
            "packets_sent": 0,
            "packets_received": 0,
            "active_nodes": 0,
            "get_peers_queries": 0,
            "announce_queries": 0,
            "hashes_discovered": 0,
        }
        self.on_info_hash = on_info_hash or (lambda h, a: None)
        self.protocol: Optional[DHTProtocol] = None
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._running = False
        self._crawl_task: Optional[asyncio.Task] = None

    async def start(self):
        """Starts the UDP listener and the crawling loop."""
        self._running = True
        loop = asyncio.get_running_loop()

        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: DHTProtocol(
                node_id=self.node_id,
                on_info_hash=self._handle_discovered_hash,
                crawler_stats=self.stats
            ),
            local_addr=('0.0.0.0', self.port)
        )

        # Bootstrap immediately
        await self.bootstrap()
        self._crawl_task = asyncio.create_task(self._crawl_loop())

    def _handle_discovered_hash(self, info_hash: str, addr: Tuple[str, int]):
        self.stats["hashes_discovered"] += 1
        self.on_info_hash(info_hash, addr)

    async def bootstrap(self):
        """Queries known bootstrap nodes to enter the DHT routing table."""
        loop = asyncio.get_running_loop()
        for host, port in BOOTSTRAP_NODES:
            try:
                # If host is already an IP
                if all(c in "0123456789." for c in host):
                    if self.protocol:
                        self.protocol.send_find_node((host, port), target_id=self.node_id)
                    continue

                addr_info = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
                if addr_info and self.protocol:
                    resolved_ip = addr_info[0][4][0]
                    self.protocol.send_find_node((resolved_ip, port), target_id=self.node_id)
            except Exception:
                continue

    async def _crawl_loop(self):
        """Active DHT walking loop."""
        while self._running:
            if not self.protocol:
                await asyncio.sleep(0.5)
                continue

            self.stats["active_nodes"] = len(self.protocol.nodes_pool)

            # If node pool is low, re-bootstrap
            if len(self.protocol.nodes_pool) < 30:
                await self.bootstrap()
                await asyncio.sleep(0.5)

            # Process a batch of nodes from the pool
            batch_count = min(len(self.protocol.nodes_pool), 50)
            for _ in range(batch_count):
                if self.protocol.nodes_pool:
                    remote_nid, node_addr = self.protocol.nodes_pool.pop(0)
                    self.protocol.send_find_node(node_addr, remote_node_id=remote_nid)

            # Prevent unbounded growth
            if len(self.protocol.nodes_pool) > 10000:
                self.protocol.nodes_pool = self.protocol.nodes_pool[-5000:]

            await asyncio.sleep(0.04)

    def stop(self):
        self._running = False
        if self._crawl_task:
            self._crawl_task.cancel()
        if self.transport:
            self.transport.close()
