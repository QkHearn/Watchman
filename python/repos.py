# -*- coding: utf-8 -*-
import os
import sys

import yaml

KEYS = ("window_window_manager", "scene_board_ext")
ENV = {
    "window_window_manager": "WATCHMAN_WINDOW_MANAGER",
    "scene_board_ext": "WATCHMAN_SCENE_BOARD_EXT",
}


def watchman_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def config_file():
    override = str(os.environ.get("WATCHMAN_REPOS") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        beside = os.path.join(exe_dir, "config", "repos.yaml")
        parent = os.path.abspath(os.path.join(exe_dir, "..", "config", "repos.yaml"))
        if os.path.isfile(beside):
            return beside
        if os.path.isfile(parent):
            return parent
        return beside
    return os.path.join(watchman_root(), "config", "repos.yaml")


def resolve(raw, base_dir):
    text = str(raw or "").strip()
    if not text:
        return ""
    text = os.path.expanduser(text)
    if not os.path.isabs(text):
        text = os.path.abspath(os.path.join(base_dir, text))
    return text


def load_env():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates = [
            os.path.join(exe_dir, ".env"),
            os.path.abspath(os.path.join(exe_dir, "..", ".env")),
        ]
    else:
        candidates = [os.path.join(watchman_root(), ".env")]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                os.environ[key] = value
        return


def load():
    load_env()
    path = config_file()
    data = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            data = loaded
    base = os.path.dirname(os.path.abspath(path))
    repos = {}
    for key in KEYS:
        env_name = ENV[key]
        from_env = str(os.environ.get(env_name) or "").strip()
        raw = from_env or data.get(key) or ""
        resolved = resolve(raw, base)
        repos[key] = {
            "raw": str(raw or "").strip(),
            "path": resolved,
            "exists": bool(resolved) and os.path.isdir(resolved),
            "source": "env" if from_env else "file",
        }
    return {"file": path, "repos": repos}


def save_key(key, raw):
    if key not in KEYS:
        raise KeyError(key)
    path = config_file()
    value = str(raw or "").strip().replace('"', "")
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    prefix = key + ":"
    found = False
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            out.append('%s: "%s"' % (key, value))
            found = True
        else:
            out.append(line)
    if not found:
        out.append('%s: "%s"' % (key, value))
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
