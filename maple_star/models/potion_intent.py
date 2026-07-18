from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PotionIntent:
    session_epoch: str
    settings_generation: int
    target_generation: int
    resource: str
    vk_code: int
    created_at: float
    expires_at: float

    def __post_init__(self) -> None:
        if not self.session_epoch or self.resource not in {"hp", "mp"}:
            raise ValueError("invalid potion intent identity or resource")
        if self.settings_generation < 0 or self.target_generation < 0:
            raise ValueError("potion intent generations must not be negative")
        if not 0 < self.vk_code <= 0xFF or self.expires_at <= self.created_at:
            raise ValueError("invalid potion intent key or deadline")


def validate_potion_intent(
    intent: PotionIntent,
    *,
    session_epoch: str,
    settings_generation: int,
    target_generation: int,
    now: float,
) -> bool:
    return bool(
        intent.session_epoch == session_epoch
        and intent.settings_generation == settings_generation
        and intent.target_generation == target_generation
        and intent.created_at <= now <= intent.expires_at
    )


__all__ = ["PotionIntent", "validate_potion_intent"]
