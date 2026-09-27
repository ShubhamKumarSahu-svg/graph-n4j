"""
code_chat.py -- Application 1: Free-form Q&A over an indexed repository.

The simplest application -- takes any natural language question about the codebase
and uses the dual-agent pipeline to retrieve relevant context and answer it.
"""

import logging

from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

TASK_INSTRUCTION = """You are answering a free-form question about a Python codebase.

Your goal is to thoroughly explore the code graph to find all relevant information,
then provide a clear, detailed answer with references to specific files, classes,
functions, and code snippets.

When answering:
- Reference specific file paths, class names, and function signatures
- Include relevant code snippets when they help explain the answer
- Explain relationships between components (inheritance, usage, etc.)
- If the answer involves multiple files or classes, explain how they connect
"""


class CodeChat:
    """Free-form Q&A over an indexed code repository."""

    def __init__(
        self,
        groq_client: GroqClient,
        graph_db: GraphDB,
        max_rounds: int = 5,
        query_mode: str = "single_query",
        **pipeline_kwargs,
    ):
        self.pipeline = CodexGraphPipeline(
            groq_client=groq_client,
            graph_db=graph_db,
            max_rounds=max_rounds,
            query_mode=query_mode,
            task_instruction=TASK_INSTRUCTION,
            **pipeline_kwargs,
        )

    def ask(self, question: str) -> PipelineResult:
        """
        Ask a question about the codebase.

        Args:
            question: Any natural language question about the indexed repo.

        Returns:
            PipelineResult with the answer and retrieval stats.
        """
        logger.info("CodeChat -- question: '%s'", question[:100])
        return self.pipeline.run(question)
