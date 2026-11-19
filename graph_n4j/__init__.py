"""Public Python interface for indexing a repository and querying its code graph."""

from graph_n4j._version import __version__
from graph_n4j.cache import ContextTracker, QueryCache, SkeletonCache
from graph_n4j.core import GraphN4J
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient
from graph_n4j.repo_manager import RepoManager, RepoMetadata
from graph_n4j.schema import SCHEMA_DESCRIPTION

__all__ = [
    "GraphN4J",
    "GraphDB",
    "GroqClient",
    "SCHEMA_DESCRIPTION",
    "SkeletonCache",
    "QueryCache",
    "ContextTracker",
    "RepoManager",
    "RepoMetadata",
    "__version__",
]
