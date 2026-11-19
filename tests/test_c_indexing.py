from graph_n4j.indexer.unified_indexer import UnifiedIndexer
from graph_n4j.repo_manager import RepoManager


def test_nested_c_files_are_discovered_and_linked(db, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "api.h").write_text("int value(void);\n")
    (source / "main.c").write_text('#include "api.h"\nint run(void) { return value(); }\n')
    manager = RepoManager(str(tmp_path / "clones"))
    meta = manager.load_local_repo(str(tmp_path), repo_id="nested-c")
    files = manager.get_source_files(meta)
    assert len(files) == 2
    db.clear_repo(meta.repo_id)
    try:
        indexer = UnifiedIndexer(db)
        indexer.index(str(tmp_path), files, meta.repo_id, "one")
        stats = db.get_stats(meta.repo_id)
        assert stats["IMPORTS"] == stats["CALLS"] == 1
        assert indexer.index(str(tmp_path), files, meta.repo_id, "two").skipped_files == 2
    finally:
        db.clear_repo(meta.repo_id)
