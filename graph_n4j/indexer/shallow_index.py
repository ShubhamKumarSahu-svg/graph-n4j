"""
shallow_index.py — Phase 1 of the CodexGraph indexing pipeline.

Single-pass AST scan of every .py file in the target repo to extract:
  - MODULE nodes
  - CLASS nodes (with signature, code, base class names)
  - FUNCTION nodes (top-level only)
  - METHOD nodes (within classes)
  - FIELD nodes (class-level attributes)
  - GLOBAL_VARIABLE nodes (module-level assignments)

Does NOT resolve cross-file relationships — that's Phase 2 (edge_completion.py).
"""

import ast
import os
import logging
import textwrap
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# Data containers for extracted symbols
# ═══════════════════════════════════════════

@dataclass
class ExtractedModule:
    name: str
    file_path: str
    imports: list[dict] = field(default_factory=list)  # [{module, names, alias, level}]


@dataclass
class ExtractedClass:
    name: str
    file_path: str
    module_name: str
    signature: str
    code: str
    base_classes: list[str] = field(default_factory=list)
    methods: list["ExtractedMethod"] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)


@dataclass
class ExtractedFunction:
    name: str
    file_path: str
    module_name: str
    signature: str
    code: str


@dataclass
class ExtractedMethod:
    name: str
    file_path: str
    module_name: str
    class_name: str
    signature: str
    code: str


@dataclass
class ExtractedField:
    name: str
    file_path: str
    module_name: str
    class_name: str


@dataclass
class ExtractedGlobalVariable:
    name: str
    file_path: str
    module_name: str
    code: str


@dataclass
class ShallowIndexResult:
    """Aggregated result from a shallow index scan."""
    modules: list[ExtractedModule] = field(default_factory=list)
    classes: list[ExtractedClass] = field(default_factory=list)
    functions: list[ExtractedFunction] = field(default_factory=list)
    methods: list[ExtractedMethod] = field(default_factory=list)
    fields: list[ExtractedField] = field(default_factory=list)
    global_variables: list[ExtractedGlobalVariable] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Modules: {len(self.modules)}, Classes: {len(self.classes)}, "
            f"Functions: {len(self.functions)}, Methods: {len(self.methods)}, "
            f"Fields: {len(self.fields)}, GlobalVars: {len(self.global_variables)}"
        )


# ═══════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════

def _file_to_module_name(file_path: str, repo_root: str) -> str:
    """Convert a file path to a dotted module name relative to the repo root."""
    rel = os.path.relpath(file_path, repo_root)
    # Normalize path separators
    rel = rel.replace(os.sep, "/")
    # Strip .py extension
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _get_source_segment(source_lines: list[str], node: ast.AST) -> str:
    """Extract source code for an AST node using line numbers."""
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return ""
    start = node.lineno - 1  # 0-indexed
    end = node.end_lineno     # exclusive
    return "\n".join(source_lines[start:end])


def _get_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a signature string like 'def foo(x: int, y: str = 'hi') -> bool:'"""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args_parts = []

    # Regular args
    all_args = node.args
    defaults_offset = len(all_args.args) - len(all_args.defaults)

    for i, arg in enumerate(all_args.args):
        part = arg.arg
        if arg.annotation:
            try:
                part += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        # Check for default
        default_idx = i - defaults_offset
        if default_idx >= 0 and default_idx < len(all_args.defaults):
            try:
                part += f" = {ast.unparse(all_args.defaults[default_idx])}"
            except Exception:
                pass
        args_parts.append(part)

    # *args
    if all_args.vararg:
        part = f"*{all_args.vararg.arg}"
        if all_args.vararg.annotation:
            try:
                part += f": {ast.unparse(all_args.vararg.annotation)}"
            except Exception:
                pass
        args_parts.append(part)
    elif all_args.kwonlyargs:
        args_parts.append("*")

    # keyword-only args
    for i, arg in enumerate(all_args.kwonlyargs):
        part = arg.arg
        if arg.annotation:
            try:
                part += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        if i < len(all_args.kw_defaults) and all_args.kw_defaults[i] is not None:
            try:
                part += f" = {ast.unparse(all_args.kw_defaults[i])}"
            except Exception:
                pass
        args_parts.append(part)

    # **kwargs
    if all_args.kwarg:
        part = f"**{all_args.kwarg.arg}"
        if all_args.kwarg.annotation:
            try:
                part += f": {ast.unparse(all_args.kwarg.annotation)}"
            except Exception:
                pass
        args_parts.append(part)

    sig = f"{prefix} {node.name}({', '.join(args_parts)})"
    if node.returns:
        try:
            sig += f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    sig += ":"
    return sig


def _get_class_signature(node: ast.ClassDef) -> str:
    """Build a signature like 'class Foo(Bar, Baz):'"""
    bases = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:
            bases.append("?")
    for kw in node.keywords:
        try:
            bases.append(f"{kw.arg}={ast.unparse(kw.value)}")
        except Exception:
            pass
    if bases:
        return f"class {node.name}({', '.join(bases)}):"
    return f"class {node.name}:"


def _get_base_class_names(node: ast.ClassDef) -> list[str]:
    """Extract base class names from a ClassDef node."""
    names = []
    for base in node.bases:
        try:
            names.append(ast.unparse(base))
        except Exception:
            pass
    return names


def _extract_class_fields(class_node: ast.ClassDef) -> list[str]:
    """
    Extract field names from a class body.

    Looks for:
      - Direct assignments: `x = ...`
      - Annotated assignments: `x: int = ...` or `x: int`
      - self.x = ... in __init__ (and other methods)
    """
    fields = set()

    for node in class_node.body:
        # Class-level assignments
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    fields.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                fields.add(node.target.id)

        # self.x = ... inside methods
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            fields.add(target.attr)
                elif isinstance(child, ast.AnnAssign):
                    if (
                        isinstance(child.target, ast.Attribute)
                        and isinstance(child.target.value, ast.Name)
                        and child.target.value.id == "self"
                    ):
                        fields.add(child.target.attr)

    return sorted(fields)


# ═══════════════════════════════════════════
# Import extraction
# ═══════════════════════════════════════════

def _extract_imports(tree: ast.Module) -> list[dict]:
    """
    Extract import statements from a module's AST.
    Returns a list of dicts with keys: module, names, alias, level.
    """
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name,
                    "names": [alias.name],
                    "alias": alias.asname,
                    "level": 0,  # absolute
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [a.name for a in node.names] if node.names else []
            imports.append({
                "module": module,
                "names": names,
                "alias": None,
                "level": node.level,  # 0=absolute, 1=relative '.', 2='..' etc.
            })
    return imports


# ═══════════════════════════════════════════
# Main extraction: single file
# ═══════════════════════════════════════════

def extract_file(
    file_path: str,
    repo_root: str,
) -> ShallowIndexResult:
    """
    Parse a single Python file and extract all symbols.

    Args:
        file_path: Absolute path to the .py file.
        repo_root: Absolute path to the repository root.

    Returns:
        ShallowIndexResult with all extracted symbols from this file.
    """
    result = ShallowIndexResult()
    rel_path = os.path.relpath(file_path, repo_root).replace(os.sep, "/")
    module_name = _file_to_module_name(file_path, repo_root)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return result

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        logger.warning("Syntax error in %s: %s", file_path, e)
        return result

    source_lines = source.splitlines()

    # ── Module node ───────────────────────────────────────
    imports = _extract_imports(tree)
    result.modules.append(ExtractedModule(
        name=module_name,
        file_path=rel_path,
        imports=imports,
    ))

    # ── Walk top-level statements ─────────────────────────
    for node in tree.body:

        # ── Top-level functions ───────────────────────────
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.functions.append(ExtractedFunction(
                name=node.name,
                file_path=rel_path,
                module_name=module_name,
                signature=_get_function_signature(node),
                code=_get_source_segment(source_lines, node),
            ))

        # ── Classes ───────────────────────────────────────
        elif isinstance(node, ast.ClassDef):
            class_code = _get_source_segment(source_lines, node)
            base_classes = _get_base_class_names(node)
            class_sig = _get_class_signature(node)
            field_names = _extract_class_fields(node)

            extracted_methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method = ExtractedMethod(
                        name=item.name,
                        file_path=rel_path,
                        module_name=module_name,
                        class_name=node.name,
                        signature=_get_function_signature(item),
                        code=_get_source_segment(source_lines, item),
                    )
                    extracted_methods.append(method)
                    result.methods.append(method)

            for fname in field_names:
                field_obj = ExtractedField(
                    name=fname,
                    file_path=rel_path,
                    module_name=module_name,
                    class_name=node.name,
                )
                result.fields.append(field_obj)

            result.classes.append(ExtractedClass(
                name=node.name,
                file_path=rel_path,
                module_name=module_name,
                signature=class_sig,
                code=class_code,
                base_classes=base_classes,
                methods=extracted_methods,
                fields=field_names,
            ))

        # ── Global variables (module-level assignments) ───
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result.global_variables.append(ExtractedGlobalVariable(
                        name=target.id,
                        file_path=rel_path,
                        module_name=module_name,
                        code=_get_source_segment(source_lines, node),
                    ))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                result.global_variables.append(ExtractedGlobalVariable(
                    name=node.target.id,
                    file_path=rel_path,
                    module_name=module_name,
                    code=_get_source_segment(source_lines, node),
                ))

    return result


# ═══════════════════════════════════════════
# Main extraction: whole repo
# ═══════════════════════════════════════════

def shallow_index_repo(repo_root: str) -> ShallowIndexResult:
    """
    Phase 1: Scan all .py files in the repo and extract symbols.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        ShallowIndexResult aggregating all files.
    """
    repo_root = os.path.abspath(repo_root)
    aggregate = ShallowIndexResult()
    file_count = 0

    for root, dirs, files in os.walk(repo_root):
        # Skip common non-source directories
        dirs[:] = [
            d for d in dirs
            if d not in {
                ".git", ".hg", ".svn", "__pycache__", ".mypy_cache",
                ".pytest_cache", "node_modules", ".tox", ".venv", "venv",
                "env", ".env", ".eggs", "*.egg-info",
            }
        ]

        for fname in files:
            if not fname.endswith(".py"):
                continue

            file_path = os.path.join(root, fname)
            file_result = extract_file(file_path, repo_root)

            aggregate.modules.extend(file_result.modules)
            aggregate.classes.extend(file_result.classes)
            aggregate.functions.extend(file_result.functions)
            aggregate.methods.extend(file_result.methods)
            aggregate.fields.extend(file_result.fields)
            aggregate.global_variables.extend(file_result.global_variables)
            file_count += 1

    logger.info("Shallow index complete — scanned %d files. %s", file_count, aggregate.summary())
    return aggregate
