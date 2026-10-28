#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from ingest import ingest_folder
from redis_store import redis_store

print('[Ingesting songs...]')
ingest_folder(Path('songs'), auto_generate=False)
stats = redis_store.get_stats()
print(f'Done. Total songs: {stats.get("total_songs", 0)}, Total hashes: {stats.get("total_hashes", 0)}')
