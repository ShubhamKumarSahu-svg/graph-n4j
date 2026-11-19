"""Define the symbol and relationship types, Cypher constraints and indexes used by Neo4j."""

from dataclasses import dataclass, field
from typing import Optional

# Node type definitions


@dataclass
class ModuleNode:
    """A source file and its repository-relative identity."""

    name: str  # dotted module path, e.g. "pkg.subpkg.module"
    file_path: str  # absolute or repo-relative file path


@dataclass
class ClassNode:
    """A Python class definition."""

    name: str
    file_path: str
    signature: str  # class header, e.g. "class Foo(Bar, Baz):"
    code: str  # full source code of the class body
    base_classes: list[str] = field(default_factory=list)  # names of base classes


@dataclass
class FunctionNode:
    """A top-level (module-level) function."""

    name: str
    file_path: str
    signature: str  # e.g. "def foo(x: int, y: str) -> bool:"
    code: str  # full source code of the function


@dataclass
class MethodNode:
    """A method belonging to a class."""

    name: str
    file_path: str
    class_name: str  # the owning class
    signature: str
    code: str


@dataclass
class FieldNode:
    """A class-level attribute / field."""

    name: str
    file_path: str
    class_name: str  # the owning class


@dataclass
class GlobalVariableNode:
    """A module-level variable assignment."""

    name: str
    file_path: str
    code: str  # the assignment statement(s)


# Edge type definitions


@dataclass
class ContainsEdge:
    """MODULE -> (CLASS | FUNCTION | GLOBAL_VARIABLE)"""

    module_name: str
    target_name: str
    target_type: str  # "CLASS", "FUNCTION", or "GLOBAL_VARIABLE"


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
    source_type: str  # "FUNCTION" or "METHOD"
    source_class: Optional[str]  # class name if METHOD, else None
    target_name: str
    target_type: str  # "GLOBAL_VARIABLE" or "FIELD"
    target_class: Optional[str]  # class name if FIELD, else None
    source_file_path: str
    target_file_path: Optional[str] = None
    source_association_type: Optional[str] = None  # e.g. "local", "parameter"
    target_association_type: Optional[str] = None  # e.g. "attribute", "global"


# Schema description for the Translation Agent

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

6. **CALLS**: `(FUNCTION | METHOD)-[:CALLS]->(FUNCTION | METHOD)`
   - Statically resolved call sites. Dynamic or ambiguous dispatch remains unresolved.
7. **IMPORTS**: `(MODULE)-[:IMPORTS]->(MODULE)`

### Example Cypher Queries

- Find call hierarchy:
  `MATCH (f:FUNCTION {name: 'main', repo_id: $repo_id})-[:CALLS*1..5]->(callee {repo_id:
  $repo_id}) RETURN callee.name, callee.file_path`


- Find all classes in a module:
  `MATCH (m:MODULE {name: 'pkg.module', repo_id: $repo_id})-[:CONTAINS]->(c:CLASS) RETURN
  c.name, c.signature`

- Find inheritance chain for a class:
  `MATCH (c:CLASS {name: 'ChildClass', repo_id: $repo_id})-[:INHERITS*]->(parent:CLASS) RETURN
  parent.name, parent.file_path`

- Find all methods of a class (including inherited):
  `MATCH (c:CLASS {name: 'MyClass', repo_id: $repo_id})-[:HAS_METHOD]->(m:METHOD) RETURN m.name,
  m.signature, m.code`

- Find what global variables a function uses:
  `MATCH (f:FUNCTION {name: 'my_func', repo_id: $repo_id})-[:USES]->(gv:GLOBAL_VARIABLE) RETURN
  gv.name, gv.code`

- Find all classes that inherit from a base:
  `MATCH (c:CLASS {repo_id: $repo_id})-[:INHERITS]->(base:CLASS {name: 'BaseClass'}) RETURN
  c.name, c.file_path`
""".strip()


# Cypher constraint & index creation statements

NODE_LABELS = ("MODULE", "CLASS", "FUNCTION", "METHOD", "FIELD", "GLOBAL_VARIABLE")
EDGE_TYPES = ("CONTAINS", "HAS_METHOD", "HAS_FIELD", "INHERITS", "USES", "CALLS", "IMPORTS")

# New names avoid silently retaining the legacy, repository-global constraints.
SCHEMA_MIGRATIONS = [
    f"DROP CONSTRAINT {name}_unique IF EXISTS"
    for name in ("module", "class", "function", "method", "field", "globalvar")
]
SCHEMA_CONSTRAINTS = [
    f"CREATE CONSTRAINT {label.lower()}_repo_unique IF NOT EXISTS FOR (n:{label}) "
    "REQUIRE (n.name, n.file_path, n.repo_id"
    + (", n.class_name" if label in ("METHOD", "FIELD") else "")
    + ") IS UNIQUE"
    for label in NODE_LABELS
]
SCHEMA_INDEXES = [
    f"CREATE INDEX {label.lower()}_name_repo_idx IF NOT EXISTS FOR (n:{label}) "
    "ON (n.name, n.repo_id)"
    for label in NODE_LABELS
] + [
    "CREATE FULLTEXT INDEX symbol_search_idx IF NOT EXISTS "
    "FOR (n:CLASS|FUNCTION|METHOD|MODULE) ON EACH [n.name, n.signature, n.docstring]"
]
