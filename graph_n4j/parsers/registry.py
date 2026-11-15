from pathlib import Path

from graph_n4j.parsers.base import BaseLanguageParser
from graph_n4j.parsers.cpp_parser import CppParser
from graph_n4j.parsers.python_parser import PythonParser


class ParserRegistry:
    def __init__(self):
        self.parsers: dict[str, BaseLanguageParser] = {}
        self.register(PythonParser(), [".py"])
        self.register(CppParser(), [".cpp", ".hpp", ".h", ".cc", ".cxx", ".hxx"])

    def register(self, parser: BaseLanguageParser, extensions: list[str]) -> None:
        for extension in extensions:
            self.parsers[extension] = parser

    def get(self, file_path: str) -> BaseLanguageParser:
        try:
            return self.parsers[Path(file_path).suffix.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported source file: {file_path}") from exc
