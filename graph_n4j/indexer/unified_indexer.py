"""Reuse cached parses, link the repository and write affected graph records."""

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from graph_n4j._version import __version__
from graph_n4j.graph_db import GraphDB
from graph_n4j.indexer.linker import TopologicalLinker
from graph_n4j.indexer.symbol_table import SymbolTable
from graph_n4j.parsers.base import ParsedFile
from graph_n4j.parsers.registry import ParserRegistry


@dataclass
class IndexMetrics:
    parse_time: float = 0
    link_time: float = 0
    ingestion_time: float = 0
    parsed_files: int = 0
    skipped_files: int = 0


class UnifiedIndexer:
    def __init__(self, db: GraphDB, registry: ParserRegistry | None = None):
        self.db = db
        self.registry = registry or ParserRegistry()
        self.metrics = IndexMetrics()

    def index(self, root: str, files: list[str], repo_id: str, commit_sha: str) -> IndexMetrics:
        from graph_n4j.cache import IncrementalCache

        self.metrics = IndexMetrics()
        start = time.perf_counter()
        previous = self.db.run_query(
            "MATCH (m:MODULE {repo_id: $repo_id}) RETURN properties(m) AS module_properties",
            {"repo_id": repo_id},
        )
        # Read properties as a map so older module nodes without cache fields do not
        # trigger Neo4j's unknown-property warnings during the first upgraded run.
        # A parse is reusable only when the bytes and extractor version both match.
        cached = {}
        for row in previous:
            properties = row.get("module_properties") or {}
            file_path = properties.get("file_path")
            if file_path:
                cached[file_path] = {
                    "content_hash": properties.get("content_hash"),
                    "parsed_data": properties.get("parsed_data"),
                    "index_version": properties.get("index_version"),
                }
        parsed: list[ParsedFile] = []
        changed = set()
        for file_path in files:
            path = Path(file_path).relative_to(root).as_posix()
            source = Path(file_path).read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            old = cached.get(path, {})
            if (
                old.get("content_hash") == digest
                and old.get("parsed_data")
                and old.get("index_version") == __version__
            ):
                item = IncrementalCache.decode(old["parsed_data"])
                self.metrics.skipped_files += 1
            else:
                item = self.registry.get(path).parse(source, path)
                item.content_hash = digest
                changed.add(path)
                self.metrics.parsed_files += 1
            parsed.append(item)
        deleted = set(cached) - {f.module.source.file_path for f in parsed}
        self.metrics.parse_time = time.perf_counter() - start
        start = time.perf_counter()
        linker = TopologicalLinker(SymbolTable(parsed))
        edges = linker.link()
        affected = IncrementalCache.reverse_invalidated(changed | deleted, linker.dependencies)
        if deleted:
            # Old IMPORTS edges retain dependents when an imported module was removed.
            rows = self.db.run_query(
                "MATCH (a:MODULE {repo_id: $repo_id})-[:IMPORTS*1..]->"
                "(b:MODULE {repo_id: $repo_id}) "
                "WHERE b.file_path IN $paths RETURN DISTINCT a.file_path AS file_path",
                {"repo_id": repo_id, "paths": list(deleted)},
            )
            affected.update(r["file_path"] for r in rows)
        self.metrics.link_time = time.perf_counter() - start
        start = time.perf_counter()
        if affected:
            self.db.run_write(
                "MATCH (n {repo_id: $repo_id}) WHERE n.file_path IN $paths DETACH DELETE n",
                {"repo_id": repo_id, "paths": sorted(affected)},
            )
            nodes = defaultdict(list)
            for item in parsed:
                if item.module.source.file_path not in affected:
                    continue
                for symbol in item.symbols:
                    row = symbol.properties()
                    if symbol.label == "MODULE":
                        row.update(
                            content_hash=item.content_hash,
                            index_version=__version__,
                            parsed_data=IncrementalCache.encode(item),
                        )
                    nodes[symbol.label].append(row)
            for label, rows in nodes.items():
                self.db.merge_nodes_batch(label, rows, repo_id, commit_sha)
            # Recreate incoming edges as well as changed/dependent outgoing edges.
            for kind, relationships in edges.items():
                self.db.merge_edges_batch(
                    kind,
                    [
                        e
                        for e in relationships
                        if e["source"]["file_path"] in affected
                        or e["target"]["file_path"] in affected
                    ],
                    repo_id,
                )
        self.db.run_write(
            "MATCH (n {repo_id: $repo_id}) SET n.commit_sha = $commit_sha",
            {"repo_id": repo_id, "commit_sha": commit_sha},
        )
        self.metrics.ingestion_time = time.perf_counter() - start
        return self.metrics
