from unittest.mock import Mock

import pytest

from graph_n4j.apps.code_chat import CodeChat
from graph_n4j.apps.code_commenter import CodeCommenter
from graph_n4j.apps.code_debugger import CodeDebugger
from graph_n4j.apps.code_generator import CodeGenerator
from graph_n4j.apps.code_unittester import CodeUnitTester
from graph_n4j.cache import QueryCache
from graph_n4j.llm.base import TokenUsage


@pytest.mark.parametrize(
    "app,method",
    [
        (CodeChat, "ask"),
        (CodeCommenter, "comment"),
        (CodeDebugger, "debug"),
        (CodeGenerator, "generate"),
        (CodeUnitTester, "generate_tests"),
    ],
)
def test_app_retrieves_before_answering(app, method, db, tmp_path):
    # Script only the model replies. Translation, query execution, result formatting
    # and the second round all go through the application's public entry point.
    client = Mock()
    client.usage = TokenUsage()
    client.chat_json.side_effect = [
        {"queries": ["Find the selected repo"], "sufficient_context": False},
        {"final_answer": "Found the repository", "sufficient_context": True},
    ]
    client.chat_cypher.return_value = "RETURN $repo_id AS name"
    cache = QueryCache(cache_dir=str(tmp_path))
    instance = app(client, db, repo_id="app-fixture", query_cache=cache, include_skeleton=False)
    result = getattr(instance, method)("Find the selected repo")
    assert result.answer == "Found the repository"
    assert result.neo4j_roundtrips == 1 and result.rounds_used == 2
    assert "app-fixture" in result.context_history[0]["results"][0]
    assert not result.errors
