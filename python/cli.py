# -*- coding: utf-8 -*-
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine
import repos


def is_module_hit(r):
    mid = (r or {}).get("module_id") or ""
    return bool(mid) and mid not in ("unknown", "out_of_scope") and not r.get("unknown") and not r.get("out_of_scope")


def log_time(line):
    m = re.search(r"\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", str(line or ""))
    return m.group(0) if m else ""


def print_triage(r):
    d = r.get("decision") or {}
    print("")
    print("分流")
    if r.get("out_of_scope"):
        print(r.get("module_name") or "非窗口问题")
    elif not is_module_hit(r):
        print(r.get("module_name") or "窗口问题，模块未分开")
    else:
        print((r.get("module_name") or r.get("module_id")) + "模块问题")
    ref = r.get("reference") or {}
    if ref.get("text"):
        print("参考历史  %s  %s" % (ref.get("id") or "", ref["text"]))
    if d.get("reason"):
        print(d["reason"])
    collect = r.get("collect") or {}
    if is_module_hit(r) and collect.get("regex"):
        print("")
        print("推荐正则")
        print(collect["regex"])
    print("")


def print_analysis(r):
    print("")
    if r.get("responsibility"):
        print("责任模块")
        print("  " + r["responsibility"])
        print("")
    sources = r.get("sources") or {}
    print("分析依据")
    used = sources.get("used") or []
    missing = sources.get("missing") or []
    if sources.get("mode") == "code" and used:
        print("  已纳入源码  " + "、".join(used))
    else:
        print("  源码路径未配置，只按 YAML")
    if missing and sources.get("mode") == "code":
        print("  未配置  " + "、".join(missing))
    if r.get("analysis_note"):
        print("  " + r["analysis_note"])
    print("")
    print("接口调用链条")
    steps = r.get("timeline") or []
    focus_id = (r.get("exception_scenario") or {}).get("id")
    if not steps:
        print("  日志未还原出调用链")
    for step in steps:
        first = (step.get("events") or [{}])[0]
        time = log_time(first.get("line")) or ("行 " + str(first.get("line_no")) if first.get("line_no") else "—")
        focused = step.get("atom_id") == focus_id and step.get("status") in ("fail", "unknown")
        chain = r.get("scenario_callchain") if focused and r.get("scenario_callchain") else (step.get("callchain") or [])
        print("  时间  " + time)
        print("  接口  " + (step.get("api") or step.get("title") or step.get("atom_id")))
        print("  链条")
        if not chain:
            print("    （无调用链）")
        for layer in chain:
            name = layer.get("name") or layer.get("do") or ""
            mark = "  ← 可能异常点" if layer.get("exception") else ""
            print("    " + (layer.get("layer_id") or "") + (("  " + name) if name else "") + mark)
    print("")
    print("可能异常点")
    broken = any(s.get("status") in ("fail", "unknown") for s in steps)
    pt = r.get("callchain_exception_point")
    if not broken:
        print("  未发现异常点")
    else:
        if pt and pt.get("layer_id"):
            funcs = pt.get("functions") or []
            print("  " + pt["layer_id"] + (("  /  " + ", ".join(funcs)) if funcs else ""))
        if r.get("hypothesis"):
            print("  " + r["hypothesis"])
        sc = r.get("exception_scenario") or {}
        if sc.get("locate"):
            print("  " + sc["locate"])
    print("")
    print("用户行为")
    print("  " + (r.get("user_behavior") or "现象未描述点击、滑动等操作。"))
    print("应用行为")
    print("  " + (r.get("app_behavior") or "日志没有对上已登记接口。"))
    print("系统行为")
    print("  " + (r.get("system_behavior") or "没有还原出框架处理。"))
    print("")


def ask(prompt):
    try:
        if prompt:
            sys.stdout.write(prompt)
            sys.stdout.flush()
        line = sys.stdin.readline()
    except EOFError:
        return None
    if line == "":
        return None
    return line.rstrip("\n")


def ask_block(title):
    print(title)
    print("多行输入，单独一行 END 结束。")
    lines = []
    while True:
        line = ask("")
        if line is None:
            return None
        if line.strip() == "END":
            return "\n".join(lines)
        lines.append(line)


def session():
    text = ask("问题现象> ")
    if text is None:
        return False
    text = text.strip()
    if not text:
        print("需要问题现象。")
        return False
    named = engine.modules_named_in(text, engine.load_modules())
    if len(named) == 1:
        print("现象已点名模块，按名称分流…")
    else:
        spec = engine.runner_spec()
        print("正在通过 %s 分流…" % spec["label"])
    routed = engine.route(text)
    print_triage(routed)
    if not is_module_hit(routed):
        again = ask("继续下一单？(y/N)> ")
        return again is not None and re.match(r"^y(es)?$", again.strip(), re.I)
    logs = ask_block("用上面的正则过滤日志后，把命中行粘贴到这里")
    if logs is None:
        return False
    if not str(logs).strip():
        print("没有日志，本单停在分流。")
    else:
        print("正在结合日志分析…")
        print_analysis(engine.analyze(routed["module_id"], text, logs))
    again = ask("继续下一单？(y/N)> ")
    return again is not None and re.match(r"^y(es)?$", again.strip(), re.I)


def ensure_repos():
    info = repos.load()
    print("源码路径")
    for key in repos.KEYS:
        row = info["repos"][key]
        if row["exists"]:
            print("  %s  已配置  %s" % (key, row["path"]))
            continue
        print("  %s  未配置" % key)
        entered = ask("请输入 %s 路径，回车跳过> " % key)
        if entered is None:
            return False
        entered = entered.strip()
        if not entered:
            continue
        resolved = repos.resolve(entered, os.path.dirname(info["file"]))
        if not os.path.isdir(resolved):
            print("  目录不存在，本次不写入：%s" % (resolved or entered))
            continue
        repos.save_key(key, entered)
        print("  已写入  %s" % resolved)
    print("")
    return True


def agent_logged_in():
    spec = engine.runner_spec()
    if spec["name"] != "cursor" or not engine.runner_available():
        return True
    cmd = [spec["cmd"], "status"] if engine.is_agent_binary(spec["cmd"]) else [spec["cmd"], "agent", "status"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = proc.stdout or ""
    return "Not logged in" not in text and "Authentication required" not in text


def ensure_ai():
    spec = engine.runner_spec()
    print("AI 命令  " + spec["label"])
    if spec["name"] != "cursor":
        print("")
        return True
    if agent_logged_in():
        print("AI  使用 %s" % spec["label"])
        print("")
        return True
    print("cursor-agent 未登录，当前不能使用 AI 分流。")
    entered = ask("现在登录？(y/N)> ")
    if entered is None:
        return False
    if not re.match(r"^y(es)?$", entered.strip(), re.I):
        print("本次分流在需要模型时会改用名称匹配。")
        print("")
        return True
    cmd = [spec["cmd"], "login"] if engine.is_agent_binary(spec["cmd"]) else [spec["cmd"], "agent", "login"]
    subprocess.call(cmd)
    print("")
    return True


def print_paths():
    info = repos.load()
    print("配置文件  " + info["file"])
    for key in repos.KEYS:
        row = info["repos"][key]
        if not row["raw"]:
            state = "未配置"
        elif row["exists"]:
            state = "存在"
        else:
            state = "目录不存在"
        print("%s  %s  %s" % (key, row["path"] or "（空）", state))


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("paths", "repos"):
        print_paths()
        return 0
    print("Watchman 离线")
    print("输入问题现象。分到模块后，按提示粘贴日志。")
    print("")
    if not ensure_repos() or not ensure_ai():
        return 0
    while session():
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
