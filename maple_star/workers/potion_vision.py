from __future__ import annotations

from maple_star.ipc.identity import MessageMeta, WorkerRole
from maple_star.ipc.messages import InputAction, InputCommand, WorkerHeartbeat
from maple_star.models.potion_intent import PotionIntent, validate_potion_intent


class PotionVisionRuntime:
    """Health/progress state kept separate from capture and OCR implementation."""

    def __init__(
        self,
        *,
        session_epoch: str,
        heartbeat_interval: float,
        incarnation: int = 1,
    ) -> None:
        self.session_epoch = session_epoch
        self.heartbeat_interval = heartbeat_interval
        self.incarnation = incarnation
        self.phase = "starting"
        self.progress_at = 0.0
        self._sequence = 0

    def begin_phase(self, phase: str, *, now: float) -> None:
        self.phase = phase
        self.progress_at = now

    def mark_progress(self, *, now: float) -> None:
        self.progress_at = now

    def heartbeat(self, *, now: float, process_id: int) -> WorkerHeartbeat:
        self._sequence += 1
        return WorkerHeartbeat(
            MessageMeta(
                self.session_epoch,
                WorkerRole.POTION,
                self.incarnation,
                "health",
                self._sequence,
                0,
                0,
                now,
            ),
            process_id=process_id,
            phase=self.phase,
            progress_at=self.progress_at,
        )


def intent_to_input_command(
    intent: PotionIntent,
    *,
    session_epoch: str,
    settings_generation: int,
    target_generation: int,
    safety_generation: int,
    now: float,
) -> InputCommand | None:
    if not validate_potion_intent(
        intent,
        session_epoch=session_epoch,
        settings_generation=settings_generation,
        target_generation=target_generation,
        now=now,
    ):
        return None
    return InputCommand(
        InputAction.TAP,
        vk_code=intent.vk_code,
        safety_generation=safety_generation,
        expires_at=intent.expires_at,
    )


__all__ = ["PotionVisionRuntime", "intent_to_input_command"]
