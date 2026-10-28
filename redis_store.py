from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False

from config import (
    REDIS_DB,
    REDIS_HOST,
    REDIS_KEY_PREFIX,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_SONGS_SET_KEY,
    REDIS_STATS_HASHES_KEY,
    REDIS_STATS_SONGS_KEY,
)

logger = logging.getLogger("SongSense.RedisStore")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class RedisFingerprintStore:
    """Manages fingerprint hash indexing in Redis with an automatic in-memory fallback."""

    def __init__(
        self,
        host: str = REDIS_HOST,
        port: int = REDIS_PORT,
        db: int = REDIS_DB,
        password: Optional[str] = REDIS_PASSWORD,
    ) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.client: Optional[redis.Redis] = None
        self.is_connected = False

        self._memory_index: Dict[str, Set[str]] = defaultdict(set)
        self._memory_songs: Set[str] = set()
        self._memory_total_hashes: int = 0

        self._connect()

    def _connect(self) -> None:
        """Attempts connection to Redis server. Falls back to in-memory on error."""
        if not REDIS_AVAILABLE:
            logger.warning(
                "Redis library not installed. Using in-memory fallback storage for fingerprints."
            )
            self.is_connected = False
            return

        try:
            client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            client.ping()
            self.client = client
            self.is_connected = True
            logger.info("Successfully connected to Redis at %s:%d (db=%d).", self.host, self.port, self.db)
        except Exception as exc:
            self.client = None
            self.is_connected = False
            logger.warning(
                "Could not connect to Redis at %s:%d (%s). Falling back gracefully to in-memory dictionary.",
                self.host,
                self.port,
                exc,
            )

    def add_song_fingerprints(
        self,
        song_id: str,
        fingerprints: List[Tuple[str, int]],
        batch_size: int = 2000,
    ) -> int:
        """Stores fingerprints for a song into the inverted index."""
        if not fingerprints:
            logger.debug("No fingerprints to add for song_id: %s", song_id)
            return 0

        total = len(fingerprints)

        if self.is_connected and self.client is not None:
            try:
                pipe = self.client.pipeline(transaction=False)
                count_in_batch = 0

                for hash_str, offset in fingerprints:
                    redis_key = f"{REDIS_KEY_PREFIX}{hash_str}"
                    entry = f"{song_id}:{offset}"
                    pipe.sadd(redis_key, entry)
                    count_in_batch += 1

                    if count_in_batch >= batch_size:
                        pipe.execute()
                        pipe = self.client.pipeline(transaction=False)
                        count_in_batch = 0

                if count_in_batch > 0:
                    pipe.execute()

                self.client.sadd(REDIS_SONGS_SET_KEY, song_id)
                self.client.set(REDIS_STATS_SONGS_KEY, self.client.scard(REDIS_SONGS_SET_KEY))
                self.client.incrby(REDIS_STATS_HASHES_KEY, total)

                logger.info("Indexed %d fingerprints for song '%s' in Redis.", total, song_id)
                return total
            except Exception as exc:
                logger.warning(
                    "Redis write failed (%s). Falling back to in-memory index for song '%s'.",
                    exc,
                    song_id,
                )
                self.is_connected = False

        for hash_str, offset in fingerprints:
            entry = f"{song_id}:{offset}"
            self._memory_index[hash_str].add(entry)

        self._memory_songs.add(song_id)
        self._memory_total_hashes += total
        logger.info("Indexed %d fingerprints for song '%s' in IN-MEMORY storage.", total, song_id)
        return total

    def lookup_hashes(
        self,
        hashes: List[str],
        batch_size: int = 2000,
    ) -> Dict[str, Set[str]]:
        """Returns matching entries for each hash."""
        unique_hashes = list(set(hashes))
        results: Dict[str, Set[str]] = {}

        if self.is_connected and self.client is not None:
            try:
                for i in range(0, len(unique_hashes), batch_size):
                    batch = unique_hashes[i : i + batch_size]
                    pipe = self.client.pipeline(transaction=False)
                    for h in batch:
                        pipe.smembers(f"{REDIS_KEY_PREFIX}{h}")
                    batch_results = pipe.execute()

                    for h, members in zip(batch, batch_results):
                        if members:
                            results[h] = set(members)
                return results
            except Exception as exc:
                logger.warning("Redis lookup failed (%s). Attempting in-memory lookup fallback.", exc)
                self.is_connected = False

        for h in unique_hashes:
            members = self._memory_index.get(h)
            if members:
                results[h] = set(members)

        return results

    def get_stats(self) -> Dict[str, int]:
        """Returns stats: total indexed songs and total stored hashes."""
        if self.is_connected and self.client is not None:
            try:
                total_songs = int(self.client.scard(REDIS_SONGS_SET_KEY) or 0)
                total_hashes = int(self.client.get(REDIS_STATS_HASHES_KEY) or 0)
                return {
                    "total_songs": total_songs,
                    "total_hashes": total_hashes,
                    "backend": "redis",
                }
            except Exception:
                pass

        return {
            "total_songs": len(self._memory_songs),
            "total_hashes": self._memory_total_hashes,
            "backend": "in-memory",
        }

    def clear(self) -> None:
        """Clears the index (useful for testing or re-indexing)."""
        if self.is_connected and self.client is not None:
            try:
                for key in self.client.scan_iter(match=f"{REDIS_KEY_PREFIX}*"):
                    self.client.unlink(key)
                self.client.delete(
                    REDIS_STATS_SONGS_KEY,
                    REDIS_STATS_HASHES_KEY,
                    REDIS_SONGS_SET_KEY,
                )
            except Exception as exc:
                logger.error("Failed to clear Redis index: %s", exc)

        self._memory_index.clear()
        self._memory_songs.clear()
        self._memory_total_hashes = 0
        logger.info("Cleared fingerprint index.")


redis_store = RedisFingerprintStore()
