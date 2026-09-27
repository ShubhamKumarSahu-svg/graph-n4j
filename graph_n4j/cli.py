"""
cli.py — Command-line interface for graph-n4j.

Entry point for the `graph-n4j` command installed by pip.

Commands:
    graph-n4j index <path>                    Index a local Python repo
    graph-n4j index-github <url>              Clone + index a GitHub repo
    graph-n4j ask "<question>"                Ask a question about the indexed repo
    graph-n4j stats                           Show graph statistics
    graph-n4j repos                           List indexed repos
    graph-n4j clear <repo_id>                 Clear data for a repo
    graph-n4j cypher "<query>"                Run a raw Cypher query
"""

import argparse
import json
import logging
import sys

from dotenv import load_dotenv, find_dotenv


def main():
    load_dotenv(find_dotenv(usecwd=True), override=True, encoding="utf-8-sig")

    parser = argparse.ArgumentParser(
        prog="graph-n4j",
        description="Bridge LLM agents with code repositories via Neo4j graph databases.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "-m", "--model", help="Override the Groq LLM model to use (e.g. llama-3.3-70b-versatile)",
    )
    
    from graph_n4j import __version__
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── index ─────────────────────────────────────────────
    p_index = subparsers.add_parser("index", help="Index a local Python repository")
    p_index.add_argument("repo_path", help="Path to the Python repository")
    p_index.add_argument("--repo-id", help="Override the repo identifier")
    p_index.add_argument("--clear", action="store_true", help="Clear existing data before indexing")
    p_index.add_argument("--stats", action="store_true", help="Show graph stats after indexing")

    # ── index-github ─────────────────────────────────────
    p_github = subparsers.add_parser("index-github", help="Clone + index a GitHub repo")
    p_github.add_argument("url", help="GitHub URL or short form (e.g. pallets/click)")
    p_github.add_argument("--commit", help="Pin to a specific commit SHA")
    p_github.add_argument("--clear", action="store_true", help="Clear existing data before indexing")
    p_github.add_argument("--force", action="store_true", help="Force re-clone")
    p_github.add_argument("--stats", action="store_true", help="Show graph stats after indexing")

    # ── ask ───────────────────────────────────────────────
    p_ask = subparsers.add_parser("ask", help="Ask a question about the indexed repo")
    p_ask.add_argument("question", help="Natural language question")
    p_ask.add_argument("--repo-id", help="Target repo ID (defaults to last indexed)")
    p_ask.add_argument("--max-rounds", type=int, default=5, help="Max retrieval rounds")
    p_ask.add_argument("--json", action="store_true", help="Output full JSON result")

    # ── stats ─────────────────────────────────────────────
    p_stats = subparsers.add_parser("stats", help="Show graph statistics")
    p_stats.add_argument("--repo-id", help="Scope to a specific repo")

    # ── repos ─────────────────────────────────────────────
    subparsers.add_parser("repos", help="List all indexed repositories")

    # ── view ──────────────────────────────────────────────
    subparsers.add_parser("view", help="View the graph visually in Neo4j Browser")

    # ── change-model ──────────────────────────────────────
    p_chmodel = subparsers.add_parser("change-model", help="Change the default Groq LLM model in .env")
    p_chmodel.add_argument("model_name", help="The new model name (e.g., llama-3.3-70b-versatile)")

    # ── clear ─────────────────────────────────────────────
    p_clear = subparsers.add_parser("clear", help="Clear data for a repo")
    p_clear.add_argument("repo_id", help="Repo ID to clear (or 'all')")

    # ── cypher ────────────────────────────────────────────
    p_cypher = subparsers.add_parser("cypher", help="Run a raw Cypher query")
    p_cypher.add_argument("query", help="Cypher query string")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Import here (after dotenv loaded) to avoid import errors on missing env vars
    from graph_n4j.core import GraphN4J

    g = None
    try:
        g = GraphN4J.from_env(model_override=args.model)

        if args.command == "index":
            _cmd_index(g, args)
        elif args.command == "index-github":
            _cmd_index_github(g, args)
        elif args.command == "ask":
            _cmd_ask(g, args)
        elif args.command == "stats":
            _cmd_stats(g, args)
        elif args.command == "repos":
            _cmd_repos(g)
        elif args.command == "clear":
            _cmd_clear(g, args)
        elif args.command == "cypher":
            _cmd_cypher(g, args)
        elif args.command == "view":
            _cmd_view()
        elif args.command == "change-model":
            _cmd_change_model(args)
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        print("💡 Hint: Set the GROQ_API_KEY environment variable.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        error_msg = str(e)
        if "neo4j" in error_msg.lower() or "serviceunavailable" in str(type(e)).lower() or "auth" in error_msg.lower():
            print(f"\n❌ Database Connection Error: {error_msg}")
            print("💡 Hint: Make sure Neo4j is running and NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD are set correctly.")
        else:
            print(f"\n❌ Error: {error_msg}", file=sys.stderr)
        
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        if g is not None:
            g.close()


def _cmd_index(g, args):
    print(f"\n{'=' * 60}")
    print(f"  graph-n4j — Indexing local repo")
    print(f"  Path: {args.repo_path}")
    print(f"{'=' * 60}\n")

    meta = g.index(args.repo_path, repo_id=args.repo_id, clear_existing=args.clear)

    print(f"\n  ✓ Indexed: {meta.repo_id}")
    print(f"  ✓ Commit:  {meta.short_sha()}")
    print(f"  ✓ Files:   {meta.total_files} ({meta.skipped_files} skipped)")
    print(f"  ✓ Time:    {meta.index_time:.1f}s")

    if args.stats:
        _print_stats(g, meta.repo_id)


def _cmd_index_github(g, args):
    print(f"\n{'=' * 60}")
    print(f"  graph-n4j — Indexing GitHub repo")
    print(f"  URL: {args.url}")
    print(f"{'=' * 60}\n")

    meta = g.index_github(
        args.url,
        commit_sha=args.commit,
        clear_existing=args.clear,
        force_clone=args.force,
    )

    print(f"\n  ✓ Indexed: {meta.repo_id}")
    print(f"  ✓ Commit:  {meta.short_sha()}")
    print(f"  ✓ Files:   {meta.total_files} ({meta.skipped_files} skipped)")
    print(f"  ✓ Time:    {meta.index_time:.1f}s")

    if args.stats:
        _print_stats(g, meta.repo_id)


def _cmd_ask(g, args):
    g.connect()

    result = g.ask(
        args.question,
        repo_id=args.repo_id,
        max_rounds=args.max_rounds,
    )

    if args.json:
        output = {
            "answer": result.answer,
            "rounds_used": result.rounds_used,
            "total_queries": result.total_queries,
            "neo4j_roundtrips": result.neo4j_roundtrips,
            "token_usage": result.token_usage,
            "cache_stats": result.cache_stats,
            "early_stopped": result.early_stopped,
            "errors": result.errors,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{result.answer}\n")
        print(f"  [{result.rounds_used} rounds, {result.total_queries} queries, "
              f"{result.neo4j_roundtrips} DB hits]")


def _cmd_stats(g, args):
    g.connect()
    _print_stats(g, getattr(args, "repo_id", None))


def _cmd_repos(g):
    g.connect()
    repos = g.list_repos()
    if not repos:
        print("No repos indexed.")
        return
    print(f"\n{'Repo ID':<30s} {'Commit':<14s} {'Modules':>8s}")
    print("-" * 54)
    for r in repos:
        sha = (r.get("commit_sha") or "?")[:12]
        print(f"  {r['repo_id']:<28s} {sha:<14s} {r.get('module_count', '?'):>6}")


def _cmd_clear(g, args):
    g.connect()
    if args.repo_id == "all":
        g.clear_all()
        print("All data cleared.")
    else:
        g.clear_repo(args.repo_id)
        print(f"Data cleared for '{args.repo_id}'.")


def _cmd_cypher(g, args):
    g.connect()
    results = g.run_cypher(args.query)
    print(json.dumps(results, indent=2, default=str))


def _cmd_view():
    import webbrowser
    print("\n🌐 Opening Neo4j Browser...")
    print("If it doesn't open automatically, visit: http://localhost:7474")
    print("\n💡 Fastest way to view the complete graph:")
    print("Once logged in, paste this Cypher query in the top bar and press Enter:\n")
    print("    MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 300\n")
    print("(Note: rendering an *entire* large codebase at once can freeze your browser, so we limit it to 300 relationships!)\n")
    try:
        webbrowser.open("http://localhost:7474")
    except Exception:
        pass


def _cmd_change_model(args):
    import os
    from dotenv import set_key, find_dotenv
    
    dotenv_path = find_dotenv(usecwd=True)
    if not dotenv_path:
        dotenv_path = os.path.join(os.getcwd(), ".env")
        with open(dotenv_path, "w", encoding="utf-8") as f:
            f.write(f"GROQ_MODEL={args.model_name}\n")
    else:
        set_key(dotenv_path, "GROQ_MODEL", args.model_name)
        
    print(f"\n✅ Default model permanently changed to: {args.model_name}")
    print(f"Updated config file: {dotenv_path}\n")


def _print_stats(g, repo_id=None):
    stats = g.stats(repo_id)
    print("\n  Graph Statistics:")
    print("  Nodes:")
    for label in ["MODULE", "CLASS", "FUNCTION", "METHOD", "FIELD", "GLOBAL_VARIABLE"]:
        print(f"    {label:20s} {stats.get(label, 0):>6d}")
    print("  Edges:")
    for rel in ["CONTAINS", "HAS_METHOD", "HAS_FIELD", "INHERITS", "USES"]:
        print(f"    {rel:20s} {stats.get(rel, 0):>6d}")


if __name__ == "__main__":
    main()
