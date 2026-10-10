# -*- coding: utf-8 -*-
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

import yaml

import codebase
import history

STOP = set("问题,现象,失败,无法,不能,第二次,连续,两次,一次,应用,通过,覆盖,不做,普通,以及,已经,成功,调用,接口,模块,日志,错误,异常,打开,点击,之后,然后,没有,不到,黑屏,白屏,卡死,闪退,启动,停止,创建,还原,参数,校验,能力,状态,操作,内容,页面,多屏".split(","))
AI_CAP = 12


def project_root():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def arr(v):
    return v if isinstance(v, list) else []


def compile_re(pattern, flags=""):
    if not pattern:
        return None
    p = str(pattern)
    f = str(flags or "")
    if p.startswith("(?i)"):
        p = p[4:]
        if "i" not in f:
            f += "i"
    rf = re.IGNORECASE if "i" in f.lower() else 0
    try:
        return re.compile(p, rf)
    except re.error:
        return None


def match_re(pattern, flags, text):
    cre = compile_re(pattern, flags)
    return bool(cre and cre.search(str(text or "")))


def load_modules():
    root = os.path.join(project_root(), "modules")
    mods = []
    if not os.path.isdir(root):
        return mods
    for name in sorted(os.listdir(root)):
        if name.startswith(".") or name == "_template":
            continue
        path = os.path.join(root, name, "module.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except Exception:
            continue
        if not doc or doc.get("enabled") is False:
            continue
        doc["module_id"] = doc.get("module_id") or name
        mods.append(doc)
    return mods


def meta_name(mod):
    return ((mod.get("meta") or {}).get("name")) or mod.get("module_id")


def apis_of(mod):
    src = mod.get("apis") or {}
    if isinstance(src, dict):
        return arr(src.get("external")) + arr(src.get("internal")) + arr(src.get("dependencies") or src.get("deps"))
    return arr(src)


def api_id(item):
    if isinstance(item, dict):
        return item.get("id") or item.get("symbol") or ""
    return str(item or "")


def atoms_of(mod):
    return [a for a in arr(mod.get("atoms")) if a and a.get("id")]


def catalog_of(mod):
    fn = []
    for item in apis_of(mod):
        ident = api_id(item)
        if ident:
            fn.append(ident)
        if isinstance(item, dict) and item.get("label"):
            fn.append(item["label"])
    for atom in atoms_of(mod):
        for layer in arr(atom.get("callchain")):
            for s in arr(layer.get("symbols") or layer.get("entry_symbols")):
                fn.append(s)
    meta = mod.get("meta") or {}
    return {
        "module_id": mod["module_id"],
        "name": meta.get("name") or mod["module_id"],
        "name_en": meta.get("name_en") or "",
        "field_name": meta.get("field_name") or "",
        "field_id": meta.get("field_id") or "",
        "description": meta.get("description") or "",
        "functions": list(dict.fromkeys([x for x in fn if x])),
        "aliases": [x for x in [meta.get("name"), meta.get("name_en"), mod["module_id"], meta.get("field_name")] if x],
    }


def collect_of(mod):
    q = mod.get("collect") or {}
    regex = str(q.get("regex") or q.get("pattern") or "").strip()
    if not regex:
        return None
    return {"title": q.get("title") or "请复制下面正则到 BetaClub 搜集日志", "regex": regex}


def blacklist_of(mod):
    return [b for b in arr(mod.get("log_blacklist")) if b and b.get("regex")]


def text_has(text, needle):
    needle = str(needle or "").strip()
    if not needle:
        return False
    if re.search(r"[\u4e00-\u9fff]", needle):
        return len(needle) >= 2 and needle in text
    return contains_ident(str(text or "").lower(), needle, text)


def blacklist_symptom(text, mods):
    best = None
    best_len = 0
    for mod in mods:
        for b in blacklist_of(mod):
            name = str(b.get("to_module_name") or "").strip()
            ident = str(b.get("to_module") or "").strip()
            needles = [s.strip() for s in re.split(r"[/、,，|]", name) if len(s.strip()) >= 2]
            if len(ident) >= 3:
                needles.append(ident)
            hit = ""
            for n in needles:
                if text_has(text, n) and len(n) > len(hit):
                    hit = n
            if not hit or len(hit) <= best_len:
                continue
            best_len = len(hit)
            best = {
                "to_module": ident,
                "to_module_name": name or ident,
                "reason": str(b.get("reason") or "").strip(),
            }
    return best


def modules_named_in(text, mods):
    text = str(text or "")
    hits = []
    for mod in mods:
        name = meta_name(mod)
        if name and len(name) >= 2 and name in text:
            hits.append(mod)
    names = [meta_name(mod) for mod in hits]
    kept = []
    for mod in hits:
        name = meta_name(mod)
        if any(name != other and name in other for other in names):
            continue
        kept.append(mod)
    return kept


def named_module(text, mods):
    return bool(modules_named_in(text, mods))


def escape_re(s):
    return re.escape(str(s))


def idents_of(raw):
    out = set()
    for part in re.split(r"[./:_-]+", str(raw or "")):
        if not part:
            continue
        out.add(part)
        bits = re.findall(r"[A-Z]{2,}(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", part) or []
        out.update(bits)
    return list(out)


def contains_ident(hay, ident, original):
    ident = str(ident or "").strip()
    if not ident:
        return False
    if re.search(r"[\u4e00-\u9fff]", ident):
        return len(ident) >= 2 and ident in original
    low = ident.lower()
    if len(low) < 3:
        return False
    return re.search(r"(?:^|[^a-z0-9_])" + escape_re(low) + r"(?:$|[^a-z0-9_])", hay, re.I) is not None


def chinese_grams(s):
    out = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", str(s or "")):
        for n in (2, 3):
            for i in range(0, max(0, len(run) - n + 1)):
                out.add(run[i:i + n])
    return out


def positive_description(d):
    text = re.split(r"不做[：:]", str(d or ""))[0]
    return re.split(r"【不要分流】", text)[0]


def neighbor_names(description, own_name, names):
    text = str(description or "")
    found = []
    for name in sorted([n for n in names if n], key=len, reverse=True):
        if name == own_name or len(name) < 2:
            continue
        if name in text and name not in found:
            found.append(name)
    return found


def gram_in_names(gram, names):
    return any(gram in name for name in names)


def heuristic_match(phenomenon, catalog):
    text = str(phenomenon or "").strip()
    if not text:
        return {"module_id": "unknown", "ambiguous": False, "reason": "现象为空，无法按描述匹配", "ai_used": False, "scores": []}
    hay = text.lower()
    all_names = [m["name"] for m in catalog if m.get("name")]
    all_scores = []
    for m in catalog:
        why = []
        score = 0
        foreign = neighbor_names(m.get("description"), m.get("name"), all_names)
        blocked = [name for name in foreign if name in text]
        own_named = bool(m.get("name") and m["name"] in text)
        for alias in m["aliases"]:
            if contains_ident(hay, alias, text) or (re.search(r"[\u4e00-\u9fff]", alias) and alias in text):
                score += 50
                why.append("名称 " + alias)
                break
        seen = set()
        fn_hits = []
        for fn in m["functions"]:
            hit = ""
            for p in [fn] + idents_of(fn):
                if contains_ident(hay, p, text) and len(str(p)) > len(hit):
                    hit = str(p)
            if hit and hit.lower() not in seen:
                seen.add(hit.lower())
                fn_hits.append(hit)
                score += 30 if len(hit) >= 6 else 18
        if fn_hits:
            why.append("函数 " + "/".join(fn_hits[:3]))
        overlap = []
        for gram in chinese_grams(positive_description(m["description"])):
            if gram in STOP or len(gram) < 2 or gram_in_names(gram, foreign):
                continue
            if gram in text:
                overlap.append(gram)
        uniq = []
        for t in overlap:
            if t in uniq:
                continue
            if len(t) >= 3 or not any(len(x) > len(t) and t in x for x in overlap):
                uniq.append(t)
        if uniq:
            score += len(uniq) * 20
            why.append("描述重叠 " + "/".join(uniq[:4]))
        if blocked and not own_named:
            score -= 80
            why.append("排他 " + "/".join(blocked))
        all_scores.append({"module_id": m["module_id"], "name": m["name"], "score": score, "reason": "；".join(why) or "无命中"})
    all_scores.sort(key=lambda x: (-x["score"], x["module_id"]))
    best = all_scores[0] if all_scores else None
    second = all_scores[1] if len(all_scores) > 1 else None
    if not best or best["score"] < 18:
        return {"module_id": "unknown", "ambiguous": False, "reason": "现象未命中已接入模块的名称或函数，也不足以匹配描述", "ai_used": False, "scores": all_scores, "oos_name": "other"}
    if second and second["score"] >= 18 and best["score"] - second["score"] < 18:
        return {
            "module_id": "unknown",
            "ambiguous": True,
            "reason": "多个模块描述接近（%s / %s），无法自动判定" % (best["name"], second["name"]),
            "ai_used": False,
            "scores": all_scores,
            "oos_name": "other",
        }
    return {
        "module_id": best["module_id"],
        "reason": "按模块名称/函数/描述匹配到「%s」（%s）" % (best["name"], best["reason"]),
        "confidence": "medium" if best["score"] >= 50 else "low",
        "ambiguous": False,
        "ai_used": False,
        "scores": all_scores,
        "oos_name": "other",
    }


DEFAULT_COMMANDS = {
    "test": "cursor-agent -p --mode ask --trust --output-format text",
    "production": "nga run",
}


def is_agent_binary(cmd):
    base = os.path.basename(str(cmd or "")).lower()
    return base == "agent" or base.startswith("cursor-agent")


def runner_config_file():
    override = str(os.environ.get("WATCHMAN_RUNNER") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        beside = os.path.join(exe_dir, "config", "runner.yaml")
        parent = os.path.abspath(os.path.join(exe_dir, "..", "config", "runner.yaml"))
        if os.path.isfile(beside):
            return beside
        if os.path.isfile(parent):
            return parent
        return beside
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "runner.yaml"))


def runner_profile():
    env_name = str(os.environ.get("WATCHMAN_ENV") or "test").strip().lower()
    if env_name in ("prod", "production"):
        return "production"
    return "test"


def load_runner_line():
    explicit = str(os.environ.get("WATCHMAN_RUN") or "").strip()
    if explicit:
        return explicit
    path = runner_config_file()
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            data = {}
    key = runner_profile()
    line = str(data.get(key) or "").strip()
    return line or DEFAULT_COMMANDS[key]


def split_command(line):
    return shlex.split(str(line or "").strip(), posix=(os.name != "nt"))


def runner_spec():
    args = split_command(load_runner_line())
    if not args:
        args = split_command(DEFAULT_COMMANDS[runner_profile()])
    binary = str(os.environ.get("WATCHMAN_NGA") or "").strip() if runner_profile() == "production" else str(os.environ.get("WATCHMAN_CURSOR") or "").strip()
    if binary:
        args[0] = binary
    cmd = args[0]
    base = os.path.basename(cmd).lower()
    name = "nga" if base == "nga" or base.startswith("nga") else "cursor"
    return {"name": name, "cmd": cmd, "args": args, "label": " ".join(args)}


def runner_available():
    cmd = runner_spec()["cmd"]
    if os.path.isabs(cmd):
        return os.path.isfile(cmd) and os.access(cmd, os.X_OK)
    return shutil.which(cmd) is not None


def extract_json(text):
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    body = fenced.group(1) if fenced else raw
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("run 输出里没有 JSON")
    return json.loads(body[start:end + 1])


def agent_prompt_file():
    override = str(os.environ.get("WATCHMAN_AGENT_PROMPT") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        beside = os.path.join(exe_dir, "config", "agent.md")
        parent = os.path.abspath(os.path.join(exe_dir, "..", "config", "agent.md"))
        if os.path.isfile(beside):
            return beside
        if os.path.isfile(parent):
            return parent
        return beside
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "agent.md"))


def global_prompt():
    path = agent_prompt_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def compose_prompt(task):
    task = str(task or "").strip()
    head = global_prompt()
    if head and task:
        return head + "\n\n" + task
    return head or task


def run_ai(prompt):
    spec = runner_spec()
    timeout = int(os.environ.get("LLM_TIMEOUT_MS") or "120000") / 1000.0
    proc = subprocess.run(
        spec["args"] + [compose_prompt(prompt)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:400]
        raise RuntimeError(spec["label"] + " 退出 %s%s" % (proc.returncode, ("：" + detail) if detail else ""))
    return {"text": proc.stdout or "", "runner": spec["label"]}


def pick_scores(scores, minimum, margin):
    ranked = sorted(scores, key=lambda x: -x["score"])
    best = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    if not best or best["score"] < minimum:
        return {"module_id": "unknown", "ambiguous": False, "reason": "各模块 AI 得分都低于 %s，无法确定" % minimum}
    if second and best["score"] - second["score"] < margin:
        return {
            "module_id": "unknown",
            "ambiguous": True,
            "reason": "AI 打分接近（%s %s / %s %s），无法自动判定" % (best["name"], best["score"], second["name"], second["score"]),
        }
    return {
        "module_id": best["module_id"],
        "ambiguous": False,
        "reason": "AI 按现象与模块描述打分，最高「%s」%s 分%s" % (best["name"], best["score"], ("：" + best["reason"]) if best.get("reason") else ""),
    }


def ai_score(phenomenon, catalog):
    spec = runner_spec()
    slim_desc = 280 if len(catalog) > 24 else 520
    payload = {
        "phenomenon": phenomenon,
        "catalog": [{
            "module_id": m["module_id"],
            "name": m["name"],
            "name_en": m["name_en"],
            "description": positive_description(m["description"])[:slim_desc],
            "exclude": neighbor_names(m.get("description"), m.get("name"), [c["name"] for c in catalog if c.get("name")]),
            "functions": [] if len(catalog) > 20 else m["functions"][:8],
        } for m in catalog],
    }
    prompt = (
        "本次任务是分流打分。请根据「问题现象」对 catalog 中每一个模块打 0～100 分。"
        "依据：模块中文名/英文名、description 里该模块自己做什么、函数名。"
        "exclude 是这个模块声明自己不负责的邻居。现象落到 exclude 里的名字时，必须给这个模块很低分。"
        "exclude 里的名字是该模块的排他证据，不能当成它命中了那个邻居。"
        "描述里写明「不做」的现象必须给很低分。"
        "必须为 catalog 里每个 module_id 输出一条，不要发明 catalog 里的模块。"
        "若现象明显不属于任何 catalog 模块，另给 oos_name：能判断领域则填中文名（如 悬浮窗），否则填 other。"
        "只输出 JSON：{\"scores\":[{\"module_id\":\"...\",\"score\":0,\"reason\":\"中文短理由\"}],\"oos_name\":\"other\"}\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        ran = run_ai(prompt)
        data = extract_json(ran["text"])
        by_id = {}
        for row in arr(data.get("scores")):
            if row and row.get("module_id"):
                by_id[str(row["module_id"])] = row
        scores = []
        for m in catalog:
            row = by_id.get(m["module_id"]) or {}
            try:
                score = int(round(float(row.get("score") or 0)))
            except (TypeError, ValueError):
                score = 0
            score = max(0, min(100, score))
            scores.append({"module_id": m["module_id"], "name": m["name"], "score": score, "reason": str(row.get("reason") or "")})
        scores.sort(key=lambda x: -x["score"])
        picked = pick_scores(scores, 40, 15)
        oos_name = re.sub(r"^非窗口问题[：:]", "", str(data.get("oos_name") or "")).strip()
        if len(oos_name) > 40:
            oos_name = oos_name[:40]
        if any(m["module_id"] == oos_name or m["name"] == oos_name for m in catalog):
            oos_name = ""
        return {
            "module_id": picked["module_id"],
            "reason": ran["runner"] + "：" + picked["reason"],
            "ambiguous": bool(picked.get("ambiguous")),
            "ai_used": True,
            "scores": scores,
            "oos_name": oos_name or "other",
        }
    except Exception as e:
        return {
            "module_id": "unknown",
            "ambiguous": False,
            "ai_used": False,
            "ai_error": str(e),
            "scores": [],
            "oos_name": "other",
            "reason": "",
        }


def match_by_description(phenomenon, catalog):
    text = str(phenomenon or "").strip()
    if not text:
        return {"module_id": "unknown", "ambiguous": False, "reason": "无问题现象，无法按描述匹配", "ai_used": False, "oos_name": "other", "scores": []}
    spec = runner_spec()
    if not runner_available():
        fb = heuristic_match(text, catalog)
        fb["reason"] = spec["label"] + " 不可用，改用名称匹配。" + fb["reason"]
        return fb
    note = ""
    target = catalog
    if len(catalog) > AI_CAP:
        fb = heuristic_match(text, catalog)
        keep = [s["module_id"] for s in sorted(fb.get("scores") or [], key=lambda x: -x["score"])[:AI_CAP]]
        target = [m for m in catalog if m["module_id"] in keep]
        note = "（%s 个模块已启发式预筛为 %s 个再打分）" % (len(catalog), len(target))
    ai = ai_score(text, target)
    if not ai.get("ai_used"):
        fb = heuristic_match(text, catalog)
        err = ai.get("ai_error") or ""
        prefix = spec["label"] + " 不可用" + (("（%s）" % err) if err else "") + "，改用名称匹配。"
        fb["reason"] = prefix + fb["reason"]
        fb["ai_error"] = err
        return fb
    by_ai = {s["module_id"]: s for s in ai.get("scores") or []}
    scores = []
    for m in catalog:
        scores.append(by_ai.get(m["module_id"]) or {"module_id": m["module_id"], "name": m["name"], "score": 0, "reason": "启发式预筛未进入 AI 候选"})
    scores.sort(key=lambda x: -x["score"])
    ai["scores"] = scores
    if note:
        ai["reason"] = (ai.get("reason") or "") + note
    return ai


def module_result(mod, rule, reason):
    return {
        "module_id": mod["module_id"],
        "module_name": meta_name(mod),
        "out_of_scope": False,
        "unknown": False,
        "collect": collect_of(mod),
        "reference": None,
        "decision": {"rule": rule, "reason": reason},
    }


def module_from_blacklist(hit, by_id):
    if not hit:
        return None
    dest = by_id.get(hit.get("to_module") or "")
    if not dest:
        return None
    why = "黑名单指向责任模块「%s」。" % meta_name(dest)
    if hit.get("reason"):
        why += hit["reason"]
    return module_result(dest, "blacklist", why)


def oos_result(name, reason, rule, reference=None, confidence="low"):
    label = name if name and name != "other" else "other"
    return {
        "module_id": "out_of_scope",
        "module_name": "非窗口问题：" + label,
        "out_of_scope": True,
        "unknown": False,
        "collect": None,
        "reference": reference,
        "decision": {"rule": rule, "reason": reason},
    }


def route(text):
    symptom = str(text or "").strip()
    mods = load_modules()
    catalog = [catalog_of(m) for m in mods]
    by_id = {m["module_id"]: m for m in mods}
    if symptom and not named_module(symptom, mods):
        hist = history.best(symptom)
        if hist:
            hist_name = hist.get("name") if hist.get("name") and hist.get("name") != "other" else "other"
            return oos_result(
                hist_name,
                "参考历史黑名单 %s（极相似）：%s。不属于任一已接入模块。" % (hist.get("id"), hist.get("text")),
                "history_blacklist",
                {"id": hist.get("id"), "text": hist.get("text"), "name": hist_name, "score": int(round(hist.get("score", 0) * 100))},
                "high",
            )
        hit = blacklist_symptom(symptom, mods)
        owned = module_from_blacklist(hit, by_id)
        if owned:
            return owned
        domain = (hit or {}).get("to_module_name") or ""
        if domain and not any(meta_name(m) == domain for m in mods):
            saved = history.remember(symptom, domain)
            extra = ("已记入历史黑名单 %s。" % saved["id"]) if saved and saved.get("fresh") else ""
            return oos_result(
                domain,
                "参考模块黑名单领域「%s」。现象未点名已接入模块，不属于任一窗口模块。%s" % (domain, extra),
                "yaml_blacklist",
                {"id": saved.get("id") if saved else "", "text": symptom, "name": domain, "fresh": bool(saved and saved.get("fresh"))},
                "medium",
            )
    named = modules_named_in(symptom, mods) if symptom else []
    if len(named) == 1:
        dest = named[0]
        return module_result(dest, "name", "现象点名了已接入模块「%s」。" % meta_name(dest))
    matched = match_by_description(symptom, catalog)
    if matched.get("module_id") and matched["module_id"] != "unknown" and matched["module_id"] in by_id:
        dest = by_id[matched["module_id"]]
        return module_result(dest, "ai_desc" if matched.get("ai_used") else "desc", matched.get("reason") or "")
    if matched.get("ambiguous"):
        return {
            "module_id": "unknown",
            "module_name": "窗口问题，模块未分开",
            "out_of_scope": False,
            "unknown": True,
            "collect": None,
            "reference": None,
            "decision": {"rule": "ambiguous", "reason": (matched.get("reason") or "") + "。仍是窗口问题，不记入非窗口历史。"},
        }
    hit = blacklist_symptom(symptom, mods) if symptom else None
    owned = module_from_blacklist(hit, by_id)
    if owned:
        return owned
    domain = ((hit or {}).get("to_module_name")) or matched.get("oos_name") or "other"
    if domain in ("unknown", "out_of_scope"):
        domain = "other"
    hist = history.best(symptom) if symptom else None
    oos_name = hist.get("name") if hist and hist.get("name") and hist.get("name") != "other" else domain
    if hist:
        reason = "不属于任一已接入模块。参考历史黑名单 %s（极相似）：%s。" % (hist.get("id"), hist.get("text"))
        reference = {"id": hist.get("id"), "text": hist.get("text"), "name": oos_name}
        rule = "history_blacklist"
    elif matched.get("ai_error"):
        reason = "没有使用 AI 完成分流。" + (matched.get("reason") or "")
        reference = None
        rule = "ai_unavailable"
    else:
        saved = history.remember(symptom, oos_name) if symptom else None
        reason = "不属于任一已接入模块。"
        if saved:
            reason += "已记入历史黑名单 %s，供以后极相似现象对照。" % saved["id"]
        if domain and domain != "other":
            reason += "参考模块黑名单领域「%s」。" % domain
        elif matched.get("reason"):
            reason += matched["reason"]
        reference = {"id": saved.get("id") if saved else "", "text": symptom, "name": oos_name, "fresh": bool(saved and saved.get("fresh"))}
        rule = "oos_named" if oos_name != "other" else "oos_other"
    return oos_result(oos_name, reason, rule, reference, "high" if hist else "low")


def flatten_probes(mod):
    out = []
    for atom in atoms_of(mod):
        packs = (("enter", arr(atom.get("enter"))), ("success", arr(atom.get("success"))), ("failure", arr(atom.get("failures"))))
        for probe, items in packs:
            for lg in items:
                if not lg or not lg.get("id"):
                    continue
                row = dict(lg)
                row["atom_id"] = atom["id"]
                row["atom_title"] = atom.get("title") or atom["id"]
                row["probe"] = probe
                out.append(row)
    return out


def match_logs(mod, logs_text):
    hits = []
    lines = str(logs_text or "").splitlines()
    for lg in flatten_probes(mod):
        cre = compile_re(lg.get("regex"), lg.get("flags") or "i")
        if not cre:
            continue
        for i, line in enumerate(lines):
            if line and cre.search(line):
                hits.append({
                    "log_id": lg.get("id"),
                    "line_no": i + 1,
                    "line": line,
                    "layer_id": lg.get("layer_id") or "",
                    "function": lg.get("function") or "",
                    "meaning": lg.get("meaning") or "",
                    "title": lg.get("title") or "",
                    "kind": lg.get("kind") or "",
                    "locate": lg.get("locate") or "",
                    "probe": lg.get("probe") or "",
                    "atom_id": lg.get("atom_id") or "",
                })
    return hits


def build_timeline(mod, hits):
    by_id = {a["id"]: a for a in atoms_of(mod)}
    steps = []
    for h in sorted(hits, key=lambda x: x["line_no"]):
        if h["atom_id"] not in by_id:
            continue
        atom = by_id[h["atom_id"]]
        step = steps[-1] if steps else None
        if not step or step["atom_id"] != h["atom_id"]:
            step = {
                "atom_id": atom["id"],
                "title": atom.get("title") or atom["id"],
                "api": atom.get("api") or "",
                "status": "enter",
                "callchain": arr(atom.get("callchain")),
                "events": [],
            }
            steps.append(step)
        step["events"].append(h)
        if h["probe"] == "success":
            step["status"] = "ok"
            step.pop("failure", None)
        if h["probe"] == "failure":
            step["status"] = "fail"
            step["failure"] = h
    for step in steps:
        if step["status"] == "enter":
            step["status"] = "unknown"
    return steps


def focus_atom(steps):
    if not steps:
        return None
    for step in reversed(steps):
        if step["status"] in ("fail", "unknown"):
            return step
    return steps[-1]


def mark_chain(step):
    chain = [dict(c, exception=False) for c in arr(step.get("callchain"))]
    if not chain:
        return []
    layer = ""
    if step["status"] == "fail" and step.get("failure"):
        layer = step["failure"].get("layer_id") or ""
    if step["status"] == "unknown":
        enters = [e for e in step["events"] if e.get("probe") == "enter"]
        enter = enters[-1] if enters else None
        idx = next((i for i, c in enumerate(chain) if enter and c.get("layer_id") == enter.get("layer_id")), -1)
        if idx >= 0 and idx + 1 < len(chain):
            layer = chain[idx + 1].get("layer_id") or ""
        elif enter:
            layer = enter.get("layer_id") or ""
        else:
            layer = chain[-1].get("layer_id") or ""
    for c in chain:
        if layer and c.get("layer_id") == layer:
            c["exception"] = True
    if layer and not any(c.get("exception") for c in chain):
        chain[-1]["exception"] = True
    return chain


def localize(module_id, logs_text):
    mods = load_modules()
    mod = next((m for m in mods if m["module_id"] == module_id), None)
    if not mod:
        raise KeyError("未找到模块 YAML: " + module_id)
    hits = match_logs(mod, logs_text)
    timeline = build_timeline(mod, hits) if atoms_of(mod) else []
    focus = focus_atom(timeline)
    chain = mark_chain(focus) if focus else []
    no_hit = len(hits) == 0
    hypothesis = ""
    exception = None
    point = None
    if timeline:
        ex = next((c for c in chain if c.get("exception")), {})
        if focus and focus["status"] in ("fail", "unknown"):
            funcs = []
            if focus.get("failure") and focus["failure"].get("function"):
                funcs.append(focus["failure"]["function"])
            funcs.extend(arr(ex.get("symbols")))
            point = {"layer_id": ex.get("layer_id") or (focus.get("failure") or {}).get("layer_id") or "", "functions": [f for f in funcs if f]}
        if no_hit:
            hypothesis = "用户日志未命中本模块原子探针，禁止编造；请人工改模块"
        elif focus and focus["status"] == "fail":
            fail = focus["failure"]
            hypothesis = "时间线断在「%s」：%s%s%s" % (
                focus["title"],
                fail.get("kind") or "",
                " · " if fail.get("kind") else "",
                fail.get("meaning") or fail.get("title") or "",
            )
            exception = {"id": focus["atom_id"], "title": focus["title"], "locate": fail.get("locate") or ""}
        elif focus and focus["status"] == "unknown":
            hypothesis = "「%s」已进入，但既无成功也无已知失败，更像真实缺陷" % focus["title"]
            exception = {"id": focus["atom_id"], "title": focus["title"] + " · 未知", "locate": "对照进入日志之后应出现的成功句，看停在调用链哪一层"}
        else:
            hypothesis = "各原子均走完，未命中已知失败"
            exception = {"id": focus["atom_id"], "title": focus["title"], "locate": ""} if focus else None
    return {
        "timeline": timeline,
        "scenario_callchain": chain,
        "exception_scenario": exception,
        "callchain_exception_point": point,
        "hypothesis": hypothesis,
        "matched_logs": hits,
    }


USER_ACT = ("点击", "滑动", "拖拽", "拖动", "双击", "长按", "捏合", "上滑", "下滑", "左滑", "右滑", "旋转")


def responsible_from_logs(logs_text, mods, current_id):
    lines = [ln for ln in str(logs_text or "").splitlines() if ln.strip()]
    scores = {}
    for mod in mods:
        for b in blacklist_of(mod):
            cre = compile_re(b.get("regex"), b.get("flags") or "i")
            if not cre:
                continue
            count = sum(1 for ln in lines if cre.search(ln))
            if count <= 0:
                continue
            ident = str(b.get("to_module") or "").strip()
            name = str(b.get("to_module_name") or ident).strip() or "other"
            key = ident or ("oos:" + name)
            row = scores.setdefault(key, {"to_module": ident, "name": name, "count": 0, "reason": str(b.get("reason") or "").strip()})
            row["count"] += count
            if b.get("reason") and not row["reason"]:
                row["reason"] = str(b.get("reason")).strip()
    if not scores:
        return None
    best = max(scores.values(), key=lambda row: (row["count"], len(row["name"])))
    if best["to_module"] == current_id:
        return None
    return best


def user_behavior(symptom):
    hits = [word for word in USER_ACT if word in str(symptom or "")]
    if hits:
        return "现象里描述了" + "、".join(hits) + "。"
    return "现象未描述点击、滑动等操作。"


def app_behavior(timeline):
    apis = []
    for step in timeline or []:
        label = step.get("api") or step.get("title")
        if label and label not in apis:
            apis.append(label)
    if not apis:
        return "日志没有对上本模块已登记的接口。"
    return "日志对上的接口：" + "、".join(apis) + "。"


def system_behavior(result, code):
    parts = []
    chain = result.get("scenario_callchain") or []
    if not chain:
        for step in result.get("timeline") or []:
            if step.get("callchain"):
                chain = step["callchain"]
                break
    names = []
    for layer in chain:
        label = " ".join(x for x in [layer.get("layer_id") or "", layer.get("name") or layer.get("do") or ""] if x).strip()
        if label:
            names.append(label)
    if names:
        parts.append("调用链：" + " → ".join(names) + "。")
    if result.get("hypothesis"):
        text = str(result["hypothesis"]).strip()
        if text and not text.endswith("。"):
            text += "。"
        parts.append(text)
    snippets = (code or {}).get("snippets") or []
    if snippets:
        places = ["%s %s:%s" % (s["repo"], s["file"], s["line"]) for s in snippets[:4]]
        parts.append("源码能对上的位置：" + "；".join(places) + "。")
    elif (code or {}).get("mode") == "yaml":
        parts.append("源码路径未配置，系统行为只根据 YAML。")
    else:
        parts.append("已配置源码，没有对上本模块符号或日志原文。")
    return "".join(p for p in parts if p)


def yaml_behaviors(symptom, result, code):
    return {
        "user_behavior": user_behavior(symptom),
        "app_behavior": app_behavior(result.get("timeline")),
        "system_behavior": system_behavior(result, code),
        "analysis_by": (code or {}).get("mode") or "yaml",
    }


def ai_behaviors(symptom, mod, result, code):
    meta = mod.get("meta") or {}
    payload = {
        "phenomenon": symptom,
        "module": {"module_id": mod.get("module_id"), "name": meta.get("name") or "", "description": str(meta.get("description") or "")[:800]},
        "hypothesis": result.get("hypothesis") or "",
        "timeline": [{
            "api": step.get("api") or step.get("title"),
            "status": step.get("status"),
            "callchain": [c.get("name") or c.get("do") or c.get("layer_id") for c in (step.get("callchain") or [])],
        } for step in (result.get("timeline") or [])],
        "sources": {"mode": code.get("mode"), "used": code.get("used"), "missing": code.get("missing")},
        "code": [{"repo": s["repo"], "file": s["file"], "line": s["line"], "text": s["text"]} for s in (code.get("snippets") or [])],
    }
    prompt = (
        "本次任务是拿到日志后的问题分析。只根据下面 JSON 里的现象、模块说明、时间线、日志结论和源码摘录。"
        "sources.mode 为 yaml 时，不要提到未提供的源码。"
        "user_behavior 只写点击、滑动等操作；现象里没有就写现象未描述点击或滑动。"
        "app_behavior 只写调用了哪个接口。"
        "system_behavior 只写事件或接口之后框架做了什么，并标出可能异常点。"
        "只输出 JSON：{\"user_behavior\":\"\",\"app_behavior\":\"\",\"system_behavior\":\"\"}\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    ran = run_ai(prompt)
    data = extract_json(ran["text"])
    user = str(data.get("user_behavior") or "").strip()
    app = str(data.get("app_behavior") or "").strip()
    system = str(data.get("system_behavior") or "").strip()
    if not (user and app and system):
        raise ValueError("分析输出缺少行为字段")
    return {
        "user_behavior": user,
        "app_behavior": app,
        "system_behavior": system,
        "analysis_by": code.get("mode") + "+" + ran["runner"],
    }


def analyze(module_id, symptom, logs_text):
    mods = load_modules()
    by_id = {m["module_id"]: m for m in mods}
    if module_id not in by_id:
        raise KeyError("未找到模块 YAML: " + module_id)
    note = ""
    target = module_id
    duty = responsible_from_logs(logs_text, mods, module_id)
    if duty and duty["to_module"] in by_id:
        target = duty["to_module"]
        note = "日志命中黑名单，责任模块是「%s」。%s" % (meta_name(by_id[target]), duty.get("reason") or "")
    elif duty and not duty["to_module"]:
        note = "日志命中黑名单，责任不在已接入模块：非窗口问题：%s。%s" % (duty["name"], duty.get("reason") or "")
    result = localize(target, logs_text)
    result["module_id"] = target
    result["module_name"] = meta_name(by_id[target])
    result["responsibility"] = note
    code = codebase.gather(by_id[target], logs_text)
    result["sources"] = {"mode": code["mode"], "used": code["used"], "missing": code["missing"]}
    behaviors = None
    if runner_available():
        try:
            behaviors = ai_behaviors(symptom, by_id[target], result, code)
        except Exception as e:
            result["analysis_note"] = runner_spec()["label"] + " 分析不可用（%s），改按 YAML 与已找到的源码摘录。" % e
    if not behaviors:
        behaviors = yaml_behaviors(symptom, result, code)
        if not runner_available() and "analysis_note" not in result:
            result["analysis_note"] = runner_spec()["label"] + " 不可用，改按 YAML 与已找到的源码摘录。"
    result.update(behaviors)
    return result
