# Inside graph-n4j 1.1.0: from source code to queryable links

**Aditya Anil Halwai (IIT2024214) / Kushal Khatri (IIT2024129) / Shubham Kumar Sahu (IIT2024209)**

## The indexing path, in plain language

Version 0.1.8 reads Python with Python's built-in Abstract Syntax Tree (AST). It records code items first, then makes a second pass to resolve and write relationships. It supports Python only and parses files again on an unchanged run.

Version 1.1.0 checks a SHA-256 fingerprint of each file. If the bytes, extractor version and saved records match, it restores the extraction. Otherwise, it uses a Tree-sitter grammar for Python, C or C++. The parser returns symbols and unresolved references in a shared format. A linker matches names across files. A Neo4j writer sends the resulting nodes and edges in batches.

Tree-sitter can update a syntax tree when given an edit. graph-n4j does not use that API. It reparses the whole file when the file changes. Its cache avoids re-parsing unchanged files, but the linker still checks current dependencies and relationships.

```text
file bytes -> SHA-256 check -> Tree-sitter parse or restore saved records
           -> link names across files -> batch graph updates in Neo4j
```

For a small example, checkout.py imports discount from rates.py. The parser first records that quote calls a name spelled discount. The import points to the target file. The linker finds the matching function and stores a CALLS edge. Version 0.1.8 did not store this cross-file call as a CALLS relationship.

Tree-sitter represents the call as a syntax tree. The visitor reads the function name and argument from that structure:

```scheme
(call
  function: (identifier) ; discount
  arguments: (argument_list
    (identifier)))       ; total
```

Cypher follows the resulting graph relationship:

```cypher
MATCH (q:FUNCTION {repo_id: $repo, name: 'quote'})-[:CALLS]->(f)
RETURN f.name AS callee, f.file_path AS file
```

On Click, both releases recover the inheritance edge from Group to MultiCommand. The new indexer also stores calls and imports, and reuses the parse of every unchanged file on the second run.

## Inputs and method

Python 3.12.12 on Windows-11-10.0.26300-SP0 with Neo4j 5.26.33. Each case ran in its own Python process. Both releases saw the same selected library sources. Each supported case started with an empty repository graph and immediately repeated the index. Setup, cloning, schema creation and graph inspection are outside the timer. Schema and database server caches could be warm.

The benchmark calls the two indexing stages from the published 0.1.8 wheel and the candidate UnifiedIndexer. It supplies the same repository and commit identifiers to both writers. Version 0.1.8 accepts Python files only. Unsupported inputs are excluded from its timing series. The corpus comprises production source selections, including the TLS component of curl. Each time is one observation. No memory, energy, model latency or token savings were measured.

| Source snapshot | Selection | Files | Source KiB |
| --- | --- | ---: | ---: |
| pallets/click @ 8.1.8 | src/click | 16 | 351.7 |
| psf/black @ 24.10.0 | src/black | 25 | 431.0 |
| DaveGamble/cJSON @ v1.7.18 | cJSON and utilities | 4 | 141.3 |
| curl/curl @ curl-8_10_1 | lib/vtls | 31 | 838.0 |
| leethomason/tinyxml2 @ 10.0.0 | tinyxml2.cpp and header | 2 | 149.9 |
| fmtlib/fmt @ 11.0.2 | include/fmt and src/*.cc | 17 | 599.1 |

## Measured results

| Input | Version | First (s) | Repeat (s) | Writes, first / repeat | Files reused | Nodes | Edges |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Click | 0.1.8 | 29.20 | 23.44 | 3,335 / 3,335 | 0 | 862 | 1,552 |
| Click | 1.1.0 | 6.39 | 0.18 | 26 / 1 | 16 | 913 | 3,097 |
| Black | 0.1.8 | 22.79 | 12.18 | 2,264 / 2,264 | 0 | 712 | 1,160 |
| Black | 1.1.0 | 1.99 | 0.14 | 22 / 1 | 25 | 734 | 1,665 |
| cJSON | 0.1.8 | Unsupported | — | — | — | — | — |
| cJSON | 1.1.0 | 0.84 | 0.08 | 17 / 1 | 4 | 187 | 493 |
| curl TLS | 0.1.8 | Unsupported | — | — | — | — | — |
| curl TLS | 1.1.0 | 2.59 | 0.16 | 25 / 1 | 31 | 1,161 | 2,451 |
| tinyxml2 | 0.1.8 | Unsupported | — | — | — | — | — |
| tinyxml2 | 1.1.0 | 0.83 | 0.04 | 20 / 1 | 2 | 479 | 685 |
| fmt | 0.1.8 | Unsupported | — | — | — | — | — |
| fmt | 1.1.0 | 3.19 | 0.13 | 26 / 1 | 17 | 1,997 | 3,459 |

The light-blue series is 0.1.8 and the dark-blue series is 1.1.0. A write is one call to the Neo4j write helper. The final counts come from queries against stored records after the unchanged rerun.

![First-index comparison in seconds](economist-figures/first-index.png)

![Write-helper calls](economist-figures/write-calls.png)

![Unchanged-index time](economist-figures/repeat-index.png)

## Following Click through both indexers

In Click 8.1.8, core.py defines Group(MultiCommand). The original shallow pass uses Python ast to record Group and its base name. Edge completion looks up MultiCommand, writes each node and relationship with MERGE, and re-reads source when resolving uses. Both live graphs returned MultiCommand for Group in src/click/core.py.

The new parser records the class, its source span and the unresolved base reference together. The linker resolves that name against the repository symbol table. The writer groups the class with other classes and its inheritance edge with other edges of that type. The next index checks the file hash and extractor version, reloads cached records, relinks and updates the commit stamp. On Click it reused 16 files.

Click has 38 INHERITS edges in the baseline and 38 in the candidate. Version 1.1.0 also stores 301 CALLS and 58 IMPORTS edges. It stores 913 nodes versus 862. Counts describe what was indexed. The Group check validates one specific relationship. Neither result establishes recall or precision across the corpus.

## Release checks and limitations

The integration suite covers edits and deletions, cache reuse, cross-repository isolation, full-text lookup, C header lookup and C++ calls. Four HTTP provider adapters are tested with recorded-format synthetic responses. The five coding apps exercise two retrieval rounds with scripted model replies and a live database. These checks do not score generated answers or test hosted services.

Version 1.0.0 skipped .c files. The candidate registers the C grammar for .c and keeps the C++ grammar for .h. Both use the same graph vocabulary. For example, the cJSON result includes CLASS and METHOD labels for native declarations. Use source spans to check classifications. Static name resolution can miss dynamic targets, and a larger graph can contain extra or duplicate concepts.

See the [runner and exact file manifests](../benchmarks/) to reproduce this run.
