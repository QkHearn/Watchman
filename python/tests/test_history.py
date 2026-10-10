# -*- coding: utf-8 -*-
import os
import unittest

from fixtures import EnvGuard, temp_root
import history


class SimilarityTest(unittest.TestCase):
    def test_exact_and_empty(self):
        self.assertEqual(history.similarity("蓝牙连不上", "蓝牙连不上"), 1)
        self.assertEqual(history.similarity("", "蓝牙"), 0)
        self.assertEqual(history.similarity("蓝牙连不上。", "蓝牙连不上"), 1)

    def test_extreme_threshold(self):
        near = history.similarity("蓝牙连不上", "蓝牙连不上了")
        far = history.similarity("蓝牙连不上", "蓝牙连接不上")
        self.assertGreaterEqual(near, history.EXTREME)
        self.assertLess(far, history.EXTREME)

    def test_contained_long_text(self):
        self.assertEqual(history.similarity("画中画第二次启动失败", "今天画中画第二次启动失败请看日志"), 0.9)


class RememberTest(unittest.TestCase):
    def test_remember_once_then_reuse(self):
        folder = temp_root()
        with EnvGuard(["WATCHMAN_OOS_DIR"]) as env:
            env.set("WATCHMAN_OOS_DIR", folder)
            first = history.remember("蓝牙连不上", "蓝牙")
            second = history.remember("蓝牙连不上", "蓝牙")
            third = history.remember("  ", "蓝牙")
        self.assertTrue(first["fresh"])
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(second["fresh"])
        self.assertIsNone(third)
        self.assertTrue(os.path.isfile(os.path.join(folder, first["id"] + ".yaml")))

    def test_best_ignores_weak_match(self):
        folder = temp_root()
        with EnvGuard(["WATCHMAN_OOS_DIR"]) as env:
            env.set("WATCHMAN_OOS_DIR", folder)
            history.remember("蓝牙连不上", "蓝牙")
            self.assertIsNone(history.best("蓝牙连接不上"))
            hit = history.best("蓝牙连不上了")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["name"], "蓝牙")


if __name__ == "__main__":
    unittest.main()
