# -*- coding: utf-8 -*-
"""在已配置的源码仓里，按模块符号和日志原文找少量对照行。"""
import os
import re
import shutil
import subprocess

import repos

SOURCE_EXT = (".cpp", ".cc", ".h", ".hpp", ".ets", ".ts")
SKIP_DIR = {".git", "out", "node_modules", ".repo"}
STOP = {
    "success", "failed", "failure", "window", "error", "nullptr", "null",
    "create", "start", "stop", "show", "update", "register", "param",
}


def configured():
    info = repos.load()
    used = []
    missing = []
    for key in repos.KEYS:
        row = info["repos"][key]
        if row.get("exists"):
            used.append({"key": key, "path": row["path"]})
        else:
            missing.append(key)
    return used, missing


def _push(needles, text):
    raw = str(text or "").strip()
    if len(raw) < 6 or len(raw) > 80:
        return
    if raw.lower() in STOP:
        return
    if not re.search(r"[A-Za-z]", raw):
        return
    if raw not in needles:
        needles.append(raw)


def literals_from_regex(pattern):
    parts = re.split(r"[\[\](){}|+*?\\.^$\s]+", str(pattern or ""))
    return [p for p in parts if len(p) >= 10 and re.search(r"[A-Za-z]", p)]


def needles_of(mod, logs_text):
    needles = []
    for atom in mod.get("atoms") or []:
        if not isinstance(atom, dict):
            continue
        _push(needles, atom.get("api"))
        for layer in atom.get("callchain") or []:
            if not isinstance(layer, dict):
                continue
            for symbol in (layer.get("symbols") or layer.get("entry_symbols") or []):
                _push(needles, symbol)
        for key in ("enter", "success", "failures"):
            for lg in atom.get(key) or []:
                if not isinstance(lg, dict):
                    continue
                _push(needles, lg.get("function"))
                for lit in literals_from_regex(lg.get("regex")):
                    _push(needles, lit)
    for item in ((mod.get("apis") or {}).get("external") or []):
        if isinstance(item, dict):
            _push(needles, item.get("id"))
    for line in str(logs_text or "").splitlines():
        for lit in literals_from_regex(line):
            _push(needles, lit)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{7,}", line):
            _push(needles, token)
    needles.sort(key=len, reverse=True)
    return needles[:24]


def _parse_rg(repo, text):
    rows = []
    root = repo["path"]
    for raw in str(text or "").splitlines():
        # path:line:content  — path may contain a colon on some systems, not on macOS
        m = re.match(r"^(.*?):(\d+):(.*)$", raw)
        if not m:
            continue
        full, line_no, content = m.group(1), int(m.group(2)), m.group(3).strip()
        rel = os.path.relpath(full, root) if os.path.isabs(full) else full
        rows.append({
            "repo": repo["key"],
            "file": rel,
            "line": line_no,
            "text": content[:180],
        })
    return rows


def search(used, needles, limit, seen):
    rg = shutil.which("rg")
    if not rg or not needles or limit <= 0:
        return []
    found = []
    globs = []
    for ext in SOURCE_EXT:
        globs.extend(["-g", "*" + ext])
    for needle in needles:
        if len(found) >= limit:
            break
        for repo in used:
            cmd = [rg, "-n", "-F", "--max-count", "2", "--max-filesize", "1M"] + globs + ["-e", needle, repo["path"]]
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=8,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            for row in _parse_rg(repo, proc.stdout):
                key = (row["repo"], row["file"], row["line"])
                if key in seen:
                    continue
                seen.add(key)
                found.append(row)
                if len(found) >= limit:
                    return found
    return found


def log_needles(logs_text):
    needles = []
    for line in str(logs_text or "").splitlines():
        msg = re.sub(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*", "", line.strip())
        msg = re.sub(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*", "", msg)
        msg = msg.strip()
        if 8 <= len(msg) <= 80 and re.search(r"[A-Za-z]", msg):
            _push(needles, msg)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{9,}", line):
            _push(needles, token)
    needles.sort(key=len, reverse=True)
    return needles[:8]


def gather(mod, logs_text):
    used, missing = configured()
    if not used:
        return {"mode": "yaml", "used": [], "missing": missing, "snippets": []}
    seen = set()
    from_logs = search(used, log_needles(logs_text), 6, seen)
    symbols = [n for n in needles_of(mod, "") if n not in from_logs]
    from_yaml = search(used, symbols, 6, seen)
    return {
        "mode": "code",
        "used": [row["key"] for row in used],
        "missing": missing,
        "snippets": from_logs + from_yaml,
    }
