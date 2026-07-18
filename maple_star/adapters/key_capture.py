from __future__ import annotations

from typing import Protocol

from ..constants import ASYNC_KEY_DOWN_MASK
from .win_input import user32

KEYSYM_ALIASES = {
    "Return": "Enter",
    "Escape": "Escape",
    "BackSpace": "Backspace",
    "Tab": "Tab",
    "space": "Space",
    "Delete": "Delete",
    "Insert": "Insert",
    "Home": "Home",
    "End": "End",
    "Prior": "PageUp",
    "Next": "PageDown",
    "Left": "Left",
    "Right": "Right",
    "Up": "Up",
    "Down": "Down",
    "minus": "-",
    "equal": "=",
    "bracketleft": "[",
    "bracketright": "]",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "grave": "`",
}
MODIFIER_KEYSYMS = {
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
}
VK_DISPLAY_NAMES = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x1B: "Escape",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2D: "Insert",
    0x2E: "Delete",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}
for code in range(0x30, 0x3A):
    VK_DISPLAY_NAMES[code] = chr(code)
for code in range(0x41, 0x5B):
    VK_DISPLAY_NAMES[code] = chr(code)
for index in range(1, 25):
    VK_DISPLAY_NAMES[0x70 + index - 1] = f"F{index}"

DETECTABLE_KEY_VKS = tuple(VK_DISPLAY_NAMES)


class KeyEvent(Protocol):
    keysym: object


def event_to_hotkey(event: KeyEvent) -> str | None:
    keysym = str(event.keysym)
    if keysym in MODIFIER_KEYSYMS:
        return None

    if keysym.startswith("KP_") and len(keysym) == 4 and keysym[-1].isdigit():
        key = keysym[-1]
    elif len(keysym) == 1:
        key = keysym.upper() if keysym.isalpha() else keysym
    elif keysym.upper().startswith("F") and keysym[1:].isdigit():
        key = keysym.upper()
    else:
        key = KEYSYM_ALIASES.get(keysym, keysym)

    return key


def vk_to_key_name(vk_code: int) -> str | None:
    return VK_DISPLAY_NAMES.get(vk_code)


def pressed_detectable_vks() -> set[int]:
    return {
        vk_code
        for vk_code in DETECTABLE_KEY_VKS
        if user32.GetAsyncKeyState(vk_code) & ASYNC_KEY_DOWN_MASK
    }
