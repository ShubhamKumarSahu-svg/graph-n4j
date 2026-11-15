"""Python extraction through one Tree-sitter CST traversal."""

from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from graph_n4j.parsers.base import (
    BaseLanguageParser,
    ParsedFile,
    ParsedReference,
    ParsedSymbol,
    SourceReference,
)


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class PythonParser(BaseLanguageParser):
    def __init__(self):
        self.parser = Parser(Language(tree_sitter_python.language()))

    def parse(self, source: bytes, file_path: str) -> ParsedFile:
        root = self.parser.parse(source).root_node

        def text(node: Node | None) -> str:
            return source[node.start_byte : node.end_byte].decode("utf-8") if node else ""

        def symbol(node: Node, label: str, name: str, owner: str = "") -> ParsedSymbol:
            body = node.child_by_field_name("body")
            signature = (
                source[node.start_byte : body.start_byte].decode("utf-8").strip()
                if body
                else text(node)
            )
            doc = ""
            if body and body.named_children:
                first = body.named_children[0]
                if (
                    first.type == "expression_statement"
                    and first.named_children
                    and first.named_children[0].type == "string"
                ):
                    doc = text(first.named_children[0]).strip("'\"")
            return ParsedSymbol(
                label,
                name,
                SourceReference(
                    file_path,
                    node.start_point.row + 1,
                    node.end_point.row + 1,
                    node.start_byte,
                    node.end_byte,
                ),
                owner,
                signature,
                text(node),
                doc,
            )

        module = symbol(root, "MODULE", module_name(file_path))
        result = ParsedFile(module, [module])

        def visit(
            node: Node,
            owner: str = "",
            scope: ParsedSymbol = module,
            enclosing: tuple[ParsedSymbol, ...] = (),
        ):
            if node.type in ("class_definition", "function_definition"):
                name = text(node.child_by_field_name("name"))
                label = (
                    "CLASS"
                    if node.type == "class_definition"
                    else ("METHOD" if owner and scope.label == "CLASS" else "FUNCTION")
                )
                # Nested names retain lexical identity without collapsing siblings.
                if scope.label in ("FUNCTION", "METHOD"):
                    name = scope.name + "." + name
                item = symbol(node, label, name, owner if label in ("METHOD", "FUNCTION") else "")
                if scope.label in ("FUNCTION", "METHOD"):
                    enclosing = (*enclosing, scope)
                result.symbols.append(item)
                if label == "CLASS":
                    bases = node.child_by_field_name("superclasses")
                    if bases:
                        for base in bases.named_children:
                            result.references.append(ParsedReference("INHERITS", text(base), item))
                    owner = name
                scope = item
            elif node.type in ("import_statement", "import_from_statement"):
                mod = text(node.child_by_field_name("module_name"))
                for child in node.named_children:
                    if child == node.child_by_field_name("module_name"):
                        continue
                    if child.type == "aliased_import":
                        name = text(child.child_by_field_name("name"))
                        alias = text(child.child_by_field_name("alias"))
                    else:
                        name, alias = text(child), text(child).split(".")[0]
                    target = f"{mod}.{name}" if mod and not mod.endswith(".") else mod + name
                    result.references.append(
                        ParsedReference("IMPORTS", target, module, alias or name)
                    )
            elif node.type in ("assignment", "augmented_assignment"):
                left = node.child_by_field_name("left")
                if left:
                    targets = (
                        left.named_children
                        if left.type in ("pattern_list", "tuple_pattern", "list_pattern")
                        else [left]
                    )
                    for assignment_target in targets:
                        name = text(assignment_target)
                        label = ""
                        field_owner = owner
                        if scope.label == "MODULE" and assignment_target.type == "identifier":
                            label = "GLOBAL_VARIABLE"
                        elif scope.label == "CLASS" and assignment_target.type == "identifier":
                            label = "FIELD"
                        elif name.startswith(("self.", "cls.")):
                            label, name = "FIELD", name.split(".", 1)[1]
                        if label:
                            result.symbols.append(
                                symbol(node, label, name, field_owner if label == "FIELD" else "")
                            )
            elif node.type == "call" and scope.label in ("FUNCTION", "METHOD"):
                result.references.append(
                    ParsedReference("CALLS", text(node.child_by_field_name("function")), scope)
                )
            elif node.type in ("identifier", "attribute") and scope.label in ("FUNCTION", "METHOD"):
                for lexical_scope in (*enclosing, scope):
                    result.references.append(ParsedReference("USES", text(node), lexical_scope))
            for child in node.named_children:
                visit(child, owner, scope, enclosing)

        visit(root)
        return result
