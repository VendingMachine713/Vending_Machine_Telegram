from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.vm_core.progress import ProgressLine, progress_snapshot
from shared.vm_core.progress_registry import collect_progress_surfaces, platform_progress_summary


class ProgressRegistryTests(unittest.TestCase):
    def test_provider_failure_is_isolated_and_rendered_as_failed_surface(self):
        def boom(root):
            raise RuntimeError("provider exploded")

        with tempfile.TemporaryDirectory() as tmp, patch(
            "shared.vm_core.progress_registry._PROVIDERS", {"broken": boom}
        ):
            surfaces = collect_progress_surfaces(Path(tmp))
        self.assertEqual(surfaces["broken"]["overall"]["status"], "FAILED")
        self.assertIn("failed safely", surfaces["broken"]["recovery_messages"][0].lower())

    def test_summary_buckets_attention_running_and_complete(self):
        def attention(root):
            return progress_snapshot(
                headline="A", overall=ProgressLine("A", 0, 1, "ATTENTION")
            )

        def running(root):
            return progress_snapshot(
                headline="B", overall=ProgressLine("B", 1, 2, "RUNNING")
            )

        def complete(root):
            return progress_snapshot(
                headline="C", overall=ProgressLine("C", 1, 1, "COMPLETE")
            )

        providers = {"a": attention, "b": running, "c": complete}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "shared.vm_core.progress_registry._PROVIDERS", providers
        ):
            summary = platform_progress_summary(Path(tmp))
        self.assertEqual(summary["surface_count"], 3)
        self.assertEqual(summary["attention"], ["a"])
        self.assertEqual(summary["running"], ["b"])
        self.assertEqual(summary["complete"], ["c"])


if __name__ == "__main__":
    unittest.main()
