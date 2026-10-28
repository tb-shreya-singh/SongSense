"""
SongSense: Audio Ingestion Engine (ingest.py)
============================================
Scans a folder (default: ./songs) for audio files (.wav, .mp3, .ogg, .flac)
and its companion metadata.csv. Extracts landmark fingerprints, writes them to Redis,
and registers the metadata knowledge graph in Neo4j.

VIVA EXPLANATION:
-----------------
1. Ingestion Workflow:
   - Reads metadata.csv to bind audio files to musical metadata (title, composer, raga).
   - For each song file:
     * Load audio normalized to mono 22,050 Hz.
     * Computes STFT dB Spectrogram.
     * Extracts Constellation energy peaks.
     * Generates combinatorial target-zone hashes.
     * Writes all hashes to Redis inverted index using pipelined batches.
     * Creates Song, Composer, Film, Singer, and Raga nodes with relations in Neo4j.
2. CLI Usage:
   python ingest.py
   python ingest.py --dir ./songs --csv ./songs/metadata.csv --generate-samples
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import soundfile as sf

# Add parent directory to sys.path so config can be imported directly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from config import (
    DEFAULT_CONFIG,
    METADATA_FILE,
    SAMPLE_RATE,
    SONGS_DIR,
)
from fingerprint import fingerprint_audio, load_audio
from neo4j_store import neo4j_store
from sqlite_store import sqlite_store

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("SongSense.Ingest")


def generate_sample_audio_files(target_dir: Path, sample_rate: int = SAMPLE_RATE) -> None:
    """
    Generates 5 distinct synthetic acoustic songs with realistic harmonic structures
    and chord progressions if no audio files exist yet.

    Viva Note:
    Synthesizes multi-harmonic polyphonic acoustic waveforms (30 seconds each)
    using distinct musical scales (Bhoopali pentatonic, Yaman heptatonic, Darbari, etc.)
    with envelope attack-decay-sustain-release (ADSR) to ensure realistic spectrogram peaks.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # 5 songs with different root frequencies and melodic scales
    song_blueprints = [
        ("song1_bhoopali.wav", 220.0, [1.0, 9/8, 5/4, 3/2, 5/3]),         # Bhoopali (C-D-E-G-A)
        ("song2_bairagi.wav", 246.94, [1.0, 16/15, 4/3, 3/2, 9/5]),        # Bairagi (B-C-E-F#-A)
        ("song3_bhoopali_night.wav", 293.66, [1.0, 9/8, 5/4, 3/2, 5/3]),  # D Bhoopali
        ("song4_yaman.wav", 261.63, [1.0, 9/8, 5/4, 45/32, 3/2, 5/3, 15/8]), # Yaman (Lydian)
        ("song5_darbari.wav", 196.0, [1.0, 9/8, 6/5, 4/3, 3/2, 8/5, 9/5]), # Darbari Kanhada
    ]

    duration_sec = 25.0
    num_samples = int(sample_rate * duration_sec)
    t = np.linspace(0, duration_sec, num_samples, endpoint=False)

    for filename, base_freq, scale_ratios in song_blueprints:
        out_path = target_dir / filename
        if out_path.exists():
            continue

        signal = np.zeros(num_samples, dtype=np.float32)

        # Generate musical phrases with notes varying over time
        note_duration = 0.5  # seconds per note
        samples_per_note = int(sample_rate * note_duration)
        total_notes = num_samples // samples_per_note

        # Seed per file for reproducible melodic patterns
        rng = np.random.RandomState(abs(int(base_freq * 100)))

        for n_idx in range(total_notes):
            ratio = rng.choice(scale_ratios)
            note_freq = base_freq * ratio
            start_s = n_idx * samples_per_note
            end_s = min(start_s + samples_per_note, num_samples)
            note_t = t[start_s:end_s] - t[start_s]

            # Harmonic rich synthesizer: fundamental + 2nd, 3rd, 4th harmonics
            note_wave = (
                0.50 * np.sin(2 * np.pi * note_freq * note_t) +
                0.25 * np.sin(2 * np.pi * 2 * note_freq * note_t) +
                0.15 * np.sin(2 * np.pi * 3 * note_freq * note_t) +
                0.10 * np.sin(2 * np.pi * 4 * note_freq * note_t)
            )

            # Smooth trapezoidal ADSR envelope to create sharp, distinctive attack peaks
            env = np.ones_like(note_wave)
            ramp_len = min(int(sample_rate * 0.05), len(env) // 2)
            if ramp_len > 0:
                env[:ramp_len] = np.linspace(0.0, 1.0, ramp_len)
                env[-ramp_len:] = np.linspace(1.0, 0.0, ramp_len)

            signal[start_s:end_s] += (note_wave * env).astype(np.float32)

        # Normalize signal amplitude to prevent clipping (-1.0 to 1.0)
        max_amp = np.max(np.abs(signal))
        if max_amp > 0:
            signal = (signal / max_amp) * 0.85

        sf.write(str(out_path), signal, sample_rate)
        logger.info("Generated synthetic audio sample: %s", out_path.name)


def load_metadata_map(csv_path: Path) -> Dict[str, Dict[str, str]]:
    """Reads metadata.csv into a lookup dictionary keyed by filename."""
    meta_map: Dict[str, Dict[str, str]] = {}
    if not csv_path.exists():
        logger.warning("Metadata CSV not found at: %s", csv_path)
        return meta_map

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("filename", "").strip()
            if fn:
                meta_map[fn] = {
                    "title": row.get("title", "").strip(),
                    "composer": row.get("composer", "").strip(),
                    "film": row.get("film", "").strip(),
                    "singer": row.get("singer", "").strip(),
                    "raga": row.get("raga", "").strip(),
                }
    return meta_map


def ingest_folder(
    songs_dir: Path = SONGS_DIR,
    metadata_csv: Path = METADATA_FILE,
    auto_generate: bool = True,
) -> None:
    """
    Main ingestion routine: scans audio folder, calculates fingerprints,
    and indexes into Redis and Neo4j.
    """
    songs_dir.mkdir(parents=True, exist_ok=True)

    # Check for audio files
    audio_extensions = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
    existing_files = [f for f in songs_dir.iterdir() if f.suffix.lower() in audio_extensions]

    if not existing_files and auto_generate:
        logger.info("No audio files detected in %s. Generating 5 synthetic song samples...", songs_dir)
        generate_sample_audio_files(songs_dir)
        existing_files = [f for f in songs_dir.iterdir() if f.suffix.lower() in audio_extensions]

    if not existing_files:
        logger.error("No audio files found in %s to ingest.", songs_dir)
        return

    metadata_map = load_metadata_map(metadata_csv)

    print("\n" + "=" * 60)
    print("  SongSense: Audio Ingestion & Indexing Pipeline")
    print("=" * 60)
    print(f"Directory:    {songs_dir.resolve()}")
    print(f"Total Songs:  {len(existing_files)}")
    print(f"SQLite Store: {sqlite_store.db_path}")
    print(f"Neo4j Target: {neo4j_store.uri} (Connected: {neo4j_store.is_connected})")
    print("=" * 60 + "\n")

    grand_total_hashes = 0

    for idx, audio_file in enumerate(sorted(existing_files), start=1):
        filename = audio_file.name
        # Use stem as default song ID
        song_id = audio_file.stem

        # Metadata extraction
        meta = metadata_map.get(filename, {})
        title = meta.get("title") or song_id.replace("_", " ").title()
        composer = meta.get("composer") or "Unknown"
        film = meta.get("film") or "Unknown"
        singer = meta.get("singer") or "Unknown"
        raga = meta.get("raga") or "Unknown"

        # Load audio & calculate duration
        try:
            y, sr = load_audio(audio_file, sample_rate=DEFAULT_CONFIG.sample_rate)
            duration_sec = float(len(y) / sr) if sr > 0 else 0.0
        except Exception as exc:
            logger.error("Skipping '%s': unable to load audio (%s)", filename, exc)
            continue

        # Extract Fingerprint Hashes
        fps = fingerprint_audio(y, config=DEFAULT_CONFIG)
        num_hashes = len(fps)
        grand_total_hashes += num_hashes

        # Index in SQLite (Persistent Index)
        sqlite_store.add_song_fingerprints(song_id=song_id, fingerprints=fps)

        # Index in Neo4j (Knowledge Graph)
        neo4j_store.add_song_metadata(
            song_id=song_id,
            title=title,
            composer=composer,
            film=film,
            singer=singer,
            raga=raga,
            duration_sec=duration_sec,
            filename=filename,
        )

        print(
            f"[{idx}/{len(existing_files)}] Indexed '{title}' ({filename}) "
            f"| Duration: {duration_sec:.1f}s | Hashes: {num_hashes:,}"
        )

    stats = sqlite_store.get_stats()
    print("\n" + "=" * 60)
    print("  Ingestion Complete!")
    print("=" * 60)
    print(f"Total Songs Processed: {len(existing_files)}")
    print(f"Total Hashes Indexed:  {grand_total_hashes:,}")
    print(f"Store Backend:         {stats.get('backend', 'unknown').upper()}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest audio files into SongSense index.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=SONGS_DIR,
        help="Path to folder containing audio files (default: ./songs)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=METADATA_FILE,
        help="Path to metadata.csv file (default: ./songs/metadata.csv)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing Redis index before ingestion",
    )
    args = parser.parse_args()

    if args.clear:
        redis_store.clear()

    ingest_folder(songs_dir=args.dir, metadata_csv=args.csv)


if __name__ == "__main__":
    main()
