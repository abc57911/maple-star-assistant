from __future__ import annotations


PACKAGE_ROOT_EXPORTS = {
    "AutoPotionController": "maple_star.controllers.auto_potion_controller",
    "AutoPotionSettings": "maple_star.models.settings",
    "SETTINGS_PATH": "maple_star.models.settings",
    "app_base_dir": "maple_star.models.settings",
    "key_down": "maple_star.adapters.win_input",
    "key_up": "maple_star.adapters.win_input",
    "load_settings": "maple_star.models.settings",
    "loading_screen_metrics": "maple_star.services.bar_detection",
    "normalize_bar_percent": "maple_star.services.bar_detection",
    "parse_vk_key": "maple_star.adapters.win_input",
    "save_settings": "maple_star.models.settings",
    "tap_hotkey": "maple_star.adapters.win_input",
}


REQUIRED_EXPORTS = {
    "maple_star.controller": {
        "AutoPotionController": "maple_star.controllers.auto_potion_controller",
        "loading_screen_metrics": "maple_star.services.bar_detection",
        "normalize_bar_percent": "maple_star.services.bar_detection",
        "AUTO_DRINK_POTION_CHECK_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "AUTO_DRINK_START_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "AUTO_DRINK_STOP_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "AUTO_PICKUP_START_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "AUTO_PICKUP_STOP_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "ExperienceOcrJob": "maple_star.models.controller_state",
        "LIE_DETECTOR_ALERT_SOUND_PATH": "maple_star.controllers.auto_potion_controller",
        "MINIMAP_CRUISE_START_WAV_PATH": "maple_star.controllers.auto_potion_controller",
        "MINIMAP_CRUISE_STOP_WAV_PATH": "maple_star.controllers.auto_potion_controller",
        "BarDetectionDebug": "maple_star.models.controller_state",
        "bgra_image_to_ppm_data": "maple_star.services.bar_detection",
    },
    "maple_star.settings": {
        name: "maple_star.models.settings"
        for name in (
            "AutoPotionSettings",
            "SETTINGS_PATH",
            "app_base_dir",
            "load_settings",
            "save_settings",
            "COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP",
            "COMBO_SCRIPT_REPEATING_JUMP_SKILL",
            "COMBO_SCRIPT_SINGLE_JUMP_SKILL",
            "MINIMAP_CRUISE_DEFAULT_LIE_DETECTOR_ALERT_VOLUME_PERCENT",
            "MINIMAP_CRUISE_DEFAULT_STATIONARY_MIN_FORWARD_PIXELS",
            "normalize_controller_button_name",
        )
    },
    "maple_star.gui": {
        "AutoPotionSettingsGui": "maple_star.views.settings_gui",
        "GuiConsoleWriter": "maple_star.views.settings_gui",
    },
    "auto_potion": {
        "AutoPotionController": "maple_star.controllers.auto_potion_controller",
        "AutoPotionSettings": "maple_star.models.settings",
        "AutoPotionSettingsGui": "maple_star.views.settings_gui",
        "GuiConsoleWriter": "maple_star.views.settings_gui",
        "SETTINGS_PATH": "maple_star.models.settings",
        "app_base_dir": "maple_star.models.settings",
        "event_to_hotkey": "maple_star.adapters.key_capture",
        "key_down": "maple_star.adapters.win_input",
        "key_up": "maple_star.adapters.win_input",
        "load_settings": "maple_star.models.settings",
        "loading_screen_metrics": "maple_star.services.bar_detection",
        "normalize_bar_percent": "maple_star.services.bar_detection",
        "parse_vk_key": "maple_star.adapters.win_input",
        "pressed_detectable_vks": "maple_star.adapters.key_capture",
        "save_settings": "maple_star.models.settings",
        "tap_hotkey": "maple_star.adapters.win_input",
        "vk_to_key_name": "maple_star.adapters.key_capture",
    },
    "maple_gamepad_macro": {
        name: "maple_star.controllers.gamepad_controller"
        for name in (
            "DEFAULT_ATTACK_KEY_HOLD_SECONDS",
            "HoldJumpAttackLoopMacro",
            "build_controller_button_bindings",
            "effective_hold_jump_attack_interval_seconds",
            "effective_repeating_jump_interval_seconds",
            "first_enabled_controller_binding",
            "sync_runtime_settings_before_controller_events",
        )
    },
}


EXPERIENCE_TARGET_OWNERS = {
    "ExperienceEfficiencyTracker": "maple_star.models.experience_tracker",
    "ExperienceSnapshot": "maple_star.models.experience_types",
    "ExperienceTextReading": "maple_star.models.experience_types",
    "ExperienceOcrImage": "maple_star.models.experience_types",
    "ExperienceOcrContinuityHint": "maple_star.models.experience_types",
    "ExperiencePixelFontAttempt": "maple_star.models.experience_types",
    "PaddleExperienceTextReader": "maple_star.services.experience_paddle_reader",
    "EXP_LEVEL_WRAP_HIGH_PERCENT": "maple_star.models.experience_constants",
    "EXP_RATE_1H_HALF_LIFE_SECONDS": "maple_star.models.experience_constants",
    "PADDLEOCR_DETECTION_MODEL_NAME": "maple_star.models.experience_constants",
    "PADDLEOCR_LANGUAGE": "maple_star.models.experience_constants",
    "PADDLEOCR_RECOGNITION_MODEL_NAME": "maple_star.models.experience_constants",
    "format_exp": "maple_star.models.experience_tracker",
    "format_duration": "maple_star.models.experience_tracker",
    "format_eta": "maple_star.models.experience_tracker",
    "format_exp_10m_gain": "maple_star.models.experience_tracker",
    "format_exp_rate": "maple_star.models.experience_tracker",
    "format_ocr_success_rate": "maple_star.models.experience_tracker",
    "format_rate_confidence": "maple_star.models.experience_tracker",
    "read_experience_burst_frames_in_worker": "maple_star.services.experience_paddle_reader",
    "read_stat_window_exp_in_worker": "maple_star.services.experience_paddle_reader",
    "read_experience_tooltip_in_worker": "maple_star.services.experience_paddle_reader",
    "parse_stat_window_exp_text": "maple_star.services.experience_text_parsing",
    "parse_experience_tooltip_text": "maple_star.services.experience_text_parsing",
    "parse_exp_percent_text": "maple_star.services.experience_text_parsing",
    "parse_current_exp_text": "maple_star.services.experience_text_parsing",
    "reading_from_paddle_result": "maple_star.services.experience_text_parsing",
    "reading_from_stat_window_text": "maple_star.services.experience_text_parsing",
    "reading_from_tooltip_paddle_result": "maple_star.services.experience_text_parsing",
    "reading_from_tooltip_text": "maple_star.services.experience_text_parsing",
    "extract_paddle_text_items": "maple_star.services.experience_text_parsing",
    "prepare_experience_ocr_image": "maple_star.services.experience_image_processing",
    "prepare_experience_tooltip_ocr_images": "maple_star.services.experience_image_processing",
    "prepare_experience_ocr_images": "maple_star.services.experience_image_processing",
    "estimate_experience_bar_percent": "maple_star.services.experience_image_processing",
    "_binarize_experience_text": "maple_star.services.experience_image_processing",
    "_clean_experience_text_mask": "maple_star.services.experience_image_processing",
    "_erase_experience_green_bar_to_text_image": "maple_star.services.experience_image_processing",
    "_suppress_experience_green_bar_background": "maple_star.services.experience_image_processing",
    "_apply_experience_ocr_continuity_guard": "maple_star.services.experience_pixel_ocr",
    "_experience_ocr_continuity_status": "maple_star.services.experience_text_parsing",
    "_decode_experience_pixel_font_text_candidates": "maple_star.services.experience_pixel_ocr",
    "_experience_pixel_font_runtime_attempts": "maple_star.services.experience_pixel_ocr",
    "_read_experience_pixel_font_adaptive": "maple_star.services.experience_pixel_ocr",
    "_pixel_font_text_reading": "maple_star.services.experience_pixel_ocr",
    "_select_pixel_font_success": "maple_star.services.experience_pixel_ocr",
    "_structured_pixel_font_text_candidates": "maple_star.services.experience_pixel_ocr",
    "_experience_should_read_secondary_roi": "maple_star.services.experience_paddle_reader",
    "_experience_text_structure_score": "maple_star.services.experience_text_parsing",
    "suppress_subprocess_windows": "maple_star.services.experience_paddle_reader",
}


EXPERIENCE_STAGED_OWNERS = {
    name: "maple_star.models.experience"
    for name in EXPERIENCE_TARGET_OWNERS
}
EXPERIENCE_STAGED_OWNERS.update(
    {
        name: EXPERIENCE_TARGET_OWNERS[name]
        for name in (
            "ExperienceSnapshot",
            "ExperienceTextReading",
            "ExperienceOcrImage",
            "ExperienceOcrContinuityHint",
            "ExperiencePixelFontAttempt",
            "EXP_LEVEL_WRAP_HIGH_PERCENT",
            "EXP_RATE_1H_HALF_LIFE_SECONDS",
            "PADDLEOCR_DETECTION_MODEL_NAME",
            "PADDLEOCR_LANGUAGE",
            "PADDLEOCR_RECOGNITION_MODEL_NAME",
            "ExperienceEfficiencyTracker",
            "format_exp",
            "format_duration",
            "format_eta",
            "format_exp_10m_gain",
            "format_exp_rate",
            "format_ocr_success_rate",
            "format_rate_confidence",
            "parse_stat_window_exp_text",
            "parse_experience_tooltip_text",
            "parse_exp_percent_text",
            "parse_current_exp_text",
            "reading_from_paddle_result",
            "reading_from_stat_window_text",
            "reading_from_tooltip_paddle_result",
            "reading_from_tooltip_text",
            "extract_paddle_text_items",
            "_experience_text_structure_score",
            "_experience_ocr_continuity_status",
            "prepare_experience_ocr_image",
            "prepare_experience_tooltip_ocr_images",
            "prepare_experience_ocr_images",
            "estimate_experience_bar_percent",
            "_binarize_experience_text",
            "_clean_experience_text_mask",
            "_erase_experience_green_bar_to_text_image",
            "_suppress_experience_green_bar_background",
            "_apply_experience_ocr_continuity_guard",
            "_decode_experience_pixel_font_text_candidates",
            "_experience_pixel_font_runtime_attempts",
            "_read_experience_pixel_font_adaptive",
            "_pixel_font_text_reading",
            "_select_pixel_font_success",
            "_structured_pixel_font_text_candidates",
            "PaddleExperienceTextReader",
            "read_experience_burst_frames_in_worker",
            "read_stat_window_exp_in_worker",
            "read_experience_tooltip_in_worker",
            "_experience_should_read_secondary_roi",
            "suppress_subprocess_windows",
        )
    }
)
REQUIRED_EXPORTS["maple_star.experience"] = EXPERIENCE_STAGED_OWNERS


MODULE_ALIASES = {
    "maple_star.controller": "maple_star.controllers.auto_potion_controller",
    "maple_star.experience": "maple_star.models.experience",
    "maple_gamepad_macro": "maple_star.controllers.gamepad_controller",
}


PATCH_POINTS = {
    "maple_star.controller": (
        "ctypes.windll",
        "key_down",
        "key_up",
        "save_settings",
        "tap_hotkey",
        "threading.Thread",
        "time.monotonic",
        "time.sleep",
        "user32.GetAsyncKeyState",
        "winsound.Beep",
        "winsound.MessageBeep",
        "winsound.PlaySound",
    ),
}


EXACT_ALL = {
    "maple_star": frozenset(PACKAGE_ROOT_EXPORTS),
    "auto_potion": frozenset(REQUIRED_EXPORTS["auto_potion"]),
}
