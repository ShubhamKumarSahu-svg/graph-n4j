"""Compare both real indexers in separate processes against the same Neo4j server.

Run: python -m benchmarks.run_benchmark --repo ./repo --output benchmarks/results.json
Uses NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. Only benchmark-owned repo IDs are cleared.
"""

import argparse
import json
import multiprocessing
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from benchmarks.synthetic_generator import generate
from graph_n4j.graph_db import GraphDB
from graph_n4j.indexer.edge_completion import complete_edges
from graph_n4j.indexer.shallow_index import shallow_index_repo
from graph_n4j.indexer.unified_indexer import UnifiedIndexer
from graph_n4j.repo_manager import RepoManager


class CountingDB(GraphDB):
    transactions = 0

    def run_query(self, cypher, parameters=None, write=False):
        self.transactions += 1
        return super().run_query(cypher, parameters, write)


def worker(root: str, mode: str, output):
    try:
        with CountingDB() as db:
            db.init_schema()
            repo_id = "graph-n4j-benchmark-" + mode
            db.clear_repo(repo_id)
            manager = RepoManager()
            meta = manager.load_local_repo(root, repo_id)
            files = manager.get_python_files(meta)
            db.transactions = 0
            start = time.perf_counter()
            if mode == "legacy":
                parse_start = time.perf_counter()
                index = shallow_index_repo(root, source_files=files)
                parse_time = time.perf_counter() - parse_start
                link_start = time.perf_counter()
                complete_edges(index, db, root, repo_id=repo_id, commit_sha="benchmark")
                link_time = time.perf_counter() - link_start
                # Legacy links and writes are interleaved, so ingestion cannot be isolated.
                ingestion_time = None
            else:
                metrics = UnifiedIndexer(db).index(root, files, repo_id, meta.commit_sha)
                parse_time, link_time, ingestion_time = (
                    metrics.parse_time,
                    metrics.link_time,
                    metrics.ingestion_time,
                )
            wall_time = time.perf_counter() - start
            transactions = db.transactions
            nodes = db.run_query(
                (
                    "MATCH (n {repo_id: $repo_id}) RETURN labels(n)[0] AS label, "
                    "n.name AS name, n.file_path AS file_path, coalesce(n.class_name, "
                    '"") AS class_name'
                ),
                {"repo_id": repo_id},
            )
            edges = db.run_query(
                (
                    "MATCH (s {repo_id: $repo_id})-[r]->(t {repo_id: $repo_id}) RETURN "
                    "type(r) AS type, labels(s)[0] AS source_label, s.name AS source, "
                    's.file_path AS source_file, coalesce(s.class_name, "") AS '
                    "source_class, labels(t)[0] AS target_label, t.name AS target, "
                    't.file_path AS target_file, coalesce(t.class_name, "") AS '
                    "target_class"
                ),
                {"repo_id": repo_id},
            )
            # Legacy stores absolute paths; normalize identities before comparing sets.
            for row in nodes + edges:
                for key in ("file_path", "source_file", "target_file"):
                    if key in row and Path(row[key]).is_absolute():
                        row[key] = str(Path(row[key]).relative_to(root))
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mb = peak / (1024 * 1024 if sys.platform == "darwin" else 1024)
            output.put(
                dict(
                    mode=mode,
                    parse_time=parse_time,
                    link_time=link_time,
                    ingestion_time=ingestion_time,
                    wall_time=wall_time,
                    rss_mb=rss_mb,
                    transactions=transactions,
                    nodes=nodes,
                    edges=edges,
                )
            )
            db.clear_repo(repo_id)
    except Exception as exc:
        output.put({"error": repr(exc)})


def compare(root: str) -> dict[str, Any]:
    results = {}
    ctx = multiprocessing.get_context("spawn")
    for mode in ("legacy", "unified"):
        queue = ctx.Queue()
        process = ctx.Process(target=worker, args=(root, mode, queue))
        process.start()
        result = queue.get(timeout=300)
        process.join(timeout=10)
        if "error" in result:
            raise RuntimeError(result["error"])
        results[mode] = result
    old, new = results["legacy"], results["unified"]

    def identities(rows):
        return {json.dumps(row, sort_keys=True) for row in rows}

    missing_nodes = identities(old["nodes"]) - identities(new["nodes"])
    missing_edges = identities(old["edges"]) - identities(new["edges"])
    results["parity"] = dict(
        missing_nodes=sorted(missing_nodes), missing_edges=sorted(missing_edges)
    )
    return results


def render_report(results: dict[str, Any]) -> str:
    old, new = results["legacy"], results["unified"]
    lines = [
        "=" * 106,
        "GRAPH-N4J ARCHITECTURAL BENCHMARK REPORT".center(106),
        "=" * 106,
        f"Repository: {results['repository']} (Commit: {results.get('commit_sha', 'local')}, "
        f"Files: {results.get('file_count', '?')})",
        "-" * 106,
        f"{'Metric':32} {'Legacy 2-Pass (AST)':>22} "
        f"{'Unified (Tree-sitter)':>24} {'Speedup / Delta':>22}",
        "-" * 106,
    ]
    names = [
        ("parse_time", "File Parse Time", "s"),
        ("link_time", "Resolution / Legacy + Ingestion", "s"),
        ("ingestion_time", "Neo4j Ingestion Time", "s"),
        ("wall_time", "Total Wall-Clock Time", "s"),
        ("rss_mb", "Peak Memory (RSS)", "MB"),
        ("transactions", "Bolt Network Transactions", "tx"),
    ]
    for key, name, unit in names:
        left, right = old[key], new[key]
        left_text = "combined above" if left is None else f"{left:.4f} {unit}"
        right_text = f"{right:.4f} {unit}"
        delta = ""
        if left is not None and right and key != "link_time":
            delta = f"{left / right:.2f}x ratio"
        lines.append(f"{name:32} {left_text:>22} {right_text:>24} {delta:>22}")
    for kind, name in [("nodes", "Node Parity"), ("edges", "Edge Parity")]:
        missing = len(results["parity"]["missing_" + kind])
        status = f"{missing} MISSING" if missing else "MATCH / SUPERSET"
        lines.append(f"{name:32} {len(old[kind]):>22} {len(new[kind]):>24} {status:>22}")
    lines += [
        "=" * 106,
        "Legacy resolution interleaves writes; its ingestion split is unavailable.",
        "Transaction counts exclude schema setup, cleanup, and parity inspection.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo")
    parser.add_argument("--files", type=int, default=20)
    parser.add_argument("--output", default="benchmarks/results.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="graph-n4j-benchmark-") as temp:
        if not args.repo:
            generate(Path(temp), args.files)
        root = str(Path(args.repo or temp).resolve())
        manager = RepoManager()
        meta = manager.load_local_repo(root)
        file_count = len(manager.get_python_files(meta))
        results = compare(root)
    results.update(
        repository=args.repo or f"synthetic Python ({args.files} files)",
        commit_sha=meta.commit_sha,
        file_count=file_count,
    )
    output = Path(args.output)
    output.write_text(json.dumps(results, indent=2) + "\n")
    report = render_report(results)
    output.with_suffix(".txt").write_text(report)
    print(report, end="")
    if any(results["parity"].values()):
        raise SystemExit("Parity failed; inspect the JSON report")


if __name__ == "__main__":
    main()
