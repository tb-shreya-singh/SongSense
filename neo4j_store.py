"""
SongSense: Neo4j Knowledge Graph Store & In-Memory Fallback (neo4j_store.py)
===========================================================================
This module manages rich music metadata and relational recommendations.

VIVA THEORY & ARCHITECTURAL OVERVIEW:
-------------------------------------
1. Graph Schema:
   - Node Labels:
     * (:Song {songId, title, durationSec, filename})
     * (:Composer {name})
     * (:Film {name})
     * (:Singer {name})
     * (:Raga {name})
   - Relationships:
     * (:Song)-[:COMPOSED_BY]->(:Composer)
     * (:Song)-[:FROM_FILM]->(:Film)
     * (:Song)-[:SUNG_BY]->(:Singer)
     * (:Song)-[:IN_RAGA]->(:Raga)

2. Graph Traversal & Recommendations:
   - When a song is identified from an audio clip, simple relational databases
     require multiple heavy SQL JOINs to find other songs sharing composers or musical ragas.
   - Neo4j indexes pointers (index-free adjacency):
     MATCH (s:Song {songId: $id})-[:COMPOSED_BY|IN_RAGA]-(hub)-[:COMPOSED_BY|IN_RAGA]-(other:Song)
     WHERE other.songId <> $id
     RETURN other, hub
   - This enables instantaneous contextual discovery (e.g. classical ragas or iconic composers).

3. Graceful Fallback:
   - If Neo4j is not running, all metadata operations fall back to an in-memory graph
     represented via Python dictionaries, logging a clear warning. The web app and
     matcher continue functioning without interruption.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    GraphDatabase = None  # type: ignore
    NEO4J_AVAILABLE = False

from config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger("SongSense.Neo4jStore")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class Neo4jMetadataStore:
    """
    Manages song metadata graph in Neo4j with an automatic in-memory fallback.
    """

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.driver = None
        self.is_connected = False

        # In-Memory Fallback Graph
        # song_id -> {title, durationSec, composer, film, singer, raga, filename}
        self._memory_songs: Dict[str, Dict[str, Any]] = {}

        self._connect()

    def _connect(self) -> None:
        """Attempts connection to Neo4j instance."""
        if not NEO4J_AVAILABLE:
            logger.warning(
                "neo4j Python driver not installed. Using in-memory fallback for metadata graph."
            )
            self.is_connected = False
            return

        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            # Test connectivity
            driver.verify_connectivity()
            self.driver = driver
            self.is_connected = True
            logger.info("Successfully connected to Neo4j at %s.", self.uri)
            self._ensure_constraints()
        except Exception as exc:
            self.driver = None
            self.is_connected = False
            logger.warning(
                "Could not connect to Neo4j at %s (%s). Falling back gracefully to in-memory graph.",
                self.uri,
                exc,
            )

    def _ensure_constraints(self) -> None:
        """Creates unique constraints and indices for fast lookup."""
        if not self.is_connected or self.driver is None:
            return

        constraint_cql = """
        CREATE CONSTRAINT song_id_unique IF NOT EXISTS
        FOR (s:Song) REQUIRE s.songId IS UNIQUE;
        """
        try:
            with self.driver.session() as session:
                session.run(constraint_cql)
        except Exception as exc:
            logger.debug("Constraint creation notice: %s", exc)

    def add_song_metadata(
        self,
        song_id: str,
        title: str,
        composer: Optional[str] = None,
        film: Optional[str] = None,
        singer: Optional[str] = None,
        raga: Optional[str] = None,
        duration_sec: float = 0.0,
        filename: Optional[str] = None,
    ) -> bool:
        """
        Adds or updates song metadata and creates relational graph edges.

        Viva Note:
        MERGE statements ensure nodes and relationships are idempotent — ingesting
        multiple songs from the same composer links them to the exact same Composer node.

        Cypher Graph Architecture:
        (:Song)-[:COMPOSED_BY]->(:Composer)
        (:Song)-[:FROM_FILM]->(:Film)
        (:Song)-[:SUNG_BY]->(:Singer)
        (:Song)-[:IN_RAGA]->(:Raga)
        """
        # Always store in memory fallback cache
        self._memory_songs[song_id] = {
            "song_id": song_id,
            "title": title or song_id,
            "composer": composer or "Unknown",
            "film": film or "Unknown",
            "singer": singer or "Unknown",
            "raga": raga or "Unknown",
            "durationSec": float(duration_sec),
            "filename": filename or "",
        }

        if not self.is_connected or self.driver is None:
            logger.info(
                "Stored metadata for song '%s' (%s) in in-memory graph fallback.",
                song_id,
                title,
            )
            return True

        cypher = """
        MERGE (s:Song {songId: $song_id})
        SET s.title = $title,
            s.durationSec = $duration_sec,
            s.filename = $filename

        FOREACH (_ IN CASE WHEN $composer IS NOT NULL AND $composer <> '' THEN [1] ELSE [] END |
            MERGE (c:Composer {name: $composer})
            MERGE (s)-[:COMPOSED_BY]->(c)
        )

        FOREACH (_ IN CASE WHEN $film IS NOT NULL AND $film <> '' THEN [1] ELSE [] END |
            MERGE (f:Film {name: $film})
            MERGE (s)-[:FROM_FILM]->(f)
        )

        FOREACH (_ IN CASE WHEN $singer IS NOT NULL AND $singer <> '' THEN [1] ELSE [] END |
            MERGE (sg:Singer {name: $singer})
            MERGE (s)-[:SUNG_BY]->(sg)
        )

        FOREACH (_ IN CASE WHEN $raga IS NOT NULL AND $raga <> '' THEN [1] ELSE [] END |
            MERGE (r:Raga {name: $raga})
            MERGE (s)-[:IN_RAGA]->(r)
        )
        RETURN s.songId AS id
        """

        try:
            with self.driver.session() as session:
                session.run(
                    cypher,
                    song_id=song_id,
                    title=title or song_id,
                    composer=composer,
                    film=film,
                    singer=singer,
                    raga=raga,
                    duration_sec=float(duration_sec),
                    filename=filename or "",
                )
            logger.info("Saved metadata for '%s' to Neo4j graph.", song_id)
            return True
        except Exception as exc:
            logger.warning("Failed to write to Neo4j (%s). Preserved in memory.", exc)
            self.is_connected = False
            return True

    def get_song_info(self, song_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves detailed metadata for a given song ID.

        Args:
            song_id: Unique song identifier.

        Returns:
            Dictionary containing song attributes and relations.
        """
        if self.is_connected and self.driver is not None:
            cypher = """
            MATCH (s:Song {songId: $song_id})
            OPTIONAL MATCH (s)-[:COMPOSED_BY]->(c:Composer)
            OPTIONAL MATCH (s)-[:FROM_FILM]->(f:Film)
            OPTIONAL MATCH (s)-[:SUNG_BY]->(sg:Singer)
            OPTIONAL MATCH (s)-[:IN_RAGA]->(r:Raga)
            RETURN s.songId AS song_id,
                   s.title AS title,
                   s.durationSec AS durationSec,
                   s.filename AS filename,
                   c.name AS composer,
                   f.name AS film,
                   sg.name AS singer,
                   r.name AS raga
            """
            try:
                with self.driver.session() as session:
                    result = session.run(cypher, song_id=song_id)
                    record = result.single()
                    if record:
                        return dict(record)
            except Exception as exc:
                logger.warning("Neo4j query failed (%s). Using fallback.", exc)
                self.is_connected = False

        # Fallback to in-memory dictionary
        return self._memory_songs.get(song_id)

    def get_related_songs(self, song_id: str) -> List[Dict[str, Any]]:
        """Return related songs from COMPOSED_BY, IN_RAGA, or SUNG_BY with unknown names ignored."""
        related: List[Dict[str, Any]] = []

        if self.is_connected and self.driver is not None:
            cypher = """
            MATCH (s:Song {songId: $song_id})
            MATCH (s)-[r1:COMPOSED_BY|IN_RAGA|SUNG_BY]->(common)<-[r2:COMPOSED_BY|IN_RAGA|SUNG_BY]-(other:Song)
            WHERE other.songId <> $song_id
            OPTIONAL MATCH (other)-[:COMPOSED_BY]->(comp:Composer)
            OPTIONAL MATCH (other)-[:IN_RAGA]->(rag:Raga)
            OPTIONAL MATCH (other)-[:SUNG_BY]->(singer:Singer)
            OPTIONAL MATCH (other)-[:FROM_FILM]->(film:Film)
            RETURN DISTINCT
                other.songId AS song_id,
                other.title AS title,
                comp.name AS composer,
                rag.name AS raga,
                singer.name AS singer,
                film.name AS film,
                type(r1) AS reason_relation,
                common.name AS common_value
            LIMIT 10
            """
            try:
                with self.driver.session() as session:
                    result = session.run(cypher, song_id=song_id)
                    for rec in result:
                        rel_type = rec["reason_relation"]
                        reason = (
                            f"Same Composer ({rec['common_value']})"
                            if rel_type == "COMPOSED_BY"
                            else f"Same Raga ({rec['common_value']})"
                            if rel_type == "IN_RAGA"
                            else f"Same Singer ({rec['common_value']})"
                        )
                        if rec["common_value"] in (None, "", "Unknown"):
                            continue
                        related.append({
                            "song_id": rec["song_id"],
                            "title": rec["title"],
                            "composer": rec["composer"] or "Unknown",
                            "raga": rec["raga"] or "Unknown",
                            "singer": rec["singer"] or "Unknown",
                            "film": rec["film"] or "Unknown",
                            "reason": reason,
                        })
                return related
            except Exception as exc:
                logger.warning("Neo4j related query failed (%s). Using fallback.", exc)
                self.is_connected = False

        target = self._memory_songs.get(song_id)
        if not target:
            return []

        target_composer = target.get("composer")
        target_raga = target.get("raga")
        target_singer = target.get("singer")

        seen_ids = set()
        for s_id, s_data in self._memory_songs.items():
            if s_id == song_id or s_id in seen_ids:
                continue

            reasons = []
            if target_composer and target_composer != "Unknown" and s_data.get("composer") == target_composer:
                reasons.append(f"Same Composer ({target_composer})")
            if target_raga and target_raga != "Unknown" and s_data.get("raga") == target_raga:
                reasons.append(f"Same Raga ({target_raga})")
            if target_singer and target_singer != "Unknown" and s_data.get("singer") == target_singer:
                reasons.append(f"Same Singer ({target_singer})")

            if reasons:
                seen_ids.add(s_id)
                related.append({
                    "song_id": s_id,
                    "title": s_data.get("title", s_id),
                    "composer": s_data.get("composer", "Unknown"),
                    "raga": s_data.get("raga", "Unknown"),
                    "singer": s_data.get("singer", "Unknown"),
                    "film": s_data.get("film", "Unknown"),
                    "reason": ", ".join(reasons),
                })

        return related

    def close(self) -> None:
        """Closes the Neo4j driver connection."""
        if self.driver is not None:
            try:
                self.driver.close()
                logger.info("Closed Neo4j driver connection.")
            except Exception as exc:
                logger.debug("Error closing Neo4j driver: %s", exc)


# Default singleton instance
neo4j_store = Neo4jMetadataStore()
