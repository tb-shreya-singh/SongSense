"""
SongSense: Audio Fingerprinting Engine (fingerprint.py)
======================================================
This module implements the landmark-based audio fingerprinting algorithm
popularized by Avery Li-Chun Wang (Shazam, 2003).

VIVA THEORY & ARCHITECTURAL OVERVIEW:
-------------------------------------
1. Spectrogram Computation (STFT):
   - Sound is digitized as a 1D time-series waveform y(t).
   - We transform the 1D signal into a 2D time-frequency spectrogram using the
     Short-Time Fourier Transform (STFT).
   - Frequency resolution depends on FFT window size (N = 4096 ~= 5.38 Hz/bin at 22.05 kHz).
   - Temporal resolution depends on hop size (H = 2048 ~= 92.88 ms/frame).
   - Amplitudes are converted to the logarithmic Decibel (dB) scale because human
     hearing perception is logarithmic: dB = 20 * log10(|S| / S_ref).

2. Constellation Map (Local Peak Picking):
   - A raw spectrogram has millions of data points; transmitting or indexing all of
     them is prohibitive and fragile to ambient noise.
   - Instead, we extract "constellation points" — robust local energy peaks where the
     magnitude is greater than all surrounding neighbors in a 2D time-frequency box.
   - We use `scipy.ndimage.maximum_filter` to perform 2D morphological dilation. A point
     is a peak if and only if its value matches the local maximum and exceeds an
     amplitude threshold above the floor.
   - Energy peaks survive heavy background noise, distortion, and mobile microphone filtering.

3. Combinatorial Hashing (Landmark Pairs):
   - Single peaks are not discriminative enough (many songs share a 440 Hz 'A' note).
   - We link each "anchor peak" (f1, t1) to N downstream peaks (f2, t2) within a
     "target zone" (t1 + delta_t_min <= t2 <= t1 + delta_t_max).
   - The triplet (f1, f2, delta_t = t2 - t1) forms a reproducible musical landmark.
   - Notice that delta_t is relative, making the hash completely shift-invariant!
   - We hash (f1, f2, delta_t) using SHA-1 (truncated to 20 hex characters = 80 bits).
   - Fingerprint tuple: `(hash_str, anchor_time_offset_t1)`.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import BinaryIO, List, Tuple, Union

import librosa
import numpy as np
from scipy.ndimage import maximum_filter

from config import DEFAULT_CONFIG, FingerprintConfig

logger = logging.getLogger("SongSense.Fingerprint")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Type alias: (hash_string, anchor_time_frame_offset)
Fingerprint = Tuple[str, int]


def load_audio(
    audio_source: Union[str, Path, BinaryIO, np.ndarray],
    sample_rate: int = DEFAULT_CONFIG.sample_rate,
) -> Tuple[np.ndarray, int]:
    """
    Loads an audio file or stream, converts to mono, and resamples to target sample rate.

    Viva Note:
    Standardizing to 22,050 Hz ensures identical frequency bin mapping during STFT
    regardless of whether the original file was 44.1 kHz, 48 kHz, or recorded via browser mic.

    Args:
        audio_source: Path to audio file, file-like binary stream, or raw numpy audio array.
        sample_rate: Target sampling rate in Hz (default 22,050).

    Returns:
        Tuple of (1D float32 audio signal array, sampling rate).
    """
    if isinstance(audio_source, np.ndarray):
        y = audio_source.astype(np.float32)
        # Convert stereo to mono if 2D array
        if y.ndim > 1:
            y = np.mean(y, axis=0)
        return y, sample_rate

    try:
        # librosa handles wav, mp3, ogg, flac, etc., converting to mono float32
        y, sr = librosa.load(audio_source, sr=sample_rate, mono=True)
        return y, sr
    except Exception as exc:
        logger.error("Failed to load audio source %s: %s", audio_source, exc)
        raise


def compute_spectrogram(
    y: np.ndarray,
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """
    Computes logarithmic magnitude spectrogram (dB) using Short-Time Fourier Transform (STFT).

    Viva Note:
    STFT splits the audio signal into overlapping chunks (windows), computes the discrete
    Fourier transform on each, and stacks the absolute magnitudes into a 2D matrix.
    Row index = Frequency bin.
    Column index = Time frame index.
    Values = Magnitude in Decibels (dB).

    Args:
        y: 1D audio time-series.
        config: Fingerprint DSP parameters.

    Returns:
        2D numpy array of shape (freq_bins, time_frames) with values in dB.
    """
    if len(y) == 0:
        return np.empty((0, 0), dtype=np.float32)

    # Compute complex STFT matrix
    stft_matrix = librosa.stft(
        y=y,
        n_fft=config.fft_window,
        hop_length=config.hop_length,
    )

    # Compute absolute magnitude
    magnitude = np.abs(stft_matrix)

    # Convert linear amplitude to decibel (logarithmic) scale
    # ref=np.max ensures the maximum amplitude is 0 dB, other values are <= 0 dB
    spectrogram_db = librosa.amplitude_to_db(magnitude, ref=np.max)
    return spectrogram_db


def extract_peaks(
    spectrogram_db: np.ndarray,
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> List[Tuple[int, int]]:
    """Extract robust local peaks restricted to musical band and relative dB thresholds."""
    if spectrogram_db.size == 0:
        return []

    freq_bins = spectrogram_db.shape[0]
    freq_resolution = config.sample_rate / (2 * config.fft_window)
    min_bin = int(config.peak_min_freq_hz / freq_resolution)
    max_bin = int(config.peak_max_freq_hz / freq_resolution)
    min_bin = max(0, min_bin)
    max_bin = min(freq_bins, max_bin)
    if min_bin >= max_bin:
        return []

    filtered = spectrogram_db[min_bin:max_bin, :]
    local_maxima = maximum_filter(
        filtered,
        size=config.peak_neighborhood,
        mode="constant",
        cval=-np.inf,
    )
    is_peak = filtered == local_maxima

    time_medians = np.median(filtered, axis=0)
    global_max = float(np.max(filtered))
    keep_mask = np.zeros_like(filtered, dtype=bool)

    for t in range(filtered.shape[1]):
        frame_values = filtered[:, t]
        frame_mask = frame_values > (time_medians[t] + config.peak_db_above_frame_median)
        if not np.any(frame_mask):
            continue
        candidate_idxs = np.where(frame_mask)[0]
        if candidate_idxs.size > 0:
            best = np.argsort(frame_values[candidate_idxs])[::-1][: config.max_peaks_per_frame]
            keep_mask[candidate_idxs[best], t] = True

    prominent_peaks = is_peak & keep_mask
    prominent_peaks &= filtered >= (global_max - config.peak_db_above_global_max)
    prominent_peaks &= filtered >= config.amp_threshold

    freq_indices, time_indices = np.where(prominent_peaks)
    peaks = sorted(zip(freq_indices.tolist(), time_indices.tolist()), key=lambda p: (p[1], p[0]))
    return [(bin_idx + min_bin, t_idx) for bin_idx, t_idx in peaks]


def generate_hashes(
    peaks: List[Tuple[int, int]],
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> List[Fingerprint]:
    """Generate landmark hashes with tighter, robust frequency and time constraints."""
    fingerprints: List[Fingerprint] = []
    num_peaks = len(peaks)

    for i in range(num_peaks):
        f1, t1 = peaks[i]
        matched_targets = 0

        for j in range(i + 1, num_peaks):
            f2, t2 = peaks[j]
            delta_t = t2 - t1
            if delta_t < config.delta_min:
                continue
            if delta_t > config.delta_max:
                break
            if abs(f2 - f1) > config.hash_freq_delta_max:
                continue

            landmark = f"{f1}|{f2}|{delta_t}".encode("utf-8")
            hash_digest = hashlib.sha1(landmark).hexdigest()[: config.hash_length]
            fingerprints.append((hash_digest, t1))
            matched_targets += 1
            if matched_targets >= config.fan_out:
                break

    return fingerprints


def fingerprint_query(
    audio_source: Union[str, Path, BinaryIO, np.ndarray],
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> List[Fingerprint]:
    """Fingerprint a diverse query with 4 overlapping shifts and de-duplicate the union."""
    y, _ = load_audio(audio_source, sample_rate=config.sample_rate)
    if len(y) == 0:
        return []

    all_fingerprints: List[Fingerprint] = []
    seen: set[Tuple[str, int]] = set()
    shift_samples = max(1, config.query_shift_samples)

    for shift in range(config.query_shift_count):
        offset = shift * (shift_samples // 4)
        segment = y[offset:]
        if len(segment) < config.fft_window:
            continue
        spectrogram_db = compute_spectrogram(segment, config=config)
        peaks = extract_peaks(spectrogram_db, config=config)
        for hash_value, frame in generate_hashes(peaks, config=config):
            key = (hash_value, frame)
            if key in seen:
                continue
            seen.add(key)
            all_fingerprints.append((hash_value, frame + offset // config.hop_length))

    return all_fingerprints


def fingerprint_audio(
    audio_source: Union[str, Path, BinaryIO, np.ndarray],
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> List[Fingerprint]:
    """
    End-to-End Pipeline: Audio Input -> Preprocessing -> STFT -> Peaks -> Hashes.

    Viva Note:
    Complete execution pipeline for audio fingerprinting:
    1. Load audio and normalize to mono 22050 Hz.
    2. Short-time Fourier transform (STFT) to log-magnitude spectrogram.
    3. Peak detection via 2D morphological maximum filter.
    4. Combinatorial pairing of peak landmarks into invariant cryptographic hashes.

    Args:
        audio_source: Audio file path, buffer, or numpy array.
        config: Optional custom configuration parameters.

    Returns:
        List of (hash, anchor_time_offset) tuples.
    """
    y, _ = load_audio(audio_source, sample_rate=config.sample_rate)
    if len(y) == 0:
        logger.warning("Empty audio provided to fingerprint_audio.")
        return []

    spectrogram_db = compute_spectrogram(y, config=config)
    peaks = extract_peaks(spectrogram_db, config=config)
    fingerprints = generate_hashes(peaks, config=config)

    logger.debug(
        "Fingerprinted audio: %d samples, %d peaks, %d fingerprints generated.",
        len(y),
        len(peaks),
        len(fingerprints),
    )
    return fingerprints
