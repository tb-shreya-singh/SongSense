#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from fingerprint import load_audio, compute_spectrogram, extract_peaks
from config import DEFAULT_CONFIG
import numpy as np

audio_file = Path('songs/Pavazha Malli_320(KoshalWorld.Com).mp3')
y, sr = load_audio(audio_file, sample_rate=22050)
print(f"Audio loaded: {len(y)} samples at {sr} Hz, duration: {len(y)/sr:.1f}s")

spec_db = compute_spectrogram(y, config=DEFAULT_CONFIG)
print(f"Spectrogram: {spec_db.shape}, min={spec_db.min():.1f} dB, max={spec_db.max():.1f} dB, median={np.median(spec_db):.1f} dB")

peaks = extract_peaks(spec_db, config=DEFAULT_CONFIG)
print(f"Extracted peaks: {len(peaks)}")
if peaks:
    print(f"  First 5 peaks: {peaks[:5]}")

# Try very relaxed thresholds
from copy import copy
relaxed = copy(DEFAULT_CONFIG)
relaxed = relaxed._replace(
    peak_db_above_frame_median=2.0,
    peak_db_above_global_max=20.0,
    amp_threshold=-40.0,
    max_peaks_per_frame=20
)
peaks_relaxed = extract_peaks(spec_db, config=relaxed)
print(f"Extracted peaks (relaxed): {len(peaks_relaxed)}")

if peaks_relaxed:
    from fingerprint import generate_hashes
    hashes = generate_hashes(peaks_relaxed, config=relaxed)
    print(f"Generated hashes: {len(hashes)}")
