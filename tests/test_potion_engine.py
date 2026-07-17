from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from maple_star.services.potion_engine import (
    PotionBarConfig,
    PotionCommand,
    PotionCommandResult,
    PotionEngine,
    PotionEngineSnapshot,
    PotionSample,
)


class PotionEngineTests(unittest.TestCase):
    def test_contracts_are_frozen(self) -> None:
        hp_config = PotionBarConfig("hp", True, 50.0, 0.5, "F1", False, 0.0)
        mp_config = PotionBarConfig("mp", True, 50.0, 0.5, "F2", False, 0.0)
        values = (
            hp_config,
            PotionSample(
                10.0,
                40.0,
                80.0,
                hp_config,
                mp_config,
                True,
                True,
                True,
                False,
                True,
                True,
            ),
            PotionCommand(1, "hp", "tap", "F1", 40.0),
            PotionCommandResult(1, "executed", 10.0),
            PotionEngineSnapshot(-999.0, -999.0, 0, 0, False),
        )
        for value in values:
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    value.__setattr__(next(iter(value.__dataclass_fields__)), None)

    def test_engine_owns_independent_hp_and_mp_state(self) -> None:
        engine = PotionEngine()
        engine.hp_potion_held_vk = 112
        engine.mp_potion_held_vk = 113
        engine.hp_pending_potion_send_at = 10.0
        engine.mp_pending_potion_send_at = 20.0

        snapshot = engine.snapshot()

        self.assertEqual((snapshot.hp_held_vk, snapshot.mp_held_vk), (112, 113))
        self.assertEqual((snapshot.hp_pending_send_at, snapshot.mp_pending_send_at), (10.0, 20.0))

    def test_controller_fields_are_engine_compatibility_views(self) -> None:
        from maple_star.controller import AutoPotionController

        controller = AutoPotionController.__new__(AutoPotionController)
        controller.hp_potion_no_effect_count = 3
        controller.mp_potion_held_vk = 114

        self.assertEqual(controller.potion_engine.hp_potion_no_effect_count, 3)
        self.assertEqual(controller.potion_engine.mp_potion_held_vk, 114)

    def test_command_result_is_applied_exactly_once(self) -> None:
        engine = PotionEngine()
        command = engine._new_command("hp", "tap", "F1", 40.0, 10.0)
        result = PotionCommandResult(command.command_id, "executed", 10.0)

        self.assertTrue(engine.apply_command_result(result))
        self.assertFalse(engine.apply_command_result(result))
        self.assertFalse(engine.apply_command_result(PotionCommandResult(999, "executed", 10.0)))

    def test_only_executed_command_advances_drink_state(self) -> None:
        outcomes = (
            "executed",
            "rejected_foreground",
            "invalid_key",
            "queue_full",
            "failed",
        )
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                engine = PotionEngine()
                engine._maybe_drink_potion(
                    "hp",
                    "HP",
                    10.0,
                    40.0,
                    True,
                    50.0,
                    "F1",
                    False,
                    0.0,
                    challenge_paused=False,
                    release_key=lambda _bar_type: None,
                    clear_bar_state=lambda _bar_type: None,
                    capture_transient=lambda _bar_type: None,
                    emit_failure_warning=lambda _now: None,
                    log_unstable=lambda _now, _label: None,
                    should_drink=engine._should_drink_for_current_mode,
                    cooldown_seconds=lambda _bar_type: 0.5,
                    is_active_before_send=lambda _label, _now: True,
                    play_blocked_sound=lambda _now: None,
                    can_fast_repeat=lambda _bar_type: True,
                    capture_confirmed=lambda _bar_type, percent: percent,
                    log_trigger_interval=lambda *_args: None,
                    execute_command=lambda command: PotionCommandResult(
                        command.command_id,
                        outcome,
                        10.0 if outcome == "executed" else None,
                    ),
                    set_last_action=lambda _action: None,
                )

                if outcome == "executed":
                    self.assertEqual(engine.last_hp_drink_at, 10.0)
                    self.assertEqual(len(engine.hp_potion_effect_attempts), 1)
                else:
                    self.assertEqual(engine.last_hp_drink_at, -999.0)
                    self.assertEqual(engine.hp_potion_effect_attempts, [])

    def test_async_command_does_not_advance_before_completion(self) -> None:
        engine = PotionEngine()
        submitted = []

        engine._maybe_drink_potion(
            "hp",
            "HP",
            10.0,
            40.0,
            True,
            50.0,
            "F1",
            False,
            0.0,
            challenge_paused=False,
            release_key=lambda _bar_type: None,
            clear_bar_state=lambda _bar_type: None,
            capture_transient=lambda _bar_type: None,
            emit_failure_warning=lambda _now: None,
            log_unstable=lambda _now, _label: None,
            should_drink=engine._should_drink_for_current_mode,
            cooldown_seconds=lambda _bar_type: 0.5,
            is_active_before_send=lambda _label, _now: True,
            play_blocked_sound=lambda _now: None,
            can_fast_repeat=lambda _bar_type: True,
            capture_confirmed=lambda _bar_type, percent: percent,
            log_trigger_interval=lambda *_args: None,
            execute_command=lambda command: submitted.append(command),
            set_last_action=lambda _action: None,
        )

        self.assertEqual(engine.last_hp_drink_at, -999.0)
        self.assertEqual(engine.hp_potion_effect_attempts, [])
        self.assertEqual(
            engine.pending_command_ids_by_bar,
            {"hp": {submitted[0].command_id}},
        )

        engine.complete_command_result(
            PotionCommandResult(submitted[0].command_id, "executed", 10.1),
            log_trigger_interval=lambda *_args: None,
            set_last_action=lambda _action: None,
            play_blocked_sound=lambda _now: None,
        )

        self.assertEqual(engine.last_hp_drink_at, 10.1)
        self.assertEqual(len(engine.hp_potion_effect_attempts), 1)

    def test_failed_due_send_keeps_pending_intent(self) -> None:
        engine = PotionEngine()
        engine._schedule_pending_potion_send("hp", 10.0, 40.0)

        engine._process_due_potion_send(
            "hp",
            "HP",
            10.0,
            True,
            50.0,
            "F1",
            False,
            gameplay_hud_active=True,
            cooldown_seconds=lambda _bar_type: 0.5,
            is_active_before_send=lambda _label, _now: True,
            execute_command=lambda command: PotionCommandResult(command.command_id, "failed"),
            log_trigger_interval=lambda *_args: None,
            set_last_action=lambda _action: None,
        )

        self.assertEqual(engine.hp_pending_potion_send_at, 10.0)
        self.assertEqual(engine.hp_pending_potion_send_percent, 40.0)
        self.assertEqual(engine.last_hp_drink_at, -999.0)

    def test_release_state_changes_only_after_executed_result(self) -> None:
        engine = PotionEngine()
        engine.hp_potion_held_vk = 0x2E
        first = engine.request_release_command("hp", 10.0)
        assert first is not None

        engine.apply_command_result(PotionCommandResult(first.command_id, "failed"))

        self.assertEqual(engine.hp_potion_held_vk, 0x2E)
        second = engine.request_release_command("hp", 10.1)
        assert second is not None
        engine.apply_command_result(PotionCommandResult(second.command_id, "executed", 10.1))
        self.assertEqual(engine.hp_potion_held_vk, 0)

    def test_release_can_follow_hold_before_hold_completion_is_drained(self) -> None:
        engine = PotionEngine()
        hold = engine._new_command(
            "hp",
            "hold",
            "Delete",
            25.0,
            10.0,
            continuous=True,
        )
        release = engine.request_release_command("hp", 10.1)
        assert release is not None

        engine.apply_result(PotionCommandResult(hold.command_id, "executed", 10.2, held_vk=0x2E))
        self.assertEqual(engine.hp_potion_held_vk, 0x2E)
        engine.apply_result(PotionCommandResult(release.command_id, "executed", 10.3))

        self.assertEqual(engine.hp_potion_held_vk, 0)

    def test_engine_module_does_not_import_controller_or_gui(self) -> None:
        path = Path(__file__).resolve().parents[1] / "maple_star" / "services" / "potion_engine.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = "\n".join(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        self.assertNotIn("controllers", imports)
        self.assertNotIn("gui", imports)


if __name__ == "__main__":
    unittest.main()
