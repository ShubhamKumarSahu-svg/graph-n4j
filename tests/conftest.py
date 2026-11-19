import os

import pytest

from graph_n4j.graph_db import GraphDB


@pytest.fixture
def db():
    uri = os.getenv("GRAPH_N4J_TEST_URI")
    if not uri:
        pytest.skip("Set GRAPH_N4J_TEST_URI for Neo4j integration tests")
    with GraphDB(uri, "neo4j", "graphn4jtest") as database:
        database.init_schema()
        yield database
