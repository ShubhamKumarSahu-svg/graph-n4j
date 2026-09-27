"""
translation_agent.py — The Translation Agent in CodexGraph's dual-agent architecture.

Per Section 3.2 ("write then translate" strategy), the Translation Agent:
  - Receives the full graph schema + a natural language query from the Primary Agent
  - Outputs a syntactically valid Cypher query
  - Uses temperature=0.0 for deterministic translations
  - The system prompt embeds the full schema so the model translates reliably
"""

import logging

from graph_n4j.llm.groq_client import GroqClient
from graph_n4j.schema import SCHEMA_DESCRIPTION

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# System prompt
# ═══════════════════════════════════════════

TRANSLATION_SYSTEM_PROMPT = f"""You are the Translation Agent in the CodexGraph system. Your ONLY job \
is to translate natural language queries about a code repository into valid Cypher \
queries for Neo4j.

{SCHEMA_DESCRIPTION}

## Rules

1. Output ONLY the Cypher query — no explanations, no markdown fences, no comments.
2. Use MATCH patterns that align with the schema above.
3. Always use parameterized property matching where possible.
4. Return useful properties in your RETURN clause (name, file_path, signature, code).
5. Use OPTIONAL MATCH when a relationship might not exist.
6. Limit results to 20 rows unless the query implies exhaustive retrieval.
7. For inheritance chains, use variable-length paths: `-[:INHERITS*]->`.
8. When searching by name, use case-sensitive exact match by default.
9. If the query mentions "all methods" or "all fields" of a class, include inherited ones via INHERITS edges.
10. Always include RETURN — never write a query that only MATCHes without returning.

## Examples

Query: "Find the class named Shape and its methods"
MATCH (c:CLASS {{name: 'Shape'}})-[:HAS_METHOD]->(m:METHOD) RETURN c.name, c.file_path, c.signature, m.name, m.signature, m.code

Query: "Find all classes that inherit from Shape"
MATCH (c:CLASS)-[:INHERITS]->(base:CLASS {{name: 'Shape'}}) RETURN c.name, c.file_path, c.signature

Query: "Find the module containing the function calculate_area"
MATCH (m:MODULE)-[:CONTAINS]->(f:FUNCTION {{name: 'calculate_area'}}) RETURN m.name, m.file_path, f.signature

Query: "Find all global variables used by the function process_data"
MATCH (f:FUNCTION {{name: 'process_data'}})-[:USES]->(gv:GLOBAL_VARIABLE) RETURN gv.name, gv.file_path, gv.code

Query: "Find the complete inheritance chain for class Circle"
MATCH (c:CLASS {{name: 'Circle'}})-[:INHERITS*]->(parent:CLASS) RETURN parent.name, parent.file_path, parent.signature
"""


class TranslationAgent:
    """
    The Translation Agent: converts natural language graph queries into Cypher.
    Uses temperature=0.0 for deterministic output.

    B5: Supports a separate model_override so you can run a cheaper model
    for translation while keeping the Primary Agent on the strong model.
    Configure via GROQ_MODEL_TRANSLATION env var or pass model_override=.
    """

    def __init__(self, groq_client: GroqClient, model_override: str | None = None):
        self.client = groq_client
        self.model_override = model_override

    def translate(self, nl_query: str) -> str:
        """
        Translate a natural language query into a Cypher query.

        Args:
            nl_query: Natural language description of what to retrieve.

        Returns:
            A Cypher query string (fences stripped).
        """
        messages = [
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": nl_query},
        ]

        cypher = self.client.chat_cypher(
            messages=messages,
            temperature=0.0,
            max_tokens=2048,
            model_override=self.model_override,
        )

        logger.info("Translation Agent -- NL: '%s' -> Cypher: '%s'", nl_query[:80], cypher[:80])
        return cypher
