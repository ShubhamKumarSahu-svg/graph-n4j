"""Resolve static references in memory, preserving uncertainty for dynamic calls."""

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from graph_n4j.indexer.symbol_table import SymbolTable
from graph_n4j.parsers.base import ParsedFile, ParsedSymbol


def endpoint(symbol: ParsedSymbol) -> dict[str, str]:
    return dict(name=symbol.name, file_path=symbol.source.file_path, class_name=symbol.class_name)


class TopologicalLinker:
    def __init__(self, table: SymbolTable):
        self.table = table
        self.dependencies: dict[str, set[str]] = defaultdict(set)
        self.imports: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        self.edges: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(self, kind: str, source: ParsedSymbol, target: ParsedSymbol):
        self.edges[kind].append(
            dict(
                source_label=source.label,
                target_label=target.label,
                source=endpoint(source),
                target=endpoint(target),
            )
        )

    def import_target(self, file: ParsedFile, target: str) -> tuple[str, str] | None:
        path = file.module.source.file_path
        if "/" in target or target.endswith((".h", ".hpp")):
            local = str(PurePosixPath(path).parent / target)
            candidates = [
                p for p in self.table.files if p == local or p == target or p.endswith("/" + target)
            ]
            if len(candidates) == 1:
                return candidates[0], ""
            return None
        if target.startswith("."):
            dots = len(target) - len(target.lstrip("."))
            package = file.module.name.split(".")
            if not path.endswith("__init__.py"):
                package.pop()
            package = package[: len(package) - dots + 1]
            target = ".".join(package + [target[dots:]])
        parts = target.split(".")
        for count in range(len(parts), 0, -1):
            name = ".".join(parts[:count])
            if name in self.table.modules:
                return self.table.modules[name].module.source.file_path, ".".join(parts[count:])
        return None

    def resolve(
        self, file: ParsedFile, source: ParsedSymbol, target: str, labels: tuple[str, ...]
    ) -> ParsedSymbol | None:
        target = target.replace("->", ".").replace("::", ".")
        parts = target.split(".")
        path = file.module.source.file_path
        candidates: list[ParsedSymbol] = []
        if parts[0] in self.imports[path]:
            imported_path, imported_name = self.imports[path][parts[0]]
            name = ".".join(filter(None, (imported_name, *parts[1:])))
            candidates = [
                s
                for s in self.table.by_file[imported_path]
                if (not s.class_name and s.name.replace("::", ".") == name)
                or (s.class_name.replace("::", ".") + "." + s.name) == name
            ]
        elif len(parts) > 1:
            owner = (
                source.class_name if parts[0] in ("self", "cls", "this") else ".".join(parts[:-1])
            )
            candidates = [
                s
                for s in self.table.by_name[parts[-1]]
                if s.class_name.replace("::", ".") == owner
                and (s.source.file_path == path or s.source.file_path in self.dependencies[path])
            ]
        else:
            candidates = [s for s in self.table.by_name[target] if s.source.file_path == path]
            if source.class_name:
                owned = [s for s in candidates if s.class_name == source.class_name]
                candidates = owned or candidates
            if not candidates:
                candidates = [
                    s
                    for s in self.table.by_name[target]
                    if s.source.file_path in self.dependencies[path]
                ]
        return self.table.unique([s for s in candidates if s.label in labels])

    def link(self) -> dict[str, list[dict[str, Any]]]:
        for path, file in self.table.files.items():
            for ref in file.references:
                if ref.kind != "IMPORTS":
                    continue
                resolved = self.import_target(file, ref.target)
                if resolved:
                    imported_path, name = resolved
                    self.dependencies[path].add(imported_path)
                    self.imports[path][ref.alias or ref.target] = (imported_path, name)
                    self.add("IMPORTS", file.module, self.table.files[imported_path].module)
            for symbol in file.symbols:
                if symbol.label == "MODULE":
                    continue
                if symbol.label in ("METHOD", "FIELD"):
                    owners = [
                        s
                        for s in self.table.by_name[symbol.class_name]
                        if s.label == "CLASS"
                        and (
                            s.source.file_path == path
                            or s.source.file_path in self.dependencies[path]
                        )
                    ]
                    owner = self.table.unique(owners)
                    if owner:
                        self.add(
                            "HAS_METHOD" if symbol.label == "METHOD" else "HAS_FIELD", owner, symbol
                        )
                else:
                    self.add("CONTAINS", file.module, symbol)
        # Resolve call sites once every file has contributed its imports and owners.
        for file in self.table.files.values():
            for ref in file.references:
                labels = {
                    "CALLS": ("FUNCTION", "METHOD"),
                    "INHERITS": ("CLASS",),
                    "USES": ("FIELD", "GLOBAL_VARIABLE"),
                }.get(ref.kind)
                if labels:
                    target = self.resolve(file, ref.source, ref.target, labels)
                    if target:
                        self.add(ref.kind, ref.source, target)
        # Propagate inherited members to a fixed point, including multi-level inheritance.
        inherited = list(self.edges["INHERITS"])
        for kind in ("HAS_METHOD", "HAS_FIELD"):
            seen = {(str(e["source"]), str(e["target"])) for e in self.edges[kind]}
            changed = True
            while changed:
                changed = False
                for relation in inherited:
                    for member in list(self.edges[kind]):
                        if member["source"] == relation["target"]:
                            edge = dict(member, source=relation["source"])
                            key = (str(edge["source"]), str(edge["target"]))
                            if key not in seen:
                                seen.add(key)
                                self.edges[kind].append(edge)
                                changed = True
        return dict(self.edges)
