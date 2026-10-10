# -*- coding: utf-8 -*-
import os
import sys
import tempfile

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class EnvGuard(object):
    def __init__(self, keys):
        self.keys = keys
        self.saved = {}

    def __enter__(self):
        for key in self.keys:
            self.saved[key] = os.environ.get(key)
        return self

    def set(self, key, value):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, old in self.saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def module(module_id, name, description="", blacklist=None, atoms=None, collect="DEMO_LOG"):
    return {
        "module_id": module_id,
        "enabled": True,
        "meta": {"name": name, "description": description},
        "log_blacklist": blacklist or [],
        "apis": {"external": [{"id": name + ".start"}]},
        "atoms": atoms if atoms is not None else [],
        "collect": {"regex": collect} if collect else {},
    }


def demo_atom():
    return {
        "id": "start",
        "title": "启动",
        "api": "Demo.start",
        "callchain": [
            {"layer_id": "L1", "name": "应用调用", "symbols": ["Demo.start"]},
            {"layer_id": "L2", "name": "框架处理", "symbols": ["Framework.run"]},
        ],
        "enter": [{
            "id": "IN",
            "regex": "enter demo",
            "flags": "i",
            "layer_id": "L1",
            "function": "Demo.start",
            "meaning": "已进入",
        }],
        "success": [{
            "id": "OK",
            "regex": "demo success",
            "flags": "i",
            "layer_id": "L2",
            "function": "Framework.run",
            "meaning": "已成功",
        }],
        "failures": [{
            "id": "BAD",
            "regex": "demo failed",
            "flags": "i",
            "layer_id": "L1",
            "kind": "应用误用",
            "meaning": "参数错误",
            "locate": "核对入参",
            "function": "Demo.start",
        }],
    }


def write_modules(root, docs):
    for doc in docs:
        folder = os.path.join(root, "modules", doc["module_id"])
        os.makedirs(folder)
        with open(os.path.join(folder, "module.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)


def temp_root():
    return tempfile.mkdtemp(prefix="watchman-test-")
