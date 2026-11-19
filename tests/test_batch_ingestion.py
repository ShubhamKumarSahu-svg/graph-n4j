from unittest.mock import Mock

import pytest

from graph_n4j.graph_db import GraphDB


def test_batches_are_parameterized_and_chunked():
    db = GraphDB()
    db.run_write = Mock(return_value=[])
    db.merge_nodes_batch(
        "FUNCTION", [{"name": str(i), "file_path": "a.py"} for i in range(5)], "r", "sha", 2
    )
    assert db.run_write.call_count == 3
    query, params = db.run_write.call_args.args
    assert "UNWIND $batch" in query
    assert params["repo_id"] == "r"
    assert len(params["batch"]) == 1
    with pytest.raises(ValueError):
        db.merge_nodes_batch("BAD", [], "r", "sha")
    with pytest.raises(ValueError):
        db.merge_nodes_batch("MODULE", [], "r", "sha", 0)


def test_multi_repo_isolation(db):
    for repo in ["batch-test-a", "batch-test-b"]:
        db.clear_repo(repo)
        db.merge_nodes_batch("FUNCTION", [{"name": "same", "file_path": "a.py"}], repo, "sha")
    rows = db.run_query(
        (
            "MATCH (n:FUNCTION {name: 'same', file_path: 'a.py'}) WHERE "
            "n.repo_id STARTS WITH 'batch-test-' RETURN count(n) AS count"
        )
    )
    assert rows[0]["count"] == 2
    for repo in ["batch-test-a", "batch-test-b"]:
        db.clear_repo(repo)
