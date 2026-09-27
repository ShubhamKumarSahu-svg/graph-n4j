"""
code_unittester.py — Application 3: Automated unit test generation.

Takes a class or function name, retrieves its full context (methods, inheritance,
fields, dependencies) from the graph, and generates comprehensive test code.
"""

import logging

from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

TASK_INSTRUCTION = """You are a test engineer generating unit tests for a Python codebase.

Your goal is to:
1. Retrieve the target class/function and its full implementation
2. Understand its dependencies: base classes, methods, fields, global variables
3. Identify edge cases and important behaviors to test
4. Generate comprehensive pytest test code

When gathering context, query for:
- The target class/function's code and signature
- Its inheritance chain (base classes and their methods)
- Fields and global variables it uses
- Related functions/classes it interacts with
- Any existing test patterns in the repository

Your final answer MUST include:
- **Test Strategy**: What aspects you're testing and why
- **Test Code**: Complete, runnable pytest code in a ```python ... ``` block
- **Coverage Notes**: What edge cases and scenarios are covered

Guidelines for test generation:
- Use pytest fixtures and parametrize where appropriate
- Test both happy paths and error cases
- Mock external dependencies when needed
- Include docstrings explaining what each test verifies
- Follow the Arrange-Act-Assert pattern
"""


class CodeUnitTester:
    """Automated unit test generation using graph-based code understanding."""

    def __init__(
        self,
        groq_client: GroqClient,
        graph_db: GraphDB,
        max_rounds: int = 5,
        query_mode: str = "multiple_queries",  # broader context helps for tests
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

    def generate_tests(self, target: str) -> PipelineResult:
        """
        Generate unit tests for a class or function.

        Args:
            target: Name of the class or function to test, e.g. "Circle" or "calculate_area".

        Returns:
            PipelineResult with test code and strategy explanation.
        """
        question = (
            f"Generate comprehensive unit tests for: {target}\n"
            f"First retrieve the implementation of '{target}', its dependencies, "
            f"inheritance chain, and any related components. Then generate pytest tests."
        )
        logger.info("CodeUnitTester — target: '%s'", target)
        return self.pipeline.run(question)
