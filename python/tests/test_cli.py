# -*- coding: utf-8 -*-
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import fixtures  # noqa: F401  把 python/ 放进导入路径
import cli


class CliTest(unittest.TestCase):
    def test_module_hit(self):
        self.assertTrue(cli.is_module_hit({"module_id": "pip"}))
        self.assertFalse(cli.is_module_hit({"module_id": "out_of_scope", "out_of_scope": True}))
        self.assertFalse(cli.is_module_hit({"module_id": "unknown", "unknown": True}))
        self.assertFalse(cli.is_module_hit({}))

    def test_log_time(self):
        self.assertEqual(cli.log_time("10-10 10:00:00.123 enter demo"), "10-10 10:00:00.123")
        self.assertEqual(cli.log_time("2026-10-10 10:00:00 start"), "2026-10-10 10:00:00")
        self.assertEqual(cli.log_time("没有时间"), "")

    def test_paths_print_states(self):
        import io
        from contextlib import redirect_stdout
        info = {
            "file": "/tmp/repos.yaml",
            "repos": {
                "window_window_manager": {"raw": "/src", "path": "/src", "exists": True, "source": "file"},
                "scene_board_ext": {"raw": "", "path": "", "exists": False, "source": "file"},
            },
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("repos.load", return_value=info):
                cli.print_paths()
        text = buf.getvalue()
        self.assertIn("存在", text)
        self.assertIn("未配置", text)


if __name__ == "__main__":
    unittest.main()
