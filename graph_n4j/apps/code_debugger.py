"""
code_debugger.py — Application 2: Root-cause analysis + unified diff patch.

Takes a bug report or issue description, uses the graph to trace through relevant
code paths, identifies the likely root cause, and generates a unified diff patch.
"""

import logging

from graph_n4j.agents.pipeline import CodexGraphPipeline, PipelineResult
from graph_n4j.graph_db import GraphDB
from graph_n4j.llm.groq_client import GroqClient

logger = logging.getLogger(__name__)

TASK_INSTRUCTION = """You are a code debugger analyzing a bug report against a Python codebase.

Your goal is to:
1. Understand the bug report / issue description
2. Query the graph to find relevant classes, functions, and their relationships
3. Trace the likely execution path that triggers the bug
4. Identify the root cause
5. Generate a fix as a unified diff patch

When gathering context, focus on:
- The classes/functions mentioned in the bug report
- Their inheritance chains and method overrides
- Global variables or fields they access
- Related modules and their dependencies

Your final answer MUST include:
- **Root Cause Analysis**: What's causing the bug and why
- **Affected Components**: List of files, classes, and functions involved
- **Suggested Fix**: A unified diff patch (```diff ... ```) showing the change

Format the diff as:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -line,count +line,count @@
 context
-old line
+new line
 context
```
"""


class CodeDebugger:
    """Bug analysis and patch generation using graph-based code understanding."""

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

    def debug(self, bug_report: str) -> PipelineResult:
        """
        Analyze a bug report and generate a fix.

        Args:
            bug_report: Description of the bug, error message, or issue text.

        Returns:
            PipelineResult with root-cause analysis and diff patch.
        """
        logger.info("CodeDebugger — bug report: '%s'", bug_report[:100])
        return self.pipeline.run(bug_report)
