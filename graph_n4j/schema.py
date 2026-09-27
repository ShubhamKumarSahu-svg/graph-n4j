"""
schema.py — Node/Edge type definitions and Cypher constraints for CodexGraph.

Defines the graph database schema per Section 3.1 / Appendix A.1 of the paper:
  - 6 node types: MODULE, CLASS, FUNCTION, METHOD, FIELD, GLOBAL_VARIABLE
  - 5 edge types: CONTAINS, HAS_METHOD, HAS_FIELD, INHERITS, USES

NOTE on storage efficiency (per the paper):
  The paper recommends storing `code` as an indexed pointer/reference to the source
  fragment to avoid duplicating large text in the DB. For this research prototype,
  we store code snippets directly as node properties in Neo4j for simplicity.
  In a production system, you'd store (file_path, start_line, end_line) and read
  the source on demand.
"""

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════
# Node type definitions
# ═══════════════════════════════════════════

@dataclass
class ModuleNode:
    """A Python module (file)."""
    name: str            # dotted module path, e.g. "pkg.subpkg.module"
    file_path: str       # absolute or repo-relative file path


@dataclass
class ClassNode:
    """A Python class definition."""
    name: str
    file_path: str
    signature: str       # class header, e.g. "class Foo(Bar, Baz):"
    code: str            # full source code of the class body
    base_classes: list[str] = field(default_factory=list)  # names of base classes


@dataclass
class FunctionNode:
    """A top-level (module-level) function."""
    name: str
    file_path: str
    signature: str       # e.g. "def foo(x: int, y: str) -> bool:"
    code: str            # full source code of the function


@dataclass
class MethodNode:
    """A method belonging to a class."""
    name: str
    file_path: str
    class_name: str      # the owning class
    signature: str
    code: str


@dataclass
class FieldNode:
    """A class-level attribute / field."""
    name: str
    file_path: str
    class_name: str      # the owning class


@dataclass
class GlobalVariableNode:
    """A module-level variable assignment."""
    name: str
    file_path: str
    code: str            # the assignment statement(s)


# ═══════════════════════════════════════════
# Edge type definitions
# ═══════════════════════════════════════════

@dataclass
class ContainsEdge:
    """MODULE -> (CLASS | FUNCTION | GLOBAL_VARIABLE)"""
    module_name: str
    target_name: str
    target_type: str     # "CLASS", "FUNCTION", or "GLOBAL_VARIABLE"


@dataclass
class HasMethodEdge:
    """CLASS -> METHOD"""
    class_name: str
    method_name: str
    file_path: str


@dataclass
class HasFieldEdge:
    """CLASS -> FIELD"""
    class_name: str
    field_name: str
    file_path: str


@dataclass
class InheritsEdge:
    """CLASS -> CLASS (base class). Supports multiple inheritance."""
    child_class: str
    parent_class: str
    child_file_path: str
    parent_file_path: Optional[str] = None  # resolved during edge completion


@dataclass
class UsesEdge:
    """
    (FUNCTION | METHOD) -> (GLOBAL_VARIABLE | FIELD)
    with association type attributes per the paper.
    """
    source_name: str
    source_type: str              # "FUNCTION" or "METHOD"
    source_class: Optional[str]   # class name if METHOD, else None
    target_name: str
    target_type: str              # "GLOBAL_VARIABLE" or "FIELD"
    target_class: Optional[str]   # class name if FIELD, else None
    source_file_path: str
    target_file_path: Optional[str] = None
    source_association_type: Optional[str] = None  # e.g. "local", "parameter"
    target_association_type: Optional[str] = None   # e.g. "attribute", "global"


# ═══════════════════════════════════════════
# Schema description for the Translation Agent
# ═══════════════════════════════════════════

SCHEMA_DESCRIPTION = """
## Neo4j Graph Database Schema -- CodexGraph

### IMPORTANT: Multi-repo scoping
All nodes have a `repo_id` property. You MUST include `repo_id: $repo_id` in
every MATCH pattern to scope queries to the correct repository. The `$repo_id`
parameter is automatically injected -- just use `$repo_id` in your Cypher.

### Node Types

All nodes share these common properties: `repo_id`, `commit_sha`

1. **MODULE**
   - Properties: `name` (dotted module path), `file_path`, `repo_id`, `commit_sha`
   - Represents a Python source file / module.

2. **CLASS**
   - Properties: `name`, `file_path`, `signature`, `code`, `repo_id`, `commit_sha`
   - Represents a class definition.

3. **FUNCTION**
   - Properties: `name`, `file_path`, `signature`, `code`, `repo_id`, `commit_sha`
   - Represents a top-level (module-level) function.

4. **METHOD**
   - Properties: `name`, `file_path`, `class_name`, `signature`, `code`, `repo_id`, `commit_sha`
   - Represents a method within a class.

5. **FIELD**
   - Properties: `name`, `file_path`, `class_name`, `repo_id`, `commit_sha`
   - Represents a class attribute / field.

6. **GLOBAL_VARIABLE**
   - Properties: `name`, `file_path`, `code`, `repo_id`, `commit_sha`
   - Represents a module-level variable assignment.

### Edge Types (Relationships)

1. **CONTAINS**: `(MODULE)-[:CONTAINS]->(CLASS | FUNCTION | GLOBAL_VARIABLE)`
   - A module contains classes, functions, and global variables.

2. **HAS_METHOD**: `(CLASS)-[:HAS_METHOD]->(METHOD)`
   - A class has methods.

3. **HAS_FIELD**: `(CLASS)-[:HAS_FIELD]->(FIELD)`
   - A class has fields/attributes.

4. **INHERITS**: `(CLASS)-[:INHERITS]->(CLASS)`
   - A class inherits from another class. Multiple inheritance is supported.

5. **USES**: `(FUNCTION | METHOD)-[:USES]->(GLOBAL_VARIABLE | FIELD)`
   - A function or method uses/accesses a global variable or field.
   - Properties: `source_association_type`, `target_association_type`

### Example Cypher Queries

- Find all classes in a module:
  `MATCH (m:MODULE {name: 'pkg.module', repo_id: $repo_id})-[:CONTAINS]->(c:CLASS) RETURN c.name, c.signature`

- Find inheritance chain for a class:
  `MATCH (c:CLASS {name: 'ChildClass', repo_id: $repo_id})-[:INHERITS*]->(parent:CLASS) RETURN parent.name, parent.file_path`

- Find all methods of a class (including inherited):
  `MATCH (c:CLASS {name: 'MyClass', repo_id: $repo_id})-[:HAS_METHOD]->(m:METHOD) RETURN m.name, m.signature, m.code`

- Find what global variables a function uses:
  `MATCH (f:FUNCTION {name: 'my_func', repo_id: $repo_id})-[:USES]->(gv:GLOBAL_VARIABLE) RETURN gv.name, gv.code`

- Find all classes that inherit from a base:
  `MATCH (c:CLASS {repo_id: $repo_id})-[:INHERITS]->(base:CLASS {name: 'BaseClass'}) RETURN c.name, c.file_path`
""".strip()


# ═══════════════════════════════════════════
# Cypher constraint & index creation statements
# ═══════════════════════════════════════════

SCHEMA_CONSTRAINTS = [
    # Uniqueness constraints — (name, file_path) pairs should be unique per type
    "CREATE CONSTRAINT module_unique IF NOT EXISTS FOR (n:MODULE) REQUIRE (n.name, n.file_path) IS UNIQUE",
    "CREATE CONSTRAINT class_unique IF NOT EXISTS FOR (n:CLASS) REQUIRE (n.name, n.file_path) IS UNIQUE",
    "CREATE CONSTRAINT function_unique IF NOT EXISTS FOR (n:FUNCTION) REQUIRE (n.name, n.file_path) IS UNIQUE",
    "CREATE CONSTRAINT method_unique IF NOT EXISTS FOR (n:METHOD) REQUIRE (n.name, n.class_name, n.file_path) IS UNIQUE",
    "CREATE CONSTRAINT field_unique IF NOT EXISTS FOR (n:FIELD) REQUIRE (n.name, n.class_name, n.file_path) IS UNIQUE",
    "CREATE CONSTRAINT globalvar_unique IF NOT EXISTS FOR (n:GLOBAL_VARIABLE) REQUIRE (n.name, n.file_path) IS UNIQUE",
]

SCHEMA_INDEXES = [
    # Indexes for fast lookups
    "CREATE INDEX module_name_idx IF NOT EXISTS FOR (n:MODULE) ON (n.name)",
    "CREATE INDEX class_name_idx IF NOT EXISTS FOR (n:CLASS) ON (n.name)",
    "CREATE INDEX function_name_idx IF NOT EXISTS FOR (n:FUNCTION) ON (n.name)",
    "CREATE INDEX method_name_idx IF NOT EXISTS FOR (n:METHOD) ON (n.name)",
    "CREATE INDEX field_name_idx IF NOT EXISTS FOR (n:FIELD) ON (n.name)",
    "CREATE INDEX globalvar_name_idx IF NOT EXISTS FOR (n:GLOBAL_VARIABLE) ON (n.name)",
    "CREATE INDEX file_path_module_idx IF NOT EXISTS FOR (n:MODULE) ON (n.file_path)",
    "CREATE INDEX file_path_class_idx IF NOT EXISTS FOR (n:CLASS) ON (n.file_path)",
    "CREATE INDEX file_path_function_idx IF NOT EXISTS FOR (n:FUNCTION) ON (n.file_path)",
    # repo_id indexes for multi-repo scoping
    "CREATE INDEX repo_id_module_idx IF NOT EXISTS FOR (n:MODULE) ON (n.repo_id)",
    "CREATE INDEX repo_id_class_idx IF NOT EXISTS FOR (n:CLASS) ON (n.repo_id)",
    "CREATE INDEX repo_id_function_idx IF NOT EXISTS FOR (n:FUNCTION) ON (n.repo_id)",
    "CREATE INDEX repo_id_method_idx IF NOT EXISTS FOR (n:METHOD) ON (n.repo_id)",
    "CREATE INDEX repo_id_field_idx IF NOT EXISTS FOR (n:FIELD) ON (n.repo_id)",
    "CREATE INDEX repo_id_globalvar_idx IF NOT EXISTS FOR (n:GLOBAL_VARIABLE) ON (n.repo_id)",
]
