"""Regenerate the report tables and figures from compare.py's JSON output."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

OLD = "#995438"
NEW = "#006A68"
NAMES = ["Click", "Black", "cJSON", "curl TLS", "tinyxml2", "fmt"]


def figure(path, groups, series, unit):
    fig, axes = plt.subplots(1, len(series), figsize=(12, 4.1), layout="constrained")
    for ax, (title, old_values, new_values) in zip(axes, series):
        y = list(range(len(groups)))
        for offset, values, color in [(-0.18, old_values, OLD), (0.18, new_values, NEW)]:
            for i, value in enumerate(values):
                if value is None:
                    ax.text(0, i + offset, " unsupported", va="center", fontsize=9, color=OLD)
                    continue
                ax.barh(i + offset, value, height=0.31, color=color)
                label = f"{value:.2f}" if unit == "seconds" else f"{value:,}"
                ax.annotate(
                    label,
                    (value, i + offset),
                    xytext=(4, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=9,
                )
        ax.set_yticks(y, groups)
        ax.invert_yaxis()
        ax.spines[:].set_visible(False)
        ax.tick_params(length=0)
        ax.margins(x=0.25)
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_xlabel(unit)
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    old = [r for r in data["runs"] if r["version"] == "0.1.8"]
    new = [r for r in data["runs"] if r["version"] == "1.1.0"]
    if len(new) != 6 or [r["sha"] for r in old] != [r["sha"] for r in new]:
        raise ValueError("Expected six matching pairs")
    click_old, click_new = old[0], new[0]
    expected = [{"path": "src/click/core.py", "parent": "MultiCommand"}]
    if any(row["group_parents"] != expected for row in (click_old, click_new)):
        raise ValueError("Click's inheritance lookup disagrees with its source")
    figures = args.output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for key, unit in [("seconds", "seconds"), ("writes", "write calls")]:
        series = []
        for index, title in enumerate(["First index", "Unchanged rerun"]):
            series.append(
                (
                    title,
                    [r["measurements"][index][key] if r["supported"] else None for r in old],
                    [r["measurements"][index][key] for r in new],
                )
            )
        figure(figures / f"{key}.png", NAMES, series, unit)
    figure(
        figures / "graph.png",
        NAMES,
        [
            (
                key.title(),
                [sum(r[key].values()) if r["supported"] else None for r in old],
                [sum(r[key].values()) for r in new],
            )
            for key in ("nodes", "edges")
        ],
        "stored records",
    )

    lines = [
        "# From Python AST to a repository graph",
        "",
        "On Click, both releases recover the inheritance edge from Group to MultiCommand. "
        "The new indexer also stores calls and imports, and reuses the parse of every "
        "unchanged file on the second run.",
        "",
        "## Inputs and method",
        "",
        f"Python {data['python']} on {data['platform']} with Neo4j {data['neo4j']}. "
        "Each case ran in its own Python process. Both releases saw the same selected "
        "library sources. Each supported case started with an empty repository graph "
        "and immediately repeated the index. Setup, cloning, schema creation and graph "
        "inspection are outside the timer. Schema and database server caches could be warm.",
        "",
        "The benchmark calls the two indexing stages from the published 0.1.8 wheel "
        "and the candidate UnifiedIndexer. It supplies the same repository and commit "
        "identifiers to both writers. Version 0.1.8 accepts Python files only. "
        "Unsupported inputs are excluded from its timing series. The corpus comprises "
        "production source selections, including the TLS component of curl. Each time "
        "is one observation. No memory, energy, model latency or token savings were measured.",
        "",
        "| Source snapshot | Selection | Files | Source KiB |",
        "| --- | --- | ---: | ---: |",
    ]
    for r, scope in zip(
        new,
        [
            "src/click",
            "src/black",
            "cJSON and utilities",
            "lib/vtls",
            "tinyxml2.cpp and header",
            "include/fmt and src/*.cc",
        ],
    ):
        url = f"https://github.com/{r['repo']}/tree/{r['sha']}"
        lines.append(
            f"| [{r['repo']} at {r['tag']}]({url}) | {scope} | {len(r['paths'])} | "
            f"{r['bytes'] / 1024:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Measured results",
            "",
            "| Input | Version | First (s) | Repeat (s) | Writes, first / repeat | "
            "Files reused | Nodes | Edges |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, pair in zip(NAMES, zip(old, new)):
        for r in pair:
            if not r["supported"]:
                lines.append(f"| {name} | 0.1.8 | Unsupported | — | — | — | — | — |")
                continue
            a, b = r["measurements"]
            lines.append(
                f"| {name} | {r['version']} | {a['seconds']:.2f} | {b['seconds']:.2f} "
                f"| {a['writes']:,} / {b['writes']:,} | {b['reused']} "
                f"| {sum(r['nodes'].values()):,} | {sum(r['edges'].values()):,} |"
            )
    lines.extend(
        [
            "",
            "The brown series is 0.1.8 and the teal series is 1.1.0. "
            "A write is one call to the Neo4j write helper. The final counts come from "
            "queries against stored records after the unchanged rerun.",
            "",
            "![Index and repeat times in seconds](figures/seconds.png)",
            "",
            "![Write calls](figures/writes.png)",
            "",
            "![Stored graph size](figures/graph.png)",
            "",
            "## Following Click through both indexers",
            "",
            "In Click 8.1.8, core.py defines Group(MultiCommand). The original shallow "
            "pass uses Python ast to record Group and its base name. Edge completion "
            "looks up MultiCommand, writes each node and relationship with MERGE, and "
            "re-reads source when resolving uses. Both live graphs returned MultiCommand "
            "for Group in src/click/core.py.",
            "",
            "The new parser records the class, its source span and the unresolved base "
            "reference together. The linker resolves that name against the repository "
            "symbol table. The writer groups the class with other classes and its "
            "inheritance edge with other edges of that type. The next index checks "
            "the file hash and extractor version, reloads cached records, relinks and "
            f"updates the commit stamp. On Click it reused "
            f"{click_new['measurements'][1]['reused']} files.",
            "",
            f"Click has {click_old['edges']['INHERITS']} INHERITS edges in the baseline and "
            f"{click_new['edges']['INHERITS']} in the candidate. Version 1.1.0 also stores "
            f"{click_new['edges']['CALLS']} CALLS and {click_new['edges']['IMPORTS']} IMPORTS "
            f"edges. It stores {sum(click_new['nodes'].values())} nodes versus "
            f"{sum(click_old['nodes'].values())}. Counts describe "
            "what was indexed. The Group check validates one specific relationship. "
            "Neither result establishes recall or precision across the corpus.",
            "",
            "## Release checks and limitations",
            "",
            "The integration suite covers edits and deletions, cache reuse, cross-repository "
            "isolation, full-text lookup, C header lookup and C++ calls. Four HTTP provider "
            "adapters are tested with recorded-format synthetic responses. The five coding "
            "apps exercise two retrieval rounds with scripted model replies and a live "
            "database. These checks do not score generated answers or test hosted services.",
            "",
            "Version 1.0.0 skipped .c files. The candidate registers the C grammar "
            "for .c and keeps the C++ grammar for .h. Both use the same graph vocabulary. "
            "For example, the cJSON result includes CLASS and METHOD labels for native "
            "declarations. Use source spans to check classifications. Static name resolution "
            "can miss dynamic targets, and a larger graph can contain extra or duplicate concepts.",
            "",
            "See the [runner and exact file manifests](../benchmarks/) to reproduce this run.",
        ]
    )
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
