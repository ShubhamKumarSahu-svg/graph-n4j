from pathlib import Path

from graph_n4j.indexer.unified_indexer import UnifiedIndexer


def test_incremental_edit_delete_and_isolation(db, tmp_path):
    (tmp_path / "base.py").write_text("def target(): return 1\n")
    (tmp_path / "main.py").write_text("from base import target\ndef run(): return target()\n")
    files = [str(p) for p in sorted(tmp_path.glob("*.py"))]
    root = str(tmp_path)
    for repo in ("unified-a", "unified-b"):
        db.clear_repo(repo)
        indexer = UnifiedIndexer(db)
        metrics = indexer.index(root, files, repo, "one")
        assert metrics.parsed_files == 2
        assert db.get_stats(repo)["CALLS"] == 1
    metrics = indexer.index(root, files, "unified-a", "two")
    assert metrics.parsed_files == 0 and metrics.skipped_files == 2
    (tmp_path / "base.py").write_text("def renamed(): return 2\n")
    metrics = indexer.index(root, files, "unified-a", "three")
    assert metrics.parsed_files == 1
    assert db.get_stats("unified-a")["CALLS"] == 0
    assert db.get_stats("unified-b")["CALLS"] == 1
    Path(files[0]).unlink()
    indexer.index(root, files[1:], "unified-a", "four")
    assert db.get_stats("unified-a")["MODULE"] == 1
    for repo in ("unified-a", "unified-b"):
        db.clear_repo(repo)


def test_cpp_index_and_fulltext(db, tmp_path):
    source = tmp_path / "main.cpp"
    source.write_text("int helper() { return 1; } int run() { return helper(); }")
    db.clear_repo("cpp-fixture")
    UnifiedIndexer(db).index(str(tmp_path), [str(source)], "cpp-fixture", "sha")
    assert db.get_stats("cpp-fixture")["CALLS"] == 1
    db.run_write("CALL db.awaitIndexes()")
    results = db.run_query(
        (
            "CALL db.index.fulltext.queryNodes('symbol_search_idx', 'helper') "
            "YIELD node WHERE node.repo_id = 'cpp-fixture' RETURN node.name AS "
            "name"
        )
    )
    assert any(r["name"] == "helper" for r in results)
    db.clear_repo("cpp-fixture")


def test_extraction_cache_does_not_duplicate_bodies_per_reference():
    from graph_n4j.cache import IncrementalCache
    from graph_n4j.parsers.python_parser import PythonParser

    source = b"def target(): return 1\ndef run():\n" + b"    target()\n" * 200
    parsed = PythonParser().parse(source, "main.py")
    encoded = IncrementalCache.encode(parsed)
    assert len(encoded) < 200_000
    decoded = IncrementalCache.decode(encoded)
    assert decoded.symbols == parsed.symbols
    assert decoded.references == parsed.references


def test_duplicate_globals_and_closure_fields(db, tmp_path):
    from graph_n4j.indexer.edge_completion import complete_edges
    from graph_n4j.indexer.shallow_index import shallow_index_repo

    (tmp_path / "a.py").write_text(
        "VALUE = 1\ndef run(): return VALUE\n"
        "class Owner:\n    field = 1\n    def method(self):\n"
        "        def inner(): return self.field\n        return inner()\n"
    )
    (tmp_path / "b.py").write_text("VALUE = 2\n")
    files = [str(p) for p in sorted(tmp_path.glob("*.py"))]
    for mode in ("legacy", "unified"):
        repo = "scope-test-" + mode
        db.clear_repo(repo)
        if mode == "legacy":
            complete_edges(
                shallow_index_repo(str(tmp_path), files), db, str(tmp_path), repo_id=repo
            )
        else:
            UnifiedIndexer(db).index(str(tmp_path), files, repo, "sha")
        rows = db.run_query(
            'MATCH (f:FUNCTION {repo_id: $repo, name: "run"})-[:USES]->(v:GLOBAL_VARIABLE) '
            "RETURN v.file_path AS file_path",
            {"repo": repo},
        )
        assert rows == [{"file_path": "a.py"}]
        rows = db.run_query(
            'MATCH (m:METHOD {repo_id: $repo, name: "method"})-[:USES]->(v:FIELD) '
            "RETURN v.name AS name",
            {"repo": repo},
        )
        assert rows == [{"name": "field"}]
        db.clear_repo(repo)
