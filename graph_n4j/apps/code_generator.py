"""
code_generator.py — Application 4: Feature-driven code generation.

Takes a feature request, explores the existing codebase via graph queries to
understand relevant patterns and structures, then generates new code that
integrates with the existing architecture.
"""

import logging

from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

TASK_INSTRUCTION = """You are a code generator creating new code for a Python codebase.

Your goal is to:
1. Understand the feature request
2. Query the graph to discover relevant existing classes, patterns, and conventions
3. Understand the inheritance hierarchy and module structure
4. Generate new code that integrates naturally with the existing architecture

When gathering context, query for:
- Existing classes/functions related to the feature domain
- The module structure and where new code should be placed
- Inheritance patterns to determine if the new code should extend existing classes
- Conventions used in the codebase (naming, patterns, etc.)
- Fields and methods that the new code might need to interact with

Your final answer MUST include:
- **Design Rationale**: Why you chose this approach and how it fits the existing code
- **New Code**: Complete, well-documented Python code in ```python ... ``` blocks
- **Integration Notes**: Where to place the code and how it connects to existing components

Guidelines:
- Follow the codebase's existing patterns and conventions
- Use proper type hints and docstrings
- Extend existing base classes when appropriate
- Reference specific existing components by name
"""


class CodeGenerator:
    """Feature-driven code generation using graph-based codebase understanding."""

    def __init__(
        self,
        groq_client: GroqClient,
        graph_db: GraphDB,
        max_rounds: int = 5,
        query_mode: str = "multiple_queries",
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

    def generate(self, feature_request: str) -> PipelineResult:
        """
        Generate code for a feature request.

        Args:
            feature_request: Description of the feature to implement.

        Returns:
            PipelineResult with generated code and integration instructions.
        """
        logger.info("CodeGenerator — feature: '%s'", feature_request[:100])
        return self.pipeline.run(feature_request)
