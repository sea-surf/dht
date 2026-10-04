"""
Global Torrent Search Provider.
Queries global DHT and index APIs (APIBay, BTDigg, etc.) in real time
for instant keyword search, retrieving titles, sizes, file counts, and magnet links.
"""

import asyncio
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List


def parse_size_bytes(size_str: str) -> int:
    """Converts human readable size string to bytes."""
    size_str = size_str.replace('\xa0', ' ').strip().upper()
    units = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
    }
    match = re.match(r'^([\d\.]+)\s*([A-Z]+)$', size_str)
    if not match:
        return 0
    val, unit = match.groups()
    try:
        return int(float(val) * units.get(unit, 1))
    except Exception:
        return 0


def fetch_apibay_sync(query: str, max_results: int = 40) -> List[Dict[str, Any]]:
    """Queries APIBay (fast JSON API with millions of indexed torrents)."""
    clean_query = query.strip()
    if not clean_query:
        return []

    url = f"https://apibay.org/q.php?q={urllib.parse.quote(clean_query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        "Accept": "application/json"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    results = []
    trackers = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce"
    ]
    tracker_args = "".join(f"&tr={urllib.parse.quote(tr)}" for tr in trackers)

    for item in data[:max_results]:
        name = item.get("name", "").strip()
        info_hash = item.get("info_hash", "").strip().lower()
        if not info_hash or info_hash == "0000000000000000000000000000000000000000":
            continue

        try:
            total_size = int(item.get("size", 0))
        except Exception:
            total_size = 0

        try:
            file_count = int(item.get("num_files", 1))
        except Exception:
            file_count = 1

        dn = urllib.parse.quote(name)
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn={dn}{tracker_args}"

        results.append({
            "info_hash": info_hash,
            "name": name,
            "total_size": total_size,
            "file_count": file_count,
            "files": [],
            "magnet_uri": magnet_uri,
            "source": "Global Index"
        })

    return results


def fetch_btdigg_sync(query: str, max_results: int = 25) -> List[Dict[str, Any]]:
    """Queries BTDigg DHT search engine as fallback."""
    clean_query = query.strip()
    if not clean_query:
        return []

    url = f"https://btdig.com/search?q={urllib.parse.quote(clean_query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return []

    results = []
    chunks = re.split(r'class="one_result[^"]*"', html)[1:]

    for c in chunks[:max_results]:
        name_m = re.search(r'class="torrent_name"[^>]*>[\s\S]*?<a [^>]*>([\s\S]*?)</a>', c)
        title = re.sub(r'<[^>]+>', '', name_m.group(1)).strip() if name_m else "Unknown Torrent"

        mag_m = re.search(r'href="(magnet:\?xt=urn:btih:([a-fA-F0-9]{40})[^"]*)"', c)
        if not mag_m:
            continue
        magnet = mag_m.group(1).replace('&amp;', '&')
        info_hash = mag_m.group(2).lower()

        size_m = re.search(r'class="torrent_size"[^>]*>([^<]+)</span>', c)
        size_str = size_m.group(1).replace('\xa0', ' ').strip() if size_m else "0 B"
        total_size = parse_size_bytes(size_str)

        files_m = re.search(r'class="torrent_files"[^>]*>([^<]+)</span>', c)
        files_str = files_m.group(1).strip() if files_m else "1"
        try:
            file_count = int(re.sub(r'\D', '', files_str))
        except Exception:
            file_count = 1

        results.append({
            "info_hash": info_hash,
            "name": title,
            "total_size": total_size,
            "file_count": file_count,
            "files": [],
            "magnet_uri": magnet,
            "source": "BTDigg Global"
        })

    return results


async def search_global_torrents(query: str, max_results: int = 50) -> List[Dict[str, Any]]:
    """Concurrently queries global DHT indexes for real-time results."""
    loop = asyncio.get_running_loop()

    # Query APIBay and BTDigg
    task_apibay = loop.run_in_executor(None, fetch_apibay_sync, query, max_results)
    task_btdigg = loop.run_in_executor(None, fetch_btdigg_sync, query, 20)

    done, _ = await asyncio.wait([task_apibay, task_btdigg], timeout=5.0)

    combined = []
    seen_hashes = set()

    for task in done:
        try:
            items = task.result()
            for it in items:
                ih = it["info_hash"]
                if ih not in seen_hashes:
                    seen_hashes.add(ih)
                    combined.append(it)
        except Exception:
            continue

    return combined
