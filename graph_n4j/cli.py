"""Command-line entry points for indexing, querying and managing repository graphs."""

import argparse
import json
import logging
import sys

from dotenv import find_dotenv, load_dotenv


def _render_markdown(text: str) -> None:
    """Render markdown text beautifully in the terminal using rich.

    Falls back to plain text output if rich is not available.
    """
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.theme import Theme

        custom_theme = Theme(
            {
                "markdown.h1": "bold bright_cyan",
                "markdown.h2": "bold bright_green",
                "markdown.h3": "bold bright_yellow",
                "markdown.code": "bright_magenta on grey11",
                "markdown.link": "bright_blue underline",
            }
        )

        console = Console(theme=custom_theme)
        md = Markdown(text)
        console.print()
        console.print(
            Panel(
                md,
                title="[bold bright_cyan]graph-n4j Answer[/]",
                border_style="bright_cyan",
                padding=(1, 2),
                expand=True,
            )
        )
        console.print()
    except ImportError:
        # Fallback: just print the raw text
        print(f"\n{text}\n")


def main():
    load_dotenv(find_dotenv(usecwd=True), override=True, encoding="utf-8-sig")

    parser = argparse.ArgumentParser(
        prog="graph-n4j",
        description="Bridge LLM agents with code repositories via Neo4j graph databases.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Override the selected provider model",
    )

    from graph_n4j import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit",
    )
    # Keep model selection global so indexing and query commands share the same settings.
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    p_index = subparsers.add_parser("index", help="Index a local Python, C++, or C repository")
    p_index.add_argument("repo_path", help="Path to the repository")
    p_index.add_argument("--repo-id", help="Override the repo identifier")
    p_index.add_argument("--clear", action="store_true", help="Clear existing data before indexing")
    p_index.add_argument("--stats", action="store_true", help="Show graph stats after indexing")

    p_github = subparsers.add_parser("index-github", help="Clone + index a GitHub repo")
    p_github.add_argument("url", help="GitHub URL or short form (e.g. pallets/click)")
    p_github.add_argument("--commit", help="Pin to a specific commit SHA")
    p_github.add_argument(
        "--clear", action="store_true", help="Clear existing data before indexing"
    )
    p_github.add_argument("--force", action="store_true", help="Force re-clone")
    p_github.add_argument("--stats", action="store_true", help="Show graph stats after indexing")

    p_ask = subparsers.add_parser("ask", help="Ask a question about the indexed repo")
    p_ask.add_argument("--provider", choices=["groq", "openai", "anthropic", "gemini", "ollama"])
    p_ask.add_argument("question", help="Natural language question")
    p_ask.add_argument("--repo-id", help="Target repo ID (defaults to last indexed)")
    p_ask.add_argument("--max-rounds", type=int, default=5, help="Max retrieval rounds")
    p_ask.add_argument("--json", action="store_true", help="Output full JSON result")

    p_stats = subparsers.add_parser("stats", help="Show graph statistics")
    p_stats.add_argument("--repo-id", help="Scope to a specific repo")

    subparsers.add_parser("repos", help="List all indexed repositories")

    subparsers.add_parser("view", help="View the graph visually in Neo4j Browser")

    p_chmodel = subparsers.add_parser(
        "change-model", help="Change the default Groq LLM model in .env"
    )
    p_chmodel.add_argument("model_name", help="The new model name (e.g., llama-3.3-70b-versatile)")

    p_clear = subparsers.add_parser("clear", help="Clear data for a repo")
    p_clear.add_argument("repo_id", help="Repo ID to clear (or 'all')")

    p_cypher = subparsers.add_parser("cypher", help="Run a raw Cypher query")
    p_cypher.add_argument("query", help="Cypher query string")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Silence overly verbose third-party loggers even in DEBUG mode unless specifically
    # debugging them
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("neo4j").setLevel(logging.WARNING)

    # Import here (after dotenv loaded) to avoid import errors on missing env vars
    from graph_n4j.core import GraphN4J

    g = None
    try:
        # Only natural-language Q&A needs an LLM. Indexing, graph maintenance,
        # Cypher queries, and stats should work without any model API key.
        needs_llm = args.command == "ask"
        g = GraphN4J.from_env(
            model_override=args.model if needs_llm else None,
            provider=getattr(args, "provider", None) if needs_llm else None,
            llm_enabled=needs_llm,
        )

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
    except KeyboardInterrupt:
        print("Stopped at your request. Run the command again to continue.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        from graph_n4j.messages import explain_error

        print(explain_error(e, args.command), file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)
    finally:
        if g is not None:
            g.close()


def _cmd_index(g, args):
    _index_with_status(args.repo_path, args, g, g.index, repo_id=args.repo_id)


def _cmd_index_github(g, args):
    _index_with_status(
        args.url, args, g, g.index_github, commit_sha=args.commit, force_clone=args.force
    )


def _index_with_status(target, args, g, index, **options):
    from rich.console import Console
    from contextlib import nullcontext

    console = Console(stderr=True)
    print(f"Indexing {target} ...", file=sys.stderr)
    status = (
        console.status("Building the code graph", spinner="dots")
        if console.is_terminal
        else nullcontext()
    )
    with status:
        meta = index(target, clear_existing=args.clear, **options)
    print(f"Indexed {meta.repo_id} at {meta.short_sha()} in {meta.index_time:.1f}s.")
    print(f"Files indexed: {meta.total_files}. Files excluded by filters: {meta.skipped_files}.")
    if not meta.total_files:
        print("Choose a folder containing Python, C or C++ source outside excluded directories.")
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
        for message in dict.fromkeys(result.errors):
            print(message, file=sys.stderr)
        _render_markdown(result.answer)
        try:
            from rich.console import Console
            from rich.text import Text

            console = Console()
            stats = Text()
            stats.append("  >> ", style="bright_yellow")
            stats.append(f"{result.rounds_used}", style="bold bright_cyan")
            stats.append(" rounds  ", style="dim")
            stats.append(f"{result.total_queries}", style="bold bright_green")
            stats.append(" queries  ", style="dim")
            stats.append(f"{result.neo4j_roundtrips}", style="bold bright_magenta")
            stats.append(" DB hits", style="dim")
            console.print(stats)
            console.print()
        except ImportError:
            print(
                f"  [{result.rounds_used} rounds, {result.total_queries} queries, "
                f"{result.neo4j_roundtrips} DB hits]"
            )


def _cmd_stats(g, args):
    g.connect()
    _print_stats(g, getattr(args, "repo_id", None))


def _cmd_repos(g):
    g.connect()
    repos = g.list_repos()
    if not repos:
        print("No repositories indexed yet. Run 'graph-n4j index .' in your project folder.")
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
        print("Cleared all data from the configured graph database.")
    else:
        g.clear_repo(args.repo_id)
        print(f"Cleared graph data for '{args.repo_id}'.")


def _cmd_cypher(g, args):
    g.connect()
    results = g.run_cypher(args.query)
    print(json.dumps(results, indent=2, default=str))


def _cmd_view():
    import webbrowser

    print("Opening Neo4j Browser at http://localhost:7474")
    print("To view up to 300 relationships, run this query in the browser:")
    print("MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 300")
    try:
        webbrowser.open("http://localhost:7474")
    except Exception:
        pass


def _cmd_change_model(args):
    import os

    from dotenv import find_dotenv, set_key

    dotenv_path = find_dotenv(usecwd=True)
    if not dotenv_path:
        dotenv_path = os.path.join(os.getcwd(), ".env")
        with open(dotenv_path, "w", encoding="utf-8") as f:
            f.write(f"GROQ_MODEL={args.model_name}\n")
    else:
        set_key(dotenv_path, "GROQ_MODEL", args.model_name)

    print(f"\n[OK] Saved the default Groq model: {args.model_name}")
    print(f"Updated config file: {dotenv_path}\n")


def _print_stats(g, repo_id=None):
    stats = g.stats(repo_id)
    print("\n  Graph statistics")
    print("  Nodes:")
    for label in ["MODULE", "CLASS", "FUNCTION", "METHOD", "FIELD", "GLOBAL_VARIABLE"]:
        print(f"    {label:20s} {stats.get(label, 0):>6d}")
    print("  Edges:")
    for rel in ["CONTAINS", "HAS_METHOD", "HAS_FIELD", "INHERITS", "USES", "CALLS", "IMPORTS"]:
        print(f"    {rel:20s} {stats.get(rel, 0):>6d}")


if __name__ == "__main__":
    main()
