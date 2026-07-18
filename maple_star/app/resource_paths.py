from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResourceResolver:
    source_root: Path
    frozen_root: Path | None = None

    @classmethod
    def for_runtime(cls) -> "ResourceResolver":
        source_root = Path(__file__).resolve().parents[2]
        bundle = getattr(sys, "_MEIPASS", None)
        return cls(source_root=source_root, frozen_root=Path(bundle) if bundle else None)

    def resolve(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("resource path must stay relative to the application root")
        return (self.frozen_root or self.source_root).joinpath(relative)


__all__ = ["ResourceResolver"]
