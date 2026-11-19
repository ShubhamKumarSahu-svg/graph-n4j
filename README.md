# graph-n4j

Index Python, C and C++ repositories in Neo4j, then ask questions about their symbols, source and relationships. The query pipeline follows the two-agent approach described in *CodexGraph: Bridging Large Language Models and Code Repositories via Code Graph Databases*.

## How indexing works

The indexer selects source files, hashes their contents and parses changed files with Tree-sitter. It stores the extracted symbols and reference sites on the module node so a later run can reuse them. On Windows and Unix, repository-relative graph paths use forward slashes.

The linker looks up imports, owners and names across the selected files. It emits a call edge when it can resolve a reference to one symbol identity. Dynamic dispatch and ambiguous names can leave gaps. The writer groups records by label and relationship type and sends batches to Neo4j. Reindexing also refreshes dependents of changed files.

| Graph records | Types |
| --- | --- |
| Symbols | MODULE, CLASS, FUNCTION, METHOD, FIELD, GLOBAL_VARIABLE |
| Relationships | CONTAINS, HAS_METHOD, HAS_FIELD, INHERITS, USES, CALLS, IMPORTS |

## Release comparison

The [benchmark report](https://github.com/ShubhamKumarSahu-svg/graph-n4j/blob/main/presentation/report.md) compares the published Python AST indexer in 0.1.8 with 1.1.0 on pinned sources from Click, Black, cJSON, curl, tinyxml2 and fmt. It includes the exact inputs, indexing and repeat-run times, database writes and graph counts.

## Quickstart

### 1. Install

```bash
pip install graph-n4j
```

### 2. Start Neo4j

```bash
docker run -d --name graph-n4j-db \
  -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/graphn4jtest \
  neo4j:5-community
```

### 3. Configure

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=graphn4jtest
export GROQ_API_KEY="gsk_your_key"        # or OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

### 4. Index & Ask

```bash
graph-n4j index-github bottlepy/bottle --stats
graph-n4j ask "How does routing work?" --repo-id bottlepy/bottle --provider groq
```

---

## CLI Reference

```bash
graph-n4j index ./project --repo-id org/project --stats
graph-n4j index-github jarro2783/cxxopts --stats
graph-n4j ask "Explain Option parsing" --provider openai
graph-n4j cypher "MATCH (c:CLASS) RETURN c.name LIMIT 10"
graph-n4j stats --repo-id bottlepy/bottle                    # graph statistics
graph-n4j repos                                              # list indexed repos
```

## Python API

```python
from graph_n4j import GraphN4J

with GraphN4J.from_env(provider="groq") as g:
    g.index_github("bottlepy/bottle")
    result = g.ask("Where is authentication handled?", repo_id="bottlepy/bottle")
    print(result.answer)
```

---

## Model providers

Use the provider flag on the ask command. Groq, OpenAI, Anthropic and Gemini read their respective API keys from the environment. Ollama connects to a local server and accepts an OLLAMA_HOST override. Indexing requires a running Neo4j instance. The client opens a model connection on the first question.

## Coding applications

CodeChat answers questions, CodeCommenter drafts documentation, CodeDebugger proposes fixes, CodeGenerator drafts features and CodeUnitTester drafts tests. Each passes a task-specific instruction to the retrieval pipeline. Review the returned answer or code before applying it.

## Development

Install the project with its dev extras and run pytest. Set GRAPH_N4J_TEST_URI to a disposable Neo4j service for the database integration tests. The benchmark runner and reproduction instructions are in the [benchmarks directory](https://github.com/ShubhamKumarSahu-svg/graph-n4j/tree/main/benchmarks).
