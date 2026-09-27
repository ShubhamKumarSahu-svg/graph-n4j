"""
repo_manager.py -- Git repository cloning, caching, and metadata management.

Handles:
  - Cloning GitHub repos into a local cache (./repos/<org>__<name>/)
  - Pinning to a specific commit SHA for reproducibility
  - Recording metadata (repo_id, commit_sha, clone time)
  - File filtering (exclude tests, vendored code, large files)
  - Size guards to prevent OOM on huge repos
"""

import json
import os
import re
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from fnmatch import fnmatch

from git import Repo as GitRepo, InvalidGitRepositoryError

logger = logging.getLogger(__name__)

# ---- Default constants -------------------------------------------------------

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "repos")

# Directories to always exclude from indexing
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    "node_modules", ".tox", ".venv", "venv", "env", ".env", ".eggs",
    "build", "dist", "vendor", "vendored", "migrations", ".nox",
    "htmlcov", ".hypothesis", "docs", "doc", "examples", "benchmarks",
}

# File-name patterns to exclude (tests, per Section 4 of the paper)
EXCLUDED_FILE_PATTERNS = [
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "setup.py",
    "setup.cfg",
    "noxfile.py",
    "fabfile.py",
]

# Directory patterns to exclude (tests)
EXCLUDED_DIR_PATTERNS = [
    "tests", "test", "testing", "Tests",
]

MAX_FILE_SIZE_BYTES = 500_000        # 500 KB per file (skip generated / data files)
MAX_TOTAL_FILES = 2000               # Hard cap; warn if exceeded

# ---- Recommended repos -------------------------------------------------------

RECOMMENDED_REPOS = {
    "pallets/click": {
        "url": "https://github.com/pallets/click",
        "description": "CLI toolkit, ~50 .py files, indexes in <30s",
        "size": "small",
    },
    "psf/requests": {
        "url": "https://github.com/psf/requests",
        "description": "HTTP library, ~80 .py files (excl. tests), indexes in ~1 min",
        "size": "medium",
    },
    "httpie/cli": {
        "url": "https://github.com/httpie/cli",
        "description": "CLI HTTP client, ~100 .py files, indexes in ~1-2 min",
        "size": "medium",
    },
}


@dataclass
class RepoMetadata:
    """Metadata about an indexed repository."""
    repo_id: str                  # e.g. "pallets/click"
    commit_sha: str               # full SHA of the indexed commit
    repo_url: Optional[str]       # GitHub URL (None for local repos)
    local_path: str               # path to the cloned/local directory
    clone_time: Optional[float] = None
    index_time: Optional[float] = None
    total_files: int = 0
    skipped_files: int = 0
    metadata_file: Optional[str] = None

    def short_sha(self) -> str:
        return self.commit_sha[:12]

    def to_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "commit_sha": self.commit_sha,
            "repo_url": self.repo_url,
            "local_path": self.local_path,
            "clone_time": self.clone_time,
            "index_time": self.index_time,
            "total_files": self.total_files,
            "skipped_files": self.skipped_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RepoMetadata":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FilterConfig:
    """Configurable indexing filter settings."""
    exclude_tests: bool = True
    exclude_vendored: bool = True
    max_file_size: int = MAX_FILE_SIZE_BYTES
    max_total_files: int = MAX_TOTAL_FILES
    additional_exclude_dirs: list[str] = field(default_factory=list)
    additional_exclude_patterns: list[str] = field(default_factory=list)


# ---- Repo Manager ------------------------------------------------------------

class RepoManager:
    """
    Manages repository cloning, caching, and metadata.

    Usage:
        mgr = RepoManager()
        meta = mgr.clone_repo("https://github.com/pallets/click")
        py_files = mgr.get_python_files(meta)
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---- Cloning & metadata --------------------------------------------------

    def clone_repo(
        self,
        url: str,
        commit_sha: Optional[str] = None,
        force: bool = False,
    ) -> RepoMetadata:
        """
        Clone a GitHub repository into the local cache.

        Args:
            url: GitHub repo URL (https://github.com/org/name or org/name).
            commit_sha: Optional commit to pin to; if None, uses HEAD.
            force: If True, re-clone even if the repo already exists locally.

        Returns:
            RepoMetadata with repo_id, commit_sha, local_path.
        """
        repo_id = self._url_to_repo_id(url)
        full_url = self._normalize_url(url)
        local_dir = os.path.join(self.cache_dir, repo_id.replace("/", "__"))

        t0 = time.time()

        if os.path.isdir(local_dir) and not force:
            logger.info("Repo %s already cached at %s", repo_id, local_dir)
            git_repo = GitRepo(local_dir)
        else:
            logger.info("Cloning %s into %s ...", full_url, local_dir)
            if os.path.isdir(local_dir):
                import shutil
                shutil.rmtree(local_dir)
            git_repo = GitRepo.clone_from(full_url, local_dir)

        clone_time = time.time() - t0

        # Checkout specific commit if requested
        if commit_sha:
            git_repo.git.checkout(commit_sha)
            actual_sha = commit_sha
        else:
            actual_sha = git_repo.head.commit.hexsha

        meta = RepoMetadata(
            repo_id=repo_id,
            commit_sha=actual_sha,
            repo_url=full_url,
            local_path=local_dir,
            clone_time=clone_time,
        )

        # Save metadata
        self._save_metadata(meta, local_dir)

        logger.info(
            "Repo %s ready — commit %s, cloned in %.1fs",
            repo_id, meta.short_sha(), clone_time,
        )
        return meta

    def load_local_repo(self, repo_path: str, repo_id: Optional[str] = None) -> RepoMetadata:
        """
        Load metadata for an already-cloned or local repository.

        Args:
            repo_path: Absolute or relative path to the repo root.
            repo_id: Optional override for the repo_id (defaults to directory name).

        Returns:
            RepoMetadata.
        """
        repo_path = os.path.abspath(repo_path)
        if not os.path.isdir(repo_path):
            raise FileNotFoundError(f"Repo path does not exist: {repo_path}")

        # Try to get git info
        commit_sha = "local"
        repo_url = None
        try:
            git_repo = GitRepo(repo_path)
            commit_sha = git_repo.head.commit.hexsha
            # Try to get remote URL
            if git_repo.remotes:
                repo_url = git_repo.remotes.origin.url
        except (InvalidGitRepositoryError, Exception):
            pass

        if not repo_id:
            if repo_url:
                repo_id = self._url_to_repo_id(repo_url)
            else:
                repo_id = os.path.basename(repo_path)

        return RepoMetadata(
            repo_id=repo_id,
            commit_sha=commit_sha,
            repo_url=repo_url,
            local_path=repo_path,
        )

    # ---- File filtering (Section 4 of the paper) -----------------------------

    def get_python_files(
        self,
        meta: RepoMetadata,
        filter_config: Optional[FilterConfig] = None,
    ) -> list[str]:
        """
        Get filtered list of .py files to index.

        Applies filtering per the paper's Section 4:
          - Only .py files
          - Exclude test directories/files
          - Exclude vendored/generated code
          - Respect max file size and total file count

        Args:
            meta: Repository metadata.
            filter_config: Optional filter configuration.

        Returns:
            List of absolute .py file paths to index.
        """
        config = filter_config or FilterConfig()
        repo_root = meta.local_path
        py_files = []
        skipped = 0

        # Build full set of excluded dirs
        excluded_dirs = set(EXCLUDED_DIRS)
        if config.exclude_tests:
            excluded_dirs.update(EXCLUDED_DIR_PATTERNS)
        if config.exclude_vendored:
            excluded_dirs.update({"vendor", "vendored", "third_party"})
        excluded_dirs.update(config.additional_exclude_dirs)

        # Build excluded file patterns
        excluded_patterns = list(EXCLUDED_FILE_PATTERNS) if config.exclude_tests else []
        excluded_patterns.extend(config.additional_exclude_patterns)

        for root, dirs, files in os.walk(repo_root):
            # Prune excluded directories in-place
            dirs[:] = [
                d for d in dirs
                if d not in excluded_dirs
                and not d.endswith(".egg-info")
            ]

            for fname in files:
                if not fname.endswith(".py"):
                    continue

                # Check file name patterns
                if any(fnmatch(fname, pat) for pat in excluded_patterns):
                    skipped += 1
                    continue

                fpath = os.path.join(root, fname)

                # Check file size
                try:
                    fsize = os.path.getsize(fpath)
                    if fsize > config.max_file_size:
                        logger.debug("Skipping large file (%d bytes): %s", fsize, fpath)
                        skipped += 1
                        continue
                except OSError:
                    continue

                py_files.append(fpath)

                # Check total file count
                if len(py_files) >= config.max_total_files:
                    logger.warning(
                        "Max file limit (%d) reached for %s. "
                        "Increase max_total_files or narrow filtering.",
                        config.max_total_files, meta.repo_id,
                    )
                    break

            if len(py_files) >= config.max_total_files:
                break

        meta.total_files = len(py_files)
        meta.skipped_files = skipped
        logger.info(
            "Found %d .py files (%d skipped) for %s",
            len(py_files), skipped, meta.repo_id,
        )
        return py_files

    # ---- List indexed repos --------------------------------------------------

    def list_cached_repos(self) -> list[RepoMetadata]:
        """List all repos in the local cache with their metadata."""
        repos = []
        if not os.path.isdir(self.cache_dir):
            return repos

        for entry in os.listdir(self.cache_dir):
            meta_file = os.path.join(self.cache_dir, entry, ".codexgraph_meta.json")
            if os.path.isfile(meta_file):
                try:
                    with open(meta_file, "r") as f:
                        data = json.load(f)
                    repos.append(RepoMetadata.from_dict(data))
                except Exception as e:
                    logger.warning("Could not load metadata for %s: %s", entry, e)
        return repos

    # ---- Helpers -------------------------------------------------------------

    @staticmethod
    def _url_to_repo_id(url: str) -> str:
        """Extract 'org/name' from a GitHub URL or short form."""
        url = url.rstrip("/")
        # Handle full URLs
        match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)", url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        # Handle short forms like "pallets/click"
        if "/" in url and not url.startswith("http"):
            return url
        return url

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Ensure a full HTTPS GitHub URL."""
        if url.startswith("http"):
            return url
        if "/" in url:
            return f"https://github.com/{url}"
        return url

    def _save_metadata(self, meta: RepoMetadata, local_dir: str):
        """Save repo metadata to a JSON file in the repo directory."""
        meta_file = os.path.join(local_dir, ".codexgraph_meta.json")
        with open(meta_file, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)
        meta.metadata_file = meta_file

    @staticmethod
    def _load_metadata(local_dir: str) -> Optional[RepoMetadata]:
        meta_file = os.path.join(local_dir, ".codexgraph_meta.json")
        if os.path.isfile(meta_file):
            with open(meta_file, "r") as f:
                return RepoMetadata.from_dict(json.load(f))
        return None
