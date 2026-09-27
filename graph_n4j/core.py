"""
core.py — High-level facade for graph-n4j.

Provides a single `GraphN4J` class that wraps all internal components
(GraphDB, GroqClient, indexer, pipeline, apps) behind a simple API.

Usage:
    from graph_n4j import GraphN4J

    g = GraphN4J.from_env()                 # reads .env / env vars
    g.index("./my-repo")                    # index a local Python project
    result = g.ask("What does class X do?") # ask anything
    print(result.answer)

    # Or clone + index a GitHub repo:
    g.index_github("pallets/click")
    result = g.ask("How does the Group class work?")
"""

import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv, find_dotenv

from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient
from graph_n4j.repo_manager import RepoManager, RepoMetadata
from graph_n4j.indexer.shallow_index import shallow_index_repo
from graph_n4j.indexer.edge_completion import complete_edges
from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.cache import SkeletonCache, QueryCache

logger = logging.getLogger(__name__)


class GraphN4J:
    """
    High-level API for graph-n4j.

    Wraps the full CodexGraph pipeline: indexing, querying, and LLM-powered
    code Q&A over a Neo4j graph database.
    """

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_model: str = "llama-3.3-70b-versatile",
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
        neo4j_database: str = "neo4j",
        cache_dir: Optional[str] = None,
        repos_dir: Optional[str] = None,
    ):
        """
        Initialize graph-n4j.

        Args:
            groq_api_key: Groq API key (or set GROQ_API_KEY env var).
            groq_model: Groq model name for the primary agent.
            neo4j_uri: Neo4j bolt URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
            neo4j_database: Neo4j database name.
            cache_dir: Directory for query/translation caches.
            repos_dir: Directory for cloned GitHub repos.
        """
        self.client = GroqClient(api_key=groq_api_key, model=groq_model)
        self.db = GraphDB(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
        )
        self.repo_manager = RepoManager(cache_dir=repos_dir)
        self.skeleton_cache = SkeletonCache()
        self.query_cache = QueryCache(cache_dir=cache_dir)

        # Track the currently active repo
        self._current_meta: Optional[RepoMetadata] = None
        self._connected = False

    # ── Factory methods ──────────────────────────────────────

    @classmethod
    def from_env(cls, dotenv_path: Optional[str] = None) -> "GraphN4J":
        """
        Create a GraphN4J instance from environment variables.

        Reads: GROQ_API_KEY, GROQ_MODEL, NEO4J_URI, NEO4J_USER,
        NEO4J_PASSWORD, NEO4J_DATABASE.

        Args:
            dotenv_path: Optional path to a .env file.
        """
        if dotenv_path is None:
            dotenv_path = find_dotenv(usecwd=True)
        load_dotenv(dotenv_path, override=True, encoding="utf-8-sig")
        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )

    # ── Connection lifecycle ─────────────────────────────────

    def connect(self) -> "GraphN4J":
        """Connect to Neo4j. Call this before indexing or querying."""
        self.db.connect()
        self.db.init_schema()
        self._connected = True
        return self

    def close(self):
        """Close the Neo4j connection."""
        self.db.close()
        self._connected = False

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_connected(self):
        if not self._connected:
            self.connect()

    # ── Indexing ─────────────────────────────────────────────

    def index(
        self,
        repo_path: str,
        repo_id: Optional[str] = None,
        clear_existing: bool = False,
    ) -> RepoMetadata:
        """
        Index a local Python repository into Neo4j.

        Args:
            repo_path: Path to the Python repository root.
            repo_id: Optional override for the repo identifier.
            clear_existing: If True, clear any existing data for this repo first.

        Returns:
            RepoMetadata with details about the indexed repo.
        """
        self._ensure_connected()
        meta = self.repo_manager.load_local_repo(repo_path, repo_id)

        if clear_existing:
            self.db.clear_repo(meta.repo_id)

        return self._run_indexing(meta)

    def index_github(
        self,
        url: str,
        commit_sha: Optional[str] = None,
        clear_existing: bool = False,
        force_clone: bool = False,
    ) -> RepoMetadata:
        """
        Clone a GitHub repository and index it into Neo4j.

        Args:
            url: GitHub URL or short form (e.g. "pallets/click").
            commit_sha: Optional commit to pin to (defaults to HEAD).
            clear_existing: If True, clear any existing data for this repo first.
            force_clone: If True, re-clone even if already cached locally.

        Returns:
            RepoMetadata with details about the indexed repo.
        """
        self._ensure_connected()
        meta = self.repo_manager.clone_repo(url, commit_sha, force=force_clone)

        if clear_existing:
            self.db.clear_repo(meta.repo_id)

        return self._run_indexing(meta)

    def _run_indexing(self, meta: RepoMetadata) -> RepoMetadata:
        """Run Phase 1 (shallow index) and Phase 2 (edge completion)."""
        t0 = time.time()

        # Phase 1: Shallow indexing
        logger.info("Phase 1: Shallow indexing %s ...", meta.repo_id)
        index_result = shallow_index_repo(meta.local_path)
        logger.info("Phase 1 complete: %s", index_result.summary())

        # Phase 2: Edge completion
        logger.info("Phase 2: Edge completion ...")
        complete_edges(index_result, self.db, meta.local_path)

        meta.index_time = time.time() - t0
        logger.info(
            "Indexing complete for %s in %.1fs",
            meta.repo_id, meta.index_time,
        )

        self._current_meta = meta

        # Pre-build skeleton for fast queries
        self.skeleton_cache.build_from_db(
            self.db, meta.repo_id, meta.commit_sha,
        )

        return meta

    # ── Querying ─────────────────────────────────────────────

    def ask(
        self,
        question: str,
        repo_id: Optional[str] = None,
        commit_sha: Optional[str] = None,
        max_rounds: int = 5,
        query_mode: str = "single_query",
        task_instruction: str = "",
    ) -> PipelineResult:
        """
        Ask a question about an indexed codebase.

        Args:
            question: Natural language question about the code.
            repo_id: Optional repo to query (defaults to last indexed).
            commit_sha: Optional commit SHA (defaults to last indexed).
            max_rounds: Maximum retrieval rounds.
            query_mode: "single_query" or "multiple_queries".
            task_instruction: Optional additional instructions for the agent.

        Returns:
            PipelineResult with the answer and retrieval stats.
        """
        self._ensure_connected()

        # Resolve repo context
        if repo_id is None and self._current_meta:
            repo_id = self._current_meta.repo_id
            commit_sha = commit_sha or self._current_meta.commit_sha
        repo_id = repo_id or ""
        commit_sha = commit_sha or ""

        pipeline = CodexGraphPipeline(
            groq_client=self.client,
            graph_db=self.db,
            max_rounds=max_rounds,
            query_mode=query_mode,
            task_instruction=task_instruction,
            repo_id=repo_id,
            commit_sha=commit_sha,
            skeleton_cache=self.skeleton_cache,
            query_cache=self.query_cache,
        )
        return pipeline.run(question)

    # ── Utility ──────────────────────────────────────────────

    def stats(self, repo_id: Optional[str] = None) -> dict:
        """Get graph statistics (node/edge counts)."""
        self._ensure_connected()
        rid = repo_id or (self._current_meta.repo_id if self._current_meta else None)
        return self.db.get_stats(rid)

    def list_repos(self) -> list[dict]:
        """List all repos indexed in Neo4j."""
        self._ensure_connected()
        return self.db.list_repos()

    def clear_repo(self, repo_id: str):
        """Remove all data for a specific repo from Neo4j."""
        self._ensure_connected()
        self.db.clear_repo(repo_id)

    def clear_all(self):
        """Remove ALL data from Neo4j. Use with caution."""
        self._ensure_connected()
        self.db.clear_all()

    def run_cypher(self, cypher: str, parameters: Optional[dict] = None) -> list[dict]:
        """Execute a raw Cypher query against Neo4j."""
        self._ensure_connected()
        return self.db.run_query(cypher, parameters)

    @property
    def token_usage(self) -> dict:
        """Get cumulative LLM token usage."""
        return self.client.usage.to_dict()
