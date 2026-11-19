# Faculty seminar demo

Run the program from this folder with `python checkout.py`. It prints **95**. Change `return total - 5` to `return total - 10` in rates.py and run the program again. It prints **90**.

To present the graph lookup live, configure graph-n4j 1.1.0 with a local Neo4j database and run the following from this folder before editing the file. Use a new demonstration repository ID if your database already contains a repository named faculty.

```sh
graph-n4j index . --repo-id faculty
graph-n4j cypher "MATCH (q:FUNCTION {repo_id: 'faculty', name: 'quote'})-[:CALLS]->(f) RETURN f.name AS callee, f.file_path AS file"
```

The query returns discount in rates.py. Repeat the index and query after the edit. The target stays the same because the changed line affects the arithmetic inside discount. The executable program supplies the before-and-after output; the static graph supplies the callee identity.

[Recorded observations](faculty-results.json) include the initial, unchanged and edited states for both releases, plus three additional Click trials per release. The Click trials use the source selection and database worker from the [release benchmark](../../benchmarks/). Each version used its own local Neo4j 5.26.33 container. Each worker process indexed an empty repository graph and then repeated the index without changing the files. Trial order was old/new, new/old and old/new. The paper reports these follow-up trials separately from the original six-repository run.

