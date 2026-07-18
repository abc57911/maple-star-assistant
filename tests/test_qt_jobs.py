from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from maple_star.app.application import ensure_application
from maple_star.views_qt.jobs import CallableJob


class QtJobTests(unittest.TestCase):
    def test_callable_job_reports_result_without_touching_widgets(self) -> None:
        ensure_application([])
        values: list[object] = []
        job = CallableJob(lambda: 42)
        job.signals.succeeded.connect(values.append)

        job.run()

        self.assertEqual(values, [42])


if __name__ == "__main__":
    unittest.main()
