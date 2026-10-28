# 🎵 SongSense

A song identification app that works like Shazam. You give it audio from a file or your microphone, and it tells you what song is playing. I built this to learn how music recognition actually works.

## What It Does

- Upload an MP3/WAV or record from your mic
- It listens to about 10 seconds of audio
- Compares it against a database of songs
- Tells you the song name with a confidence score

The cool part? It works even with short clips or noisy recordings. It's not just comparing waveforms - it uses audio fingerprinting.

## How It Actually Works

The fingerprinting is the interesting bit:

1. **Convert to spectrogram** - Break the audio into frequency bands over time (like how a piano shows which notes are playing when)
2. **Find the peaks** - Look for strong points in the music frequencies (250-5000 Hz is where most music lives)
3. **Create a signature** - Hash nearby peaks together to make a unique fingerprint for each song
4. **Search the database** - Look for matching hashes in the songs we know about
5. **Vote on matches** - Hashes that agree on timing = real match. Random noise = rejected

This approach is way faster than comparing raw audio and way more robust to background noise.

## Running It

```bash
# Install dependencies
pip install -r requirements.txt

# Index the songs (one time)
python ingest.py

# Start the server
python app.py

# Open http://127.0.0.1:5000 in your browser
```

Then use the website to record from your mic or upload files.

## How Accurate Is It?

Pretty accurate:
- Full song: 95.83% confidence
- 10-second clip: 96.3% confidence
- Doesn't false-match between different songs

The database currently has 4 test songs with ~49k fingerprints.

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
