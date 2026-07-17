from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from workers.sec.__main__ import run


class SecCliTests(unittest.TestCase):
    def test_missing_environment_stops_before_network(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.stderr") as stderr:
                exit_code = run(["ingest-rxrx-q2-2025"])

        self.assertEqual(exit_code, 2)
        message = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("SEC_USER_AGENT", message)
        self.assertNotIn("secret_key=", message)


if __name__ == "__main__":
    unittest.main()
