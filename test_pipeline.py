"""
Unit tests for SongSense core modules.
"""

from pathlib import Path
import numpy as np
import pytest

from config import DEFAULT_CONFIG
from fingerprint import (
    compute_spectrogram,
    extract_peaks,
    generate_hashes,
    load_audio,
    fingerprint_audio,
)
from redis_store import RedisFingerprintStore
from neo4j_store import Neo4jMetadataStore
from matcher import identify_audio


def test_fingerprint_pipeline_on_sine_wave():
    # 3 second multi-tone audio
    sr = 22050
    t = np.linspace(0, 3.0, int(sr * 3.0), endpoint=False)
    signal = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t)

    spectrogram_db = compute_spectrogram(signal, DEFAULT_CONFIG)
    assert spectrogram_db.ndim == 2
    assert spectrogram_db.shape[0] > 0

    peaks = extract_peaks(spectrogram_db, DEFAULT_CONFIG)
    assert len(peaks) > 0

    hashes = generate_hashes(peaks, DEFAULT_CONFIG)
    assert len(hashes) > 0
    # Hash length check
    assert len(hashes[0][0]) == DEFAULT_CONFIG.hash_length


def test_in_memory_stores_and_matching():
    r_store = RedisFingerprintStore()
    n_store = Neo4jMetadataStore()

    # Clear memory
    r_store.clear()

    # Synthetic signal 1
    sr = 22050
    t = np.linspace(0, 5.0, int(sr * 5.0), endpoint=False)
    sig1 = 0.6 * np.sin(2 * np.pi * 523.25 * t) + 0.3 * np.sin(2 * np.pi * 659.25 * t)
    fps1 = fingerprint_audio(sig1, DEFAULT_CONFIG)

    r_store.add_song_fingerprints("song_c_major", fps1)
    n_store.add_song_metadata(
        song_id="song_c_major",
        title="C Major Symphony",
        composer="Mozart",
        raga="Bilawal",
    )

    # Query with identical clip
    res = identify_audio(sig1[: int(sr * 2.5)], store=r_store, config=DEFAULT_CONFIG)
    assert res.matched is True
    assert res.song_id == "song_c_major"
    assert res.votes >= DEFAULT_CONFIG.min_votes
    assert res.confidence > 0.0
