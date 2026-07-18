from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters.win_input import key_down, key_up, parse_vk_key, tap_hotkey
    from .controllers.auto_potion_controller import (
        AutoPotionController,
        loading_screen_metrics,
        normalize_bar_percent,
    )
    from .models.settings import AutoPotionSettings, SETTINGS_PATH, app_base_dir, load_settings, save_settings


_LAZY_EXPORTS = {
    "AutoPotionController": ("maple_star.controllers.auto_potion_controller", "AutoPotionController"),
    "AutoPotionSettings": ("maple_star.models.settings", "AutoPotionSettings"),
    "SETTINGS_PATH": ("maple_star.models.settings", "SETTINGS_PATH"),
    "app_base_dir": ("maple_star.models.settings", "app_base_dir"),
    "key_down": ("maple_star.adapters.win_input", "key_down"),
    "key_up": ("maple_star.adapters.win_input", "key_up"),
    "load_settings": ("maple_star.models.settings", "load_settings"),
    "loading_screen_metrics": ("maple_star.controllers.auto_potion_controller", "loading_screen_metrics"),
    "normalize_bar_percent": ("maple_star.controllers.auto_potion_controller", "normalize_bar_percent"),
    "parse_vk_key": ("maple_star.adapters.win_input", "parse_vk_key"),
    "save_settings": ("maple_star.models.settings", "save_settings"),
    "tap_hotkey": ("maple_star.adapters.win_input", "tap_hotkey"),
}

__all__ = [
    "AutoPotionController",
    "AutoPotionSettings",
    "SETTINGS_PATH",
    "app_base_dir",
    "key_down",
    "key_up",
    "load_settings",
    "loading_screen_metrics",
    "normalize_bar_percent",
    "parse_vk_key",
    "save_settings",
    "tap_hotkey",
]


def __getattr__(name: str):
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
