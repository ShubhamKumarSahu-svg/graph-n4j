"""C++ CST extraction, including declarations and out-of-line methods."""

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from graph_n4j.parsers.base import (
    BaseLanguageParser,
    ParsedFile,
    ParsedReference,
    ParsedSymbol,
    SourceReference,
)
from graph_n4j.parsers.python_parser import module_name


class CppParser(BaseLanguageParser):
    def __init__(self):
        self.parser = Parser(Language(tree_sitter_cpp.language()))

    def parse(self, source: bytes, file_path: str) -> ParsedFile:
        root = self.parser.parse(source).root_node

        def text(node: Node | None) -> str:
            return source[node.start_byte : node.end_byte].decode("utf-8") if node else ""

        def make(node: Node, label: str, name: str, owner: str = "") -> ParsedSymbol:
            body = node.child_by_field_name("body")
            signature = (
                source[node.start_byte : body.start_byte].decode("utf-8").strip()
                if body
                else text(node)
            )
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
            )

        module = make(root, "MODULE", module_name(file_path))
        result = ParsedFile(module, [module])

        def declarator_name(node: Node | None) -> str:
            if node is None:
                return ""
            inner = node.child_by_field_name("declarator")
            return declarator_name(inner) if inner else text(node)

        def visit(node: Node, owner: str = "", scope: ParsedSymbol = module, namespace: str = ""):
            if node.type == "namespace_definition":
                name = text(node.child_by_field_name("name"))
                namespace = "::".join(filter(None, (namespace, name)))
            if node.type in ("class_specifier", "struct_specifier"):
                name = text(node.child_by_field_name("name"))
                if name:
                    owner = "::".join(filter(None, (namespace, name)))
                    scope = make(node, "CLASS", owner)
                    result.symbols.append(scope)
                    for child in node.named_children:
                        if child.type == "base_class_clause":
                            for base in child.named_children:
                                if base.type not in ("access_specifier",):
                                    result.references.append(
                                        ParsedReference("INHERITS", text(base), scope)
                                    )
            elif node.type == "function_definition":
                name = declarator_name(node.child_by_field_name("declarator"))
                method_owner = owner
                if "::" in name:
                    method_owner, name = name.rsplit("::", 1)
                if not method_owner and namespace:
                    name = namespace + "::" + name
                scope = make(node, "METHOD" if method_owner else "FUNCTION", name, method_owner)
                result.symbols.append(scope)
            elif node.type in ("field_declaration", "declaration"):
                for decl in node.children_by_field_name("declarator"):
                    name = declarator_name(decl)
                    # Function declarations are symbols too, allowing header references.
                    current = decl
                    while current.child_by_field_name("declarator"):
                        if current.type == "function_declarator":
                            break
                        next_declarator = current.child_by_field_name("declarator")
                        if next_declarator is None:
                            break
                        current = next_declarator
                    if current.type == "function_declarator":
                        result.symbols.append(
                            make(node, "METHOD" if owner else "FUNCTION", name, owner)
                        )
                    elif scope.label in ("MODULE", "CLASS") and name:
                        result.symbols.append(
                            make(node, "FIELD" if owner else "GLOBAL_VARIABLE", name, owner)
                        )
            elif node.type == "preproc_include":
                result.references.append(
                    ParsedReference(
                        "IMPORTS", text(node.child_by_field_name("path")).strip('"<>'), module
                    )
                )
            elif node.type == "call_expression" and scope.label in ("FUNCTION", "METHOD"):
                result.references.append(
                    ParsedReference("CALLS", text(node.child_by_field_name("function")), scope)
                )
            elif node.type in ("identifier", "field_expression") and scope.label in (
                "FUNCTION",
                "METHOD",
            ):
                result.references.append(ParsedReference("USES", text(node), scope))
            for child in node.named_children:
                visit(child, owner, scope, namespace)

        visit(root)
        return result
