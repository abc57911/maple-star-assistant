import unittest
from types import SimpleNamespace
from unittest.mock import patch

from maple_gamepad_macro import (
    DEFAULT_ATTACK_KEY_HOLD_SECONDS,
    HoldJumpAttackLoopMacro,
    build_controller_button_bindings,
    effective_hold_jump_attack_interval_seconds,
    effective_repeating_jump_interval_seconds,
    first_enabled_controller_binding,
    sync_runtime_settings_before_controller_events,
)
from maple_star.controller_worker import CONTROLLER_BUTTONS_BY_NAME
from maple_star.settings import AutoPotionSettings, COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP


class GamepadMacroTests(unittest.TestCase):
    def test_controller_button_bindings_include_only_enabled_functions(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {"enabled": False, "trigger_button": "RB"},
                "B": {"enabled": False, "trigger_button": "LB"},
            },
        )
        rb_macro = SimpleNamespace(name="A", slot_id="A")
        lb_macro = SimpleNamespace(name="B", slot_id="B")

        bindings = build_controller_button_bindings(
            settings,
            (rb_macro, lb_macro),  # type: ignore[arg-type]
        )

        self.assertEqual(bindings, {})

        settings.combo_slots["A"]["enabled"] = True
        bindings = build_controller_button_bindings(
            settings,
            (rb_macro, lb_macro),  # type: ignore[arg-type]
        )

        self.assertEqual(bindings[CONTROLLER_BUTTONS_BY_NAME["RB"]], (rb_macro,))
        self.assertNotIn(CONTROLLER_BUTTONS_BY_NAME["LB"], bindings)

    def test_disabled_bound_button_selects_no_binding(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {"enabled": False, "trigger_button": "RB"},
                "B": {"enabled": False, "trigger_button": "LB"},
            },
        )
        rb_macro = SimpleNamespace(name="A", slot_id="A")
        lb_macro = SimpleNamespace(name="B", slot_id="B")
        bindings = build_controller_button_bindings(
            settings,
            (rb_macro, lb_macro),  # type: ignore[arg-type]
        )

        self.assertIsNone(
            first_enabled_controller_binding(
                bindings.get(CONTROLLER_BUTTONS_BY_NAME["RB"], ()),
                settings,
            )
        )

    def test_same_trigger_can_switch_enabled_function_without_rebinding(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {"enabled": False, "trigger_button": "RB"},
                "B": {"enabled": True, "trigger_button": "RB"},
            },
        )
        rb_macro = SimpleNamespace(name="A", slot_id="A")
        lb_macro = SimpleNamespace(name="B", slot_id="B")
        bindings = build_controller_button_bindings(
            settings,
            (rb_macro, lb_macro),  # type: ignore[arg-type]
        )
        trigger_bindings = bindings[CONTROLLER_BUTTONS_BY_NAME["RB"]]

        self.assertIs(
            first_enabled_controller_binding(
                trigger_bindings,
                settings,
            ),
            lb_macro,
        )

        settings.combo_slots["A"]["enabled"] = True
        trigger_bindings = build_controller_button_bindings(
            settings,
            (rb_macro, lb_macro),  # type: ignore[arg-type]
        )[CONTROLLER_BUTTONS_BY_NAME["RB"]]
        self.assertIs(
            first_enabled_controller_binding(
                trigger_bindings,
                settings,
            ),
            rb_macro,
        )

    def test_sync_runtime_settings_before_controller_events_uses_signal_committed_settings(self):
        events: list[str] = []
        settings = SimpleNamespace(rb_enabled=False)

        class Gui:
            def sync_after_event_processing(self) -> bool:
                events.append("gui")
                settings.rb_enabled = True
                return True

        auto_potion = SimpleNamespace(gui=Gui())

        def sync_controller_button_bindings() -> None:
            events.append(f"sync:{settings.rb_enabled}")

        self.assertTrue(
            sync_runtime_settings_before_controller_events(
                auto_potion,  # type: ignore[arg-type]
                sync_controller_button_bindings,
            )
        )
        self.assertEqual(events, ["sync:False"])

    def test_sync_runtime_settings_before_controller_events_does_not_pump_gui(self):
        events: list[str] = []

        class Gui:
            def sync_after_event_processing(self) -> bool:
                events.append("gui")
                return False

        auto_potion = SimpleNamespace(gui=Gui())

        def sync_controller_button_bindings() -> None:
            events.append("sync")

        self.assertTrue(
            sync_runtime_settings_before_controller_events(
                auto_potion,  # type: ignore[arg-type]
                sync_controller_button_bindings,
            )
        )
        self.assertEqual(events, ["sync"])

    def test_repeating_jump_interval_reports_runtime_effective_floor(self):
        slot = {
            "skill_delay_seconds": 0.05,
            "jump_interval_seconds": 0.01,
        }

        self.assertAlmostEqual(effective_repeating_jump_interval_seconds(slot), 0.06)

    def test_hold_jump_attack_interval_respects_attack_hold_floor(self):
        slot = {
            "jump_interval_seconds": 0.2,
        }

        self.assertAlmostEqual(effective_hold_jump_attack_interval_seconds(slot), DEFAULT_ATTACK_KEY_HOLD_SECONDS + 0.01)

    def test_hold_jump_attack_loop_holds_jump_and_cycles_attack(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {
                    "enabled": True,
                    "script_id": COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
                    "trigger_button": "RB",
                    "jump_key": "X",
                    "attack_key": "C",
                    "attack_hold_seconds": 0.4,
                    "jump_interval_seconds": 1.2,
                }
            }
        )
        macro = HoldJumpAttackLoopMacro(settings, "A", "組合A")
        events: list[tuple[str, int]] = []

        def parse_key(key: str) -> int:
            return {"X": 1, "C": 2}[key]

        with (
            patch("maple_star.controllers.gamepad_controller.foreground_window_title", return_value="MSW"),
            patch("maple_star.controllers.gamepad_controller.is_target_window_active", return_value=True),
            patch("maple_star.controllers.gamepad_controller.time.monotonic", return_value=100.0),
            patch("maple_star.controllers.gamepad_controller.parse_vk_key", side_effect=parse_key),
            patch("maple_star.controllers.gamepad_controller.key_down", side_effect=lambda vk: events.append(("down", vk))),
            patch("maple_star.controllers.gamepad_controller.key_up", side_effect=lambda vk: events.append(("up", vk))),
        ):
            macro.on_button_down()
            macro.update(100.1)
            macro.update(100.4)
            macro.update(101.2)
            macro.on_button_up()

        self.assertEqual(
            events,
            [
                ("down", 1),
                ("down", 2),
                ("down", 1),
                ("up", 2),
                ("down", 1),
                ("down", 1),
                ("down", 2),
                ("up", 2),
                ("up", 1),
            ],
        )

    def test_hold_jump_attack_interval_respects_configured_attack_hold(self):
        slot = {
            "attack_hold_seconds": 1.8,
            "jump_interval_seconds": 0.2,
        }

        self.assertAlmostEqual(effective_hold_jump_attack_interval_seconds(slot), 1.81)

    def test_hold_jump_attack_loop_waits_for_configured_start_delay(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {
                    "enabled": True,
                    "script_id": COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
                    "trigger_button": "RB",
                    "jump_key": "X",
                    "attack_key": "C",
                    "attack_start_delay_seconds": 0.3,
                    "attack_hold_seconds": 0.4,
                    "jump_interval_seconds": 1.2,
                }
            }
        )
        macro = HoldJumpAttackLoopMacro(settings, "A", "組合A")
        events: list[tuple[str, int]] = []

        def parse_key(key: str) -> int:
            return {"X": 1, "C": 2}[key]

        with (
            patch("maple_star.controllers.gamepad_controller.foreground_window_title", return_value="MSW"),
            patch("maple_star.controllers.gamepad_controller.is_target_window_active", return_value=True),
            patch("maple_star.controllers.gamepad_controller.time.monotonic", return_value=100.0),
            patch("maple_star.controllers.gamepad_controller.parse_vk_key", side_effect=parse_key),
            patch("maple_star.controllers.gamepad_controller.key_down", side_effect=lambda vk: events.append(("down", vk))),
            patch("maple_star.controllers.gamepad_controller.key_up", side_effect=lambda vk: events.append(("up", vk))),
        ):
            macro.on_button_down()
            macro.update(100.1)
            macro.update(100.29)
            macro.update(100.3)
            macro.on_button_up()

        self.assertEqual(
            events,
            [
                ("down", 1),
                ("down", 1),
                ("down", 1),
                ("down", 1),
                ("down", 2),
                ("up", 2),
                ("up", 1),
            ],
        )

    def test_hold_jump_attack_loop_rejects_same_jump_and_attack_key(self):
        settings = AutoPotionSettings(
            combo_slots={
                "A": {
                    "enabled": True,
                    "script_id": COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP,
                    "trigger_button": "RB",
                    "jump_key": "X",
                    "attack_key": "X",
                }
            }
        )
        macro = HoldJumpAttackLoopMacro(settings, "A", "組合A")
        events: list[tuple[str, int]] = []

        with (
            patch("maple_star.controllers.gamepad_controller.foreground_window_title", return_value="MSW"),
            patch("maple_star.controllers.gamepad_controller.is_target_window_active", return_value=True),
            patch("maple_star.controllers.gamepad_controller.parse_vk_key", return_value=1),
            patch("maple_star.controllers.gamepad_controller.key_down", side_effect=lambda vk: events.append(("down", vk))),
        ):
            macro.on_button_down()

        self.assertFalse(macro.active)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
