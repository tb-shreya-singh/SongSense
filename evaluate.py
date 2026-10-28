"""
SongSense: Audio Identification Evaluation Benchmark (evaluate.py)
==================================================================
Automated empirical test harness:
- Cuts 20 random 10-second clips from the indexed songs.
- Adds Gaussian noise at multiple Signal-to-Noise Ratio (SNR) levels.
- Runs matcher.identify_audio on each query clip.
- Computes Identification Accuracy, Average Query Latency, and saves results.csv.

VIVA EXPLANATION:
-----------------
1. Noise Robustness Testing:
   - Mobile microphone recordings in cafes or cars suffer from ambient noise.
   - We test three noise levels:
     * Clean (No noise, Inf dB SNR)
     * Mild Noise (20 dB SNR - background whisper / quiet room)
     * Moderate Noise (10 dB SNR - bustling cafe / outdoor traffic)
     * Heavy Noise (5 dB SNR - noisy bar / loud vehicle)
2. Evaluation Metric:
   - Top-1 Accuracy: % of clips correctly mapped to their ground truth song.
   - Query Latency: Time in milliseconds to fingerprint and match a 10s query.
"""

from __future__ import annotations

import csv
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

# Ensure local imports work cleanly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from config import DEFAULT_CONFIG, RESULTS_FILE, SAMPLE_RATE, SONGS_DIR
from fingerprint import load_audio
from ingest import generate_sample_audio_files, ingest_folder
from matcher import identify_audio
from redis_store import redis_store

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("SongSense.Evaluate")


def add_gaussian_noise(signal: np.ndarray, snr_db: float) -> np.ndarray:
    """
    Adds white Gaussian noise to audio signal to achieve the specified Signal-to-Noise Ratio (SNR in dB).

    Viva Note:
    SNR_dB = 10 * log10(P_signal / P_noise)
    P_noise = P_signal / (10^(SNR_dB / 10))
    """
    signal_power = np.mean(signal ** 2)
    if signal_power == 0:
        return signal

    noise_power = signal_power / (10.0 ** (snr_db / 10.0))
    noise = np.random.normal(0, np.sqrt(noise_power), len(signal)).astype(np.float32)
    noisy_signal = signal + noise
    # Prevent digital clipping
    max_val = np.max(np.abs(noisy_signal))
    if max_val > 1.0:
        noisy_signal = noisy_signal / max_val
    return noisy_signal


def run_evaluation(
    num_trials: int = 20,
    clip_duration_sec: float = 10.0,
    output_csv: Path = RESULTS_FILE,
) -> Dict[str, float]:
    """
    Executes benchmark over random clips under varying noise levels.
    """
    # 1. Ensure songs exist and are ingested
    audio_files = list(SONGS_DIR.glob("*.wav")) + list(SONGS_DIR.glob("*.mp3"))
    if not audio_files:
        logger.info("No audio files found. Generating samples and running ingestion...")
        generate_sample_audio_files(SONGS_DIR)
        ingest_folder(auto_generate=True)
        audio_files = list(SONGS_DIR.glob("*.wav")) + list(SONGS_DIR.glob("*.mp3"))

    stats = redis_store.get_stats()
    if stats.get("total_songs", 0) == 0:
        logger.info("Index empty. Running ingestion...")
        ingest_folder()

    print("\n" + "=" * 70)
    print("  SongSense: Audio Fingerprinting Evaluation & Robustness Benchmark")
    print("=" * 70)
    print(f"Number of Trials:   {num_trials}")
    print(f"Clip Duration:      {clip_duration_sec} seconds")
    print(f"Available Songs:    {len(audio_files)}")
    print(f"Index Backend:      {stats.get('backend', 'unknown').upper()}")
    print("=" * 70 + "\n")

    # Load all indexed songs into memory for fast cutting
    song_cache: Dict[str, np.ndarray] = {}
    for f in audio_files:
        song_id = f.stem
        audio, _ = load_audio(f, sample_rate=SAMPLE_RATE)
        song_cache[song_id] = audio

    # Noise levels to test: None (Clean), 20 dB (Mild), 10 dB (Moderate), 5 dB (Heavy)
    test_conditions = [
        ("Clean (No Noise)", None),
        ("20 dB SNR (Mild)", 20.0),
        ("10 dB SNR (Moderate)", 10.0),
        ("5 dB SNR (Heavy)", 5.0),
    ]

    results_records: List[Dict[str, str | float | int | bool]] = []
    condition_stats: Dict[str, Dict[str, float]] = {}

    rng = random.Random(42)
    np_rng = np.random.RandomState(42)

    for cond_name, snr in test_conditions:
        correct_count = 0
        total_latency = 0.0

        for trial in range(1, num_trials + 1):
            # Select random song
            target_song_id = rng.choice(list(song_cache.keys()))
            full_audio = song_cache[target_song_id]

            clip_samples = int(clip_duration_sec * SAMPLE_RATE)
            max_start = max(0, len(full_audio) - clip_samples)
            start_idx = rng.randint(0, max_start) if max_start > 0 else 0
            raw_clip = full_audio[start_idx : start_idx + clip_samples]

            # Inject noise if condition specifies SNR
            if snr is not None:
                eval_clip = add_gaussian_noise(raw_clip, snr_db=snr)
            else:
                eval_clip = raw_clip

            # Run identification and measure execution time
            t0 = time.perf_counter()
            match_res = identify_audio(eval_clip, store=redis_store, config=DEFAULT_CONFIG)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            total_latency += latency_ms

            is_correct = (match_res.matched and match_res.song_id == target_song_id)
            if is_correct:
                correct_count += 1

            results_records.append({
                "trial": trial,
                "condition": cond_name,
                "snr_db": snr if snr is not None else "Clean",
                "ground_truth": target_song_id,
                "predicted": match_res.song_id or "None",
                "correct": is_correct,
                "votes": match_res.votes,
                "confidence": match_res.confidence,
                "offset_sec": match_res.offset_sec,
                "latency_ms": round(latency_ms, 2),
            })

        acc = (correct_count / num_trials) * 100.0
        avg_lat = total_latency / num_trials
        condition_stats[cond_name] = {"accuracy": acc, "avg_latency_ms": avg_lat}

    # Save detailed CSV
    fieldnames = [
        "trial", "condition", "snr_db", "ground_truth", "predicted",
        "correct", "votes", "confidence", "offset_sec", "latency_ms"
    ]
    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results_records)

    # Print Summary Table
    print("\n" + "-" * 70)
    print(f"{'Condition':<25} | {'Accuracy (%)':<15} | {'Avg Latency (ms)':<15}")
    print("-" * 70)
    for cond_name, stats_dict in condition_stats.items():
        print(
            f"{cond_name:<25} | {stats_dict['accuracy']:>13.1f}% | "
            f"{stats_dict['avg_latency_ms']:>13.2f} ms"
        )
    print("-" * 70)
    print(f"\n[+] Detailed trial results exported to: {output_csv.resolve()}\n")

    return {k: v["accuracy"] for k, v in condition_stats.items()}


def main() -> None:
    run_evaluation(num_trials=20, clip_duration_sec=10.0)


if __name__ == "__main__":
    main()
