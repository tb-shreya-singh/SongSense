"""
SongSense: Audio Fingerprinting and Song Identification System
Configuration Module (config.py)
================================================================
Centralized configuration parameters for audio DSP, fingerprinting,
Redis key-value indexing, and Neo4j knowledge graph storage.

VIVA EXPLANATION NOTE:
- Sample rate (22050 Hz): Captures frequencies up to 11025 Hz (Nyquist limit),
  which covers musical melody and harmonics while halving computation vs 44.1 kHz.
- FFT Window (4096 samples): ~186ms window, yielding ~5.38 Hz frequency resolution
  bins. High frequency resolution is vital to distinguish closely spaced musical notes.
- Hop Length (2048 samples): 50% overlap (~93ms between successive time frames),
  balancing temporal precision against data volume.
- Peak Neighborhood Size (20): Defines the 2D local region in the spectrogram
  wherein an intensity point must be the maximum to qualify as a constellation peak.
- Fan-out (10): Each anchor peak is paired with up to 10 subsequent peaks in the
  target zone to form combinatorial hashes resilient to ambient noise and clipping.
- Target Zone (1-200 frames): ~0.09s to ~18.6s window forward in time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

# ==========================================
# 1. Base Directory Paths
# ==========================================
BASE_DIR: Path = Path(__file__).resolve().parent
SONGS_DIR: Path = BASE_DIR / "songs"
METADATA_FILE: Path = SONGS_DIR / "metadata.csv"
RESULTS_FILE: Path = BASE_DIR / "results.csv"
UPLOAD_FOLDER: Path = BASE_DIR / "uploads"

# Ensure directories exist
SONGS_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# ==========================================
# 2. Redis Configuration
# ==========================================
# Redis stores the inverted index:
#   Key:   "fp:<hash>"
#   Value: Set of "song_id:offset" strings
# In-memory dictionary fallback will be used if connection fails.
REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD: str | None = os.getenv("REDIS_PASSWORD", None)
REDIS_KEY_PREFIX: str = "fp:"
REDIS_STATS_SONGS_KEY: str = "stats:total_songs"
REDIS_STATS_HASHES_KEY: str = "stats:total_hashes"
REDIS_SONGS_SET_KEY: str = "stats:songs_set"

# ==========================================
# 3. Neo4j Configuration
# ==========================================
# Neo4j stores music knowledge graph:
#   Nodes: Song, Composer, Film, Singer, Raga
#   Edges: COMPOSED_BY, FROM_FILM, SUNG_BY, IN_RAGA
# In-memory graph fallback will be used if connection fails.
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")

# ==========================================
# 4. Audio Processing & DSP Parameters
# ==========================================
# Standardized sample rate for audio consistency
SAMPLE_RATE: int = 22050

# Short-Time Fourier Transform (STFT) window and hop length
FFT_WINDOW: int = 4096
HOP_LENGTH: int = 2048

# ==========================================
# 5. Constellation Map & Peak Detection Parameters
# ==========================================
# Neighborhood footprint size for scipy.ndimage.maximum_filter (freq_bins x time_frames)
PEAK_NEIGHBORHOOD_SIZE: int = 20

# Minimum dB amplitude threshold to filter out silence and low-energy background hiss
AMPLITUDE_THRESHOLD: float = -60.0  # Relaxed to capture real music

# Phones and laptop microphones often record speaker audio heavily filtered by AGC/noise suppression.
# These thresholds keep only robust musical energy peaks that survive that degradation.
PEAK_MIN_FREQ_HZ: int = 250
PEAK_MAX_FREQ_HZ: int = 5000
PEAK_DB_ABOVE_FRAME_MEDIAN: float = 2.0  # Relaxed for real music
PEAK_DB_ABOVE_GLOBAL_MAX: float = 20.0  # Relaxed for real music
MAX_PEAKS_PER_FRAME: int = 20  # Increased for real music

# ==========================================
# 6. Combinatorial Hashing Parameters
# ==========================================
# Number of downstream target peaks paired with each anchor peak
FAN_OUT: int = 10

# Target zone boundary in time frames relative to anchor peak
# Minimum delta (1 frame) avoids self-pairing or identical time slice
TARGET_ZONE_TIME_DELTA_MIN: int = 1
TARGET_ZONE_TIME_DELTA_MAX: int = 64

# Frequency-bin separation bound between paired peaks for phone-speaker/laptop-mic robustness
HASH_FREQ_DELTA_MAX: int = 300

# Truncated length of SHA-1 hex hash string (20 characters = 80 bits entropy)
HASH_LENGTH: int = 20

# Query fingerprinting offset pattern: 4 overlapping passes offset by hop/4 samples
QUERY_SHIFT_COUNT: int = 4
QUERY_SHIFT_SAMPLES: int = 512

# ==========================================
# 7. Matcher & Verification Parameters
# ==========================================
# Minimum number of aligned temporal votes required to declare a confident match
MIN_MATCH_VOTES: int = 25
MATCH_NEIGHBORHOOD_OFFSET: int = 1
MATCH_RUNNER_UP_RATIO: float = 2.0

# Mic capture defaults for browser recording in the web UI
MIC_RECORDING_TIMEOUT_MS: int = 10000
MIC_MANUAL_STOP_MS: int = 4000
MIC_AUDIO_CONFIG: dict[str, float | bool | int] = {
    "echoCancellation": False,
    "noiseSuppression": False,
    "autoGainControl": False,
    "channelCount": 1,
}

# ==========================================
# 8. Web App Configuration
# ==========================================
FLASK_HOST: str = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")
MAX_CONTENT_LENGTH: int = 32 * 1024 * 1024  # 32 MB max upload size


class FingerprintConfig(NamedTuple):
    sample_rate: int = SAMPLE_RATE
    fft_window: int = FFT_WINDOW
    hop_length: int = HOP_LENGTH
    peak_neighborhood: int = PEAK_NEIGHBORHOOD_SIZE
    amp_threshold: float = AMPLITUDE_THRESHOLD
    peak_min_freq_hz: int = PEAK_MIN_FREQ_HZ
    peak_max_freq_hz: int = PEAK_MAX_FREQ_HZ
    peak_db_above_frame_median: float = PEAK_DB_ABOVE_FRAME_MEDIAN
    peak_db_above_global_max: float = PEAK_DB_ABOVE_GLOBAL_MAX
    max_peaks_per_frame: int = MAX_PEAKS_PER_FRAME
    fan_out: int = FAN_OUT
    delta_min: int = TARGET_ZONE_TIME_DELTA_MIN
    delta_max: int = TARGET_ZONE_TIME_DELTA_MAX
    hash_freq_delta_max: int = HASH_FREQ_DELTA_MAX
    hash_length: int = HASH_LENGTH
    query_shift_count: int = QUERY_SHIFT_COUNT
    query_shift_samples: int = QUERY_SHIFT_SAMPLES
    min_votes: int = MIN_MATCH_VOTES
    match_neighbor_offsets: tuple[int, ...] = (-1, 0, 1)
    match_runner_up_ratio: float = MATCH_RUNNER_UP_RATIO


DEFAULT_CONFIG = FingerprintConfig()
