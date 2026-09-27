"""
graph-n4j — Bridge LLM agents with code repositories via Neo4j graph databases.

Based on the CodexGraph NAACL 2025 paper:
"CodexGraph: Bridging Large Language Models and Code Repositories via Code Graph Databases"

Quick Start:
    from graph_n4j import GraphN4J

    g = GraphN4J.from_env()              # reads GROQ_API_KEY, NEO4J_* from .env
    g.index("./my-python-project")       # index a local repo
    result = g.ask("What does the Foo class do?")
    print(result.answer)
"""

__version__ = "0.1.8"

from graph_n4j.core import GraphN4J
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient
from graph_n4j.schema import SCHEMA_DESCRIPTION
from graph_n4j.cache import SkeletonCache, QueryCache, ContextTracker
from graph_n4j.repo_manager import RepoManager, RepoMetadata

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
