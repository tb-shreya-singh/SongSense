# 🎵 SongSense: Shazam-Style Audio Fingerprinting & Song Identification

A production-grade audio identification engine and musical recommendation system built in Python, using **Redis** for sub-second inverted-index fingerprint lookups and **Neo4j** for rich knowledge graph traversals.

---

## 🌟 Key Features

1. **Acoustic Landmark Fingerprinting (Avery Li-Chun Wang Algorithm)**:
   - Resamples audio to mono 22,050 Hz.
   - Computes Short-Time Fourier Transform (STFT) spectrogram with logarithmic Decibel scaling.
   - Robust peak picking using 2D morphological dilation (`scipy.ndimage.maximum_filter`).
   - Combinatorial target-zone landmark pairing into shift-invariant 80-bit SHA-1 hashes.
2. **Sub-Second Indexing via Redis**:
   - Inverted index maps `fp:<hash>` &rarr; `Set("song_id:offset")`.
   - Batched pipelining for rapid ingestion and zero-roundtrip multi-hash queries.
   - **Automatic In-Memory Fallback**: Runs completely standalone even without Docker or Redis installed!
3. **Diagonal Offset Alignment Voting**:
   - Computes relative time differences $\Delta t = t_{db} - t_{clip}$ across all candidate matches.
   - True songs cluster into an unmistakable temporal spike, rejecting spurious ambient noise collisions.
4. **Graph-Powered Discovery with Neo4j**:
   - Graph Schema: `(:Song)-[:COMPOSED_BY]->(:Composer)`, `(:Song)-[:IN_RAGA]->(:Raga)`, `(:Song)-[:FROM_FILM]->(:Film)`, `(:Song)-[:SUNG_BY]->(:Singer)`.
   - Recommends songs sharing classical Ragas or legendary Composers without SQL joins.
5. **Interactive Web Interface & Microphone Recorder**:
   - Live in-browser microphone recording via HTML5 `MediaRecorder` API.
   - Drag-and-drop audio file upload.
   - Clean dark-mode dashboard displaying matched song, confidence metrics, and graph connections.

---

## 🏗️ System Architecture

```
       +--------------------------------------------------------+
       |                   Audio Input Clip                     |
       |         (Browser Microphone or Uploaded File)          |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |               Pre-processing & STFT (dB)               |
       |     22,050 Hz Mono, FFT Window 4096, Hop Size 2048     |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |         Constellation Map Peak Extraction              |
       |        scipy.ndimage.maximum_filter (Size: 20)         |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |             Combinatorial Hash Generation              |
       |    Anchor Peak (f1, t1) + Target Peak (f2, t2)         |
       |      Hash: SHA1(f1|f2|delta_t)[:20] + Clip Offset t1   |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |              Redis Hash Inverted Index                 |
       |        Look up matches: "song_id:db_offset"            |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |          Diagonal Offset Alignment Voting              |
       |     Histogram of (song_id, db_offset - clip_offset)    |
       |             Identify Song with Highest Peak            |
       +---------------------------+----------------------------+
                                   |
                                   v
       +--------------------------------------------------------+
       |            Neo4j Music Knowledge Graph                 |
       |    Fetch Song Metadata & Related Songs by Raga/Composer|
       +--------------------------------------------------------+
```

---

## 🎓 Viva Explanation Guide

If asked to explain this project during an examination or technical viva:

1. **Why not compare audio waveforms directly?**
   - Direct audio waveforms change drastically due to microphone distortion, volume variations, room acoustics, and phase shifts. Spectrogram energy peaks represent true musical frequency content and remain invariant under distortion.
2. **What is a Constellation Map?**
   - It is a sparse 2D point cloud of prominent local maxima in the time-frequency spectrogram. By keeping only the strongest peaks within each neighborhood, we compress gigabytes of audio into lightweight, robust coordinates.
3. **Why do we pair peaks into hashes instead of single frequencies?**
   - A single note (e.g. 440 Hz) is shared by thousands of songs. By pairing an anchor peak $(f_1, t_1)$ with a downstream peak $(f_2, t_2)$, the triplet $(f_1, f_2, \Delta t)$ creates high entropy ($>80$ bits) that is unique to that specific musical phrase.
4. **Why is the hash time-invariant?**
   - The hash only uses the relative difference $\Delta t = t_2 - t_1$. Whether the song started 10 seconds ago or 1 hour ago, the distance between those two musical notes is identical.
5. **How does Temporal Alignment (Offset Voting) work?**
   - For every candidate hash matched in Redis, we subtract the clip's offset from the song's stored offset: $\Delta = t_{db} - t_{clip}$.
   - For the correct song, all landmarks will yield the exact same time difference $\Delta$ (the point in the song where the recording began).
   - Random noise collisions produce random $\Delta$ values that scatter across the timeline. The true match produces a tall, unambiguous histogram spike.

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.10+
- (Optional) Docker for Redis and Neo4j

### 2. Installation
Clone or navigate to the project directory:
```bash
cd SongSense
python -m pip install -r requirements.txt
```

### 3. (Optional) Run Redis & Neo4j with Docker
If you want to use dedicated database instances:
```bash
# Start Redis
docker run -d --name songsense-redis -p 6379:6379 redis:alpine

# Start Neo4j
docker run -d --name songsense-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest
```
> **Note**: If you don't run Docker, **SongSense automatically falls back to built-in in-memory stores** for both Redis and Neo4j, so all scripts and web features run immediately without extra setup!

---

## 📂 Project Structure

```
SongSense/
├── config.py             # DSP constants, Redis/Neo4j endpoints, and thresholds
├── fingerprint.py        # STFT, 2D peak extraction, combinatorial hashing
├── redis_store.py        # Redis inverted index with fallback in-memory dict
├── neo4j_store.py        # Neo4j Cypher queries with fallback in-memory graph
├── matcher.py            # Offset alignment histogram voting algorithm
├── ingest.py             # Audio folder scanner, synthesizer & database indexing
├── evaluate.py           # 20-trial noise benchmark (Clean, 20dB, 10dB, 5dB SNR)
├── app.py                # Flask server with REST API and health checks
├── requirements.txt      # Project dependencies
├── results.csv           # Benchmark results output
├── templates/
│   └── index.html        # Modern responsive dark-mode UI with Web Audio mic recording
└── songs/
    ├── metadata.csv      # CSV defining title, composer, film, singer, raga
    ├── song1_bhoopali.wav
    ├── song2_bairagi.wav
    ├── song3_bhoopali_night.wav
    ├── song4_yaman.wav
    └── song5_darbari.wav
```

---

## 🏃 Running the Project

### Step 1: Ingest Songs & Build the Index
Runs the ingestion CLI. If the `songs/` folder has no audio files, it automatically generates 5 high-quality harmonic audio samples across different classical scales (Bhoopali, Yaman, Darbari, etc.):
```bash
python ingest.py
```

### Step 2: Run Evaluation & Noise Benchmark
Cuts 20 random 10-second clips from the catalog, injects Gaussian noise at different Signal-to-Noise Ratios, measures query accuracy and latency, and saves results to `results.csv`:
```bash
python evaluate.py
```

### Step 3: Start the Web Application
Launch the Flask development server:
```bash
python app.py
```
Open your browser and navigate to:
**[http://127.0.0.1:5000](http://127.0.0.1:5000)**

You can:
- Click the **Microphone** button to record live audio from your device.
- Upload any `.wav` or `.mp3` snippet to identify the song and explore related tracks from the Neo4j knowledge graph.
