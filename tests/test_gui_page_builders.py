from __future__ import annotations

import dataclasses
import unittest
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock, patch

from maple_star.views import gui_theme
from maple_star.views.settings_gui import AutoPotionSettingsGui
from maple_star.views.pages import contracts


class GuiPageBuilderContractTests(unittest.TestCase):
    def test_theme_is_a_leaf_module(self) -> None:
        self.assertEqual(gui_theme.APP_BG, "#09111f")
        self.assertFalse(hasattr(gui_theme, "AutoPotionSettingsGui"))

    def test_contexts_are_frozen_and_do_not_expose_runtime_service_locators(self) -> None:
        context_types = (
            contracts.MonitorPageContext,
            contracts.MonitorControlsContext,
            contracts.PotionPageContext,
            contracts.MinimapPageContext,
            contracts.ComboPageContext,
            contracts.ConsolePageContext,
        )
        forbidden = {"gui", "controller", "queue", "runtime", "settings_store"}
        for context_type in context_types:
            with self.subTest(context=context_type.__name__):
                self.assertTrue(context_type.__dataclass_params__.frozen)
                field_names = {field.name for field in dataclasses.fields(context_type)}
                self.assertTrue(field_names.isdisjoint(forbidden))

    def test_contexts_use_page_specific_widget_protocols(self) -> None:
        expected = {
            contracts.MonitorPageContext: contracts.MonitorWidgets,
            contracts.MonitorControlsContext: contracts.MonitorControlsWidgets,
            contracts.PotionPageContext: contracts.PotionWidgets,
            contracts.MinimapPageContext: contracts.MinimapWidgets,
            contracts.ComboPageContext: contracts.ComboWidgets,
            contracts.ConsolePageContext: contracts.ConsoleWidgets,
        }
        for context_type, widget_protocol in expected.items():
            with self.subTest(context=context_type.__name__):
                self.assertIs(get_type_hints(context_type)["widgets"], widget_protocol)

    def test_refs_are_frozen_publish_values(self) -> None:
        ref_types = (
            contracts.MonitorPageRefs,
            contracts.MonitorControlsRefs,
            contracts.PotionPageRefs,
            contracts.MinimapPageRefs,
            contracts.ComboPageRefs,
            contracts.ConsolePageRefs,
            contracts.ConsoleTextRefs,
        )
        for ref_type in ref_types:
            with self.subTest(refs=ref_type.__name__):
                self.assertTrue(ref_type.__dataclass_params__.frozen)


class GuiPageBuilderLifecycleTests(unittest.TestCase):
    def test_finish_page_build_keeps_placeholder_when_builder_fails(self) -> None:
        gui = Mock()
        gui.closed = False
        gui.active_page = "自動喝水"
        gui.page_build_after_id = "pending"
        placeholder = Mock()
        gui.page_placeholders = {"自動喝水": placeholder}
        gui._ensure_page_built.side_effect = RuntimeError("build failed")

        with self.assertRaisesRegex(RuntimeError, "build failed"):
            AutoPotionSettingsGui._finish_page_build(gui, "自動喝水")

        self.assertIs(gui.page_placeholders["自動喝水"], placeholder)
        placeholder.destroy.assert_not_called()
        self.assertIsNone(gui.page_build_after_id)

    def test_minimap_sync_failure_rolls_back_refs_and_widgets(self) -> None:
        gui = Mock()
        gui.minimap_cruise_group_collapsed = False
        gui.minimap_page_refs = None
        gui.minimap_cruise_section = None
        gui.minimap_cruise_body = None
        gui.minimap_cruise_title_label = None
        page = Mock()
        existing = Mock()
        partial = Mock()
        page.winfo_children.side_effect = [[existing], [existing, partial]]
        refs = SimpleNamespace(section=Mock(), body=Mock(), title_label=Mock())
        gui.set_minimap_cruise_group_collapsed.side_effect = RuntimeError("sync failed")

        with patch("maple_star.views.settings_gui.build_minimap_page", return_value=refs):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                AutoPotionSettingsGui._build_minimap_page(gui, page)

        partial.destroy.assert_called_once_with()
        self.assertIsNone(gui.minimap_page_refs)
        self.assertIsNone(gui.minimap_cruise_section)
        self.assertIsNone(gui.minimap_cruise_body)
        self.assertIsNone(gui.minimap_cruise_title_label)

    def test_combo_sync_failure_rolls_back_refs_registries_and_widgets(self) -> None:
        gui = Mock()
        gui.combo_group_collapsed = False
        registries = (
            "combo_field_flows",
            "combo_skill_key_fields",
            "combo_attack_key_fields",
            "combo_skill_delay_fields",
            "combo_attack_start_delay_fields",
            "combo_attack_hold_fields",
            "combo_jump_interval_fields",
        )
        for name in registries:
            setattr(gui, name, {})
        page = Mock()
        existing = Mock()
        partial = Mock()
        page.winfo_children.side_effect = [[existing], [existing, partial]]
        slot_refs = SimpleNamespace(
            field_flow=Mock(),
            skill_key_fields=(),
            attack_key_fields=(),
            skill_delay_fields=(),
            attack_start_delay_fields=(),
            attack_hold_fields=(),
            jump_interval_fields=(),
        )
        refs = SimpleNamespace(
            section=Mock(), body=Mock(), title_label=Mock(), slots={"A": slot_refs, "B": slot_refs}
        )
        gui._refresh_combo_script_visibility.side_effect = RuntimeError("sync failed")

        with patch("maple_star.views.settings_gui.build_combo_page", return_value=refs):
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                AutoPotionSettingsGui._build_combo_page(gui, page)

        partial.destroy.assert_called_once_with()
        self.assertIsNone(gui.combo_page_refs)
        self.assertIsNone(gui.combo_group_section)
        for name in registries:
            self.assertEqual(getattr(gui, name), {})

    def test_monitor_post_build_failure_rolls_back_and_schedules_retry(self) -> None:
        gui = Mock()
        page = Mock()
        existing = Mock()
        partial = Mock()
        page.winfo_children.side_effect = [[existing], [existing, partial]]
        gui.page_frames = {"監控": page}
        gui.profile_select = None
        gui.closed = False
        gui.full_panel_widgets = [existing]
        gui.compact_experience_mode = False
        gui.root.after.return_value = "retry-id"
        gui.root.after_idle.side_effect = RuntimeError("post-build failed")
        gui.settings.profile_names.return_value = ["預設"]
        refs = SimpleNamespace(
            hotkey_section=Mock(),
            profile_section=Mock(),
            profile_select=Mock(),
            full_panel_widgets=(Mock(), Mock()),
        )

        with patch("maple_star.views.settings_gui.build_monitor_controls", return_value=refs):
            with self.assertRaisesRegex(RuntimeError, "post-build failed"):
                AutoPotionSettingsGui._build_monitor_controls(gui)

        partial.destroy.assert_called_once_with()
        self.assertIsNone(gui.monitor_controls_refs)
        self.assertIsNone(gui.profile_select)
        self.assertEqual(gui.full_panel_widgets, [existing])
        self.assertEqual(gui.monitor_controls_after_id, "retry-id")
        gui.root.after.assert_called_once_with(250, gui._build_monitor_controls)

    def test_close_cancels_pending_builds_and_destroys_placeholders(self) -> None:
        gui = Mock()
        gui.settings = Mock()
        gui.closed = False
        gui.page_build_after_id = "page-id"
        gui.monitor_controls_after_id = "monitor-id"
        gui.console_resize_after_id = None
        gui.console_height_after_id = None
        gui.restore_repaint_after_id = None
        gui.console_flush_after_id = None
        placeholder = Mock()
        gui.page_placeholders = {"自動喝水": placeholder}

        with patch("maple_star.views.settings_gui.save_settings"):
            AutoPotionSettingsGui.close(gui)

        gui.root.after_cancel.assert_any_call("page-id")
        gui.root.after_cancel.assert_any_call("monitor-id")
        placeholder.destroy.assert_called_once_with()
        self.assertEqual(gui.page_placeholders, {})
        self.assertTrue(gui.closed)


if __name__ == "__main__":
    unittest.main()
