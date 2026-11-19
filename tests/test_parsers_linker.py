from graph_n4j.indexer.linker import TopologicalLinker
from graph_n4j.indexer.symbol_table import SymbolTable
from graph_n4j.parsers.cpp_parser import CppParser
from graph_n4j.parsers.python_parser import PythonParser


def test_python_symbols_and_cross_file_calls():
    parser = PythonParser()
    base = parser.parse(
        (
            b"class Base:\n    value = 1\n    def helper(self):\n        return "
            b"self.value\n\ndef utility():\n    return 1\n"
        ),
        "pkg/base.py",
    )
    child = parser.parse(
        (
            b"from .base import Base as B, utility as u\nclass Child(B):\n    "
            b"def run(self):\n        self.x = 1\n        return u()\n"
        ),
        "pkg/child.py",
    )
    edges = TopologicalLinker(SymbolTable([base, child])).link()
    assert any(
        e["source"]["name"] == "Child" and e["target"]["name"] == "Base" for e in edges["INHERITS"]
    )
    assert any(
        e["source"]["name"] == "run" and e["target"]["name"] == "utility" for e in edges["CALLS"]
    )
    assert any(
        e["source"]["name"] == "Child" and e["target"]["name"] == "helper"
        for e in edges["HAS_METHOD"]
    )
    assert any(s.label == "FIELD" and s.name == "x" for s in child.symbols)
    assert edges["USES"]


def test_cpp_symbols_and_calls():
    parser = CppParser()
    header = parser.parse(
        (
            b"struct Base { int value; void helper() {} }; class Child : public "
            b"Base { public: void run(); };"
        ),
        "base.hpp",
    )
    impl = parser.parse(
        (
            b'#include "base.hpp"\nint global = 1;\nint utility() { return '
            b"global; }\nvoid Child::run() { utility(); }"
        ),
        "main.cpp",
    )
    assert any(
        s.label == "METHOD" and s.name == "run" and s.class_name == "Child" for s in impl.symbols
    )
    edges = TopologicalLinker(SymbolTable([header, impl])).link()
    assert any(
        e["source"]["name"] == "run" and e["target"]["name"] == "utility" for e in edges["CALLS"]
    )
    assert any(e["source"]["name"] == "Child" for e in edges["INHERITS"])


def test_ambiguous_cross_file_names_are_not_guessed():
    parser = PythonParser()
    a = parser.parse(b"def same(): pass", "a.py")
    b = parser.parse(b"def same(): pass", "b.py")
    c = parser.parse(b"def run(): same()", "c.py")
    assert not TopologicalLinker(SymbolTable([a, b, c])).link().get("CALLS")
