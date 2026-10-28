"""SQLite-based persistent fingerprint store for cross-process data sharing."""

import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("SongSense.SQLiteStore")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

DB_PATH = Path(__file__).parent / "fingerprints.db"


class SQLiteFingerprintStore:
    """Persistent fingerprint store using SQLite for cross-process sharing."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._ensure_schema()
        logger.info(f"Initialized SQLiteFingerprintStore at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a fresh connection to the database."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Creates tables if they don't exist."""
        conn = self._get_connection()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                hash TEXT NOT NULL,
                song_id TEXT NOT NULL,
                offset INTEGER NOT NULL,
                PRIMARY KEY (hash, song_id, offset)
            );
            CREATE INDEX IF NOT EXISTS idx_hash ON fingerprints(hash);
            CREATE INDEX IF NOT EXISTS idx_song ON fingerprints(song_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def add_song_fingerprints(
        self,
        song_id: str,
        fingerprints: List[Tuple[str, int]],
        batch_size: int = 2000,
    ) -> int:
        """Stores fingerprints for a song. Returns count of fingerprints added."""
        if not fingerprints:
            logger.debug(f"No fingerprints to add for song_id: {song_id}")
            return 0

        conn = self._get_connection()
        try:
            # Delete old fingerprints for this song (in case of re-ingestion)
            conn.execute("DELETE FROM fingerprints WHERE song_id = ?", (song_id,))

            # Insert in batches
            for i in range(0, len(fingerprints), batch_size):
                batch = fingerprints[i : i + batch_size]
                conn.executemany(
                    "INSERT OR IGNORE INTO fingerprints (hash, song_id, offset) VALUES (?, ?, ?)",
                    [(h, song_id, o) for h, o in batch],
                )
            conn.commit()
            logger.info(f"Indexed {len(fingerprints)} fingerprints for song '{song_id}' in SQLite.")
            return len(fingerprints)
        finally:
            conn.close()

    def lookup_hashes(self, hashes: List[str], batch_size: int = 2000) -> Dict[str, Set[str]]:
        """Returns matching entries for each hash in format 'song_id:offset'."""
        unique_hashes = list(set(hashes))
        results: Dict[str, Set[str]] = {}

        if not unique_hashes:
            return results

        conn = self._get_connection()
        try:
            for i in range(0, len(unique_hashes), batch_size):
                batch = unique_hashes[i : i + batch_size]
                placeholders = ",".join("?" * len(batch))
                query = f"SELECT hash, song_id, offset FROM fingerprints WHERE hash IN ({placeholders})"
                rows = conn.execute(query, batch).fetchall()

                for row in rows:
                    h = row["hash"]
                    entry = f"{row['song_id']}:{row['offset']}"
                    if h not in results:
                        results[h] = set()
                    results[h].add(entry)

            return results
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, int]:
        """Returns stats: total songs and total hashes."""
        conn = self._get_connection()
        try:
            total_hashes = conn.execute("SELECT COUNT(*) as cnt FROM fingerprints").fetchone()["cnt"]
            total_songs = conn.execute(
                "SELECT COUNT(DISTINCT song_id) as cnt FROM fingerprints"
            ).fetchone()["cnt"]
            return {
                "total_songs": total_songs,
                "total_hashes": total_hashes,
                "backend": "sqlite",
            }
        finally:
            conn.close()

    def clear(self) -> None:
        """Clears all fingerprints."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM fingerprints")
            conn.commit()
            logger.info("Cleared all fingerprints from SQLite.")
        finally:
            conn.close()


# Global singleton
sqlite_store = SQLiteFingerprintStore()
