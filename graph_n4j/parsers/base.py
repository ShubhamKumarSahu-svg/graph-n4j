"""Language-neutral extraction records, using UTF-8 byte source locations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceReference:
    file_path: str
    start_line: int
    end_line: int
    byte_start: int
    byte_end: int


@dataclass
class ParsedSymbol:
    label: str
    name: str
    source: SourceReference
    class_name: str = ""
    signature: str = ""
    code: str = ""
    docstring: str = ""

    def properties(self) -> dict[str, Any]:
        # Neo4j stores source ranges as scalar properties alongside each symbol.
        return dict(
            name=self.name,
            file_path=self.source.file_path,
            class_name=self.class_name,
            signature=self.signature,
            code=self.code,
            docstring=self.docstring,
            start_line=self.source.start_line,
            end_line=self.source.end_line,
            byte_start=self.source.byte_start,
            byte_end=self.source.byte_end,
        )


@dataclass
class ParsedReference:
    kind: str
    target: str
    source: ParsedSymbol
    alias: str = ""


@dataclass
class ParsedFile:
    module: ParsedSymbol
    symbols: list[ParsedSymbol] = field(default_factory=list)
    references: list[ParsedReference] = field(default_factory=list)
    content_hash: str = ""


class BaseLanguageParser(ABC):
    @abstractmethod
    def parse(self, source: bytes, file_path: str) -> ParsedFile:
        """Parse once and extract symbols and reference sites."""
