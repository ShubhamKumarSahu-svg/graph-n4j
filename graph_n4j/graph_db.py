"""Manage Neo4j sessions and write repository-scoped symbols and relationships."""

import logging
import os
from typing import Any, Optional

from neo4j import Driver, GraphDatabase, Result
from neo4j.exceptions import AuthError, ServiceUnavailable

from graph_n4j.schema import (
    EDGE_TYPES,
    NODE_LABELS,
    SCHEMA_CONSTRAINTS,
    SCHEMA_INDEXES,
    SCHEMA_MIGRATIONS,
)

logger = logging.getLogger(__name__)


class GraphDB:
    """Neo4j graph database connection and query interface for CodexGraph."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "neo4j",
    ):
        self.uri = uri or os.getenv("NEO4J_URI") or "bolt://localhost:7687"
        self.user = user or os.getenv("NEO4J_USER") or "neo4j"
        self.password = password or os.getenv("NEO4J_PASSWORD") or "password"
        self.database = database
        self._driver: Optional[Driver] = None

    def connect(self) -> "GraphDB":
        """Establish connection to Neo4j."""
        try:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self._driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", self.uri)
        except ServiceUnavailable:
            logger.debug("Neo4j is unreachable at %s", self.uri, exc_info=True)
            raise
        except AuthError:
            logger.debug("Neo4j rejected the configured credentials", exc_info=True)
            raise
        return self

    def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Disconnected from Neo4j.")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError("Not connected. Call .connect() first.")
        return self._driver

    def init_schema(self):
        """Create constraints and indexes. Safe to call repeatedly (IF NOT EXISTS)."""
        for stmt in SCHEMA_MIGRATIONS + SCHEMA_CONSTRAINTS + SCHEMA_INDEXES:
            self.run_write(stmt)

    def clear_all(self):
        """Delete all nodes and relationships. USE WITH CAUTION."""
        with self.driver.session(database=self.database) as session:
            session.run(
                "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 100 ROWS"
            ).consume()
        logger.info("All data cleared from database '%s'.", self.database)

    def clear_repo(self, repo_id: str):
        """Delete all nodes and relationships for a specific repo."""
        with self.driver.session(database=self.database) as session:
            session.run(
                "MATCH (n {repo_id: $repo_id}) "
                "CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 100 ROWS",
                repo_id=repo_id,
            ).consume()
        logger.info("Cleared data for repo '%s'.", repo_id)

    def run_query(
        self,
        cypher: str,
        parameters: Optional[dict[str, Any]] = None,
        write: bool = False,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as a list of dicts."""
        parameters = parameters or {}

        def _work(tx):
            result: Result = tx.run(cypher, parameters)
            return [record.data() for record in result]

        with self.driver.session(database=self.database) as session:
            if write:
                return session.execute_write(_work)
            else:
                return session.execute_read(_work)

    def run_write(
        self, cypher: str, parameters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Shortcut for run_query(..., write=True)."""
        return self.run_query(cypher, parameters, write=True)

    def run_scoped_query(
        self,
        cypher: str,
        repo_id: str,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a Cypher query with repo_id injected as a parameter.
        The Translation Agent generates queries using $repo_id; this injects the
        actual value via query parameters (no string interpolation = no injection).
        """
        params = {"repo_id": repo_id}
        if extra_params:
            params.update(extra_params)
        return self.run_query(cypher, params)

    def merge_nodes_batch(
        self,
        label: str,
        nodes: list[dict[str, Any]],
        repo_id: str,
        commit_sha: str,
        batch_size: int = 500,
    ) -> None:
        if label not in NODE_LABELS or batch_size <= 0:
            raise ValueError("Invalid node label or batch size")
        identity = "name: row.name, file_path: row.file_path, repo_id: $repo_id"
        # Classes in the same file can reuse a member name. Include the owner in its key.
        if label in ("METHOD", "FIELD"):
            identity += ", class_name: row.class_name"
        query = (
            f"UNWIND $batch AS row MERGE (n:{label} {{{identity}}}) "
            "SET n += row, n.repo_id = $repo_id, n.commit_sha = $commit_sha"
        )
        for offset in range(0, len(nodes), batch_size):
            self.run_write(
                query,
                {
                    "batch": nodes[offset : offset + batch_size],
                    "repo_id": repo_id,
                    "commit_sha": commit_sha,
                },
            )

    def merge_edges_batch(
        self, edge_type: str, edges: list[dict[str, Any]], repo_id: str, batch_size: int = 1000
    ) -> None:
        if edge_type not in EDGE_TYPES or batch_size <= 0:
            raise ValueError("Invalid relationship type or batch size")
        # Group by endpoint labels so indexed MATCH patterns remain selective.
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in edges:
            labels = (edge["source_label"], edge["target_label"])
            if any(label not in NODE_LABELS for label in labels):
                raise ValueError("Invalid endpoint label")
            groups.setdefault(labels, []).append(edge)
        for (src, dst), rows in groups.items():
            patterns = []
            for alias, label, key in (("s", src, "source"), ("t", dst, "target")):
                identity = (
                    f"name: row.{key}.name, file_path: row.{key}.file_path, repo_id: $repo_id"
                )
                if label in ("METHOD", "FIELD"):
                    identity += f", class_name: row.{key}.class_name"
                patterns.append(f"MATCH ({alias}:{label} {{{identity}}})")
            query = (
                "UNWIND $batch AS row "
                + " ".join(patterns)
                + f" MERGE (s)-[r:{edge_type}]->(t) SET r += coalesce(row.properties, {{}})"
            )
            for offset in range(0, len(rows), batch_size):
                self.run_write(
                    query, {"batch": rows[offset : offset + batch_size], "repo_id": repo_id}
                )

    def merge_module(self, name: str, file_path: str, repo_id: str = "", commit_sha: str = ""):
        self.run_write(
            """
            MERGE (m:MODULE {name: $name, file_path: $file_path, repo_id: $repo_id})
            ON CREATE SET m.commit_sha = $commit_sha
            ON MATCH SET m.commit_sha = $commit_sha
            """,
            {"name": name, "file_path": file_path, "repo_id": repo_id, "commit_sha": commit_sha},
        )

    def merge_class(
        self,
        name: str,
        file_path: str,
        signature: str,
        code: str,
        repo_id: str = "",
        commit_sha: str = "",
    ):
        self.run_write(
            """
            MERGE (c:CLASS {name: $name, file_path: $file_path, repo_id: $repo_id})
            ON CREATE SET c.signature = $signature, c.code = $code, c.commit_sha = $commit_sha
            ON MATCH SET c.signature = $signature, c.code = $code, c.commit_sha = $commit_sha
            """,
            {
                "name": name,
                "file_path": file_path,
                "signature": signature,
                "code": code,
                "repo_id": repo_id,
                "commit_sha": commit_sha,
            },
        )

    def merge_function(
        self,
        name: str,
        file_path: str,
        signature: str,
        code: str,
        repo_id: str = "",
        commit_sha: str = "",
    ):
        self.run_write(
            """
            MERGE (f:FUNCTION {name: $name, file_path: $file_path, repo_id: $repo_id})
            ON CREATE SET f.signature = $signature, f.code = $code, f.commit_sha = $commit_sha
            ON MATCH SET f.signature = $signature, f.code = $code, f.commit_sha = $commit_sha
            """,
            {
                "name": name,
                "file_path": file_path,
                "signature": signature,
                "code": code,
                "repo_id": repo_id,
                "commit_sha": commit_sha,
            },
        )

    def merge_method(
        self,
        name: str,
        file_path: str,
        class_name: str,
        signature: str,
        code: str,
        repo_id: str = "",
        commit_sha: str = "",
    ):
        self.run_write(
            """
            MERGE (m:METHOD {name: $name, class_name: $class_name, file_path: $file_path,
            repo_id: $repo_id})
            ON CREATE SET m.signature = $signature, m.code = $code, m.commit_sha = $commit_sha
            ON MATCH SET m.signature = $signature, m.code = $code, m.commit_sha = $commit_sha
            """,
            {
                "name": name,
                "file_path": file_path,
                "class_name": class_name,
                "signature": signature,
                "code": code,
                "repo_id": repo_id,
                "commit_sha": commit_sha,
            },
        )

    def merge_field(
        self, name: str, file_path: str, class_name: str, repo_id: str = "", commit_sha: str = ""
    ):
        self.run_write(
            """
            MERGE (f:FIELD {name: $name, class_name: $class_name, file_path: $file_path,
            repo_id: $repo_id})
            ON CREATE SET f.commit_sha = $commit_sha
            ON MATCH SET f.commit_sha = $commit_sha
            """,
            {
                "name": name,
                "file_path": file_path,
                "class_name": class_name,
                "repo_id": repo_id,
                "commit_sha": commit_sha,
            },
        )

    def merge_global_variable(
        self, name: str, file_path: str, code: str, repo_id: str = "", commit_sha: str = ""
    ):
        self.run_write(
            """
            MERGE (gv:GLOBAL_VARIABLE {name: $name, file_path: $file_path, repo_id: $repo_id})
            ON CREATE SET gv.code = $code, gv.commit_sha = $commit_sha
            ON MATCH SET gv.code = $code, gv.commit_sha = $commit_sha
            """,
            {
                "name": name,
                "file_path": file_path,
                "code": code,
                "repo_id": repo_id,
                "commit_sha": commit_sha,
            },
        )

    def merge_contains(
        self,
        module_name: str,
        module_file: str,
        target_name: str,
        target_file: str,
        target_label: str,
        repo_id: str = "",
    ):
        """CONTAINS: MODULE -> (CLASS | FUNCTION | GLOBAL_VARIABLE)"""
        cypher = f"""
        MATCH (m:MODULE {{name: $module_name, file_path: $module_file, repo_id: $repo_id}})
        MATCH (t:{target_label} {{name: $target_name, file_path: $target_file, repo_id: $repo_id}})
        MERGE (m)-[:CONTAINS]->(t)
        """
        self.run_write(
            cypher,
            {
                "module_name": module_name,
                "module_file": module_file,
                "target_name": target_name,
                "target_file": target_file,
                "repo_id": repo_id,
            },
        )

    def merge_has_method(
        self,
        class_name: str,
        class_file: str,
        method_name: str,
        method_file: str,
        repo_id: str = "",
    ):
        """HAS_METHOD: CLASS -> METHOD"""
        self.run_write(
            """
            MATCH (c:CLASS {name: $class_name, file_path: $class_file, repo_id: $repo_id})
            MATCH (m:METHOD {name: $method_name, class_name: $class_name, file_path:
            $method_file, repo_id: $repo_id})
            MERGE (c)-[:HAS_METHOD]->(m)
            """,
            {
                "class_name": class_name,
                "class_file": class_file,
                "method_name": method_name,
                "method_file": method_file,
                "repo_id": repo_id,
            },
        )

    def merge_has_field(
        self, class_name: str, class_file: str, field_name: str, field_file: str, repo_id: str = ""
    ):
        """HAS_FIELD: CLASS -> FIELD"""
        self.run_write(
            """
            MATCH (c:CLASS {name: $class_name, file_path: $class_file, repo_id: $repo_id})
            MATCH (f:FIELD {name: $field_name, class_name: $class_name, file_path: $field_file,
            repo_id: $repo_id})
            MERGE (c)-[:HAS_FIELD]->(f)
            """,
            {
                "class_name": class_name,
                "class_file": class_file,
                "field_name": field_name,
                "field_file": field_file,
                "repo_id": repo_id,
            },
        )

    def merge_inherits(
        self,
        child_name: str,
        child_file: str,
        parent_name: str,
        parent_file: str,
        repo_id: str = "",
    ):
        """INHERITS: CLASS -> CLASS (base class)"""
        self.run_write(
            """
            MATCH (child:CLASS {name: $child_name, file_path: $child_file, repo_id: $repo_id})
            MATCH (parent:CLASS {name: $parent_name, file_path: $parent_file, repo_id: $repo_id})
            MERGE (child)-[:INHERITS]->(parent)
            """,
            {
                "child_name": child_name,
                "child_file": child_file,
                "parent_name": parent_name,
                "parent_file": parent_file,
                "repo_id": repo_id,
            },
        )

    def merge_uses(
        self,
        source_name: str,
        source_label: str,
        source_file: str,
        target_name: str,
        target_label: str,
        target_file: str,
        source_class: Optional[str] = None,
        target_class: Optional[str] = None,
        source_association_type: Optional[str] = None,
        target_association_type: Optional[str] = None,
        repo_id: str = "",
    ):
        """USES: (FUNCTION|METHOD) -> (GLOBAL_VARIABLE|FIELD)"""
        if source_label == "METHOD":
            source_match = (
                f"MATCH (src:{source_label} "
                f"{{name: $source_name, class_name: $source_class, "
                f"file_path: $source_file, repo_id: $repo_id}})"
            )
        else:
            source_match = (
                f"MATCH (src:{source_label} "
                f"{{name: $source_name, file_path: $source_file, repo_id: $repo_id}})"
            )

        if target_label == "FIELD":
            target_match = (
                f"MATCH (tgt:{target_label} "
                f"{{name: $target_name, class_name: $target_class, "
                f"file_path: $target_file, repo_id: $repo_id}})"
            )
        else:
            target_match = (
                f"MATCH (tgt:{target_label} "
                f"{{name: $target_name, file_path: $target_file, repo_id: $repo_id}})"
            )

        cypher = f"""
        {source_match}
        {target_match}
        MERGE (src)-[r:USES]->(tgt)
        ON CREATE SET r.source_association_type = $sat, r.target_association_type = $tat
        ON MATCH SET r.source_association_type = $sat, r.target_association_type = $tat
        """
        self.run_write(
            cypher,
            {
                "source_name": source_name,
                "source_class": source_class,
                "source_file": source_file,
                "target_name": target_name,
                "target_class": target_class,
                "target_file": target_file,
                "sat": source_association_type,
                "tat": target_association_type,
                "repo_id": repo_id,
            },
        )

    def get_stats(self, repo_id: Optional[str] = None) -> dict[str, int]:
        """Return counts of each node label and relationship type, optionally scoped."""
        stats = {}
        repo_filter = " {repo_id: $repo_id}" if repo_id else ""
        params = {"repo_id": repo_id} if repo_id else {}

        for label in ["MODULE", "CLASS", "FUNCTION", "METHOD", "FIELD", "GLOBAL_VARIABLE"]:
            result = self.run_query(
                f"MATCH (n:{label}{repo_filter}) RETURN count(n) AS cnt", params
            )
            stats[label] = result[0]["cnt"] if result else 0

        for rel in ["CONTAINS", "HAS_METHOD", "HAS_FIELD", "INHERITS", "USES", "CALLS", "IMPORTS"]:
            if repo_id:
                result = self.run_query(
                    f"MATCH (a{{repo_id: $repo_id}})-[r:{rel}]->() RETURN count(r) AS cnt",
                    params,
                )
            else:
                result = self.run_query(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS cnt")
            stats[rel] = result[0]["cnt"] if result else 0
        return stats

    def list_repos(self) -> list[dict]:
        """List all distinct repo_id values in the database."""
        result = self.run_query(
            "MATCH (n:MODULE) RETURN DISTINCT n.repo_id AS repo_id, "
            "n.commit_sha AS commit_sha, count(*) AS module_count "
            "ORDER BY n.repo_id"
        )
        return result

    def format_results(self, records: list[dict[str, Any]], max_code_len: int = 500) -> str:
        """Format query results into a readable string for the Primary Agent."""
        if not records:
            return "(No results found)"

        lines = []
        for i, record in enumerate(records, 1):
            parts = []
            for key, value in record.items():
                if key in ("repo_id", "commit_sha"):
                    continue  # Skip internal fields in display
                if isinstance(value, str) and len(value) > max_code_len:
                    value = value[:max_code_len] + "... (truncated)"
                parts.append(f"  {key}: {value}")
            lines.append(f"Result {i}:\n" + "\n".join(parts))
        return "\n\n".join(lines)
