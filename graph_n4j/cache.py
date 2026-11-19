"""Cache graph summaries, translations and query results by repository and revision."""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional, cast

import diskcache

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")


# Graph structure skeleton cache


@dataclass
class RepoSkeleton:
    """
    Compact structural overview of a repo: module -> class -> method names.
    No code bodies. Used to give the Primary Agent a "map" of the repo without
    burning tokens re-discovering it via round-trip queries each time.
    """

    repo_id: str
    commit_sha: str
    modules: list[dict] = field(default_factory=list)
    # Each module: {name, file_path, classes: [{name, methods: [name], fields: [name]}],
    # functions: [name], globals: [name]}
    built_at: float = 0.0

    def to_prompt_text(self, max_chars: int = 4000) -> str:
        """
        Render skeleton as a compact text block for inclusion in system prompts.
        Truncates to max_chars to control token cost.
        """
        lines = [f"## Repo Skeleton: {self.repo_id} @ {self.commit_sha[:12]}"]
        for mod in self.modules:
            lines.append(f"\n### {mod['name']} ({mod['file_path']})")
            for cls in mod.get("classes", []):
                methods = ", ".join(cls.get("methods", []))
                fields_str = ", ".join(cls.get("fields", []))
                lines.append(f"  class {cls['name']}")
                if methods:
                    lines.append(f"    methods: {methods}")
                if fields_str:
                    lines.append(f"    fields: {fields_str}")
            for fn in mod.get("functions", []):
                lines.append(f"  def {fn}()")
            for gv in mod.get("globals", []):
                lines.append(f"  {gv} = ...")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (skeleton truncated)"
        return text


class SkeletonCache:
    """In-memory cache for repo skeletons, keyed by (repo_id, commit_sha)."""

    def __init__(self):
        self._cache: dict[str, RepoSkeleton] = {}

    def _key(self, repo_id: str, commit_sha: str) -> str:
        return f"{repo_id}@{commit_sha[:12]}"

    def get(self, repo_id: str, commit_sha: str) -> Optional[RepoSkeleton]:
        return self._cache.get(self._key(repo_id, commit_sha))

    def put(self, skeleton: RepoSkeleton):
        key = self._key(skeleton.repo_id, skeleton.commit_sha)
        self._cache[key] = skeleton
        logger.debug("Skeleton cached for %s", key)

    def invalidate(self, repo_id: str, commit_sha: str):
        key = self._key(repo_id, commit_sha)
        self._cache.pop(key, None)

    def build_from_db(self, graph_db, repo_id: str, commit_sha: str) -> RepoSkeleton:
        """
        Build a skeleton by querying Neo4j for node names (no code bodies).
        """
        skeleton = RepoSkeleton(repo_id=repo_id, commit_sha=commit_sha, built_at=time.time())
        skeleton.modules = graph_db.run_query(
            "MATCH (m:MODULE {repo_id: $repo_id}) "
            "RETURN m.name AS name, m.file_path AS file_path, "
            "[(m)-[:CONTAINS]->(c:CLASS) | {name: c.name, "
            "methods: [(c)-[:HAS_METHOD]->(f:METHOD) | f.name], "
            "fields: [(c)-[:HAS_FIELD]->(v:FIELD) | v.name]}] AS classes, "
            "[(m)-[:CONTAINS]->(f:FUNCTION) | f.name] AS functions, "
            "[(m)-[:CONTAINS]->(g:GLOBAL_VARIABLE) | g.name] AS globals ORDER BY name",
            {"repo_id": repo_id},
        )

        self.put(skeleton)
        logger.info(
            "Built skeleton for %s - %d modules",
            self._key(repo_id, commit_sha),
            len(skeleton.modules),
        )
        return skeleton


# Query result cache + NL->Cypher translation cache


class QueryCache:
    """
    Disk-backed caches for:
      - Cypher query results (keyed by query + repo_id + commit_sha)
      - NL -> Cypher translations (keyed by NL text + schema version)

    Uses diskcache for persistence across sessions.
    """

    def __init__(self, cache_dir: Optional[str] = None, enabled: bool = True):
        self.enabled = enabled
        cache_dir = cache_dir or DEFAULT_CACHE_DIR

        self._cypher_cache = diskcache.Cache(
            os.path.join(cache_dir, "cypher_results"),
            size_limit=100 * 1024 * 1024,  # 100 MB
        )
        self._translation_cache = diskcache.Cache(
            os.path.join(cache_dir, "translations"),
            size_limit=50 * 1024 * 1024,  # 50 MB
        )
        # Stats
        self.cypher_hits = 0
        self.cypher_misses = 0
        self.translation_hits = 0
        self.translation_misses = 0

    def _cypher_key(self, cypher: str, repo_id: str, commit_sha: str) -> str:
        """Stable hash key for a Cypher query scoped to a repo version."""
        raw = f"{repo_id}|{commit_sha[:12]}|{cypher}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cypher_result(self, cypher: str, repo_id: str, commit_sha: str) -> Optional[list[dict]]:
        """Lookup cached Cypher query result."""
        if not self.enabled:
            return None
        key = self._cypher_key(cypher, repo_id, commit_sha)
        result = self._cypher_cache.get(key)
        if result is not None:
            self.cypher_hits += 1
            logger.debug("Cypher cache HIT: %s", cypher[:60])
            return cast(list[dict], result)
        self.cypher_misses += 1
        return None

    def put_cypher_result(self, cypher: str, repo_id: str, commit_sha: str, result: list[dict]):
        """Cache a Cypher query result."""
        if not self.enabled:
            return
        key = self._cypher_key(cypher, repo_id, commit_sha)
        self._cypher_cache.set(key, result, expire=3600 * 24 * 7)  # 7 day TTL

    def _translation_key(self, nl_query: str) -> str:
        """Key for NL->Cypher translation cache."""
        normalized = nl_query.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def get_translation(self, nl_query: str) -> Optional[str]:
        """Lookup cached NL -> Cypher translation."""
        if not self.enabled:
            return None
        # Exact match
        key = self._translation_key(nl_query)
        result = self._translation_cache.get(key)
        if result is not None:
            self.translation_hits += 1
            logger.debug("Translation cache HIT (exact): %s", nl_query[:60])
            return str(result)
        # Near-duplicate detection via simple string similarity
        result = self._find_similar_translation(nl_query)
        if result is not None:
            self.translation_hits += 1
            return result
        self.translation_misses += 1
        return None

    def put_translation(self, nl_query: str, cypher: str):
        """Cache an NL -> Cypher translation."""
        if not self.enabled:
            return
        key = self._translation_key(nl_query)
        self._translation_cache.set(key, cypher, expire=3600 * 24 * 7)

    def _find_similar_translation(self, nl_query: str, threshold: float = 0.85) -> Optional[str]:
        """
        Find a cached translation with high string similarity.
        Uses SequenceMatcher for cheap local comparison (no LLM call needed).
        """
        normalized = nl_query.strip().lower()
        # Only check a bounded number of recent entries to keep this fast
        for key in list(self._translation_cache)[:200]:
            try:
                cached_nl = self._translation_cache.get(f"_nl_{key}")
                if cached_nl and SequenceMatcher(None, normalized, cached_nl).ratio() >= threshold:
                    result = self._translation_cache.get(key)
                    if result:
                        logger.debug("Translation cache HIT (similar): %s", nl_query[:60])
                        return str(result)
            except Exception:
                continue
        return None

    def put_translation_with_nl(self, nl_query: str, cypher: str):
        """Cache translation with the original NL query for similarity matching."""
        if not self.enabled:
            return
        key = self._translation_key(nl_query)
        self._translation_cache.set(key, cypher, expire=3600 * 24 * 7)
        self._translation_cache.set(f"_nl_{key}", nl_query.strip().lower(), expire=3600 * 24 * 7)

    def stats(self) -> dict:
        """Return cache hit/miss statistics."""
        return {
            "cypher_hits": self.cypher_hits,
            "cypher_misses": self.cypher_misses,
            "cypher_hit_rate": (self.cypher_hits / max(1, self.cypher_hits + self.cypher_misses)),
            "translation_hits": self.translation_hits,
            "translation_misses": self.translation_misses,
            "translation_hit_rate": (
                self.translation_hits / max(1, self.translation_hits + self.translation_misses)
            ),
        }

    def clear(self):
        """Clear all caches."""
        self._cypher_cache.clear()
        self._translation_cache.clear()
        self.cypher_hits = self.cypher_misses = 0
        self.translation_hits = self.translation_misses = 0


# Context pruning: track seen nodes


class ContextTracker:
    """
    Tracks which nodes have been fully retrieved in previous rounds.
    When a node is seen again, replaces its 'code' field with a compact reference
    tag instead of re-transmitting the full text.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._seen_nodes: dict[str, str] = {}  # node_key -> label
        self._seen_code: dict[str, int] = {}  # node_key -> round when first seen

    def _node_key(self, record: dict) -> Optional[str]:
        """Generate a unique key for a node from its properties."""
        name = (
            record.get("name")
            or record.get("c.name")
            or record.get("f.name")
            or record.get("m.name")
        )
        file_path = (
            record.get("file_path") or record.get("c.file_path") or record.get("f.file_path")
        )
        if name:
            return f"{name}:{file_path or '?'}"
        return None

    def compact_results(self, results_text: str, round_num: int) -> str:
        """
        Replace already-seen code blocks with compact reference tags.
        Returns the compacted text.
        """
        if not self.enabled:
            return results_text

        lines = results_text.split("\n")
        output_lines = []
        current_node_key = None

        for line in lines:
            # Detect node name from "name:" fields
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip()
                current_node_key = name

            # Check for code fields
            if stripped.startswith("code:") and current_node_key:
                if current_node_key in self._seen_code:
                    seen_round = self._seen_code[current_node_key]
                    output_lines.append(
                        f"  code: [already retrieved in round {seen_round}, see {current_node_key}]"
                    )
                    continue
                else:
                    self._seen_code[current_node_key] = round_num

            output_lines.append(line)

        return "\n".join(output_lines)

    def mark_seen(self, record: dict, round_num: int):
        """Mark a node as seen in the given round."""
        key = self._node_key(record)
        if key and key not in self._seen_code:
            self._seen_code[key] = round_num

    def is_seen(self, record: dict) -> bool:
        key = self._node_key(record)
        return key in self._seen_code if key else False

    def reset(self):
        self._seen_nodes.clear()
        self._seen_code.clear()


# Result truncation / relevance filtering


def truncate_results(
    records: list[dict],
    max_rows: int = 15,
    enabled: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """
    Truncate query results to top-K rows.

    Returns:
        (truncated_records, note_string_or_None)
    """
    if not enabled or len(records) <= max_rows:
        return records, None

    total = len(records)
    remaining = total - max_rows
    note = f"(+{remaining} more results, refine your query to narrow results)"
    return records[:max_rows], note


# Early-stopping heuristic


def should_early_stop(
    current_results: list[str],
    previous_results: list[str],
    enabled: bool = True,
) -> tuple[bool, str]:
    """
    Check if the pipeline should early-stop based on result patterns.

    Returns:
        (should_stop, reason)
    """
    if not enabled:
        return False, ""

    # All results empty
    if all(r.strip() == "(No results found)" or r.strip() == "" for r in current_results):
        return True, "All queries returned empty results"

    # Results identical to previous round
    if previous_results and current_results == previous_results:
        return True, "Results identical to previous round"

    return False, ""


class IncrementalCache:
    """Serialize extraction records and invalidate reverse import dependents."""

    @staticmethod
    def encode(parsed) -> str:
        from dataclasses import asdict

        def identity(symbol):
            return (
                symbol.label,
                symbol.name,
                symbol.class_name,
                symbol.source.byte_start,
                symbol.source.byte_end,
            )

        # Many references share a caller. Store its position once instead of copying its body.
        indexes = {identity(symbol): index for index, symbol in enumerate(parsed.symbols)}
        return json.dumps(
            {
                "format_version": 1,
                "module": indexes[identity(parsed.module)],
                "symbols": [asdict(symbol) for symbol in parsed.symbols],
                "references": [
                    dict(
                        kind=ref.kind,
                        target=ref.target,
                        alias=ref.alias,
                        source=indexes[identity(ref.source)],
                    )
                    for ref in parsed.references
                ],
                "content_hash": parsed.content_hash,
            }
        )

    @staticmethod
    def decode(data: str):
        from graph_n4j.parsers.base import (
            ParsedFile,
            ParsedReference,
            ParsedSymbol,
            SourceReference,
        )

        def symbol(row):
            return ParsedSymbol(**dict(row, source=SourceReference(**row["source"])))

        row = json.loads(data)
        symbols = [symbol(s) for s in row["symbols"]]
        if row.get("format_version") == 1:
            return ParsedFile(
                symbols[row["module"]],
                symbols,
                [
                    ParsedReference(**dict(r, source=symbols[r["source"]]))
                    for r in row["references"]
                ],
                row["content_hash"],
            )
        # Read extraction records written before compact reference encoding.
        return ParsedFile(
            symbol(row["module"]),
            symbols,
            [ParsedReference(**dict(r, source=symbol(r["source"]))) for r in row["references"]],
            row["content_hash"],
        )

    @staticmethod
    def reverse_invalidated(changed: set[str], dependencies: dict[str, set[str]]) -> set[str]:
        affected = set(changed)
        while True:
            more = {path for path, imports in dependencies.items() if imports & affected}
            if more <= affected:
                return affected
            affected.update(more)
