"""Measure the indexer and database writes in a fresh process for each case."""

import json
import logging
import os
import sys
import time
from pathlib import Path

from graph_n4j import GraphDB, __version__


class CountingDB(GraphDB):
    writes = 0

    def run_write(self, *args, **kwargs):
        self.writes += 1
        return super().run_write(*args, **kwargs)


def measure(version, root, sha, uri):
    if __version__ != version:
        raise ValueError(f"Loaded {__version__}, expected {version}")
    repo = "benchmark-" + root.name
    files = sorted(str(p) for p in root.rglob("*") if p.is_file())
    if version == "0.1.8":
        from graph_n4j.indexer.edge_completion import complete_edges
        from graph_n4j.indexer.shallow_index import shallow_index_repo

        if not any(p.endswith(".py") for p in files):
            return dict(version=version, supported=False)
    else:
        from graph_n4j.indexer.unified_indexer import UnifiedIndexer

    with CountingDB(uri, "neo4j", os.getenv("NEO4J_PASSWORD", "benchmark")) as db:
        db.init_schema()
        db.run_query("CALL db.awaitIndexes()")
        runs = []
        for state in ["empty", "unchanged"]:
            # Count writes issued during indexing. Schema setup, inspection and
            # cleanup are outside the measurement window for both versions.
            db.writes = 0
            start = time.perf_counter()
            if version == "0.1.8":
                extracted = shallow_index_repo(str(root))
                complete_edges(extracted, db, str(root), repo, sha)
                parsed, reused = len(extracted.modules), 0
            else:
                metrics = UnifiedIndexer(db).index(str(root), files, repo, sha)
                parsed, reused = metrics.parsed_files, metrics.skipped_files
            runs.append(
                dict(
                    state=state,
                    seconds=time.perf_counter() - start,
                    parsed=parsed,
                    reused=reused,
                    writes=db.writes,
                )
            )
        params = {"repo": repo}
        nodes = db.run_query(
            "MATCH (n {repo_id:$repo}) RETURN labels(n)[0] AS kind, count(*) AS n", params
        )
        edges = db.run_query(
            "MATCH (a {repo_id:$repo})-[r]->() RETURN type(r) AS kind, count(*) AS n", params
        )
        example = db.run_query(
            "MATCH (g:CLASS {repo_id:$repo, name:'Group'})-[r:INHERITS]->(c:CLASS) "
            "RETURN g.file_path AS path, c.name AS parent",
            params,
        )
        db.clear_repo(repo)
    return dict(
        version=version,
        supported=True,
        measurements=runs,
        nodes={r["kind"]: r["n"] for r in nodes},
        edges={r["kind"]: r["n"] for r in edges},
        group_parents=example,
    )


if __name__ == "__main__":
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    requested, path, commit, database_uri = sys.argv[1:]
    print(json.dumps(measure(requested, Path(path), commit, database_uri)))
