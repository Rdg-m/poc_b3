from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dolt_loader import DoltConfig  # noqa: E402


class DoltConfigTest(unittest.TestCase):
    def test_local_dolt_allows_explicit_empty_password(self):
        environment = {
            "DOLT_HOST": "127.0.0.1",
            "DOLT_DATABASE": "b3_derivatives",
            "DOLT_USER": "root",
            "DOLT_PASSWORD": "",
            "DOLT_SSL_MODE": "DISABLED",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = DoltConfig.from_environment()
        self.assertEqual(config.password, "")
        self.assertEqual(config.branch, "main")

    def test_rejects_unknown_ssl_mode(self):
        environment = {
            "DOLT_HOST": "127.0.0.1",
            "DOLT_DATABASE": "b3_derivatives",
            "DOLT_USER": "root",
            "DOLT_PASSWORD": "",
            "DOLT_SSL_MODE": "SOMETHING_ELSE",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "DOLT_SSL_MODE inválido"):
                DoltConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
