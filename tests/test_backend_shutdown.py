from __future__ import annotations

import unittest

from maple_star.backend.shutdown import OrderedShutdown


class BackendShutdownTests(unittest.TestCase):
    def test_all_cleanup_steps_run_after_failure_and_only_once(self) -> None:
        calls: list[str] = []

        def step(name: str, *, fail: bool = False):
            def run() -> None:
                calls.append(name)
                if fail:
                    raise RuntimeError(name)

            return run

        shutdown = OrderedShutdown(
            stop_commands=step("commands"),
            safety_release=step("release", fail=True),
            stop_workers=step("workers"),
            close_transport=step("transport"),
            confirm_children=step("children"),
        )

        failures = shutdown.run()
        second = shutdown.run()

        self.assertEqual(calls, ["commands", "release", "workers", "transport", "children"])
        self.assertEqual([failure.step for failure in failures], ["safety_release"])
        self.assertIs(second, failures)


if __name__ == "__main__":
    unittest.main()
