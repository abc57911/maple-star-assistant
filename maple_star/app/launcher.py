from __future__ import annotations


def run_application() -> None:
    from maple_star.controllers.gamepad_controller import main

    main()


__all__ = ["run_application"]
