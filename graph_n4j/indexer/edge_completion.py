"""
edge_completion.py — Phase 2 of the CodexGraph indexing pipeline.

Second pass that resolves cross-file relationships:
  - Resolves relative imports to absolute dotted paths
  - Establishes CONTAINS edges (MODULE -> CLASS/FUNCTION/GLOBAL_VARIABLE)
  - Records INHERITS edges per class (including multiple inheritance)
  - Creates HAS_METHOD and HAS_FIELD edges
  - Propagates inherited FIELD/METHOD edges down the inheritance hierarchy
  - Detects USES edges (FUNCTION/METHOD -> GLOBAL_VARIABLE/FIELD)

All edges are written via MERGE (idempotent).
"""

import ast
import os
import logging
from typing import Optional

from graph_n4j.graph_db import GraphDB
from graph_n4j.indexer.shallow_index import ShallowIndexResult, ExtractedClass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# Import resolution helpers
# ═══════════════════════════════════════════

def _resolve_relative_import(
    current_module: str,
    import_module: str,
    level: int,
) -> str:
    """
    Resolve a relative import to an absolute dotted module path.

    Args:
        current_module: Dotted path of the importing module, e.g. "pkg.sub.mod"
        import_module:  The module string from the import (may be empty for 'from . import X')
        level:          Number of dots (0 = absolute, 1 = '.', 2 = '..', etc.)

    Returns:
        Absolute dotted module path.
    """
    if level == 0:
        return import_module

    parts = current_module.split(".")
    # Go up `level` packages
    if level >= len(parts):
        base = ""
    else:
        base = ".".join(parts[:-level])

    if import_module:
        return f"{base}.{import_module}" if base else import_module
    return base


def _build_module_lookup(index: ShallowIndexResult) -> dict[str, str]:
    """
    Build a mapping: module_name -> file_path for fast resolution.
    """
    return {m.name: m.file_path for m in index.modules}


def _build_class_lookup(index: ShallowIndexResult) -> dict[str, list[ExtractedClass]]:
    """
    Build a mapping: class_name -> [ExtractedClass, ...] (may have duplicates across files).
    """
    lookup: dict[str, list[ExtractedClass]] = {}
    for cls in index.classes:
        lookup.setdefault(cls.name, []).append(cls)
    return lookup


def _build_import_resolution_map(index: ShallowIndexResult) -> dict[str, dict[str, str]]:
    """
    For each module, build a map of imported names to their resolved module paths.

    Returns:
        {module_name: {imported_name: resolved_module_path, ...}, ...}
    """
    module_lookup = _build_module_lookup(index)
    resolution_map: dict[str, dict[str, str]] = {}

    for mod in index.modules:
        name_map: dict[str, str] = {}
        for imp in mod.imports:
            resolved_module = _resolve_relative_import(
                mod.name, imp["module"], imp["level"]
            )
            for name in imp["names"]:
                # 'from pkg.module import ClassName' -> ClassName resolves to pkg.module
                name_map[name] = resolved_module
            if imp["alias"]:
                name_map[imp["alias"]] = resolved_module
        resolution_map[mod.name] = name_map

    return resolution_map


# ═══════════════════════════════════════════
# USES edge detection via AST DFS
# ═══════════════════════════════════════════

def _detect_uses_in_function(
    func_node: ast.AST,
    known_globals: set[str],
    known_fields: dict[str, set[str]],  # class_name -> {field_names}
) -> list[dict]:
    """
    Walk a function/method AST to find references to known globals and fields.

    Returns list of dicts with keys:
      target_name, target_type ("GLOBAL_VARIABLE" or "FIELD"),
      target_class (if FIELD), association_type
    """
    uses = []
    for node in ast.walk(func_node):
        # Global variable access: bare Name that matches a known global
        if isinstance(node, ast.Name) and node.id in known_globals:
            uses.append({
                "target_name": node.id,
                "target_type": "GLOBAL_VARIABLE",
                "target_class": None,
                "source_association_type": "reference",
                "target_association_type": "global",
            })

        # Field access via self.attr or ClassName.attr
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                accessor = node.value.id
                attr = node.attr
                # self.field
                if accessor == "self":
                    # We'll resolve the class in the caller
                    uses.append({
                        "target_name": attr,
                        "target_type": "FIELD",
                        "target_class": "__self__",  # placeholder, resolved by caller
                        "source_association_type": "attribute",
                        "target_association_type": "instance",
                    })
                # ClassName.field
                elif accessor in known_fields and attr in known_fields[accessor]:
                    uses.append({
                        "target_name": attr,
                        "target_type": "FIELD",
                        "target_class": accessor,
                        "source_association_type": "attribute",
                        "target_association_type": "class",
                    })

    return uses


# ═══════════════════════════════════════════
# Main edge completion
# ═══════════════════════════════════════════

def complete_edges(
    index: ShallowIndexResult,
    db: GraphDB,
    repo_root: str,
    repo_id: str = "",
    commit_sha: str = "",
):
    """
    Phase 2: Resolve all cross-file relationships and write edges to Neo4j.
    All nodes/edges are tagged with repo_id and commit_sha for multi-repo support.
    """
    repo_root = os.path.abspath(repo_root)
    module_lookup = _build_module_lookup(index)
    class_lookup = _build_class_lookup(index)
    import_map = _build_import_resolution_map(index)

    # ── Step 1: Write all nodes ───────────────────────────
    logger.info("Writing nodes to Neo4j...")

    for mod in index.modules:
        db.merge_module(mod.name, mod.file_path, repo_id=repo_id, commit_sha=commit_sha)

    for cls in index.classes:
        db.merge_class(cls.name, cls.file_path, cls.signature, cls.code,
                       repo_id=repo_id, commit_sha=commit_sha)

    for func in index.functions:
        db.merge_function(func.name, func.file_path, func.signature, func.code,
                          repo_id=repo_id, commit_sha=commit_sha)

    for method in index.methods:
        db.merge_method(
            method.name, method.file_path, method.class_name,
            method.signature, method.code,
            repo_id=repo_id, commit_sha=commit_sha,
        )

    for fld in index.fields:
        db.merge_field(fld.name, fld.file_path, fld.class_name,
                       repo_id=repo_id, commit_sha=commit_sha)

    for gv in index.global_variables:
        db.merge_global_variable(gv.name, gv.file_path, gv.code,
                                 repo_id=repo_id, commit_sha=commit_sha)

    logger.info("All nodes written.")

    # ── Step 2: CONTAINS edges ────────────────────────────
    logger.info("Creating CONTAINS edges...")

    for cls in index.classes:
        db.merge_contains(cls.module_name, cls.file_path, cls.name, cls.file_path, "CLASS",
                          repo_id=repo_id)

    for func in index.functions:
        db.merge_contains(func.module_name, func.file_path, func.name, func.file_path, "FUNCTION",
                          repo_id=repo_id)

    for gv in index.global_variables:
        db.merge_contains(gv.module_name, gv.file_path, gv.name, gv.file_path, "GLOBAL_VARIABLE",
                          repo_id=repo_id)

    # ── Step 3: HAS_METHOD and HAS_FIELD edges ────────────
    logger.info("Creating HAS_METHOD and HAS_FIELD edges...")

    for cls in index.classes:
        for method in cls.methods:
            db.merge_has_method(cls.name, cls.file_path, method.name, method.file_path,
                               repo_id=repo_id)
        for field_name in cls.fields:
            db.merge_has_field(cls.name, cls.file_path, field_name, cls.file_path,
                              repo_id=repo_id)

    # ── Step 4: INHERITS edges ────────────────────────────
    logger.info("Resolving INHERITS edges...")

    for cls in index.classes:
        for base_name in cls.base_classes:
            parent_file = _resolve_base_class(
                base_name, cls.module_name, class_lookup, import_map, module_lookup
            )
            if parent_file:
                db.merge_inherits(cls.name, cls.file_path, base_name, parent_file,
                                  repo_id=repo_id)
                logger.debug("  %s -> %s (in %s)", cls.name, base_name, parent_file)
            else:
                # Could be a builtin or external class — skip silently
                logger.debug(
                    "  Could not resolve base class '%s' for '%s'", base_name, cls.name
                )

    # ── Step 5: Propagate inherited methods/fields ────────
    logger.info("Propagating inherited methods and fields...")
    _propagate_inheritance(index, db, class_lookup, repo_id=repo_id)

    # ── Step 6: USES edges ────────────────────────────────
    logger.info("Detecting USES edges...")
    _create_uses_edges(index, db, repo_root, repo_id=repo_id)

    logger.info("Edge completion finished.")


def _resolve_base_class(
    base_name: str,
    current_module: str,
    class_lookup: dict[str, list[ExtractedClass]],
    import_map: dict[str, dict[str, str]],
    module_lookup: dict[str, str],
) -> Optional[str]:
    """
    Resolve a base class name to its file_path.

    Strategy:
      1. If base_name contains '.', treat as dotted path and resolve
      2. Check if it's imported in the current module
      3. Check if it's defined in the current file
      4. Check all known classes with that simple name
    """
    # Handle dotted names like module.ClassName
    if "." in base_name:
        parts = base_name.rsplit(".", 1)
        # Try to find the class name
        simple_name = parts[-1]
        if simple_name in class_lookup:
            for cls in class_lookup[simple_name]:
                return cls.file_path
        return None

    # Check imports of the current module
    if current_module in import_map:
        imp = import_map[current_module]
        if base_name in imp:
            resolved_module = imp[base_name]
            # Find the class in that module
            if base_name in class_lookup:
                for cls in class_lookup[base_name]:
                    if cls.module_name == resolved_module:
                        return cls.file_path
                # If exact module match fails, return first match
                return class_lookup[base_name][0].file_path

    # Check same file
    if base_name in class_lookup:
        for cls in class_lookup[base_name]:
            if cls.module_name == current_module:
                return cls.file_path
        # Fallback: return first known definition
        return class_lookup[base_name][0].file_path

    return None


def _propagate_inheritance(
    index: ShallowIndexResult,
    db: GraphDB,
    class_lookup: dict[str, list[ExtractedClass]],
    repo_id: str = "",
):
    """
    For each class, propagate methods and fields from parent classes.
    Creates HAS_METHOD and HAS_FIELD edges from child to inherited members.
    """
    # Build inheritance chains (simple BFS)
    for cls in index.classes:
        visited = set()
        queue = list(cls.base_classes)

        while queue:
            parent_name = queue.pop(0)
            if parent_name in visited:
                continue
            visited.add(parent_name)

            # Handle dotted names
            simple_parent = parent_name.rsplit(".", 1)[-1] if "." in parent_name else parent_name

            if simple_parent not in class_lookup:
                continue

            for parent_cls in class_lookup[simple_parent]:
                # Propagate methods not already defined in child
                child_method_names = {m.name for m in cls.methods}
                for method in parent_cls.methods:
                    if method.name not in child_method_names:
                        # Create an inherited method edge from child class
                        db.merge_has_method(
                            cls.name, cls.file_path,
                            method.name, method.file_path,
                            repo_id=repo_id,
                        )

                # Propagate fields not already defined in child
                child_field_names = set(cls.fields)
                for field_name in parent_cls.fields:
                    if field_name not in child_field_names:
                        db.merge_has_field(
                            cls.name, cls.file_path,
                            field_name, parent_cls.file_path,
                            repo_id=repo_id,
                        )

                # Continue up the chain
                queue.extend(parent_cls.base_classes)


def _create_uses_edges(
    index: ShallowIndexResult,
    db: GraphDB,
    repo_root: str,
    repo_id: str = "",
):
    """
    Parse function/method bodies to detect USES relationships.
    """
    # Build lookup sets
    known_globals = {gv.name for gv in index.global_variables}
    known_fields: dict[str, set[str]] = {}
    for cls in index.classes:
        known_fields[cls.name] = set(cls.fields)

    # Global variable file lookup
    gv_file_lookup: dict[str, str] = {}
    for gv in index.global_variables:
        gv_file_lookup[gv.name] = gv.file_path

    # Field file lookup: (class_name, field_name) -> file_path
    field_file_lookup: dict[tuple[str, str], str] = {}
    for fld in index.fields:
        field_file_lookup[(fld.class_name, fld.name)] = fld.file_path

    # Process functions
    for func in index.functions:
        file_path = os.path.join(repo_root, func.file_path)
        func_ast = _parse_function_from_file(file_path, func.name, is_method=False)
        if func_ast is None:
            continue

        uses = _detect_uses_in_function(func_ast, known_globals, known_fields)
        for use in uses:
            if use["target_type"] == "GLOBAL_VARIABLE":
                target_file = gv_file_lookup.get(use["target_name"])
                if target_file:
                    db.merge_uses(
                        source_name=func.name,
                        source_label="FUNCTION",
                        source_file=func.file_path,
                        target_name=use["target_name"],
                        target_label="GLOBAL_VARIABLE",
                        target_file=target_file,
                        source_association_type=use["source_association_type"],
                        target_association_type=use["target_association_type"],
                        repo_id=repo_id,
                    )

    # Process methods
    for method in index.methods:
        file_path = os.path.join(repo_root, method.file_path)
        method_ast = _parse_function_from_file(
            file_path, method.name, is_method=True, class_name=method.class_name
        )
        if method_ast is None:
            continue

        uses = _detect_uses_in_function(method_ast, known_globals, known_fields)
        for use in uses:
            if use["target_type"] == "GLOBAL_VARIABLE":
                target_file = gv_file_lookup.get(use["target_name"])
                if target_file:
                    db.merge_uses(
                        source_name=method.name,
                        source_label="METHOD",
                        source_file=method.file_path,
                        source_class=method.class_name,
                        target_name=use["target_name"],
                        target_label="GLOBAL_VARIABLE",
                        target_file=target_file,
                        source_association_type=use["source_association_type"],
                        target_association_type=use["target_association_type"],
                        repo_id=repo_id,
                    )
            elif use["target_type"] == "FIELD":
                target_class = use["target_class"]
                # Resolve __self__ placeholder
                if target_class == "__self__":
                    target_class = method.class_name
                target_file = field_file_lookup.get((target_class, use["target_name"]))
                if target_file:
                    db.merge_uses(
                        source_name=method.name,
                        source_label="METHOD",
                        source_file=method.file_path,
                        source_class=method.class_name,
                        target_name=use["target_name"],
                        target_label="FIELD",
                        target_file=target_file,
                        target_class=target_class,
                        source_association_type=use["source_association_type"],
                        target_association_type=use["target_association_type"],
                        repo_id=repo_id,
                    )


def _parse_function_from_file(
    file_path: str,
    func_name: str,
    is_method: bool = False,
    class_name: Optional[str] = None,
) -> Optional[ast.AST]:
    """
    Re-parse a file and find the specific function/method AST node.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except Exception:
        return None

    if is_method and class_name:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == func_name:
                            return item
    else:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    return node

    return None
