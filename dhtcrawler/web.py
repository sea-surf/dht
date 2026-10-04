"""
Minimalist Dark Search Engine Interface for BitTorrent DHT.
Provides a clean, quiet search engine without discovery feeds or terminal noise.
"""

import asyncio
import json
import urllib.parse
from typing import Any, Callable, Dict, Optional

from .database import TorrentDatabase
from .search_provider import search_global_torrents

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>dhtcrawler</title>
  <style>
    :root {
      --bg: #0b0d11;
      --surface: #12151b;
      --surface-hover: #171a22;
      --border: #20242e;
      --border-focus: #3b4252;
      --text: #e2e5eb;
      --text-muted: #6e7683;
      --text-dim: #4b5260;
      --accent: #8b9bb4;
      --success: #4ade80;
      --mono: ui-monospace, "SF Mono", "Cascadia Code", "Segoe UI Mono", "Noto Mono", Consolas, monospace;
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", Helvetica, Arial, sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    a {
      color: var(--text);
      text-decoration: none;
    }
    a:hover {
      text-decoration: underline;
    }

    /* Centered Home State */
    .home-view {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 80vh;
      padding: 2rem 1.5rem;
      width: 100%;
      max-width: 650px;
      margin: 0 auto;
    }

    .home-brand {
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin-bottom: 1.75rem;
      user-select: none;
    }

    .search-box-wrap {
      width: 100%;
    }

    .search-input {
      width: 100%;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--text);
      font-family: var(--sans);
      font-size: 1rem;
      padding: 0.75rem 1rem;
      outline: none;
      transition: border-color 0.15s ease;
    }
    .search-input:focus {
      border-color: var(--border-focus);
    }
    .search-input::placeholder {
      color: var(--text-dim);
    }

    /* Search Results State Header */
    header {
      display: none;
      border-bottom: 1px solid var(--border);
      padding: 0.85rem 1.5rem;
      background: var(--bg);
      position: sticky;
      top: 0;
      z-index: 50;
    }

    .header-inner {
      max-width: 1050px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      gap: 1.5rem;
    }

    .header-brand {
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      white-space: nowrap;
      cursor: pointer;
    }

    .header-search {
      flex: 1;
      max-width: 600px;
    }
    .header-search .search-input {
      padding: 0.5rem 0.85rem;
      font-size: 0.92rem;
    }

    /* Results Area */
    .results-area {
      display: none;
      max-width: 1050px;
      margin: 1.5rem auto;
      padding: 0 1.5rem;
      flex: 1;
      width: 100%;
    }

    .status-line {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-bottom: 1rem;
      padding-bottom: 0.5rem;
      border-bottom: 1px solid var(--border);
    }

    .torrent-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }

    .torrent-item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.75rem 1rem;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .torrent-item:hover {
      background: var(--surface-hover);
      border-color: var(--border-focus);
    }

    .item-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 1rem;
    }

    .torrent-title {
      font-size: 0.98rem;
      font-weight: 600;
      line-height: 1.35;
      color: var(--text);
      word-break: break-all;
    }
    .torrent-title:hover {
      color: #fff;
    }

    .item-actions {
      display: flex;
      gap: 0.4rem;
      flex-shrink: 0;
    }

    .btn-action {
      background: transparent;
      border: 1px solid var(--border);
      border-radius: 3px;
      color: var(--text-muted);
      font-family: var(--mono);
      font-size: 0.75rem;
      padding: 0.22rem 0.55rem;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-action:hover {
      color: var(--text);
      border-color: var(--border-focus);
      background: rgba(255, 255, 255, 0.03);
    }

    .item-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem;
      margin-top: 0.45rem;
      font-family: var(--mono);
      font-size: 0.78rem;
      color: var(--text-muted);
    }

    .meta-size {
      color: var(--text);
      font-weight: 500;
    }
    .meta-hash {
      color: var(--text-dim);
      font-size: 0.72rem;
    }

    .empty-msg {
      text-align: center;
      padding: 4rem 1rem;
      color: var(--text-muted);
      font-size: 0.95rem;
    }

    /* Modal */
    .modal-overlay {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      z-index: 100;
      justify-content: center;
      align-items: center;
      padding: 1.5rem;
    }
    .modal-box {
      background: var(--surface);
      border: 1px solid var(--border-focus);
      border-radius: 6px;
      max-width: 800px;
      width: 100%;
      max-height: 80vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }
    .modal-head {
      padding: 0.9rem 1.25rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-head h3 {
      font-size: 0.95rem;
      font-weight: 600;
      word-break: break-all;
    }
    .modal-close {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 1.2rem;
      cursor: pointer;
      line-height: 1;
    }
    .modal-close:hover { color: var(--text); }
    .modal-body {
      padding: 1rem 1.25rem;
      overflow-y: auto;
      flex: 1;
      font-family: var(--mono);
      font-size: 0.8rem;
    }
    .file-row {
      display: flex;
      justify-content: space-between;
      padding: 0.35rem 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .file-name { color: var(--text); word-break: break-all; margin-right: 1rem; }
    .file-len { color: var(--text-muted); white-space: nowrap; }
  </style>
</head>
<body>

  <!-- Home Clean View -->
  <div id="homeView" class="home-view">
    <div class="home-brand"><b>dhtcrawler</b></div>
    <form class="search-box-wrap" onsubmit="event.preventDefault(); triggerSearch(document.getElementById('homeSearch').value);">
      <input type="search" id="homeSearch" class="search-input" placeholder="Search the BitTorrent DHT..." autocomplete="off" autofocus />
    </form>
  </div>

  <!-- Header for Results View -->
  <header id="appHeader">
    <div class="header-inner">
      <div class="header-brand" onclick="goHome()"><b>dhtcrawler</b></div>
      <form class="header-search" onsubmit="event.preventDefault(); triggerSearch(document.getElementById('headerSearch').value);">
        <input type="search" id="headerSearch" class="search-input" placeholder="Search the BitTorrent DHT..." autocomplete="off" />
      </form>
    </div>
  </header>

  <!-- Results View -->
  <main id="resultsArea" class="results-area">
    <div id="statusLine" class="status-line"></div>
    <ul id="torrentList" class="torrent-list"></ul>
    <div id="emptyMsg" class="empty-msg" style="display:none;">No results found for this search.</div>
  </main>

  <!-- Modal for Files -->
  <div id="fileModal" class="modal-overlay">
    <div class="modal-box">
      <div class="modal-head">
        <h3 id="modalTitle">Files</h3>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div id="modalHash" style="color:var(--text-dim); margin-bottom:0.75rem;"></div>
        <div id="modalFileList"></div>
      </div>
    </div>
  </div>

  <script>
    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function goHome() {
      document.getElementById('homeView').style.display = 'flex';
      document.getElementById('appHeader').style.display = 'none';
      document.getElementById('resultsArea').style.display = 'none';
      document.getElementById('homeSearch').value = '';
      document.getElementById('headerSearch').value = '';
      document.getElementById('homeSearch').focus();
    }

    async function triggerSearch(q) {
      q = (q || '').trim();
      if (!q) {
        goHome();
        return;
      }

      // Switch to results view
      document.getElementById('homeView').style.display = 'none';
      document.getElementById('appHeader').style.display = 'block';
      document.getElementById('resultsArea').style.display = 'block';
      document.getElementById('headerSearch').value = q;
      document.getElementById('headerSearch').focus();

      const statusEl = document.getElementById('statusLine');
      const listEl = document.getElementById('torrentList');
      const emptyEl = document.getElementById('emptyMsg');

      listEl.innerHTML = '';
      emptyEl.style.display = 'none';
      statusEl.textContent = `Searching for "${q}"...`;

      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        const items = data.items || [];
        const total = data.total || items.length;

        if (items.length === 0) {
          statusEl.textContent = '';
          emptyEl.style.display = 'block';
          return;
        }

        statusEl.textContent = `${total} results for "${q}"`;

        items.forEach(t => {
          const li = document.createElement('li');
          li.className = 'torrent-item';
          li.innerHTML = `
            <div class="item-top">
              <a href="javascript:void(0)" onclick="inspectFiles('${t.info_hash}')" class="torrent-title">${escapeHtml(t.name)}</a>
              <div class="item-actions">
                <button class="btn-action" onclick="copyMagnet('${t.magnet_uri}', this)">magnet</button>
                <button class="btn-action" onclick="inspectFiles('${t.info_hash}')">files</button>
              </div>
            </div>
            <div class="item-meta">
              <span class="meta-size">${formatBytes(t.total_size)}</span>
              <span>${t.file_count || 1} file(s)</span>
              <span class="meta-hash">${t.info_hash}</span>
            </div>
          `;
          listEl.appendChild(li);
        });
      } catch (e) {
        statusEl.textContent = 'Search encountered an error. Please try again.';
      }
    }

    function copyMagnet(uri, btn) {
      navigator.clipboard.writeText(uri).then(() => {
        const orig = btn.textContent;
        btn.textContent = 'copied';
        btn.style.color = 'var(--success)';
        btn.style.borderColor = 'var(--success)';
        setTimeout(() => {
          btn.textContent = orig;
          btn.style.color = '';
          btn.style.borderColor = '';
        }, 1500);
      });
    }

    async function inspectFiles(infoHash) {
      try {
        const res = await fetch(`/api/torrent/${infoHash}`);
        const t = await res.json();
        if (!t) return;

        document.getElementById('modalTitle').textContent = t.name;
        document.getElementById('modalHash').textContent = `${t.info_hash} · ${formatBytes(t.total_size)}`;
        const list = document.getElementById('modalFileList');
        list.innerHTML = '';

        if (t.files && t.files.length) {
          t.files.forEach(f => {
            const div = document.createElement('div');
            div.className = 'file-row';
            div.innerHTML = `<span class="file-name">${escapeHtml(f.path)}</span><span class="file-len">${formatBytes(f.length)}</span>`;
            list.appendChild(div);
          });
        } else {
          list.innerHTML = `<div style="color:var(--text-muted); padding:0.5rem 0;">Single file: ${escapeHtml(t.name)}</div>`;
        }

        document.getElementById('fileModal').style.display = 'flex';
      } catch (e) {}
    }

    function closeModal() {
      document.getElementById('fileModal').style.display = 'none';
    }

    window.onclick = function(e) {
      if (e.target.id === 'fileModal') closeModal();
    };

    window.onkeydown = function(e) {
      if (e.key === 'Escape') closeModal();
    };
  </script>
</body>
</html>
"""


class WebServer:
    def __init__(
        self,
        db: TorrentDatabase,
        stats_callback: Callable[[], Dict[str, Any]],
        host: str = "0.0.0.0",
        port: int = 8000
    ):
        self.db = db
        self.stats_callback = stats_callback
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return

            req_line = line.decode('utf-8', errors='replace').strip()
            parts = req_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, full_path = parts[0], parts[1]

            # Read headers
            while True:
                header = await reader.readline()
                if not header or header in (b'\r\n', b'\n'):
                    break

            parsed_url = urllib.parse.urlparse(full_path)
            path = parsed_url.path
            query_params = urllib.parse.parse_qs(parsed_url.query)

            # Route requests
            if path in ("/", "/index.html"):
                self.send_response(writer, 200, "text/html; charset=utf-8", HTML_TEMPLATE.encode('utf-8'))
            elif path == "/api/stats":
                stats_data = self.stats_callback()
                stats_data["db"] = self.db.get_stats()
                self.send_json(writer, stats_data)
            elif path == "/api/search":
                q = query_params.get("q", [""])[0].strip()
                page = int(query_params.get("page", [1])[0])

                # 1. Search local SQLite DB
                local_items, local_total = self.db.search(query=q, page=page, per_page=40)

                # 2. Concurrently query live global DHT index
                global_items = []
                if q:
                    try:
                        global_items = await search_global_torrents(q, max_results=40)
                        for it in global_items:
                            self.db.save_torrent(
                                info_hash=it["info_hash"],
                                name=it["name"],
                                total_size=it["total_size"],
                                files=it.get("files", [])
                            )
                    except Exception:
                        pass

                # Merge without duplicates
                seen_hashes = {it["info_hash"].lower() for it in local_items}
                merged = list(local_items)
                for it in global_items:
                    if it["info_hash"].lower() not in seen_hashes:
                        seen_hashes.add(it["info_hash"].lower())
                        merged.append(it)

                total = max(len(merged), local_total)
                self.send_json(writer, {"items": merged, "total": total})
            elif path.startswith("/api/torrent/"):
                info_hash = path[len("/api/torrent/"):]
                torrent = self.db.get_torrent(info_hash)
                if torrent:
                    self.send_json(writer, torrent)
                else:
                    self.send_response(writer, 404, "application/json", b'{"error": "Not found"}')
            else:
                self.send_response(writer, 404, "text/plain", b"Not Found")

        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def send_json(self, writer: asyncio.StreamWriter, data: Any):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(writer, 200, "application/json; charset=utf-8", body)

    def send_response(self, writer: asyncio.StreamWriter, status_code: int, content_type: str, body: bytes):
        headers = [
            f"HTTP/1.1 {status_code} OK",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "Access-Control-Allow-Origin: *",
            "\r\n"
        ]
        response = "\r\n".join(headers).encode('ascii') + body
        writer.write(response)

    def stop(self):
        if self.server:
            self.server.close()
