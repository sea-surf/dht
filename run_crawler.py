"""
Entry point for DHT Crawler 2.0 (Modern Python Edition).
Orchestrates the DHT sniffer, BEP 09/10 metadata fetcher, SQLite database, and web UI.
"""

import argparse
import asyncio
import os
import signal
import sys
import time

from dhtcrawler.database import TorrentDatabase
from dhtcrawler.dht import DHTCrawler
from dhtcrawler.metadata import MetadataManager
from dhtcrawler.web import WebServer


def format_bytes(num_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


async def main():
    parser = argparse.ArgumentParser(
        description="Modern BitTorrent DHT Crawler & Metadata Sniffer"
    )
    parser.add_argument("--port", "-p", type=int, default=6881, help="UDP port for DHT crawler (default: 6881)")
    parser.add_argument("--web-port", "-w", type=int, default=8000, help="HTTP port for Web UI (default: 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Web UI bind address (default: 0.0.0.0)")
    parser.add_argument("--db", "-d", type=str, default="torrents.db", help="SQLite database path (default: torrents.db)")
    parser.add_argument("--workers", type=int, default=60, help="Concurrent metadata fetcher workers (default: 60)")

    args = parser.parse_args()

    # Initialize Database
    db = TorrentDatabase(db_path=args.db)

    # Stats Tracker
    metadata_stats = {"queue_size": 0, "fetch_attempts": 0, "fetch_success": 0}

    # Callback when a full torrent metadata is fetched
    def on_torrent_fetched(data: dict):
        db.save_torrent(
            info_hash=data["info_hash"],
            name=data["name"],
            total_size=data["total_size"],
            files=data["files"]
        )

    # Initialize Metadata Manager
    metadata_mgr = MetadataManager(
        db_has_torrent=db.has_torrent,
        on_metadata_saved=on_torrent_fetched,
        max_concurrent=args.workers,
        stats_dict=metadata_stats
    )

    def on_hash_discovered(info_hash: str, addr: tuple):
        # 1. Immediately store in DB so it shows up in dashboard & search
        db.record_sniffed_hash(info_hash)
        # 2. Queue for metadata fetching
        metadata_mgr.enqueue(info_hash, addr)

    # Initialize DHT Crawler
    crawler = DHTCrawler(
        port=args.port,
        on_info_hash=on_hash_discovered
    )

    # Initialize Web Server
    def get_stats():
        return {
            "crawler": crawler.stats,
            "metadata": metadata_stats
        }

    web_server = WebServer(
        db=db,
        stats_callback=get_stats,
        host=args.host,
        port=args.web_port
    )

    print(f"[*] Torrent search engine running at http://localhost:{args.web_port}")
    print("    Press Ctrl+C to exit.\n")

    # Start services
    await metadata_mgr.start()
    await crawler.start()
    await web_server.start()

    stop_event = asyncio.Event()

    def handle_exit(*_):
        stop_event.set()

    # Register signals on platforms supporting them
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_exit)

    try:
        while not stop_event.is_set():
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("\nShutting down crawler gracefully...")
        crawler.stop()
        metadata_mgr.stop()
        web_server.stop()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
