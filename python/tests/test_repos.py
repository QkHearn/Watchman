# -*- coding: utf-8 -*-
import os
import unittest

from fixtures import EnvGuard, temp_root
import repos


class SaveKeyTest(unittest.TestCase):
    def test_save_keeps_other_key(self):
        root = temp_root()
        cfg = os.path.join(root, "repos.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("# keep\nwindow_window_manager: \"src\"\nscene_board_ext: \"\"\n")
        keys = ["WATCHMAN_REPOS", "WATCHMAN_WINDOW_MANAGER", "WATCHMAN_SCENE_BOARD_EXT"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_REPOS", cfg)
            env.set("WATCHMAN_WINDOW_MANAGER", "")
            env.set("WATCHMAN_SCENE_BOARD_EXT", "")
            repos.save_key("scene_board_ext", "/tmp/scene_board_ext")
            info = repos.load()
        with open(cfg, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("# keep", text)
        self.assertIn('window_window_manager: "src"', text)
        self.assertEqual(info["repos"]["scene_board_ext"]["raw"], "/tmp/scene_board_ext")


class ReposTest(unittest.TestCase):
    def test_relative_path_and_env_override(self):
        root = temp_root()
        src = os.path.join(root, "src")
        override = os.path.join(root, "board")
        os.makedirs(src)
        os.makedirs(override)
        cfg = os.path.join(root, "repos.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('window_window_manager: "src"\nscene_board_ext: ""\n')
        keys = ["WATCHMAN_REPOS", "WATCHMAN_WINDOW_MANAGER", "WATCHMAN_SCENE_BOARD_EXT"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_REPOS", cfg)
            env.set("WATCHMAN_WINDOW_MANAGER", "")
            env.set("WATCHMAN_SCENE_BOARD_EXT", override)
            info = repos.load()
        wm = info["repos"]["window_window_manager"]
        board = info["repos"]["scene_board_ext"]
        self.assertEqual(wm["path"], src)
        self.assertTrue(wm["exists"])
        self.assertEqual(wm["source"], "file")
        self.assertEqual(board["path"], override)
        self.assertTrue(board["exists"])
        self.assertEqual(board["source"], "env")

    def test_missing_directory(self):
        root = temp_root()
        cfg = os.path.join(root, "repos.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('window_window_manager: "nope"\nscene_board_ext: ""\n')
        keys = ["WATCHMAN_REPOS", "WATCHMAN_WINDOW_MANAGER", "WATCHMAN_SCENE_BOARD_EXT"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_REPOS", cfg)
            env.set("WATCHMAN_WINDOW_MANAGER", "")
            env.set("WATCHMAN_SCENE_BOARD_EXT", "")
            info = repos.load()
        wm = info["repos"]["window_window_manager"]
        self.assertFalse(wm["exists"])
        self.assertTrue(wm["path"].endswith("nope"))
        self.assertEqual(info["repos"]["scene_board_ext"]["path"], "")


if __name__ == "__main__":
    unittest.main()
