from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    target: str = "--"
    workers: str = "--"
    hp_mp: str = "--"
    experience: str = "--"
    last_action: str = "--"
    metrics: dict[str, object] = field(default_factory=dict)

    def dashboard_values(self) -> dict[str, object]:
        return {
            "target": self.target,
            "workers": self.workers,
            "hp_mp": self.hp_mp,
            "experience": self.experience,
            "last_action": self.last_action,
        }


__all__ = ["RuntimeSnapshot"]
