# Reproduce the indexing comparison

Run from the project root with Python 3.10 or later, the development dependencies and Git installed. The checked-in run used Python 3.12 and Neo4j 5.26.33. The exact interpreter version, file lists, byte counts, commit hashes and raw measurements are in [results.json](results.json).

Start a fresh disposable Neo4j service on a loopback port. The runner installs each release's schema, including constraint migrations, and clears its own repository graph after each case. Use a separate container for each complete run.

```sh
docker run --rm -d --name graph-n4j-compare -p 127.0.0.1:17687:7687 -e NEO4J_AUTH=none neo4j:5.26.33-community
python -m pip install -e ".[dev]"
python -m pip download --no-deps --only-binary=:all: graph-n4j==0.1.8 -d .cache
python benchmarks/compare.py --wheel .cache/graph_n4j-0.1.8-py3-none-any.whl --disposable-uri bolt://localhost:17687 --output benchmarks/results.json
python -m pip install matplotlib
python benchmarks/report.py benchmarks/results.json presentation
docker stop graph-n4j-compare
```

Wait for Bolt to accept connections before starting the runner. A wheel checksum check prevents accidental comparisons with a different distribution. Each worker imports one package version in a new interpreter. A separate checkout supplies each repository's pinned source files. The runner copies only the listed paths into a temporary tree so test suites and build tools cannot change the language mix.

The indexing timer includes parsing, linking and writing to a running database. The second pass indexes identical content under the same commit. Graph counts come from database queries after that pass. Unsupported source languages have no timing. Schema creation, cloning, initializing an LLM, building a query prompt and end-user answer quality fall outside this timer.

## Check application behavior

Run `python -m pytest tests`. Set `GRAPH_N4J_TEST_URI` to your disposable Bolt URL to include integration tests. The suite covers parser and linker behavior, batching, isolation, edits and deletions, source discovery, full-text retrieval and application entry points. Provider checks use synthetic responses. The tests use the username neo4j and password graphn4jtest when authentication is enabled.
