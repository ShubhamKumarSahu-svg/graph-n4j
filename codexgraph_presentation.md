---
marp: true
theme: default
class: lead
backgroundColor: #fff
backgroundImage: url('https://marp.app/assets/hero-background.svg')
style: |
  section {
    font-family: 'Inter', sans-serif;
  }
  h1 {
    color: #0b2e59;
  }
  h2 {
    color: #1d4e89;
  }
---

# CODEXGRAPH
## Bridging Large Language Models and Code Repositories via Code Graph Databases
**Xiangyan Liu, Bo Lan, Zhiyuan Hu, Yang Liu, Zhicheng Zhang, Fei Wang, Michael Shieh, Wenmeng Zhou**
*(NAACL 2025)*

---

# 1. Introduction
- **The Rise of LLMs**: LLMs excel in stand-alone code tasks (e.g., HumanEval, MBPP).
- **The Challenge**: They struggle with **repository-level** tasks involving large, complex codebases due to context length limits and intricate dependencies.
- **The Solution**: **CODEXGRAPH** - A system that integrates LLM agents with graph database interfaces extracted from code repositories.

---

# 2. Motivation
- Real-world software engineering requires understanding cross-file code structures and multi-hop reasoning.
- Feeding entire codebases into LLMs is impossible due to context window constraints.
- We need a way to **retrieve** only the relevant code structures precisely when the LLM needs them.

---

# 3. Literature Review
## Paradigm 1: Similarity-based Retrieval
- E.g., BM25, Dense Retrievers.
- **Pros**: Easy to implement.
- **Cons**: Limited to surface-level matching; fails at complex reasoning and understanding structural dependencies.

---

# 4. Literature Review
## Paradigm 2: Manual Tools and APIs
- E.g., AutoCodeRover, Moatless Tools.
- **Pros**: Highly optimized for specific tasks (like SWE-bench).
- **Cons**: Requires expert knowledge; lacks flexibility and generalizability across diverse coding tasks.

---

# 5. Research Gap
- Similarity retrieval lacks structural awareness and reasoning.
- Tool-based methods are brittle and task-specific.
- **The Gap**: We need a flexible, task-agnostic interface that structurally represents code repositories and allows LLMs to perform multi-hop, context-aware reasoning.

---

# 6. Problem Statement
**How can we empower LLMs to seamlessly navigate, query, and reason over entire code repositories without relying on task-specific heuristics or fragile similarity searches?**

---

# 7. Proposed Framework: CODEXGRAPH
- **Core Idea**: Use **Graph Databases** (like Neo4j) as the interface between the LLM and the code repository.
- Code symbols (classes, methods, variables) become **Nodes**.
- Relationships (inheritance, usage, containment) become **Edges**.
- LLMs query this graph dynamically using graph query languages (Cypher).

---

# 8. Graph Database Schema
- **Nodes**: `MODULE`, `CLASS`, `METHOD`, `FUNCTION`, `FIELD`, `GLOBAL_VARIABLE`.
- **Node Attributes**: Name, file path, signature, and a pointer to the code snippet.
- **Edges**: `CONTAINS`, `INHERITS`, `HAS_METHOD`, `HAS_FIELD`, `USES`.
- *Code is indexed by reference to ensure efficient storage and multi-granularity searches.*

---

# 9. Phase 1: Shallow Indexing
- A single-pass static analysis scan of the repository.
- Extracts symbols and relationships from each Python file.
- Captures nodes and their meta-information quickly and efficiently.
- *Limitation*: May miss complex cross-file relationships like deep inheritance.

---

# 10. Phase 2: Edge Completion
- Addresses limitations of shallow indexing using Depth-First Search (DFS) on the Abstract Syntax Tree (AST).
- Resolves Python's re-export issues and relative imports.
- Establishes accurate cross-file `CONTAINS` and `INHERITS` relationships.
- Results in a comprehensive, topologically accurate code graph.

---

# 11. LLM Interaction: Code Structure-Aware Search
- LLMs construct complex queries (e.g., *"Find classes under module X containing method Y"*).
- Achieves precise, structure-aware retrieval impossible with standard BM25 or Dense Retrievers.
- Prevents hallucination by firmly grounding the LLM in the actual repository architecture.

---

# 12. "Write then Translate" Strategy
- Directly generating complex Cypher queries is syntactically demanding for LLMs.
- **CODEXGRAPH Solution**:
  1. **Primary Agent**: Analyzes the problem and outputs a Natural Language Query.
  2. **Translation Agent**: Translates the NL query into a strictly formatted, executable Cypher query.
- *Benefits*: Eases the reasoning load and minimizes syntax errors.

---

# 13. Iterative Pipeline
- Code tasks are rarely solved in a single step.
- CODEXGRAPH uses an **Iterative Pipeline**:
  - The LLM agent formulates queries based on current knowledge.
  - Analyzes retrieved graph data.
  - Decides if it has sufficient context or if it needs to execute further queries.

---

# 14. Experimental Setup
- **Benchmarks**: 
  - *CrossCodeEval* (Code Completion)
  - *SWE-bench* (GitHub Issue Resolution)
  - *EvoCodeBench* (Evolutionary Code Generation)
- **Baselines**: BM25, AutoCodeRover, No-RAG.
- **LLMs Evaluated**: GPT-4o, DeepSeek-Coder-V2, Qwen2-72b-Instruct.

---

# 15. Results: Superior Performance
- **CrossCodeEval**: CODEXGRAPH outperforms AutoCodeRover (27.90 vs 21.20 Exact Match with GPT-4o).
- **SWE-bench**: CODEXGRAPH matches highly-specialized AutoCodeRover (22.96% Pass@1).
- **EvoCodeBench**: CODEXGRAPH excels in Recall@1 (11.87 vs 11.17).
- *Takeaway*: CODEXGRAPH adapts effectively to varied tasks using a universal schema.

---

# 16. Results: The Importance of Edges
- **Ablation Study**: Removing edge information (relying only on node attributes) causes GPT-4o performance to plummet from **27.90% to 16.40%**.
- This proves that structural relationships (edges) are critical for deep repository understanding.

---

# 17. Results: The Translation Agent
- **Ablation Study**: Removing the Translation Agent and forcing the Primary Agent to write Cypher directly drops performance from **27.90% to 8.30%**.
- The "Write then Translate" dual-agent architecture is vital for robust query execution.

---

# 18. Real-World Applications
CODEXGRAPH isn't just for academic benchmarks. It powers 5 real-world agents:
1. **Code Chat**: Ask questions about the repo architecture.
2. **Code Debugger**: Diagnose and resolve complex bugs.
3. **Code Unittestor**: Generate context-aware tests.
4. **Code Generator**: Implement new features.
5. **Code Commentor**: Enhance documentation accurately.

---

# 19. Introducing `graph-n4j`: The Package
- **From Paper to Product**: We transformed the CodexGraph research into a fully-fledged, installable Python library (`pip install graph-n4j`).
- **Developer Experience First**: 
  - Zero-friction setup with automated `.env` loading and `.gitignore` defaults.
  - A comprehensive CLI tool designed for speed and ease of use.
  - Built-in `view` commands to instantly visualize your code graph in the browser.

---

# 20. How `graph-n4j` Differs from the Paper
While the paper laid the theoretical groundwork, our package brings practical engineering:
1. **Dynamic Model Selection**: The paper assumed fixed models; we introduced a `--model` flag to dynamically swap out LLMs (e.g., Llama-3, Qwen) on the fly without breaking the workflow.
2. **Robust Pathing & Environment**: Solved complex execution context bugs and BOM encoding issues native to Windows and Git Bash, ensuring cross-platform stability.
3. **Optimized Queries**: Shipped with pre-baked, browser-safe visual Cypher queries to prevent massive codebases from crashing developer tools.

---

# 21. Future Roadmap: Core Advancements
To push `graph-n4j` to enterprise-grade scalability, we are targeting three major architectural upgrades:

1. **Tree-sitter instead of AST**: Moving away from standard Python AST parsing to `tree-sitter`. This unlocks multi-language support (Java, C++, TS, Rust) and provides far superior resilience against broken or incomplete code.
2. **Universal LLM APIs**: Expanding beyond Groq to support OpenAI, Anthropic, Gemini, and local LLMs (Ollama) natively.

---

# 22. Future Roadmap: Incremental Indexing
*(Solving the 5-Hour Indexing Problem)*

3. **Content-Hash-Based Incremental Indexing**:
   - Hash each file's contents (e.g., XXH3 or SHA1).
   - On re-index, skip unchanged files entirely.
   - Only re-run extraction and edge resolution for files whose hash changed, **plus** files that import the changed file (dependency-aware invalidation).
   - *Impact*: Turns "5 hours for the whole repo" into **"milliseconds for a one-file commit."**

---

# 23. Conclusion
- CODEXGRAPH and `graph-n4j` successfully bridge LLMs and code repositories using Graph Databases.
- It provides a flexible, task-agnostic, structure-aware retrieval system.
- Outperforms or matches task-specific tools across diverse benchmarks, proving its generalizability and real-world viability.

---
<!-- class: lead -->
# Thank You
**Install now via:** `pip install graph-n4j`
