from pathlib import Path

import tree_sitter_c
from tree_sitter import Language

from graph_n4j.parsers.base import BaseLanguageParser
from graph_n4j.parsers.cpp_parser import CppParser
from graph_n4j.parsers.python_parser import PythonParser


class ParserRegistry:
    def __init__(self):
        self.parsers: dict[str, BaseLanguageParser] = {}
        self.register(PythonParser(), [".py"])
        self.register(CppParser(Language(tree_sitter_c.language())), [".c"])
        # A header may contain C++ declarations even when it ends in .h.
        self.register(CppParser(), [".cpp", ".hpp", ".h", ".cc", ".cxx", ".hxx"])

    def register(self, parser: BaseLanguageParser, extensions: list[str]) -> None:
        for extension in extensions:
            self.parsers[extension] = parser

    def get(self, file_path: str) -> BaseLanguageParser:
        try:
            return self.parsers[Path(file_path).suffix.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported source file: {file_path}") from exc
