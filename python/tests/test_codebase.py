# -*- coding: utf-8 -*-
import os
import shutil
import unittest

from fixtures import EnvGuard, temp_root
import codebase


class NeedleTest(unittest.TestCase):
    def test_log_phrase_survives_timestamp(self):
        needles = codebase.log_needles("10-10 10:00:00.123 start pip success\n")
        self.assertIn("start pip success", needles)

    def test_symbol_needles_skip_short_words(self):
        mod = {
            "atoms": [{
                "api": "Demo.start",
                "callchain": [{"symbols": ["OnStartPictureInPicture", "ok"]}],
                "enter": [{"function": "JsPipController", "regex": "start pip success|x"}],
                "success": [],
                "failures": [],
            }],
            "apis": {"external": [{"id": "PiPController.startPiP"}]},
        }
        needles = codebase.needles_of(mod, "")
        self.assertIn("OnStartPictureInPicture", needles)
        self.assertIn("JsPipController", needles)
        self.assertIn("PiPController.startPiP", needles)
        self.assertNotIn("ok", needles)
        self.assertNotIn("success", needles)


class SearchTest(unittest.TestCase):
    def test_gather_finds_log_line(self):
        if not shutil.which("rg"):
            self.skipTest("没有 rg")
        root = temp_root()
        src = os.path.join(root, "wm")
        os.makedirs(src)
        with open(os.path.join(src, "a.cpp"), "w", encoding="utf-8") as f:
            f.write('LOG("start pip success");\n')
        cfg = os.path.join(root, "repos.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('window_window_manager: "%s"\nscene_board_ext: ""\n' % src)
        mod = {"atoms": [], "apis": {}}
        keys = ["WATCHMAN_REPOS", "WATCHMAN_WINDOW_MANAGER", "WATCHMAN_SCENE_BOARD_EXT"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_REPOS", cfg)
            env.set("WATCHMAN_WINDOW_MANAGER", "")
            env.set("WATCHMAN_SCENE_BOARD_EXT", "")
            found = codebase.gather(mod, "10-10 10:00:00.123 start pip success\n")
        self.assertEqual(found["mode"], "code")
        self.assertEqual(found["used"], ["window_window_manager"])
        self.assertIn("scene_board_ext", found["missing"])
        self.assertTrue(any(row["file"] == "a.cpp" and row["line"] == 1 for row in found["snippets"]))

    def test_gather_without_repos_is_yaml(self):
        root = temp_root()
        cfg = os.path.join(root, "repos.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('window_window_manager: ""\nscene_board_ext: ""\n')
        keys = ["WATCHMAN_REPOS", "WATCHMAN_WINDOW_MANAGER", "WATCHMAN_SCENE_BOARD_EXT"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_REPOS", cfg)
            env.set("WATCHMAN_WINDOW_MANAGER", "")
            env.set("WATCHMAN_SCENE_BOARD_EXT", "")
            found = codebase.gather({"atoms": [], "apis": {}}, "")
        self.assertEqual(found["mode"], "yaml")
        self.assertEqual(found["snippets"], [])


if __name__ == "__main__":
    unittest.main()
