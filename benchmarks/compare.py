"""Run both releases against pinned source files on a disposable Neo4j database."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA256 = "6f032e39640785e61f8e78d73f901be8ff97ca44c09cf8add9b0096287da4cd0"
# Limit each input to the library under study. Build tools would give Python-only
# 0.1.8 something unrelated to index in the native-language repositories.
CASES = [
    ("pallets/click", "8.1.8", "934813e4d421071a1b3db3973c02fe2721359a6e", ["src/click/*.py"]),
    ("psf/black", "24.10.0", "1b2427a2b785cc4aac97c19bb4b9a0de063f9547", ["src/black/*.py"]),
    (
        "DaveGamble/cJSON",
        "v1.7.18",
        "acc76239bee01d8e9c858ae2cab296704e52d916",
        ["cJSON.c", "cJSON.h", "cJSON_Utils.c", "cJSON_Utils.h"],
    ),
    (
        "curl/curl",
        "curl-8_10_1",
        "7eb8c048470ed2cc14dca75be9c1cdae7ac8498b",
        ["lib/vtls/*.c", "lib/vtls/*.h"],
    ),
    (
        "leethomason/tinyxml2",
        "10.0.0",
        "321ea883b7190d4e85cae5512a12e5eaa8f8731f",
        ["tinyxml2.cpp", "tinyxml2.h"],
    ),
    (
        "fmtlib/fmt",
        "11.0.2",
        "0c9fce2ffefecfdce794e1859584e25877b7b592",
        ["include/fmt/*.h", "src/*.cc"],
    ),
]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--repos", type=Path, default=ROOT / "repos")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--disposable-uri",
        required=True,
        help="Empty benchmark database. Schema creation and migration run here.",
    )
    args = parser.parse_args()
    if hashlib.sha256(args.wheel.read_bytes()).hexdigest() != BASELINE_SHA256:
        parser.error("Baseline wheel differs from the PyPI 0.1.8 artifact")
    from neo4j import GraphDatabase

    with GraphDatabase.driver(
        args.disposable_uri, auth=("neo4j", os.getenv("NEO4J_PASSWORD", "benchmark"))
    ) as driver:
        with driver.session() as session:
            if (
                session.run("MATCH (n) RETURN n LIMIT 1").peek()
                or session.run("SHOW CONSTRAINTS").peek()
            ):
                parser.error("Supply a fresh disposable database")
            server = session.run(
                "CALL dbms.components() YIELD versions RETURN versions[0]"
            ).single()[0]

    results = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "neo4j": server,
        "baseline_sha256": BASELINE_SHA256,
        "runs": [],
    }
    with tempfile.TemporaryDirectory() as temp:
        scratch = Path(temp)
        legacy = scratch / "wheel"
        with zipfile.ZipFile(args.wheel) as archive:
            archive.extractall(legacy)
        for version, package in [("0.1.8", legacy), ("1.1.0", ROOT)]:
            for name, tag, sha, patterns in CASES:
                short = name.split("/")[-1]
                repo = args.repos / short
                if not repo.exists():
                    subprocess.run(
                        [
                            "git",
                            "clone",
                            "--quiet",
                            "--depth",
                            "1",
                            "--branch",
                            tag,
                            f"https://github.com/{name}.git",
                            str(repo),
                        ],
                        check=True,
                    )
                if git(repo, "rev-parse", "HEAD") != sha or git(
                    repo, "diff", "HEAD", "--name-only"
                ):
                    raise ValueError(f"Expected a clean checkout of {name} at {sha}")
                files = git(repo, "ls-files", "--", *patterns).splitlines()
                if not files:
                    raise ValueError(f"No files selected for {name}")
                target = scratch / short
                for rel in files:
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(repo / rel, target / rel)
                print(f"{version}  {name}  {len(files)} files", flush=True)
                data = subprocess.check_output(
                    [
                        sys.executable,
                        str(ROOT / "benchmarks/worker.py"),
                        version,
                        str(target),
                        sha,
                        args.disposable_uri,
                    ],
                    cwd=scratch,
                    env={**os.environ, "PYTHONPATH": str(package)},
                    text=True,
                )
                results["runs"].append(
                    dict(
                        repo=name,
                        sha=sha,
                        tag=tag,
                        paths=files,
                        bytes=sum((target / p).stat().st_size for p in files),
                        **json.loads(data),
                    )
                )
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
