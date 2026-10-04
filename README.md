# DHT Crawler

Modified dht crawler

## Run

```bash
python run_crawler.py
http://localhost:8000
```

---

## CLI

```text
usage: run_crawler.py [-h] [--port PORT] [--web-port WEB_PORT] [--host HOST] [--db DB] [--workers WORKERS]

options:
  -h, --help            show this help message and exit
  --port PORT, -p PORT  UDP port for DHT crawler (default: 6881)
  --web-port WEB_PORT, -w WEB_PORT
                        HTTP port for Web UI (default: 8000)
  --host HOST           Web UI bind address (default: 0.0.0.0)
  --db DB, -d DB        SQLite database path (default: torrents.db)
  --workers WORKERS     Concurrent metadata fetcher workers (default: 60)
```

---

## Architecture

```
dhtcrawler/
├── run_crawler.py       # Main CLI entry point orchestrator
├── start_crawler.bat    # Windows launcher
├── test_crawler.py      
├── torrents.db          # Embedded SQLite FTS5 database
├── README.md            
├── LICENSE.txt
├── img/                
└── dhtcrawler_py/
    ├── __init__.py
    ├── bencode.py       # Fast bencode encoder/decoder
    ├── database.py      # SQLite storage with FTS5 search
    ├── dht.py           # BitTorrent Kademlia KRPC DHT crawler
    ├── metadata.py      # BEP 09/10 metadata downloader pool
    ├── search_provider.py # Real-time global search provider
    └── web.py           # Minimalist dark web search interface
```

---

## REST API Endpoints

- `GET /api/stats` - Returns crawler metrics (packets sent/received, hashes discovered, active queue, database count).
- `GET /api/recent?page=1` - Returns the latest discovered torrents.
- `GET /api/search?q=<keyword>&page=1` - Full-text search across discovered torrents.
- `GET /api/torrent/<info_hash>` - Detailed torrent metadata including full file lists and sizes.
