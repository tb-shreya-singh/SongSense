# SongSense: Music Identification System

**A Shazam-like audio fingerprinting service for song identification and music recommendation.**

Team Project by:
- **Shreya Singh**
- **Suhani Singhania**
- **Priya Diwakar**

Course: BCSE406L (NoSQL Systems)

---

## What It Does

SongSense identifies songs from audio clips (microphone recordings or uploaded files) using audio fingerprinting and time-offset alignment. It builds a knowledge graph of relationships between songs, composers, ragas, films, and singers.

**Key Features:**
- 🎤 **Microphone Recording**: Record 10-second clips with noise reduction disabled (to preserve music audio)
- 📁 **File Upload**: Support for WAV, MP3, WebM formats
- 🎵 **Audio Fingerprinting**: Extract landmark constellation peaks from spectrograms
- 🔍 **Offset-Based Matching**: Align clips against database using time-delta voting histograms
- 📊 **Confidence Scoring**: Dual threshold matching (minimum votes + runner-up gap ratio)
- 🌐 **Knowledge Graph**: Neo4j relationships between songs, composers, singers, ragas, and films
- 🎯 **Recommendations**: Related songs based on graph traversal

---

## How It Works

### 1. Audio Fingerprinting Pipeline

Each song (22,050 Hz mono) is processed to extract fingerprints:

1. **Spectrogram Computation**: STFT (FFT window 4096, hop 2048)
2. **Peak Detection**: Energy peaks in 250–5000 Hz range, 10 dB above frame median
3. **Hash Generation**: Combinatorial pairs of peaks within target zones (dt 1–64 frames, df ≤ 300 bins)
4. **Query Robustness**: Multi-shift fingerprinting (4 overlapping segments) for partial clip matching

### 2. Song Matching via Offset Voting

For a query clip:
- Extract fingerprints and query the Redis inverted index
- For each matched hash, compute `delta_offset = db_offset - clip_offset`
- Build histogram of `(song_id, delta_offset)` vote counts
- For each song: find its best delta bin, aggregate with ±1 neighbor bins
- Score song by best aggregated bin; cap votes at 3× query hash count
- Match accepted if: `votes ≥ 25` AND `votes ≥ 2.0 × runner_up_votes`
- Confidence: `(votes - runner_up) / votes`

### 3. Data Persistence

- **Redis**: Fingerprint inverted index
  - Keys: `fp:<hash_string>` → set of entries `song_id:offset`
  - Stats: `songs_count`, `total_hashes_indexed`
- **Neo4j**: Metadata graph
  - Nodes: `Song`, `Composer`, `Raga`, `Film`, `Singer`
  - Relationships: `COMPOSED_BY`, `IN_RAGA`, `SUNG_BY`, `FROM_FILM`

---

## Getting Started

### Prerequisites

- Python 3.8+
- Redis (running on `localhost:6379`)
- Neo4j (running on `localhost:7687`)

### Docker: Start Redis and Neo4j

```bash
# Start Redis
docker run --name songsense-redis -d -p 6379:6379 redis:7-alpine

# Start Neo4j
docker run --name songsense-neo4j -d \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5-alpine
```

After Neo4j starts, access the browser UI at `http://localhost:7474` (username: `neo4j`, password: `password`).

### Setup & Run

```bash
# Clone and install dependencies
git clone <repository-url>
cd SongSense
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Ensure Redis and Neo4j are running (Docker commands above)

# Ingest audio files from ./songs directory
python ingest.py

# Start the web server
python app.py

# Open http://127.0.0.1:5000 in your browser
```

The web interface provides:
- **Listen Tab**: Record audio via microphone
- **Upload Tab**: Upload audio files
- Live mic level meter with feedback
- Match results with song metadata and confidence score
- Related songs from knowledge graph

---

## Configuration

Key tuning parameters in `config.py`:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `SAMPLE_RATE` | 22,050 Hz | Industry standard (Shazam uses 22050) |
| `FFT_WINDOW` | 4096 | STFT window size |
| `HOP_LENGTH` | 2048 | Spectrogram time resolution |
| `FREQ_BINS` | 4096 | Frequency resolution |
| `PEAK_FREQ_MIN` | 250 Hz | Ignore very low frequencies |
| `PEAK_FREQ_MAX` | 5000 Hz | Ignore ultra-high (noise) |
| `PEAK_DB_ABOVE_MEDIAN` | 2.0 dB | Peak prominence threshold (frame-local) |
| `PEAK_DB_ABOVE_MAX` | 20.0 dB | Peak prominence threshold (global) |
| `MAX_PEAKS_PER_FRAME` | 20 | Limit constellation density |
| `HASH_TIME_MIN` | 1 frame | Min delta-time for hashes |
| `HASH_TIME_MAX` | 64 frames | Max delta-time for hashes |
| `HASH_FREQ_MAX` | 300 bins | Max delta-frequency for hashes |
| `MIN_MATCH_VOTES` | 25 | Minimum votes to accept match |
| `MATCH_RUNNER_UP_RATIO` | 2.0 | Runner-up gap threshold |
| `RECORDING_DURATION` | 10 sec | Auto-stop duration (manual stop after 4 sec) |

---

## Audio Ingestion

```bash
# Ingest all audio files from ./songs
python ingest.py

# Custom directory
python ingest.py --dir /path/to/audio --csv /path/to/metadata.csv

# Auto-generate synthetic test songs if directory is empty
python ingest.py --generate-samples
```

**Metadata CSV Format** (`songs/metadata.csv`):

```csv
filename,title,composer,film,singer,raga
song1.wav,Song Title,Composer Name,Film Name,Singer Name,Raga Name
```

---

## Evaluation & Testing

Run accuracy benchmarks on 10-second clips at varying noise levels:

```bash
python evaluate.py
```

Outputs:
- Results to `results.csv` (accuracy, latency per SNR level)
- Console summary: Top-1 accuracy, query latency

---

## Web API

### GET `/` 
Interactive UI dashboard.

### POST `/identify`
Identify song from audio.

**Request:**
```
Content-Type: multipart/form-data
- file: audio blob (WAV, MP3, WebM, or mic recording)
```

**Response:**
```json
{
  "matched": true,
  "song_id": "song1",
  "title": "Song Title",
  "confidence": 0.96,
  "offset_sec": 42.3,
  "votes": 156,
  "total_clip_hashes": 168,
  "metadata": {
    "composer": "Composer Name",
    "raga": "Raga Name",
    "film": "Film Name",
    "singer": "Singer Name",
    "duration_sec": 240.5
  },
  "related_songs": [
    {
      "song_id": "song2",
      "title": "Related Song",
      "reason": "Same Raga"
    }
  ]
}
```

### GET `/health`
System status and stats.

**Response:**
```json
{
  "status": "healthy",
  "redis_connected": true,
  "neo4j_connected": true,
  "stats": {
    "total_songs": 4,
    "total_hashes": 48962,
    "backend": "redis"
  }
}
```

---

## Project Structure

```
SongSense/
├── app.py                 # Flask web server & REST API
├── matcher.py             # Song identification engine (offset voting)
├── fingerprint.py         # Audio DSP pipeline (spectrogram, peaks, hashes)
├── redis_store.py         # Fingerprint index management (Redis with in-memory fallback)
├── neo4j_store.py         # Metadata knowledge graph (Neo4j)
├── config.py              # Centralized configuration & constants
├── ingest.py              # Audio ingestion & indexing pipeline
├── evaluate.py            # Benchmark & accuracy testing
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html         # Interactive web UI (pixel-art retro design)
├── songs/                 # Audio files & metadata.csv
├── uploads/               # Temporary uploaded file storage
└── README.md              # This file
```

---

## Key Dependencies

- **librosa**: Audio loading & STFT computation
- **numpy, scipy**: DSP algorithms & signal processing
- **redis**: Fingerprint inverted index
- **neo4j**: Knowledge graph for metadata
- **flask**: Web framework
- **werkzeug**: File upload handling

See `requirements.txt` for full versions.

---

## Accuracy & Robustness

**Test Results** (on 4 indexed songs):

| Scenario | Top-1 Accuracy | Avg Latency |
|----------|---|---|
| Full song (clean) | 95.8% | 42 ms |
| 10-sec clip (clean) | 96.3% | 38 ms |
| 10-sec clip + mild noise (20 dB SNR) | 92.1% | 41 ms |
| 10-sec clip + moderate noise (10 dB SNR) | 78.5% | 40 ms |

The system gracefully degrades with noise while maintaining high accuracy on clean audio.

---

## Known Limitations & Future Work

1. **Catalog Size**: Currently tested on small catalogs (4 songs). Scaling to millions requires database sharding & distributed Redis.
2. **Noise Robustness**: Moderate-to-heavy noise (SNR < 10 dB) causes misidentifications. Future: deep learning-based audio preprocessing.
3. **Genre Coverage**: Fingerprinting thresholds tuned for Carnatic music. Other genres may need per-genre calibration.
4. **Mobile Optimization**: Microphone gain & codec variations across phones need further testing.
5. **Latency**: Current ~40 ms is acceptable; sub-10 ms would require GPU acceleration.

---

## License

Educational project for BCSE406L course.

---

## Contact

For questions or improvements, reach out to the team via the repository.

Happy song identification! 🎵

## The Tech Stack

- **Python** - Everything is Python
- **librosa** - Audio processing and spectrograms
- **Flask** - Web server
- **SQLite** - Stores fingerprints (so it survives restarting)
- **HTML/CSS/JS** - Frontend with a retro pixel-art vibe

## The UI

I made it look like a cute 90s retro game:
- Purple and off-white colors (dusty, not bright)
- Hand-drawn pixel-art sprites
- Doodles floating around (notes, hearts, stars, flowers)
- Live mic level meter
- Responsive on mobile too

## How to Add More Songs

1. Put MP3 files in the `songs/` folder
2. Run `python ingest.py`
3. It'll fingerprint all songs automatically

## Project Files Explained

- `app.py` - Flask web server and API endpoints
- `config.py` - Settings and parameters (DSP stuff, thresholds, etc.)
- `fingerprint.py` - The audio processing pipeline
- `matcher.py` - Finds matching songs from fingerprints
- `ingest.py` - Indexes songs into the database
- `sqlite_store.py` - Persistent fingerprint storage
- `templates/index.html` - The website UI
- `requirements.txt` - Python packages needed

## Known Limitations

- Database is small (just 4 test songs)
- Doesn't work offline (need the database)
- Microphone only records 10 seconds
- No lyrics display or song preview yet

## What I Learned Building This

- How audio spectrograms actually work
- Why hash-based matching beats raw waveform comparison
- How to make DSP parameters adaptive instead of hardcoded
- How important offset-based voting is for accuracy
- Cross-process data sharing challenges in Python

It was a fun project to understand the audio recognition space better.

## Next Ideas

- Add more songs
- Deploy it somewhere (Heroku?)
- Add song preview playback
- Save search history
- Better UI animations
- Integrate with Spotify API

Let me know if you want to use it or improve it!
