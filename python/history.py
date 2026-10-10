# -*- coding: utf-8 -*-
import os
import random
import re
from datetime import datetime

import yaml

EXTREME = 0.72


def app_dir():
    import sys
    if os.environ.get("WATCHMAN_OOS_DIR"):
        return os.environ["WATCHMAN_OOS_DIR"]
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, "memory", "non-window")


def compact(raw):
    return re.sub(r"[，。！？、,.!?:：；;（）()【】\[\]\"'“”\s]", "", str(raw or ""))


def grams(text):
    out = set()
    for n in (2, 3):
        for i in range(0, max(0, len(text) - n + 1)):
            out.add(text[i:i + n])
    return out


def similarity(a, b):
    left, right = compact(a), compact(b)
    if not left or not right:
        return 0
    if left == right:
        return 1
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) >= 8 and short in long:
        return 0.9
    ga, gb = grams(left), grams(right)
    if not ga or not gb:
        return 0
    inter = len(ga & gb)
    return inter / float(len(ga) + len(gb) - inter)


def list_cases():
    folder = app_dir()
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        if not name.endswith((".yaml", ".yml")):
            continue
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                rec = yaml.safe_load(f)
            if rec and rec.get("text"):
                out.append(rec)
        except Exception:
            continue
    return out


def best(text):
    top = None
    for item in list_cases():
        score = similarity(text, item.get("text"))
        if top is None or score > top["score"]:
            merged = dict(item)
            merged["score"] = score
            top = merged
    if not top or top["score"] < EXTREME:
        return None
    return top


def remember(text, name):
    symptom = str(text or "").strip()
    if not symptom:
        return None
    hit = best(symptom)
    if hit:
        hit["fresh"] = False
        return hit
    folder = app_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    rec_id = "NW-%s-%s" % (stamp, "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4)))
    rec = {
        "id": rec_id,
        "created": datetime.utcnow().isoformat() + "Z",
        "text": symptom,
        "name": name or "other",
    }
    with open(os.path.join(folder, rec_id + ".yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(rec, f, allow_unicode=True, sort_keys=False)
    rec["score"] = 1
    rec["fresh"] = True
    return rec
