"""Decide which graph facts to retrieve and when to answer the question."""

import logging

from graph_n4j.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)


# System prompts

PRIMARY_SYSTEM_PROMPT = """You are the Primary Agent in the CodexGraph system. Your job is to help \
answer questions about a Python code repository by deciding what information to \
retrieve from a code graph database.

The graph database contains the following node and edge types:

**Nodes:** MODULE (name, file_path), CLASS (name, file_path, signature, code), \
FUNCTION (name, file_path, signature, code), METHOD (name, file_path, class_name, \
signature, code), FIELD (name, file_path, class_name), GLOBAL_VARIABLE (name, \
file_path, code)

**Edges:** CONTAINS (MODULE->CLASS/FUNCTION/GLOBAL_VARIABLE), \
HAS_METHOD (CLASS->METHOD), HAS_FIELD (CLASS->FIELD), \
INHERITS (CLASS->CLASS), USES (FUNCTION/METHOD->GLOBAL_VARIABLE/FIELD, \
with source_association_type and target_association_type)

## Your Process

Each round, you will:
1. Analyze what information you still need
2. Write natural language queries describing what to retrieve from the graph
3. Decide if you have gathered enough context to answer the question

## Output Format

You MUST respond with valid JSON in this exact format:
{{
  "analysis": "Your analysis of what information is needed and why",
  "queries": [
    "Natural language description of what to retrieve from the graph database"
  ],
  "sufficient_context": false
}}

When sufficient_context is true, include a "final_answer" field:
{{
  "analysis": "Final analysis synthesizing all gathered context",
  "queries": [],
  "sufficient_context": true,
  "final_answer": "Your comprehensive answer to the user's question"
}}

## Rules
- Each query should describe ONE specific retrieval operation
- Queries should reference specific node types, names, and relationships from the schema
- Be precise: "Find the class named X" is better than "find the relevant class"
- {query_mode_instruction}
- Use information from previous rounds to refine your queries
- Do NOT write Cypher - write natural language descriptions of what to retrieve
"""

SINGLE_QUERY_INSTRUCTION = "Generate exactly ONE query per round (best for complex reasoning tasks)"
MULTIPLE_QUERIES_INSTRUCTION = (
    "Generate up to 3 queries per round (best for gathering broad context quickly)"
)


def get_system_prompt(
    query_mode: str = "single_query",
    task_specific_instruction: str = "",
) -> str:
    """
    Build the Primary Agent's system prompt.

    Args:
        query_mode: "single_query" or "multiple_queries"
        task_specific_instruction: Additional instructions for specific tasks
            (e.g., Code Debugger, Code Generator, etc.)
    """
    instruction = (
        SINGLE_QUERY_INSTRUCTION if query_mode == "single_query" else MULTIPLE_QUERIES_INSTRUCTION
    )

    prompt = PRIMARY_SYSTEM_PROMPT.format(query_mode_instruction=instruction)

    if task_specific_instruction:
        prompt += f"\n\n## Task-Specific Instructions\n{task_specific_instruction}"

    return prompt


# Primary Agent class


class PrimaryAgent:
    """
    The Primary Agent: analyzes the user's question, generates NL graph queries,
    and synthesizes a final answer when sufficient context is gathered.
    """

    def __init__(
        self,
        groq_client: BaseLLMClient,
        query_mode: str = "single_query",
        task_instruction: str = "",
        temperature: float = 0.3,
    ):
        self.client = groq_client
        self.query_mode = query_mode
        self.temperature = temperature
        self.system_prompt = get_system_prompt(query_mode, task_instruction)

    def run(
        self,
        user_question: str,
        context_history: list[dict],
    ) -> dict:
        """
        Execute one round of the Primary Agent.

        Args:
            user_question: The original user question.
            context_history: List of prior round results:
                [{"round": 1, "queries": [...], "results": [...]}, ...]

        Returns:
            Parsed JSON dict with keys: analysis, queries, sufficient_context,
            and optionally final_answer.
        """
        messages = [{"role": "system", "content": self.system_prompt}]

        # Pair each earlier query with its result so the next round can cite its evidence.
        user_content = f"## User Question\n{user_question}\n"

        if context_history:
            user_content += "\n## Context from Previous Rounds\n"
            for entry in context_history:
                user_content += f"\n### Round {entry['round']}\n"
                for i, (query, result) in enumerate(zip(entry["queries"], entry["results"]), 1):
                    user_content += f"**Query {i}:** {query}\n"
                    user_content += f"**Result:** {result}\n\n"
        else:
            user_content += "\n(This is the first round - no prior context.)\n"

        messages.append({"role": "user", "content": user_content})

        # Some providers reject structured output. Retry in plain text and recover the object.
        try:
            response = self.client.chat_json(
                messages=messages,
                temperature=self.temperature,
            )
        except Exception:
            logger.debug("Retrying without JSON mode", exc_info=True)
            import json as _json
            import re as _re

            raw = self.client.chat(
                messages=messages,
                temperature=self.temperature,
                json_mode=False,
            )
            # Try to extract JSON from the plain text response
            try:
                response = _json.loads(raw)
            except _json.JSONDecodeError:
                match = _re.search(r"\{.*\}", raw, _re.DOTALL)
                if match:
                    try:
                        response = _json.loads(match.group(0))
                    except _json.JSONDecodeError:
                        response = {
                            "analysis": raw,
                            "queries": [],
                            "sufficient_context": True,
                            "final_answer": raw,
                        }
                else:
                    response = {
                        "analysis": raw,
                        "queries": [],
                        "sufficient_context": True,
                        "final_answer": raw,
                    }

        # Fill optional fields before the pipeline reads the response.
        if "analysis" not in response:
            response["analysis"] = ""
        if "queries" not in response:
            response["queries"] = []
        if "sufficient_context" not in response:
            response["sufficient_context"] = False

        # Enforce query mode limits
        if self.query_mode == "single_query" and len(response["queries"]) > 1:
            response["queries"] = response["queries"][:1]

        logger.info(
            "Primary Agent - round analysis: %s queries, sufficient=%s",
            len(response["queries"]),
            response["sufficient_context"],
        )

        return response
