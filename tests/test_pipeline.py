from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_pipeline  # noqa: E402
from b3_download import B3FileUnavailable  # noqa: E402


class PipelineTest(unittest.TestCase):
    @patch("run_pipeline.download_one")
    def test_discovers_latest_available_date(self, download):
        expected = Path("/tmp/SPRD260904.zip")
        download.side_effect = [
            B3FileUnavailable("empty"),
            B3FileUnavailable("empty"),
            expected,
        ]
        found_date, found_path = run_pipeline.discover_latest(
            start_date=date(2026, 9, 6),
            lookback_days=5,
            raw_root=Path("/tmp/raw"),
            retries=1,
            timeout=1,
            refresh=True,
        )
        self.assertEqual(found_date, date(2026, 9, 4))
        self.assertEqual(found_path, expected)
        attempted = [call.args[1] for call in download.call_args_list]
        self.assertEqual(
            attempted,
            [date(2026, 9, 6), date(2026, 9, 5), date(2026, 9, 4)],
        )

    @patch("run_pipeline.download_one", side_effect=B3FileUnavailable("empty"))
    def test_fails_when_lookback_is_exhausted(self, _download):
        with self.assertRaisesRegex(RuntimeError, "nenhum arquivo SPRD"):
            run_pipeline.discover_latest(
                start_date=date(2026, 9, 6),
                lookback_days=2,
                raw_root=Path("/tmp/raw"),
                retries=1,
                timeout=1,
                refresh=True,
            )

    def test_dotenv_does_not_override_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DOLT_HOST=from-file\nDOLT_PORT=3307\n", encoding="utf-8")
            with patch.dict(os.environ, {"DOLT_HOST": "already-set"}, clear=True):
                run_pipeline.load_dotenv(path)
                self.assertEqual(os.environ["DOLT_HOST"], "already-set")
                self.assertEqual(os.environ["DOLT_PORT"], "3307")


if __name__ == "__main__":
    unittest.main()
