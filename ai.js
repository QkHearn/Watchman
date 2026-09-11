"use strict";

const env = require("./env");

const STOP = new Set("问题,现象,失败,无法,不能,第二次,连续,两次,一次,应用,通过,覆盖,不做,普通,以及,已经,成功,调用,接口,模块,日志,错误,异常,打开,点击,之后,然后,没有,不到,黑屏,白屏,卡死,闪退,启动,停止,创建,还原,参数,校验,能力,状态,操作,内容,页面,多屏".split(","));

function aiEnabled() {
  const c = env.llm();
  return Boolean(c.enabled && c.apiKey && c.model && c.modelAllowed);
}

function escapeRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function positiveDescription(d) {
  return String(d || "").split(/不做[：:]/)[0];
}

function identsOf(raw) {
  const out = new Set();
  for (const part of String(raw || "").split(/[./:_-]+/)) {
    if (!part) continue;
    out.add(part);
    const bits = part.match(/[A-Z]{2,}(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[A-Z]+|[0-9]+/g) || [];
    for (const b of bits) out.add(b);
  }
  return [...out];
}

function containsIdent(hay, ident) {
  const id = String(ident || "").trim();
  if (!id) return false;
  if (/[\u4e00-\u9fff]/.test(id)) return id.length >= 2 && hay.includes(id);
  const low = id.toLowerCase();
  if (low.length < 3) return false;
  return new RegExp("(?:^|[^a-z0-9_])" + escapeRe(low) + "(?:$|[^a-z0-9_])", "i").test(hay);
}

function chineseGrams(s) {
  const runs = String(s || "").match(/[\u4e00-\u9fff]+/g) || [];
  const out = new Set();
  for (const run of runs) {
    for (let n = 2; n <= 3; n++) {
      for (let i = 0; i + n <= run.length; i++) out.add(run.slice(i, i + n));
    }
  }
  return [...out];
}

function heuristicMatch(phenomenon, catalog) {
  const text = String(phenomenon || "").trim();
  if (!text) {
    return {
      module_id: "unknown",
      reason: "现象为空，无法按描述匹配",
      confidence: "low",
      ai_used: false,
      scores: catalog.map((m) => ({ module_id: m.module_id, name: m.name, score: 0, reason: "无现象" }))
    };
  }
  const hay = text.toLowerCase();
  const all = [];
  for (const m of catalog) {
    const why = [];
    let score = 0;
    const aliases = [m.name, m.name_en, m.module_id, m.field_name, m.field_id].concat(m.aliases || []).filter(Boolean);
    for (const a of aliases) {
      if (containsIdent(hay, a) || (/[\u4e00-\u9fff]/.test(a) && text.includes(a))) {
        score += 50;
        why.push("名称 " + a);
        break;
      }
    }
    const fnHits = [];
    const seenFn = new Set();
    for (const fn of m.functions || []) {
      let hit = "";
      for (const p of [fn].concat(identsOf(fn))) {
        if (containsIdent(hay, p) && String(p).length > hit.length) hit = p;
      }
      if (hit) {
        const k = hit.toLowerCase();
        if (!seenFn.has(k)) {
          seenFn.add(k);
          fnHits.push(hit);
          score += hit.length >= 6 ? 30 : 18;
        }
      }
    }
    if (fnHits.length) why.push("函数 " + fnHits.slice(0, 3).join("/"));
    const overlapHits = [];
    for (const t of chineseGrams(positiveDescription(m.description))) {
      if (STOP.has(t) || t.length < 2) continue;
      if (text.includes(t)) overlapHits.push(t);
    }
    const uniq = [...new Set(overlapHits)].filter((t, _, arr) =>
      t.length >= 3 || !arr.some((x) => x.length > t.length && x.includes(t))
    );
    if (uniq.length) {
      score += uniq.length * 20;
      why.push("描述重叠 " + uniq.slice(0, 4).join("/"));
    }
    all.push({ module_id: m.module_id, name: m.name, score, reason: why.join("；") || "无命中" });
  }
  all.sort((a, b) => b.score - a.score || String(a.module_id).localeCompare(String(b.module_id)));
  const best = all[0];
  const second = all[1];
  if (!best || best.score < 18) {
    return { module_id: "unknown", reason: "现象未命中已接入模块的名称或函数，也不足以匹配描述", confidence: "low", ai_used: false, scores: all };
  }
  if (second && second.score >= 18 && best.score - second.score < 18) {
    return {
      module_id: "unknown",
      reason: "多个模块描述接近（" + (best.name || best.module_id) + " / " + (second.name || second.module_id) + "），无法自动判定",
      confidence: "low",
      ai_used: false,
      scores: all
    };
  }
  return {
    module_id: best.module_id,
    reason: "按模块名称/函数/描述匹配到「" + (best.name || best.module_id) + "」（" + (best.reason || "") + "）",
    confidence: best.score >= 50 ? "medium" : "low",
    ai_used: false,
    scores: all
  };
}

function clampScore(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return 0;
  return Math.max(0, Math.min(100, Math.round(x)));
}

function pickFromScores(scores, min, margin) {
  const ranked = (scores || []).slice().sort((a, b) => b.score - a.score);
  const best = ranked[0];
  const second = ranked[1];
  if (!best || best.score < min) {
    return { module_id: "unknown", reason: "各模块 AI 得分都低于 " + min + "，无法确定" };
  }
  if (second && best.score - second.score < margin) {
    return {
      module_id: "unknown",
      reason: "AI 打分接近（" + (best.name || best.module_id) + " " + best.score + " / " +
        (second.name || second.module_id) + " " + second.score + "），无法自动判定"
    };
  }
  return {
    module_id: best.module_id,
    reason: "AI 按现象与模块描述打分，最高「" + (best.name || best.module_id) + "」" + best.score +
      " 分" + (best.reason ? "：" + best.reason : "")
  };
}

async function aiScoreModules(phenomenon, catalog) {
  const c = env.llm();
  const payload = {
    model: c.model,
    temperature: 0.1,
    messages: [
      {
        role: "system",
        content:
          "你是 OpenHarmony 问题分流器。请根据「问题现象」对 catalog 中每一个模块打 0～100 分。" +
          "依据：模块中文名/英文名、完整描述（含做什么与不做）、函数名。" +
          "描述里写明「不做」的现象必须给很低分。" +
          "必须为 catalog 里每个 module_id 输出一条，不要发明 catalog 里的模块。" +
          "若现象明显不属于任何 catalog 模块，另给 oos_name：能判断领域则填中文名（如 悬浮窗），否则填 other。" +
          "只输出 JSON：{\"scores\":[{\"module_id\":\"...\",\"score\":0,\"reason\":\"中文短理由\"}],\"oos_name\":\"other\"}"
      },
      {
        role: "user",
        content: JSON.stringify({
          phenomenon,
          catalog: catalog.map((m) => ({
            module_id: m.module_id,
            name: m.name,
            name_en: m.name_en || "",
            description: String(m.description || "").slice(0, catalog.length > 24 ? 280 : 520),
            functions: catalog.length > 20 ? [] : (m.functions || []).slice(0, 8)
          }))
        })
      }
    ]
  };
  payload.max_tokens = c.maxTokens || Math.min(2500, 400 + catalog.length * 48);

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), c.timeoutMs || 60000);
  try {
    const res = await fetch(c.baseUrl + "/chat/completions", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + c.apiKey,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload),
      signal: ac.signal
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data && data.error && data.error.message) || res.statusText);
    const text = (((data.choices || [])[0] || {}).message || {}).content || "";
    const json = JSON.parse(String(text).replace(/^```json\s*|\s*```$/g, ""));
    const byId = new Map();
    for (const row of arrScore(json.scores)) {
      if (!row || !row.module_id) continue;
      byId.set(String(row.module_id), row);
    }
    const scores = catalog.map((m) => {
      const row = byId.get(m.module_id) || {};
      return {
        module_id: m.module_id,
        name: m.name,
        score: clampScore(row.score),
        reason: String(row.reason || "")
      };
    }).sort((a, b) => b.score - a.score);
    const picked = pickFromScores(scores, 40, 15);
    let oosName = String(json.oos_name || "").replace(/^非窗口问题[：:]/, "").trim();
    if (oosName.length > 40) oosName = oosName.slice(0, 40);
    if (catalog.some((m) => m.module_id === oosName || m.name === oosName)) oosName = "";
    return {
      module_id: picked.module_id,
      reason: picked.reason,
      confidence: picked.module_id === "unknown" ? "low" : "medium",
      ai_used: true,
      scores,
      oos_name: oosName || "other"
    };
  } catch (e) {
    const fb = heuristicMatch(phenomenon, catalog);
    fb.reason = "AI 打分不可用（" + (e.message || e) + "），改用启发式。" + fb.reason;
    return fb;
  } finally {
    clearTimeout(timer);
  }
}

function arrScore(v) {
  return Array.isArray(v) ? v : [];
}

const AI_CATALOG_CAP = 12;

async function matchByDescription(phenomenon, catalog) {
  if (!String(phenomenon || "").trim()) {
    return {
      module_id: "unknown",
      reason: "无问题现象，无法按描述匹配",
      confidence: "low",
      ai_used: false,
      scores: catalog.map((m) => ({ module_id: m.module_id, name: m.name, score: 0, reason: "无现象" }))
    };
  }
  if (!aiEnabled()) return heuristicMatch(phenomenon, catalog);
  if (catalog.length <= AI_CATALOG_CAP) return aiScoreModules(phenomenon, catalog);

  const fb = heuristicMatch(phenomenon, catalog);
  const keep = new Set((fb.scores || []).slice().sort((a, b) => b.score - a.score).slice(0, AI_CATALOG_CAP).map((s) => s.module_id));
  const slim = catalog.filter((m) => keep.has(m.module_id));
  const ai = await aiScoreModules(phenomenon, slim);
  const byAi = new Map((ai.scores || []).map((s) => [s.module_id, s]));
  const scores = catalog.map((m) => byAi.get(m.module_id) || {
    module_id: m.module_id,
    name: m.name,
    score: 0,
    reason: "启发式预筛未进入 AI 候选"
  }).sort((a, b) => b.score - a.score);
  return {
    ...ai,
    scores,
    reason: (ai.reason || "") + "（" + catalog.length + " 个模块已启发式预筛为 " + slim.length + " 个再打分）"
  };
}

module.exports = { aiEnabled, matchByDescription, heuristicMatch };
