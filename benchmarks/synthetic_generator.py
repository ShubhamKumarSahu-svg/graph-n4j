"""Generate a deterministic Python/C++ repository for indexing comparisons."""

from pathlib import Path


def generate(root: Path, count: int = 20, language: str = "python") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        if language == "python":
            (root / f"module_{index}.py").write_text(
                f"VALUE_{index} = {index}\n\n"
                f"def helper_{index}():\n    return VALUE_{index}\n\n"
                f"def run_{index}():\n    return helper_{index}()\n\n"
                f"class Item{index}:\n    value = {index}\n"
                f"    def run(self):\n        return helper_{index}()\n"
            )
        else:
            (root / f"module_{index}.cpp").write_text(
                f"int value_{index} = {index};\n"
                f"int helper_{index}() {{ return value_{index}; }}\n"
                f"int run_{index}() {{ return helper_{index}(); }}\n"
            )
