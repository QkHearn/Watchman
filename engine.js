"use strict";

const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");
const ai = require("./ai");

const ROOT = __dirname;

const API_KIND_LABEL = {
  external: "对外接口",
  internal: "对内接口",
  dependency: "外部依赖接口"
};

function loadYaml(file) {
  return yaml.load(fs.readFileSync(file, "utf8"));
}

function registry() {
  const file = path.join(ROOT, "config", "modules.yaml");
  if (!fs.existsSync(file)) return {};
  return loadYaml(file) || {};
}

function disabledIds() {
  return new Set(arr(registry().disabled).map(String));
}

function discoverModuleFiles() {
  const dir = path.join(ROOT, "modules");
  if (!fs.existsSync(dir)) return [];
  const skip = new Set(["_template"]);
  const disabled = disabledIds();
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    if (skip.has(name) || name.startsWith(".")) continue;
    const file = path.join(dir, name, "module.yaml");
    if (!fs.existsSync(file)) continue;
    let y;
    try {
      y = loadYaml(file);
    } catch {
      continue;
    }
    if (!y || y.enabled === false) continue;
    const id = y.module_id || name;
    if (disabled.has(id) || disabled.has(name)) continue;
    y.module_id = id;
    y.__file = file;
    out.push(normalize(y));
  }
  return out.sort((a, b) => String(a.module_id).localeCompare(String(b.module_id)));
}

function modulePath(id) {
  const rec = discoverModuleFiles().find((m) => m.module_id === id);
  if (!rec) throw new Error("未找到模块 YAML: " + id + "（放到 modules/" + id + "/module.yaml）");
  return rec.__file;
}

function loadModule(id) {
  const y = loadYaml(modulePath(id));
  y.module_id = y.module_id || id;
  y.__file = modulePath(id);
  return normalize(y);
}

function enabledModules() {
  return discoverModuleFiles();
}

function compileRe(pattern, flags) {
  if (!pattern) return null;
  let p = String(pattern);
  let f = String(flags || "");
  if (p.startsWith("(?i)")) {
    p = p.slice(4);
    if (!f.includes("i")) f += "i";
  }
  p = p.replace(/\(\?i\)/g, "");
  if (!f) f = "m";
  if (!f.includes("m")) f += "m";
  try {
    return new RegExp(p, f);
  } catch {
    return null;
  }
}

function matchRe(pattern, flags, text) {
  const re = compileRe(pattern, flags);
  return Boolean(re && text && re.test(String(text)));
}

function arr(v) {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

function blob(input) {
  return [input.text, arr(input.apis).join("\n"), arr(input.errors).join("\n"), input.logs]
    .filter(Boolean)
    .join("\n");
}

function asApi(item, kind, mod, depModule) {
  if (item == null) return null;
  const raw = typeof item === "string" ? { id: item } : item;
  const id = raw.id || raw.symbol;
  if (!id) return null;
  return {
    id: String(id),
    label: String(raw.label || id),
    role: raw.role ? String(raw.role) : "",
    kind,
    kind_label: API_KIND_LABEL[kind] || kind,
    dep_module: String(depModule || raw.module || raw.dep_module || ""),
    module_id: mod.module_id,
    module_name: (mod.meta && mod.meta.name) || mod.module_id
  };
}

function apiGroups(mod) {
  const src = mod.apis;
  const external = [];
  const internal = [];
  const dependencies = [];
  if (src && !Array.isArray(src) && typeof src === "object") {
    for (const a of arr(src.external)) {
      const x = asApi(a, "external", mod);
      if (x) external.push(x);
    }
    for (const a of arr(src.internal)) {
      const x = asApi(a, "internal", mod);
      if (x) internal.push(x);
    }
    for (const a of arr(src.dependencies || src.deps)) {
      const x = asApi(a, "dependency", mod, a && a.module);
      if (x) dependencies.push(x);
    }
  } else {
    for (const a of arr(src || (mod.route && mod.route.api_choices))) {
      const x = asApi(a, "external", mod);
      if (x) external.push(x);
    }
  }
  return { external, internal, dependencies };
}

function declaredApis(mod) {
  const g = apiGroups(mod);
  const items = g.external.slice();
  if (items.length) return items;
  for (const sc of scenariosOf(mod)) {
    for (const layer of arr(sc.callchain)) {
      if (layer.layer_id !== "L-JS" && layer.layer_id !== "L-NDK") continue;
      for (const s of arr(layer.symbols || layer.entry_symbols)) {
        const x = asApi(s, "external", mod);
        if (x && !items.some((i) => i.id === x.id)) items.push(x);
      }
    }
  }
  return items;
}

function logWhitelist(mod) {
  const out = arr(mod.log_whitelist);
  if (out.length) return out;
  const w = (mod.route && mod.route.whitelist) || {};
  return arr(w.log_tags).map((t, i) => ({
    id: "WL-TAG-" + i,
    regex: escapeRe(String(t)),
    flags: "i",
    meaning: "log_tags"
  }));
}

function logBlacklist(mod) {
  const out = arr(mod.log_blacklist);
  if (out.length) return out;
  return arr(mod.route && mod.route.blacklist).map((bl) => ({
    id: bl.id,
    regex: arr(bl.keywords).concat(arr(bl.symptoms)).map(escapeRe).join("|"),
    flags: "i",
    to_module: bl.to_module || "",
    to_module_name: bl.to_module_name || "",
    reason: bl.reason || "",
    unless_whitelist: true
  })).filter((x) => x.regex);
}

function scenariosOf(mod) {
  const top = arr(mod.scenarios);
  if (top.length) return top;
  const loc = mod.localize || {};
  const logs = loc.logs || loc.key_logs || [];
  const byId = {};
  for (const lg of arr(logs)) if (lg && lg.id) byId[lg.id] = lg;
  const chain = arr(loc.callchain);
  return arr(loc.scenarios).map((sc) => {
    const ids = arr(sc.match && sc.match.any_logs).concat(arr(sc.match && sc.match.all_logs));
    const cut = [];
    for (const c of chain) {
      cut.push({
        layer_id: c.layer_id,
        name: c.name,
        symbols: arr(c.entry_symbols || c.symbols),
        exception: c.layer_id === sc.exception_layer
      });
      if (c.layer_id === sc.exception_layer) break;
    }
    return {
      id: sc.id,
      title: sc.title,
      boundary: sc.boundary,
      priority: sc.priority,
      summary: sc.summary,
      callchain: cut.length ? cut : chain,
      key_logs: ids.map((id) => byId[id]).filter(Boolean)
    };
  });
}

function collectOf(mod) {
  const q = mod.collect || (mod.localize && mod.localize.collect);
  if (!q) return null;
  let regex = String(q.regex || q.pattern || "").trim();
  if (!regex) {
    const parts = arr(q.queries).map((x) => String((x && x.regex) || "").trim()).filter(Boolean);
    regex = parts.join("|");
  }
  if (!regex) return null;
  return {
    source: "module.yaml",
    title: q.title || "请复制下面正则到 BetaClub 搜集日志",
    where: q.where || "BetaClub",
    hint: q.hint || "复制正则到 BetaClub 搜集，把命中行完整粘贴到阶段二",
    regex
  };
}

function atomsOf(mod) {
  return arr(mod.atoms).filter((a) => a && a.id);
}

function flattenKeyLogs(mod) {
  const out = [];
  const seen = new Set();
  const atoms = atomsOf(mod);
  if (atoms.length) {
    for (const atom of atoms) {
      const packs = [
        ["enter", arr(atom.enter)],
        ["success", arr(atom.success)],
        ["failure", arr(atom.failures)]
      ];
      for (const [probe, list] of packs) {
        for (const lg of list) {
          if (!lg || !lg.id) continue;
          const key = atom.id + "\0" + lg.id;
          if (seen.has(key)) continue;
          seen.add(key);
          out.push(Object.assign({}, lg, {
            atom_id: atom.id,
            atom_title: atom.title || atom.id,
            probe,
            exception: probe === "failure",
            scenario_ids: [atom.id]
          }));
        }
      }
    }
    return out;
  }
  for (const sc of scenariosOf(mod)) {
    for (const lg of arr(sc.key_logs)) {
      if (!lg || !lg.id) continue;
      const key = sc.id + "\0" + lg.id;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(Object.assign({}, lg, { scenario_ids: [sc.id] }));
    }
  }
  return out;
}

function scenarioException(sc) {
  const layer = arr(sc.callchain).find((c) => c.exception) || arr(sc.callchain)[arr(sc.callchain).length - 1] || {};
  return {
    layer_id: layer.layer_id || sc.exception_layer || "",
    functions: arr(layer.symbols || layer.entry_symbols).concat(arr(sc.exception_functions))
  };
}

function normalize(mod) {
  if (mod.__normalized) return mod;
  mod.atoms = atomsOf(mod);
  mod.scenarios = scenariosOf(mod);
  mod.collect = (mod.collect || (mod.localize && mod.localize.collect)) || null;
  mod.log_whitelist = logWhitelist(mod);
  mod.log_blacklist = logBlacklist(mod);
  mod.apis = apiGroups(mod);
  mod.__normalized = true;
  return mod;
}

function loadMisroutes() {
  const dir = path.join(ROOT, "memory", "misroutes");
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"))
    .map((f) => loadYaml(path.join(dir, f)))
    .filter(Boolean);
}

function similarMisroute(mr, input) {
  const inp = mr.input || {};
  const apis = arr(input.apis).map(String);
  const errs = arr(input.errors).map(String);
  const a = arr(inp.apis).map(String);
  const e = arr(inp.error_codes || inp.errors).map(String);
  return apis.some((x) => a.includes(x)) || errs.some((x) => e.includes(x));
}

function escapeRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function logsBlob(input) {
  return [input.logs, input.text].filter(Boolean).join("\n");
}

function whitelistHits(mod, input) {
  const text = logsBlob(input);
  return logWhitelist(mod).filter((w) => matchRe(w.regex, w.flags || "i", text));
}

function blacklistHits(mod, input, wlOk) {
  const text = logsBlob(input);
  return logBlacklist(mod).filter((b) => {
    if (!matchRe(b.regex, b.flags || "i", text)) return false;
    if ((b.unless_whitelist !== false) && wlOk) return false;
    return true;
  });
}

function selectedApiHits(mod, input) {
  const selected = new Set(arr(input.apis).map(String));
  const hay = [input.text, input.logs].filter(Boolean).join("\n");
  const hayL = hay.toLowerCase();
  const hits = [];
  const seen = new Set();
  for (const a of apiGroups(mod).external) {
    let weight = 0;
    if (selected.size) {
      if (selected.has(a.id)) weight = 40;
    } else if (a.id && hayL.includes(String(a.id).toLowerCase())) {
      weight = 40;
    } else if (a.label && hayL.includes(String(a.label).toLowerCase())) {
      weight = 40;
    } else {
      const parts = String(a.id || "").split(/[./]/).filter((p) => p.length >= 6);
      if (parts.some((p) => hayL.includes(p.toLowerCase()))) weight = 30;
    }
    if (!weight || seen.has(a.id)) continue;
    seen.add(a.id);
    hits.push({ id: a.id, kind: "external", weight });
  }
  const name = mod.meta && mod.meta.name;
  if (!selected.size && name && hay.includes(String(name))) {
    hits.push({ id: "meta.name", kind: "name", weight: 20 });
  }
  return hits;
}

function scoreModule(mod, input, misroutes, allMods) {
  const cfg = registry().routing || {};
  let score = 0;
  const evidence = [];
  const foreign = [];
  const wl = whitelistHits(mod, input);
  if (wl.length) {
    score += 80 + Math.min(40, (wl.length - 1) * 20);
    evidence.push(...wl.map((w) => w.id));
  }
  const apis = selectedApiHits(mod, input);
  const seenKind = new Set();
  for (const a of apis) {
    const k = a.kind + ":" + a.id;
    if (seenKind.has(k)) continue;
    seenKind.add(k);
    score += a.weight;
    if (a.kind === "name") evidence.push("NAME");
    else evidence.push("API-" + a.kind + ":" + a.id);
  }
  const bl = blacklistHits(mod, input, wl.length > 0);
  for (const b of bl) {
    score += -80;
    evidence.push(b.id);
    foreign.push({
      from_module: mod.module_id,
      to_module: b.to_module || "",
      to_module_name: b.to_module_name || b.to_module || "",
      log_id: b.id,
      reason: b.reason || "日志黑名单"
    });
  }
  for (const other of allMods) {
    if (other.module_id === mod.module_id) continue;
    const otherWl = whitelistHits(other, input).length > 0;
    for (const b of blacklistHits(other, input, otherWl)) {
      const target = b.to_module;
      if (target && target === mod.module_id) {
        score += 60;
        evidence.push("PEER-" + other.module_id + ":" + b.id);
      }
    }
  }
  for (const mr of misroutes) {
    if (!similarMisroute(mr, input)) continue;
    if (mr.from_module === mod.module_id) {
      score += Number(cfg.misroute_penalty || -25);
      evidence.push(mr.id);
    } else if (mr.to_module === mod.module_id && mr.to_module !== "unknown") {
      score += Number(cfg.misroute_boost || 20);
      evidence.push(mr.id);
    }
  }
  return {
    module_id: mod.module_id,
    name: (mod.meta && mod.meta.name) || mod.module_id,
    score,
    evidence: [...new Set(evidence)],
    foreign
  };
}

function reassignButtons(currentId, highlightIds) {
  const hi = new Set(arr(highlightIds).filter(Boolean));
  return enabledModules()
    .filter((m) => m.module_id !== currentId)
    .map((m) => ({
      module_id: m.module_id,
      label: "改到：" + ((m.meta && m.meta.name) || m.module_id),
      highlight: hi.has(m.module_id)
    }));
}

function moduleCatalog(mod) {
  const g = apiGroups(mod);
  const fn = [];
  for (const a of g.external.concat(g.internal, g.dependencies)) fn.push(a.id);
  const chains = atomsOf(mod).concat(scenariosOf(mod));
  for (const sc of chains) {
    for (const layer of arr(sc.callchain)) {
      for (const s of arr(layer.symbols || layer.entry_symbols)) fn.push(s);
    }
  }
  const labels = [];
  for (const a of g.external.concat(g.internal, g.dependencies)) {
    if (a.label) labels.push(a.label);
  }
  const meta = mod.meta || {};
  return {
    module_id: mod.module_id,
    name: meta.name || mod.module_id,
    name_en: meta.name_en || "",
    field_name: meta.field_name || "",
    field_id: meta.field_id || "",
    description: meta.description || "",
    functions: [...new Set(fn.concat(labels).filter(Boolean))],
    aliases: [meta.name, meta.name_en, mod.module_id, meta.field_name].filter(Boolean)
  };
}

function oosLabel(raw) {
  const s = String(raw || "").replace(/^非窗口问题[：:]/, "").trim();
  if (!s || s === "unknown" || s === "out_of_scope") return "other";
  return s;
}

function oosTitle(raw) {
  return "非窗口问题：" + oosLabel(raw);
}

function foreignModuleHints(mods) {
  const out = [];
  for (const m of mods) {
    for (const b of logBlacklist(m)) {
      const name = String(b.to_module_name || "").trim();
      const id = String(b.to_module || "").trim();
      if (name || id) out.push({ id, name: name || id });
    }
  }
  return out;
}

function guessForeignName(text, mods) {
  const t = String(text || "");
  if (!t.trim()) return "";
  let best = "";
  for (const h of foreignModuleHints(mods)) {
    const needles = String(h.name).split(/[\/、,，|]/).map((s) => s.trim()).filter((s) => s.length >= 2);
    if (h.id && h.id.length >= 2) needles.push(h.id);
    for (const n of needles) {
      if (t.includes(n) && String(h.name).length >= String(best).length) best = h.name;
    }
  }
  return best;
}

function resolveOosName(text, mods, aiName) {
  return guessForeignName(text, mods) || oosLabel(aiName);
}

function finishOos(mods, rec) {
  const label = oosLabel(rec.oos_name);
  return finishRoute(mods, Object.assign({}, rec, {
    module_id: "out_of_scope",
    module_name: oosTitle(label),
    out_of_scope: true,
    oos_name: label
  }));
}

function finishRoute(mods, rec) {
  const mid = rec.module_id;
  const y = mid && mid !== "unknown" && mid !== "out_of_scope"
    ? mods.find((m) => m.module_id === mid)
    : null;
  const outOfScope = rec.out_of_scope === true;
  return {
    module_id: outOfScope ? "out_of_scope" : mid,
    module_name: rec.module_name || (y && y.meta && y.meta.name) || mid,
    confidence: rec.confidence || "medium",
    score: rec.score || 0,
    evidence: rec.evidence || [],
    alternatives: rec.alternatives || [],
    foreign_hits: rec.foreign_hits || [],
    collect: y ? collectOf(y) : null,
    candidates: rec.candidates || [],
    unknown: mid === "unknown" && !outOfScope,
    out_of_scope: outOfScope,
    decision: rec.decision,
    scores: rec.scores || [],
    next_actions: rec.next_actions || (y
      ? ["请复制下方这一条正则到 BetaClub 搜集日志，把命中行完整粘贴后再定位"]
      : ["未能进入已接入模块，请改预分流、补日志，或人工改模块"]),
    reassign_buttons: reassignButtons(outOfScope ? "out_of_scope" : mid, rec.highlightIds || []),
    registered_modules: mods.map((m) => ({
      module_id: m.module_id,
      name: m.meta && m.meta.name
    })),
    auto_correct: false
  };
}

function decideLogs(wlHits, blHits, mods, pre) {
  if (!wlHits.length && !blHits.length) return null;
  const registered = new Map(mods.map((m) => [m.module_id, m]));
  const votes = new Map();
  function add(id, n, evidence, via) {
    const cur = votes.get(id) || { score: 0, evidence: [], via: [] };
    cur.score += n;
    cur.evidence.push(...evidence);
    cur.via.push(via);
    votes.set(id, cur);
  }
  for (const w of wlHits) {
    add(w.mod.module_id, w.hits.length * 100, w.hits.map((h) => h.id), "whitelist");
  }
  const oos = [];
  for (const b of blHits) {
    const tid = String(b.to_module || "").trim();
    if (tid && registered.has(tid)) add(tid, 80, [b.log_id], "blacklist");
    else oos.push(b);
  }
  const ranked = [...votes.entries()].sort((a, b) => {
    if (b[1].score !== a[1].score) return b[1].score - a[1].score;
    const aWl = a[1].via.includes("whitelist") ? 1 : 0;
    const bWl = b[1].via.includes("whitelist") ? 1 : 0;
    if (bWl !== aWl) return bWl - aWl;
    if (pre && a[0] === pre) return -1;
    if (pre && b[0] === pre) return 1;
    return String(a[0]).localeCompare(String(b[0]));
  });
  const scores = ranked.map(([id, rec]) => {
    const m = registered.get(id);
    return {
      module_id: id,
      name: (m && m.meta && m.meta.name) || id,
      score: rec.score,
      reason: rec.via.includes("whitelist") && rec.via.includes("blacklist")
        ? "白名单+黑名单指向本模块"
        : rec.via.includes("whitelist") ? "日志白名单（本模块问题）" : "日志黑名单（他模块改派至此）"
    };
  });
  if (ranked.length) {
    const [id, rec] = ranked[0];
    const dest = registered.get(id);
    const via = rec.via.includes("whitelist") && rec.via.includes("blacklist")
      ? "log_both"
      : rec.via.includes("whitelist") ? "whitelist" : "blacklist";
    return { kind: "module", dest, rec, via, scores, blHits };
  }
  if (oos.length) {
    return { kind: "oos", hit: oos[0], scores, blHits };
  }
  return null;
}

async function route(input) {
  input = input || {};
  const pre = input.pre_module && input.pre_module !== "other" && input.pre_module !== "unknown"
    ? String(input.pre_module)
    : "";
  const mods = enabledModules();
  const hasLogs = Boolean(String(input.logs || "").trim());
  const wlHits = [];
  const blHits = [];
  if (hasLogs) {
    const logInput = { logs: String(input.logs || ""), text: "" };
    for (const m of mods) {
      const wl = whitelistHits(m, logInput);
      if (wl.length) wlHits.push({ mod: m, hits: wl });
      const bl = blacklistHits(m, logInput, wl.length > 0);
      for (const b of bl) {
        blHits.push({
          from_module: m.module_id,
          to_module: b.to_module || "",
          to_module_name: b.to_module_name || b.to_module || "",
          log_id: b.id,
          reason: b.reason || "日志黑名单"
        });
      }
    }
  }

  const logDecision = decideLogs(wlHits, blHits, mods, pre);
  if (logDecision && logDecision.kind === "module") {
    const dest = logDecision.dest;
    const rec = logDecision.rec;
    const via = logDecision.via;
    const names = {
      whitelist: "日志白名单命中，确认是本模块问题「",
      blacklist: "日志黑名单命中，归到对应模块「",
      log_both: "日志白名单与黑名单均指向「"
    };
    return finishRoute(mods, {
      module_id: dest.module_id,
      module_name: dest.meta && dest.meta.name,
      confidence: "high",
      evidence: rec.evidence,
      foreign_hits: logDecision.blHits,
      highlightIds: [dest.module_id],
      scores: logDecision.scores,
      decision: {
        rule: via,
        reason: (names[via] || "日志命中「") + ((dest.meta && dest.meta.name) || dest.module_id) +
          "」。白名单=本模块问题，黑名单=改派到 to_module 对应模块。",
        overridden_pre: Boolean(pre && pre !== dest.module_id),
        ai_used: false
      }
    });
  }
  if (logDecision && logDecision.kind === "oos") {
    const hit = logDecision.hit;
    const label = hit.to_module_name || hit.to_module || "未知领域";
    return finishRoute(mods, {
      module_id: "out_of_scope",
      module_name: oosTitle(label),
      out_of_scope: true,
      confidence: "high",
      evidence: [hit.log_id],
      foreign_hits: logDecision.blHits,
      scores: logDecision.scores,
      decision: {
        rule: "blacklist_oos",
        reason: "日志黑名单指向「" + label + "」（to_module=" + (hit.to_module || "空") + "），该模块尚未接入 Watchman/modules。",
        overridden_pre: Boolean(pre),
        ai_used: false
      },
      next_actions: ["请上传对应模块 YAML（module_id 与黑名单 to_module 一致），或人工改到已有模块"]
    });
  }

  if (pre) {
    try {
      const dest = loadModule(pre);
      return finishRoute(mods, {
        module_id: dest.module_id,
        module_name: dest.meta && dest.meta.name,
        confidence: hasLogs ? "medium" : "medium",
        evidence: ["PRESELECT:" + pre],
        decision: {
          rule: "preselect",
          reason: "日志未命中任何模块白/黑名单，按用户预分流「" + ((dest.meta && dest.meta.name) || pre) + "」。",
          overridden_pre: false,
          ai_used: false
        }
      });
    } catch (e) {
      return finishOos(mods, {
        oos_name: "other",
        confidence: "low",
        evidence: [],
        decision: {
          rule: "oos_other",
          reason: "预分流模块不可用：" + e.message + "，分流为非窗口问题：other。",
          ai_used: false
        }
      });
    }
  }

  const catalog = mods.map(moduleCatalog);
  const matched = await ai.matchByDescription(input.text || "", catalog);
  if (matched.module_id && matched.module_id !== "unknown") {
    const dest = mods.find((m) => m.module_id === matched.module_id);
    if (dest) {
      return finishRoute(mods, {
        module_id: dest.module_id,
        module_name: dest.meta && dest.meta.name,
        confidence: matched.confidence || "medium",
        evidence: [matched.ai_used ? "AI-DESC" : "DESC-OVERLAP"],
        scores: matched.scores || [],
        score: ((matched.scores || [])[0] || {}).score || 0,
        decision: {
          rule: matched.ai_used ? "ai_desc" : "desc",
          reason: matched.reason,
          overridden_pre: false,
          ai_used: Boolean(matched.ai_used)
        }
      });
    }
  }

  const llmOn = ai.aiEnabled();
  const oosName = resolveOosName(input.text || "", mods, matched && matched.oos_name);
  const named = oosName !== "other";
  return finishOos(mods, {
    oos_name: oosName,
    confidence: "low",
    evidence: [],
    scores: (matched && matched.scores) || [],
    decision: {
      rule: named ? "oos_named" : "oos_other",
      reason: named
        ? ((matched && matched.reason) || "无法归入已接入模块") + "。对应「" + oosName + "」，分流为非窗口问题：" + oosName + "。"
        : ((matched && matched.reason) || "无法确认已接入模块") + "。分流为非窗口问题：other。",
      ai_used: Boolean(matched && matched.ai_used),
      llm_enabled: llmOn
    },
    next_actions: [named
      ? "目标模块「" + oosName + "」尚未接入，可上传对应 YAML 或人工改到已有模块"
      : "未能确认模块，已归为非窗口问题：other。可改预分流、补日志，或人工改模块"]
  });
}

function matchLogs(mod, logsText) {
  const hits = [];
  const lines = String(logsText || "").split(/\r?\n/);
  for (const lg of flattenKeyLogs(mod)) {
    const re = compileRe(lg.regex, lg.flags);
    if (!re) continue;
    lines.forEach((line, i) => {
      if (!line) return;
      re.lastIndex = 0;
      if (!re.test(line)) return;
      hits.push({
        log_id: lg.id,
        line_no: i + 1,
        line,
        layer_id: lg.layer_id,
        function: lg.function,
        meaning: lg.meaning || "",
        title: lg.title || "",
        kind: lg.kind || "",
        locate: lg.locate || "",
        probe: lg.probe || "",
        atom_id: lg.atom_id || "",
        atom_title: lg.atom_title || "",
        severity: lg.severity || "info",
        exception: lg.exception === true,
        scenario_ids: arr(lg.scenario_ids)
      });
    });
  }
  return hits;
}

function matchScenarios(mod, hits) {
  const ids = new Set(hits.map((h) => h.log_id));
  const out = [];
  for (const sc of scenariosOf(mod)) {
    const keyIds = arr(sc.key_logs).map((l) => l && l.id).filter(Boolean);
    const matched = keyIds.filter((id) => ids.has(id));
    if (!matched.length) continue;
    const ex = scenarioException(sc);
    out.push({
      id: sc.id,
      title: sc.title,
      boundary: sc.boundary,
      priority: sc.priority || 100,
      exception_layer: ex.layer_id,
      exception_functions: ex.functions,
      summary: sc.summary,
      locate: (arr(sc.callchain).find((c) => c.exception) || {}).locate || "",
      callchain: arr(sc.callchain),
      matched_logs: matched,
      hit_count: matched.length
    });
  }
  return out.sort((a, b) => a.priority - b.priority || b.hit_count - a.hit_count);
}

function exceptionPoints(mod, hits, scenarios) {
  const chain = scenarios[0] ? arr(scenarios[0].callchain) : [];
  const order = {};
  chain.forEach((c, i) => {
    order[c.layer_id] = i;
  });
  let ex = hits.filter((h) => h.exception);
  if (!ex.length) ex = hits.filter((h) => h.severity === "error" || h.severity === "warn");
  const grouped = {};
  for (const h of ex) {
    grouped[h.layer_id] = grouped[h.layer_id] || [];
    grouped[h.layer_id].push(h);
  }
  const points = Object.keys(grouped)
    .map((layer) => {
      const hs = grouped[layer];
      const logs = [];
      const seen = new Set();
      for (const h of hs) {
        const k = h.log_id + "\n" + h.line;
        if (seen.has(k)) continue;
        seen.add(k);
        logs.push({ log_id: h.log_id, line: h.line, meaning: h.meaning || "" });
      }
      return {
        layer_id: layer,
        order: order[layer] != null ? order[layer] : 99,
        functions: [...new Set(hs.map((h) => h.function).filter(Boolean))],
        logs
      };
    })
    .sort((a, b) => a.order - b.order);
  let primary = points[0] || null;
  if (scenarios.length) {
    const top = scenarios[0];
    primary = points.find((p) => p.layer_id === top.exception_layer) || points[0] || null;
    if (!primary && top.exception_layer) {
      primary = {
        layer_id: top.exception_layer,
        order: order[top.exception_layer] != null ? order[top.exception_layer] : 99,
        functions: top.exception_functions,
        logs: hits
          .filter((h) => top.matched_logs.includes(h.log_id))
          .map((h) => ({ log_id: h.log_id, line: h.line }))
      };
    }
  }
  return [points, primary];
}

function buildTimeline(mod, hits) {
  const byId = new Map(atomsOf(mod).map((a) => [a.id, a]));
  const ordered = (hits || []).slice().sort((a, b) => a.line_no - b.line_no);
  const steps = [];
  for (const h of ordered) {
    if (!h.atom_id || !byId.has(h.atom_id)) continue;
    const atom = byId.get(h.atom_id);
    let step = steps[steps.length - 1];
    if (!step || step.atom_id !== h.atom_id) {
      step = {
        atom_id: atom.id,
        title: atom.title || atom.id,
        api: atom.api || "",
        status: "enter",
        callchain: arr(atom.callchain),
        events: []
      };
      steps.push(step);
    }
    step.events.push({
      log_id: h.log_id,
      probe: h.probe,
      line_no: h.line_no,
      line: h.line,
      meaning: h.meaning || "",
      layer_id: h.layer_id,
      function: h.function
    });
    if (h.probe === "success") {
      step.status = "ok";
      delete step.failure;
    }
    if (h.probe === "failure") {
      step.status = "fail";
      step.failure = {
        id: h.log_id,
        title: h.title || h.meaning || h.log_id,
        kind: h.kind || "",
        meaning: h.meaning || "",
        locate: h.locate || "",
        layer_id: h.layer_id,
        function: h.function
      };
    }
  }
  for (const s of steps) {
    if (s.status === "enter") s.status = "unknown";
  }
  return steps;
}

function focusAtom(steps) {
  if (!steps.length) return null;
  return steps.slice().reverse().find((s) => s.status === "fail" || s.status === "unknown") || steps[steps.length - 1];
}

function atomChainWithMark(step) {
  const chain = arr(step && step.callchain).map((c) => Object.assign({}, c, { exception: false }));
  if (!chain.length) return [];
  let layer = step.status === "fail" && step.failure ? step.failure.layer_id : "";
  if (step.status === "unknown") {
    const enter = (step.events || []).filter((e) => e.probe === "enter").pop();
    const idx = enter ? chain.findIndex((c) => c.layer_id === enter.layer_id) : -1;
    layer = idx >= 0 && chain[idx + 1] ? chain[idx + 1].layer_id : (enter && enter.layer_id) || chain[chain.length - 1].layer_id;
  }
  for (const c of chain) {
    if (layer && c.layer_id === layer) c.exception = true;
  }
  if (layer && !chain.some((c) => c.exception) && chain.length) chain[chain.length - 1].exception = true;
  return chain;
}

function localize(modId, logsText) {
  const mod = loadModule(modId);
  const hits = matchLogs(mod, logsText);
  const timeline = atomsOf(mod).length ? buildTimeline(mod, hits) : [];
  const focus = focusAtom(timeline);
  const scenarios = timeline.length ? [] : matchScenarios(mod, hits);
  const chain = focus ? atomChainWithMark(focus) : (scenarios[0] ? arr(scenarios[0].callchain) : []);
  const [points, primaryFromOld] = exceptionPoints(mod, hits, scenarios);
  const noHit = hits.length === 0;
  const foreign = blacklistHits(mod, { logs: logsText }, whitelistHits(mod, { logs: logsText }).length > 0);

  let primary = primaryFromOld;
  let hypothesis;
  let confidence;
  let exceptionScenario = null;

  if (timeline.length) {
    const exLayer = chain.find((c) => c.exception) || {};
    primary = focus && (focus.status === "fail" || focus.status === "unknown")
      ? {
          layer_id: exLayer.layer_id || (focus.failure && focus.failure.layer_id) || "",
          functions: [focus.failure && focus.failure.function, ...(exLayer.symbols || [])].filter(Boolean),
          logs: (focus.events || []).filter((e) => e.probe === "failure" || focus.status === "unknown").map((e) => ({
            log_id: e.log_id,
            line: e.line,
            meaning: e.meaning
          }))
        }
      : primary;
    if (noHit) {
      hypothesis = "用户日志未命中本模块原子探针，禁止编造；请人工改模块";
      confidence = "low";
    } else if (focus && focus.status === "fail") {
      hypothesis = "时间线断在「" + focus.title + "」：" + (focus.failure.kind || "") +
        (focus.failure.kind ? " · " : "") + (focus.failure.meaning || focus.failure.title);
      confidence = "high";
      exceptionScenario = {
        id: focus.atom_id,
        title: focus.title + (focus.failure.title ? " · " + focus.failure.title : ""),
        summary: hypothesis,
        locate: focus.failure.locate || "",
        boundary: focus.failure.kind || ""
      };
    } else if (focus && focus.status === "unknown") {
      hypothesis = "「" + focus.title + "」已进入，但既无成功也无已知失败，更像真实缺陷";
      confidence = "medium";
      exceptionScenario = {
        id: focus.atom_id,
        title: focus.title + " · 未知",
        summary: hypothesis,
        locate: "对照进入日志之后应出现的成功句，看停在调用链哪一层",
        boundary: "未知"
      };
    } else {
      hypothesis = "各原子均走完，未命中已知失败";
      confidence = "medium";
      exceptionScenario = focus
        ? { id: focus.atom_id, title: focus.title, summary: hypothesis, locate: "", boundary: "" }
        : null;
    }
  } else {
    exceptionScenario = scenarios[0]
      ? {
          id: scenarios[0].id,
          title: scenarios[0].title,
          summary: scenarios[0].summary,
          locate: scenarios[0].locate || "",
          boundary: scenarios[0].boundary
        }
      : null;
    confidence = noHit ? "low" : scenarios.length && primary ? "high" : "medium";
    hypothesis = noHit
      ? "用户日志未命中本模块场景关键日志，禁止编造场景；请人工改模块"
      : scenarios[0]
        ? scenarios[0].summary
        : "命中关键日志但未映射到场景，请补全该模块 YAML 场景";
  }

  return {
    module_id: mod.module_id,
    module_name: mod.meta && mod.meta.name,
    yaml: modulePath(modId),
    matched_logs: hits,
    timeline,
    callchain_hits: points,
    callchain_exception_point: primary,
    scenario_callchain: chain,
    matched_scenarios: scenarios,
    exception_scenario: exceptionScenario,
    confidence,
    hypothesis,
    collect: collectOf(mod),
    assist_apis: {
      internal: apiGroups(mod).internal,
      dependencies: apiGroups(mod).dependencies
    },
    foreign_hits: foreign.map((b) => ({
      from_module: mod.module_id,
      to_module: b.to_module || "",
      to_module_name: b.to_module_name || "",
      log_id: b.id,
      reason: b.reason || "日志黑名单"
    })),
    reassign_buttons: reassignButtons(modId, foreign.map((b) => b.to_module)),
    next_actions: noHit
      ? ["YAML 0 命中：核对是否用 BetaClub 按 collect 正则搜集，或点按钮改到其他模块"]
      : ["按时间线对照该原子调用链上的标红层"],
    auto_correct: false
  };
}

function validate(modId) {
  const mod = loadModule(modId);
  const errors = [];
  if (!logWhitelist(mod).length) errors.push("missing log_whitelist");
  if (!collectOf(mod) || !collectOf(mod).regex) errors.push("missing collect.regex");
  const atoms = atomsOf(mod);
  const scs = scenariosOf(mod);
  if (!atoms.length && !scs.length) errors.push("missing atoms");
  const kinds = new Set(["应用误用", "依赖失败", "框架缺陷"]);
  for (const atom of atoms) {
    if (!arr(atom.callchain).length) errors.push("atom " + atom.id + " missing callchain");
    const probes = arr(atom.enter).concat(arr(atom.success), arr(atom.failures));
    if (!probes.length) errors.push("atom " + atom.id + " missing enter/success/failures");
    for (const lg of probes) {
      if (!lg.regex) errors.push("atom " + atom.id + " log " + (lg.id || "?") + " missing regex");
      if (!lg.layer_id) errors.push("atom " + atom.id + " log " + (lg.id || "?") + " missing layer_id");
    }
    for (const lg of arr(atom.failures)) {
      if (lg.kind && !kinds.has(lg.kind)) errors.push("atom " + atom.id + " failure " + lg.id + " kind 必须是 应用误用/依赖失败/框架缺陷");
    }
  }
  for (const w of logWhitelist(mod)) {
    if (!w.regex) errors.push("log_whitelist " + w.id + " missing regex");
  }
  for (const b of logBlacklist(mod)) {
    if (!b.regex) errors.push("log_blacklist " + b.id + " missing regex");
    if (!b.to_module && !b.to_module_name) errors.push("log_blacklist " + b.id + " missing to_module/to_module_name");
  }
  for (const sc of scs) {
    if (!arr(sc.callchain).length) errors.push("scenario " + sc.id + " missing callchain");
    if (!arr(sc.key_logs).length) errors.push("scenario " + sc.id + " missing key_logs");
    const ex = arr(sc.callchain).filter((c) => c.exception);
    if (!ex.length) errors.push("scenario " + sc.id + " callchain missing exception: true");
    for (const lg of arr(sc.key_logs)) {
      if (!lg.regex) errors.push("scenario " + sc.id + " log " + (lg.id || "?") + " missing regex");
      if (!lg.layer_id) errors.push("scenario " + sc.id + " log " + (lg.id || "?") + " missing layer_id");
    }
  }
  const apis = apiGroups(mod);
  if (!apis.external.length) errors.push("missing apis.external");
  return { module_id: modId, ok: errors.length === 0, errors };
}

function listApis(moduleId) {
  const mods = enabledModules();
  if (!moduleId || moduleId === "other" || moduleId === "unknown") return [];
  const m = mods.find((x) => x.module_id === moduleId);
  return m ? declaredApis(m) : [];
}

function templatePath() {
  return path.join(ROOT, "modules", "_template", "module.yaml");
}

function installModuleYaml(text, overwrite) {
  const raw = String(text || "").replace(/^\uFEFF/, "");
  if (!raw.trim()) throw new Error("YAML 为空");
  let doc;
  try {
    doc = yaml.load(raw);
  } catch (e) {
    throw new Error("YAML 解析失败: " + e.message);
  }
  if (!doc || typeof doc !== "object") throw new Error("YAML 根节点必须是对象");
  const id = String(doc.module_id || "").trim();
  if (!/^[a-z][a-z0-9_-]{0,40}$/.test(id)) throw new Error("module_id 须为小写字母开头的 id（字母数字_-，最长 41）");
  if (id === "_template") throw new Error("不能使用保留 id _template");
  const dir = path.join(ROOT, "modules", id);
  const file = path.join(dir, "module.yaml");
  if (fs.existsSync(file) && !overwrite) {
    const err = new Error("模块已存在: " + id + "（确认后可覆盖）");
    err.code = "EXISTS";
    throw err;
  }
  let out = raw;
  if (/^enabled:\s*\S+/m.test(out)) out = out.replace(/^enabled:\s*\S+/m, "enabled: true");
  else out = "enabled: true\n" + out;
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, out, "utf8");
  const check = validate(id);
  return {
    module_id: id,
    name: (doc.meta && doc.meta.name) || id,
    overwritten: Boolean(overwrite),
    validate: check
  };
}

function listModules() {
  return enabledModules().map((m) => ({
    module_id: m.module_id,
    name: m.meta && m.meta.name,
    description: m.meta && m.meta.description,
    yaml: "modules/" + m.module_id + "/module.yaml",
    apis: declaredApis(m)
  }));
}

function pick(id) {
  const mod = loadModule(id);
  return {
    module_id: mod.module_id,
    module_name: mod.meta && mod.meta.name,
    collect: collectOf(mod),
    source: "dropdown",
    reassign_buttons: reassignButtons(id, []),
    registered_modules: listModules(),
    auto_correct: false
  };
}

function reassign(body) {
  const from = body.from_module;
  const to = body.to_module;
  if (!to) throw new Error("必须由人指定 to_module，系统不自动纠正");
  if (to === from) throw new Error("目标模块与当前相同");
  loadModule(to);
  const day = new Date();
  const stamp = day.toISOString().slice(0, 10).replace(/-/g, "");
  const id = "MR-" + stamp + "-" + from + "-to-" + to;
  const rec = {
    id,
    created: new Date().toISOString(),
    source: "human_reassign",
    from_module: from,
    to_module: to,
    trigger: "button",
    input: body.input || {},
    result: {
      reason: body.reason || "人工改模块",
      fooling_features: arr(body.fooling_features)
    }
  };
  const file = path.join(ROOT, "memory", "misroutes", id + ".yaml");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, yaml.dump(rec, { lineWidth: 100 }), "utf8");
  const dest = loadModule(to);
  return {
    reassign: true,
    from_module: from,
    to_module: to,
    misroute_id: id,
    collect: collectOf(dest),
    module_name: dest.meta && dest.meta.name,
    next_actions: ["已换到目标模块。请复制新的正则到 BetaClub 再搜集日志后定位"],
    auto_correct: false
  };
}

module.exports = { route, localize, validate, listModules, listApis, pick, reassign, installModuleYaml, templatePath, ROOT };
