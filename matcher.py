"""
SongSense: Audio Matcher & Temporal Alignment Engine (matcher.py)
================================================================
This module matches recorded audio clips against the fingerprint index
using relative time-offset alignment histograms.

VIVA THEORY & ARCHITECTURAL OVERVIEW:
-------------------------------------
Why does Hash Matching alone NOT work?
---------------------------------------
In a music catalog with millions of songs, individual landmark hashes
coincidentally collide across different songs. Furthermore, background noise
and chatter introduce spurious hashes. If we merely counted total shared hashes,
the longest song in the database would always win due to random false positives!

The Core Innovation: Diagonal / Offset Alignment Voting
--------------------------------------------------------
Suppose a 5-second query clip is recorded starting at exactly second 42 of Song A:
  - If anchor peak 1 was detected at clip_offset = 2 frames, its original position in
    Song A was at db_offset = 452 frames.
  - The time difference is: delta = db_offset - clip_offset = 452 - 2 = 450 frames.
  - If anchor peak 2 was detected at clip_offset = 15 frames, its original position in
    Song A was at db_offset = 465 frames.
  - The time difference is: delta = db_offset - clip_offset = 465 - 15 = 450 frames.

KEY INSIGHT:
For the TRUE matching song, all genuine matched landmarks share the EXACT SAME
time difference:
    delta = t_db - t_clip = constant (the recording offset within the song).

For incorrect songs or random noise collisions, the differences (t_db - t_clip)
are randomly scattered uniformly across the entire duration of the song.

Histogram of Offsets:
We build a 2D histogram / counter:
    Counter[(song_id, delta_offset)] += 1

The true match produces an unmistakable giant "spike" (cluster) at the true delta_offset!
The peak height of this spike is our aligned vote count.

Confidence Score:
    confidence = top_votes / total_clip_hashes
If top_votes < MIN_MATCH_VOTES (default 5), we classify the clip as "no match".
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

import numpy as np

from config import DEFAULT_CONFIG, FingerprintConfig
from fingerprint import Fingerprint, fingerprint_audio, fingerprint_query
from neo4j_store import neo4j_store

logger = logging.getLogger("SongSense.Matcher")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class MatchResult:
    """Represents the outcome of a song identification query."""

    def __init__(
        self,
        matched: bool,
        song_id: Optional[str] = None,
        votes: int = 0,
        total_clip_hashes: int = 0,
        confidence: float = 0.0,
        offset_frame: int = 0,
        offset_sec: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        related_songs: Optional[List[Dict[str, Any]]] = None,
        message: str = "",
    ) -> None:
        self.matched = matched
        self.song_id = song_id
        self.votes = votes
        self.total_clip_hashes = total_clip_hashes
        self.confidence = round(confidence, 4)
        self.offset_frame = offset_frame
        self.offset_sec = round(offset_sec, 2)
        self.metadata = metadata or {}
        self.related_songs = related_songs or []
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        """Serializes result for JSON API responses."""
        return {
            "matched": self.matched,
            "song_id": self.song_id,
            "votes": self.votes,
            "total_clip_hashes": self.total_clip_hashes,
            "confidence": self.confidence,
            "offset_frame": self.offset_frame,
            "offset_sec": self.offset_sec,
            "metadata": self.metadata,
            "related_songs": self.related_songs,
            "message": self.message,
        }

    def __repr__(self) -> str:
        if self.matched:
            return (
                f"<MatchResult MATCH song='{self.song_id}' votes={self.votes} "
                f"conf={self.confidence:.1%} offset={self.offset_sec}s>"
            )
        return f"<MatchResult NO_MATCH msg='{self.message}'>"


def find_matches(
    fingerprints: List[Fingerprint],
    store: Any = None,
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> Tuple[Optional[str], int, int, int, int]:
    """
    Return song ID, votes (at best delta), offset (best delta), total_hashes, and runner-up best votes.
    
    Per-song logic:
    - Build histogram of (song_id, delta_offset) pairs.
    - For each song, find its single best delta_offset (highest vote bin).
    - Add votes from delta-1 and delta+1 neighbors to that bin.
    - Score each song by its best bin (after neighbor aggregation).
    - Return: best song, its best-bin score, its best delta, total query hashes, runner-up best score.
    - Votes never exceed total_clip_hashes * 3 (each hash matched at most 3 times).
    """
    if store is None:
        from redis_store import redis_store
        store = redis_store

    total_clip_hashes = len(fingerprints)
    if total_clip_hashes == 0:
        return None, 0, 0, 0, 0

    hashes_to_query = [h for h, _ in fingerprints]
    lookup_map = store.lookup_hashes(hashes_to_query)

    diff_counter: Counter[Tuple[str, int]] = Counter()

    for query_hash, clip_offset in fingerprints:
        matches = lookup_map.get(query_hash)
        if not matches:
            continue

        for entry in matches:
            try:
                song_id, db_offset_str = entry.rsplit(":", 1)
                db_offset = int(db_offset_str)
                delta_offset = db_offset - clip_offset
                diff_counter[(song_id, delta_offset)] += 1
            except ValueError:
                continue

    if not diff_counter:
        return None, 0, 0, total_clip_hashes, 0

    # Group votes by song_id
    song_deltas: Dict[str, Dict[int, int]] = {}
    for (song_id, delta_offset), vote_count in diff_counter.items():
        if song_id not in song_deltas:
            song_deltas[song_id] = {}
        song_deltas[song_id][delta_offset] = vote_count

    # For each song, find best delta and aggregate with neighbors
    song_best_scores: Dict[str, Tuple[int, int]] = {}  # song_id -> (best_score, best_delta)
    for song_id, deltas in song_deltas.items():
        best_delta = max(deltas, key=lambda d: deltas[d])
        best_bin_votes = deltas[best_delta]
        
        # Add votes from delta-1 and delta+1
        neighbor_votes = deltas.get(best_delta - 1, 0) + deltas.get(best_delta + 1, 0)
        aggregated_score = best_bin_votes + neighbor_votes
        
        song_best_scores[song_id] = (aggregated_score, best_delta)

    if not song_best_scores:
        return None, 0, 0, total_clip_hashes, 0

    # Find best and runner-up songs by aggregated score
    best_song_id, (top_votes, best_delta) = max(song_best_scores.items(), key=lambda item: item[1][0])
    
    # Get runner-up best score (second highest)
    sorted_scores = sorted(song_best_scores.values(), key=lambda x: x[0], reverse=True)
    runner_up = sorted_scores[1][0] if len(sorted_scores) > 1 else 0

    # Cap votes to 3x total clip hashes
    top_votes = min(top_votes, total_clip_hashes * 3)

    return best_song_id, top_votes, best_delta, total_clip_hashes, runner_up


def identify_audio(
    audio_source: Union[str, Path, BinaryIO, np.ndarray],
    store: Any = None,
    config: FingerprintConfig = DEFAULT_CONFIG,
) -> MatchResult:
    """
    Full identification pipeline:
    Audio Clip -> Fingerprints -> Store Lookup -> Offset Voting -> Neo4j Metadata.

    Args:
        audio_source: File path, stream, or numpy audio array.
        store: Fingerprint store instance (defaults to Redis).
        config: System configuration.

    Returns:
        MatchResult object.
    """
    if store is None:
        from redis_store import redis_store
        store = redis_store
    try:
        fingerprints = fingerprint_query(audio_source, config=config)
    except Exception as exc:
        logger.error("Failed to extract fingerprints from audio: %s", exc)
        try:
            fingerprints = fingerprint_audio(audio_source, config=config)
        except Exception as fallback_exc:
            logger.error("Fallback fingerprint extraction failed: %s", fallback_exc)
            return MatchResult(
                matched=False,
                message=f"Audio processing error: {exc}",
            )

    if not fingerprints:
        return MatchResult(
            matched=False,
            message="No prominent audio landmarks found. The clip may be silent or too noisy.",
        )

    best_song_id, votes, offset_frame, total_hashes, runner_up = find_matches(
        fingerprints=fingerprints,
        store=store,
        config=config,
    )

    confidence = ((votes - runner_up) / votes) if votes > 0 else 0.0

    offset_sec = (offset_frame * config.hop_length) / config.sample_rate

    if not best_song_id or votes < config.min_votes or runner_up > 0 and votes < (runner_up * config.match_runner_up_ratio):
        return MatchResult(
            matched=False,
            votes=votes,
            total_clip_hashes=total_hashes,
            confidence=confidence,
            message=(
                f"No confident match found. (Votes: {votes}, Required: {config.min_votes})"
            ),
        )

    metadata = neo4j_store.get_song_info(best_song_id) or {
        "song_id": best_song_id,
        "title": best_song_id,
        "composer": "Unknown",
        "film": "Unknown",
        "singer": "Unknown",
        "raga": "Unknown",
        "durationSec": 0.0,
    }

    related_songs = neo4j_store.get_related_songs(best_song_id)

    return MatchResult(
        matched=True,
        song_id=best_song_id,
        votes=votes,
        total_clip_hashes=total_hashes,
        confidence=confidence,
        offset_frame=offset_frame,
        offset_sec=offset_sec,
        metadata=metadata,
        related_songs=related_songs,
        message=f"Song successfully identified as '{metadata.get('title', best_song_id)}'!",
    )
