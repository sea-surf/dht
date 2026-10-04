"""
SQLite database storage and search engine with FTS5 Full-Text Search.
Provides persistent storage for discovered torrents with zero external dependencies.
"""

import contextlib
import json
import sqlite3
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class TorrentDatabase:
    def __init__(self, db_path: str = "torrents.db"):
        self.db_path = Path(db_path).resolve()
        self.has_fts5 = False
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS torrents (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    info_hash TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    total_size INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    files_json TEXT NOT NULL,
                    discovered_at INTEGER NOT NULL,
                    magnet_uri TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_discovered ON torrents(discovered_at DESC)")

            # Check and setup FTS5
            try:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS torrents_fts USING fts5(
                        name,
                        info_hash UNINDEXED,
                        content='torrents',
                        content_rowid='rowid'
                    )
                """)

                # Triggers to keep FTS index synchronized
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS torrents_ai AFTER INSERT ON torrents BEGIN
                        INSERT INTO torrents_fts(rowid, name, info_hash) VALUES (new.rowid, new.name, new.info_hash);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS torrents_ad AFTER DELETE ON torrents BEGIN
                        INSERT INTO torrents_fts(torrents_fts, rowid, name, info_hash) VALUES('delete', old.rowid, old.name, old.info_hash);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS torrents_au AFTER UPDATE ON torrents BEGIN
                        INSERT INTO torrents_fts(torrents_fts, rowid, name, info_hash) VALUES('delete', old.rowid, old.name, old.info_hash);
                        INSERT INTO torrents_fts(rowid, name, info_hash) VALUES (new.rowid, new.name, new.info_hash);
                    END;
                """)
                self.has_fts5 = True
            except sqlite3.OperationalError:
                self.has_fts5 = False
            conn.commit()

    def has_torrent(self, info_hash: str) -> bool:
        """Checks if a torrent with the given info_hash has complete metadata."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM torrents WHERE info_hash = ? AND total_size > 0 LIMIT 1", (info_hash.lower(),))
            return cur.fetchone() is not None

    def record_sniffed_hash(self, info_hash: str) -> bool:
        """Immediately stores a sniffed hash so it appears in live feed before metadata arrives."""
        info_hash = info_hash.lower()
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}"
        placeholder_name = f"[Sniffed] {info_hash[:12]}..."
        now = int(time.time())

        with self._get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO torrents (info_hash, name, total_size, file_count, files_json, discovered_at, magnet_uri)
                    VALUES (?, ?, 0, 0, '[]', ?, ?)
                    ON CONFLICT(info_hash) DO NOTHING
                """, (info_hash, placeholder_name, now, magnet_uri))
                conn.commit()
                return cur.rowcount > 0
            except Exception:
                return False

    def save_torrent(
        self,
        info_hash: str,
        name: str,
        total_size: int,
        files: List[Dict[str, Any]],
        discovered_at: Optional[int] = None
    ) -> bool:
        """
        Saves or updates torrent with full metadata.
        Returns True if newly inserted or updated.
        """
        info_hash = info_hash.lower()
        if discovered_at is None:
            discovered_at = int(time.time())

        dn_param = urllib.parse.quote(name)
        magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn={dn_param}"

        files_json = json.dumps(files, ensure_ascii=False)
        file_count = len(files) if files else 1

        with self._get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO torrents (info_hash, name, total_size, file_count, files_json, discovered_at, magnet_uri)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(info_hash) DO UPDATE SET
                        name = excluded.name,
                        total_size = excluded.total_size,
                        file_count = excluded.file_count,
                        files_json = excluded.files_json,
                        magnet_uri = excluded.magnet_uri
                """, (info_hash, name, total_size, file_count, files_json, discovered_at, magnet_uri))
                conn.commit()
                return True
            except Exception:
                return False

    def search(self, query: str, page: int = 1, per_page: int = 25) -> Tuple[List[Dict[str, Any]], int]:
        """
        Searches torrents by keyword or info_hash.
        Returns (list_of_results, total_count).
        """
        query = query.strip()
        if not query:
            return self.get_recent(page=page, per_page=per_page)

        # Exact match on info_hash (40 hex chars)
        if len(query) == 40 and all(c in "0123456789abcdefABCDEF" for c in query):
            item = self.get_torrent(query.lower())
            if item:
                return [item], 1
            return [], 0

        offset = max(0, (page - 1) * per_page)
        with self._get_connection() as conn:
            cur = conn.cursor()

            if self.has_fts5:
                # Sanitize query for FTS5 (escape special FTS characters)
                safe_words = [f'"{w}"*' for w in query.replace('"', '').split() if w]
                fts_query = " ".join(safe_words)
                if not fts_query:
                    return [], 0

                try:
                    cur.execute("""
                        SELECT count(*) FROM torrents_fts WHERE torrents_fts MATCH ?
                    """, (fts_query,))
                    total = cur.fetchone()[0]

                    cur.execute("""
                        SELECT t.info_hash, t.name, t.total_size, t.file_count, t.discovered_at, t.magnet_uri
                        FROM torrents_fts f
                        JOIN torrents t ON t.rowid = f.rowid
                        WHERE torrents_fts MATCH ?
                        ORDER BY rank
                        LIMIT ? OFFSET ?
                    """, (fts_query, per_page, offset))
                    rows = cur.fetchall()
                    return [dict(r) for r in rows], total
                except sqlite3.OperationalError:
                    pass

            # Fallback to standard LIKE search
            like_query = f"%{query}%"
            cur.execute("SELECT count(*) FROM torrents WHERE name LIKE ?", (like_query,))
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT info_hash, name, total_size, file_count, discovered_at, magnet_uri
                FROM torrents
                WHERE name LIKE ?
                ORDER BY discovered_at DESC
                LIMIT ? OFFSET ?
            """, (like_query, per_page, offset))
            rows = cur.fetchall()
            return [dict(r) for r in rows], total

    def get_recent(self, page: int = 1, per_page: int = 25) -> Tuple[List[Dict[str, Any]], int]:
        """Returns the most recently discovered torrents."""
        offset = max(0, (page - 1) * per_page)
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM torrents")
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT info_hash, name, total_size, file_count, discovered_at, magnet_uri
                FROM torrents
                ORDER BY discovered_at DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset))
            rows = cur.fetchall()
            return [dict(r) for r in rows], total

    def get_torrent(self, info_hash: str) -> Optional[Dict[str, Any]]:
        """Returns full torrent details including file list."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT info_hash, name, total_size, file_count, files_json, discovered_at, magnet_uri
                FROM torrents
                WHERE info_hash = ?
                LIMIT 1
            """, (info_hash.lower(),))
            row = cur.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["files"] = json.loads(data["files_json"])
            except Exception:
                data["files"] = []
            return data

    def get_stats(self) -> Dict[str, Any]:
        """Returns database overview statistics."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*), coalesce(sum(total_size), 0) FROM torrents")
            count, total_bytes = cur.fetchone()

            one_hour_ago = int(time.time()) - 3600
            cur.execute("SELECT count(*) FROM torrents WHERE discovered_at >= ?", (one_hour_ago,))
            last_hour = cur.fetchone()[0]

            return {
                "total_torrents": count,
                "total_size_bytes": total_bytes,
                "last_hour_torrents": last_hour,
                "fts_enabled": self.has_fts5
            }
