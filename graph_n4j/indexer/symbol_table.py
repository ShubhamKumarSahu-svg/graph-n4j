"""Repository-scoped symbol indexes. Ambiguous matches remain unresolved."""

from collections import defaultdict

from graph_n4j.parsers.base import ParsedFile, ParsedSymbol


class SymbolTable:
    def __init__(self, files: list[ParsedFile]):
        self.files = {f.module.source.file_path: f for f in files}
        self.by_name: dict[str, list[ParsedSymbol]] = defaultdict(list)
        self.by_file: dict[str, list[ParsedSymbol]] = defaultdict(list)
        self.modules = {f.module.name: f for f in files}
        for file in files:
            for symbol in file.symbols:
                self.by_name[symbol.name].append(symbol)
                self.by_file[symbol.source.file_path].append(symbol)

    @staticmethod
    def unique(candidates: list[ParsedSymbol]) -> ParsedSymbol | None:
        # A repeated declaration can share an identity. Distinct owners make a name ambiguous.
        keys = {(s.label, s.name, s.source.file_path, s.class_name): s for s in candidates}
        return next(iter(keys.values())) if len(keys) == 1 else None
