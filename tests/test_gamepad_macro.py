import unittest
from types import SimpleNamespace

from maple_gamepad_macro import (
    build_controller_button_bindings,
    effective_repeating_jump_interval_seconds,
    first_enabled_controller_binding,
    sync_runtime_settings_before_controller_events,
)
from maple_star.controller_worker import CONTROLLER_BUTTONS_BY_NAME
from maple_star.settings import AutoPotionSettings


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

    def test_sync_runtime_settings_before_controller_events_applies_gui_before_binding_sync(self):
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
        self.assertEqual(events, ["gui", "sync:True"])

    def test_sync_runtime_settings_before_controller_events_skips_binding_sync_when_gui_not_ready(self):
        events: list[str] = []

        class Gui:
            def sync_after_event_processing(self) -> bool:
                events.append("gui")
                return False

        auto_potion = SimpleNamespace(gui=Gui())

        def sync_controller_button_bindings() -> None:
            events.append("sync")

        self.assertFalse(
            sync_runtime_settings_before_controller_events(
                auto_potion,  # type: ignore[arg-type]
                sync_controller_button_bindings,
            )
        )
        self.assertEqual(events, ["gui"])

    def test_repeating_jump_interval_reports_runtime_effective_floor(self):
        slot = {
            "skill_delay_seconds": 0.05,
            "jump_interval_seconds": 0.01,
        }

        self.assertAlmostEqual(effective_repeating_jump_interval_seconds(slot), 0.06)


if __name__ == "__main__":
    unittest.main()
