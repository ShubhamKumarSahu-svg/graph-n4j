"""
code_commenter.py — Application 5: Docstring and comment generation.

Takes a file path or function/class name, retrieves its structural context from
the graph (relationships, callers, inheritance), and generates contextually
rich docstrings and inline comments.
"""

import logging

from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

TASK_INSTRUCTION = """You are a documentation expert generating docstrings and comments for Python code.

Your goal is to:
1. Retrieve the target function/class/module and its code
2. Understand its role in the broader codebase via graph relationships
3. Generate comprehensive docstrings and inline comments informed by structural context

When gathering context, query for:
- The target's full source code
- Its module and containing structure
- Inheritance chains (for classes)
- Methods and fields (for classes)
- What global variables or fields it uses
- What other components reference or inherit from it

Your final answer MUST include:
- **Context Summary**: How this component fits in the broader codebase
- **Documented Code**: The full code with added/improved docstrings and comments
  in a ```python ... ``` block

Docstring guidelines:
- Use Google-style or NumPy-style docstrings consistently
- Include: Summary line, detailed description, Args, Returns, Raises, Examples
- For classes: document the class purpose, inheritance context, and key attributes
- For methods: document parameters, return values, side effects, and interactions
- Add inline comments for non-obvious logic, referencing related components
- Note any design patterns being used (e.g., Template Method, Strategy)
"""


class CodeCommenter:
    """Contextual docstring and comment generation using graph-based understanding."""

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

    def comment(self, target: str) -> PipelineResult:
        """
        Generate docstrings and comments for a code target.

        Args:
            target: Function name, class name, or file path to document.

        Returns:
            PipelineResult with documented code and context summary.
        """
        question = (
            f"Generate comprehensive docstrings and comments for: {target}\n"
            f"First retrieve the implementation of '{target}', its relationships "
            f"(inheritance, methods, fields, usage), and structural context. "
            f"Then generate thorough documentation."
        )
        logger.info("CodeCommenter — target: '%s'", target)
        return self.pipeline.run(question)
