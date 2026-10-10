# -*- coding: utf-8 -*-
import os
import unittest
from unittest.mock import patch

from fixtures import EnvGuard, demo_atom, module, temp_root, write_modules
import engine


def sample_modules():
    return [
        module("pip", "画中画", "小窗播放", blacklist=[
            {"id": "BL-AV", "regex": "AVPlayer", "flags": "i", "to_module": "", "to_module_name": "媒体播放", "reason": "纯播放器"},
        ], atoms=[demo_atom()], collect="PIP_LOG"),
        module("sub", "子窗口", "应用内子窗"),
    ]


class ParseTest(unittest.TestCase):
    def test_extract_json_fenced_and_raw(self):
        self.assertEqual(engine.extract_json('说明\n```json\n{"scores":[]}\n```'), {"scores": []})
        self.assertEqual(engine.extract_json('前文 {"a": 1} 后文'), {"a": 1})

    def test_extract_json_missing(self):
        with self.assertRaises(ValueError):
            engine.extract_json("没有对象")

    def test_compile_re_rejects_bad_pattern(self):
        self.assertIsNone(engine.compile_re("["))
        self.assertTrue(engine.match_re("(?i)Demo", "", "demo"))

    def test_pick_scores(self):
        low = engine.pick_scores([{"module_id": "a", "name": "甲", "score": 10, "reason": ""}], 40, 15)
        close = engine.pick_scores([
            {"module_id": "a", "name": "甲", "score": 80, "reason": ""},
            {"module_id": "b", "name": "乙", "score": 70, "reason": ""},
        ], 40, 15)
        win = engine.pick_scores([
            {"module_id": "a", "name": "甲", "score": 80, "reason": "像"},
            {"module_id": "b", "name": "乙", "score": 20, "reason": ""},
        ], 40, 15)
        self.assertEqual(low["module_id"], "unknown")
        self.assertFalse(low["ambiguous"])
        self.assertTrue(close["ambiguous"])
        self.assertEqual(win["module_id"], "a")

    def test_text_boundary_and_compose(self):
        self.assertFalse(engine.text_has("window_layout", "window"))
        self.assertTrue(engine.text_has("使用 pip 接口", "pip"))
        self.assertTrue(engine.text_has("媒体播放失败", "媒体播放"))
        with patch("engine.global_prompt", return_value="# Watchman"):
            self.assertEqual(engine.compose_prompt("本次任务"), "# Watchman\n\n本次任务")


class RunnerSpecTest(unittest.TestCase):
    def test_run_env_overrides_file(self):
        keys = ["WATCHMAN_ENV", "WATCHMAN_RUN", "WATCHMAN_CURSOR", "WATCHMAN_NGA"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_ENV", "test")
            env.set("WATCHMAN_CURSOR", "")
            env.set("WATCHMAN_NGA", "")
            env.set("WATCHMAN_RUN", 'cursor-agent -p --mode ask --trust --output-format text')
            spec = engine.runner_spec()
        self.assertEqual(spec["args"], [
            "cursor-agent", "-p", "--mode", "ask", "--trust", "--output-format", "text",
        ])
        self.assertNotIn("run", spec["args"])

    def test_binary_override_keeps_flags(self):
        keys = ["WATCHMAN_ENV", "WATCHMAN_RUN", "WATCHMAN_CURSOR"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_ENV", "test")
            env.set("WATCHMAN_RUN", "cursor-agent -p --trust")
            env.set("WATCHMAN_CURSOR", "/tmp/cursor-agent")
            spec = engine.runner_spec()
        self.assertEqual(spec["args"], ["/tmp/cursor-agent", "-p", "--trust"])

    def test_production_file_uses_nga_run(self):
        root = temp_root()
        path = os.path.join(root, "runner.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write('test: "echo test"\nproduction: "nga run"\n')
        keys = ["WATCHMAN_ENV", "WATCHMAN_RUN", "WATCHMAN_RUNNER", "WATCHMAN_NGA", "WATCHMAN_CURSOR"]
        with EnvGuard(keys) as env:
            env.set("WATCHMAN_ENV", "production")
            env.set("WATCHMAN_RUN", "")
            env.set("WATCHMAN_NGA", "")
            env.set("WATCHMAN_CURSOR", "")
            env.set("WATCHMAN_RUNNER", path)
            spec = engine.runner_spec()
        self.assertEqual(spec["args"], ["nga", "run"])
        self.assertEqual(spec["name"], "nga")


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.remembered = []
        self.patches = [
            patch("engine.load_modules", return_value=sample_modules()),
            patch("engine.runner_available", return_value=False),
            patch("engine.history.best", return_value=None),
            patch("engine.history.remember", side_effect=self._remember),
        ]
        for item in self.patches:
            item.start()

    def _remember(self, text, name=None):
        self.remembered.append(text)
        return {"id": "NW-TEST", "fresh": True, "text": text, "name": name or "other"}

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def test_named_module(self):
        routed = engine.route("画中画第二次启动失败")
        self.assertEqual(routed["module_id"], "pip")
        self.assertEqual(routed["collect"]["regex"], "PIP_LOG")
        self.assertEqual(self.remembered, [])

    def test_blacklist_routes_to_responsible_module(self):
        mods = sample_modules()
        mods[1]["log_blacklist"] = [{
            "id": "BL-SPLIT",
            "regex": "splitScreen",
            "to_module": "pip",
            "to_module_name": "分屏",
            "reason": "分屏归画中画",
        }]
        with patch("engine.load_modules", return_value=mods):
            routed = engine.route("分屏打不开")
        self.assertEqual(routed["module_id"], "pip")
        self.assertEqual(routed["decision"]["rule"], "blacklist")
        self.assertEqual(self.remembered, [])

    def test_foreign_blacklist_is_non_window(self):
        routed = engine.route("媒体播放没有声音")
        self.assertEqual(routed["module_id"], "out_of_scope")
        self.assertIn("媒体播放", routed["module_name"])
        self.assertEqual(len(self.remembered), 1)
        self.assertEqual(self.remembered[0], "媒体播放没有声音")

    def test_history_blocks_before_remember(self):
        hit = {"id": "NW-1", "text": "蓝牙连不上", "name": "蓝牙", "score": 0.9}
        with patch("engine.history.best", return_value=hit):
            routed = engine.route("蓝牙连不上了")
        self.assertEqual(routed["decision"]["rule"], "history_blacklist")
        self.assertEqual(routed["reference"]["id"], "NW-1")
        self.assertEqual(self.remembered, [])

    def test_close_modules_stay_window(self):
        mods = [module("pip", "画中画"), module("sub", "子窗口")]
        with patch("engine.load_modules", return_value=mods):
            routed = engine.route("画中画和子窗口都坏了")
        self.assertEqual(routed["module_id"], "unknown")
        self.assertTrue(routed["unknown"])
        self.assertIn("窗口问题", routed["module_name"])
        self.assertEqual(self.remembered, [])

    def test_empty_symptom(self):
        routed = engine.route("  ")
        self.assertTrue(routed["out_of_scope"])
        self.assertEqual(self.remembered, [])


class LocalizeTest(unittest.TestCase):
    def setUp(self):
        self.root = temp_root()
        doc = module("demo", "示例", atoms=[demo_atom()], collect="enter demo")
        write_modules(self.root, [doc])
        self.patch = patch("engine.project_root", return_value=self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_success_has_no_exception(self):
        result = engine.localize("demo", "enter demo\ndemo success\n")
        self.assertEqual(result["timeline"][0]["status"], "ok")
        self.assertEqual(result["timeline"][0]["api"], "Demo.start")
        self.assertFalse(any(layer.get("exception") for layer in result["scenario_callchain"]))

    def test_enter_without_success_marks_next_layer(self):
        result = engine.localize("demo", "10-10 10:00:00.123 enter demo\n")
        self.assertEqual(result["timeline"][0]["status"], "unknown")
        marked = [layer["layer_id"] for layer in result["scenario_callchain"] if layer.get("exception")]
        self.assertEqual(marked, ["L2"])

    def test_known_failure(self):
        result = engine.localize("demo", "demo failed\n")
        self.assertEqual(result["timeline"][0]["status"], "fail")
        self.assertIn("应用误用", result["hypothesis"])
        self.assertEqual(result["exception_scenario"]["locate"], "核对入参")

    def test_missing_module(self):
        with self.assertRaises(KeyError):
            engine.localize("missing", "enter demo")


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.root = temp_root()
        demo = module("demo", "示例", atoms=[demo_atom()], collect="enter demo")
        other = module("other", "邻模块", atoms=[demo_atom()], collect="OTHER")
        other["log_blacklist"] = [{
            "id": "BL",
            "regex": "AVPLAYER_ONLY",
            "to_module": "other",
            "to_module_name": "邻模块",
            "reason": "这是邻模块的日志",
        }]
        foreign = module("demo", "示例")
        self.docs = (demo, other, foreign)
        write_modules(self.root, [demo, other])
        self.patches = [
            patch("engine.project_root", return_value=self.root),
            patch("engine.runner_available", return_value=False),
            patch("engine.codebase.gather", return_value={"mode": "yaml", "used": [], "missing": ["window_window_manager", "scene_board_ext"], "snippets": []}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def test_behaviors_without_source(self):
        result = engine.analyze("demo", "点击后没有出来", "enter demo\n")
        self.assertEqual(result["sources"]["mode"], "yaml")
        self.assertIn("点击", result["user_behavior"])
        self.assertIn("Demo.start", result["app_behavior"])
        self.assertIn("只根据 YAML", result["system_behavior"])
        self.assertIn("不可用", result["analysis_note"])

    def test_log_blacklist_switches_module(self):
        result = engine.analyze("demo", "点击没反应", "AVPLAYER_ONLY enter demo\n")
        self.assertEqual(result["module_id"], "other")
        self.assertIn("邻模块", result["responsibility"])

    def test_code_snippet_is_cited(self):
        code = {
            "mode": "code",
            "used": ["window_window_manager"],
            "missing": ["scene_board_ext"],
            "snippets": [{"repo": "window_window_manager", "file": "wm/a.cpp", "line": 8, "text": "enter demo"}],
        }
        with patch("engine.codebase.gather", return_value=code):
            result = engine.analyze("demo", "没有操作描述", "enter demo\n")
        self.assertIn("wm/a.cpp:8", result["system_behavior"])
        self.assertIn("未描述", result["user_behavior"])


class ExclusionScoreTest(unittest.TestCase):
    def test_neighbor_mention_excludes_that_module(self):
        docs = [
            module("pip", "画中画", "【做什么】小窗没出来。\n【不要分流】闪控窗 / 闪控球。"),
            module("float_view", "闪控窗", "【做什么】与画中画互斥，窗没出来。\n【不要分流】画中画 / 闪控球。"),
            module("floating_ball", "闪控球", "【做什么】球没出来。\n【不要分流】画中画 / 闪控窗。"),
        ]
        catalog = [engine.catalog_of(doc) for doc in docs]
        result = engine.heuristic_match("画中画 没有正确拉起", catalog)
        self.assertEqual(result["module_id"], "pip")
        by_name = {row["name"]: row for row in result["scores"]}
        self.assertIn("排他", by_name["闪控窗"]["reason"])
        self.assertNotIn("描述重叠", by_name["闪控窗"]["reason"])
        self.assertLess(by_name["闪控窗"]["score"], 0)
        self.assertLess(by_name["闪控球"]["score"], 0)


class AiUnavailableTest(unittest.TestCase):
    def test_auth_failure_is_not_recorded(self):
        remembered = []

        def boom(prompt):
            raise RuntimeError("Authentication required")

        def remember(text, name=None):
            remembered.append(text)
            return {"id": "NW-TEST", "fresh": True, "text": text, "name": name or "other"}

        with patch("engine.runner_available", return_value=True), \
                patch("engine.run_ai", side_effect=boom), \
                patch("engine.history.best", return_value=None), \
                patch("engine.history.remember", side_effect=remember), \
                patch("engine.load_modules", return_value=[module("pip", "画中画", "小窗")]):
            routed = engine.route("蓝牙耳机没有声音")
        self.assertEqual(routed["decision"]["rule"], "ai_unavailable")
        self.assertIn("没有使用 AI", routed["decision"]["reason"])
        self.assertEqual(remembered, [])


class NamedModuleRouteTest(unittest.TestCase):
    def test_explicit_pip_name_does_not_call_agent(self):
        def boom(prompt):
            raise AssertionError("现象已点名模块，不应调用模型")

        with patch("engine.run_ai", side_effect=boom):
            routed = engine.route("画中画 没有正确拉起")
        self.assertEqual(routed["module_id"], "pip")
        self.assertEqual(routed["decision"]["rule"], "name")
        self.assertIn("画中画", routed["module_name"])


class DisabledModuleTest(unittest.TestCase):
    def test_disabled_and_template_are_skipped(self):
        root = temp_root()
        write_modules(root, [module("demo", "示例")])
        os.makedirs(os.path.join(root, "modules", "_template"))
        off = module("off", "关闭")
        off["enabled"] = False
        write_modules(root, [off])
        with patch("engine.project_root", return_value=root):
            loaded = engine.load_modules()
        self.assertEqual([m["module_id"] for m in loaded], ["demo"])


if __name__ == "__main__":
    unittest.main()
