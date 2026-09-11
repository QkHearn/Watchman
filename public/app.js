const state = {
  view: "work",
  stage: 1,
  module_id: null,
  problem_id: null,
  lastInput: {},
  lastCollect: null,
  modules: [],
  apiCatalog: [],
  pickedApis: []
};

async function api(url, body, method) {
  const opt = { method: method || (body ? "POST" : "GET"), headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(url, opt);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = new Error((data && data.error) || res.statusText);
    err.code = data && data.code;
    err.status = res.status;
    throw err;
  }
  return data;
}

function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function gatherInput() {
  const apis = selectedApis();
  const errors = $("errors").value.split(/[,，\s]+/).filter(Boolean);
  return {
    text: $("text").value.trim(),
    apis,
    errors,
    symptoms: [],
    logs: $("snippet").value,
    pre_module: $("preModule").value || "other"
  };
}

function canEnterStage2(r) {
  const id = (r && r.module_id) || "";
  return Boolean(id) && id !== "unknown" && id !== "out_of_scope" && !r.unknown && !r.out_of_scope;
}

function decisionLabel(rule) {
  return {
    blacklist: "日志黑名单 · 对应模块",
    blacklist_oos: "日志黑名单 · 目标模块未接入",
    whitelist: "日志白名单 · 本模块问题",
    log_both: "日志白名单+黑名单",
    preselect: "用户预分流",
    ai_desc: "AI 描述匹配",
    desc: "描述/函数匹配",
    oos_named: "非窗口问题 · 已知模块",
    oos_other: "非窗口问题 · other",
    unknown: "非窗口问题 · other"
  }[rule] || rule || "分流";
}

function selectedApis() {
  return state.pickedApis.slice();
}

function closeApiMenu() {
  $("apiMenu").classList.add("hidden");
}

function renderApiPicker() {
  const catalog = state.apiCatalog || [];
  const picked = new Set(state.pickedApis);
  const trigger = $("apiTrigger");
  const menu = $("apiMenu");
  const pickedBox = $("apiPicked");
  const pre = $("preModule").value;
  if (!pre || pre === "other") {
    trigger.disabled = true;
    trigger.textContent = "请先选择预分流模块";
    menu.innerHTML = "";
    pickedBox.innerHTML = "";
    closeApiMenu();
    return;
  }
  trigger.disabled = catalog.length === 0;
  trigger.textContent = catalog.length
    ? (picked.size ? `已选 ${picked.size} 个故障接口` : "选择故障接口")
    : "该模块 YAML 未声明故障接口";
  menu.innerHTML = catalog.map((a) => {
    const on = picked.has(a.id);
    return `<button type="button" class="api-opt${on ? " on" : ""}" data-api="${escapeHtml(a.id)}">
      <span>${escapeHtml(a.label)}</span>
      <span class="role">${escapeHtml(a.role || (on ? "已选" : "点击选择"))}</span>
    </button>`;
  }).join("");
  pickedBox.innerHTML = state.pickedApis.map((id) => {
    const a = catalog.find((x) => x.id === id);
    const label = a ? a.label : id;
    return `<span class="tag">${escapeHtml(label)}<button type="button" data-drop="${escapeHtml(id)}" aria-label="移除">×</button></span>`;
  }).join("");
  menu.querySelectorAll("[data-api]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = btn.getAttribute("data-api");
      if (picked.has(id)) state.pickedApis = state.pickedApis.filter((x) => x !== id);
      else state.pickedApis.push(id);
      renderApiPicker();
    });
  });
  pickedBox.querySelectorAll("[data-drop]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.pickedApis = state.pickedApis.filter((x) => x !== btn.getAttribute("data-drop"));
      renderApiPicker();
    });
  });
}

async function refreshApiChoices() {
  const pre = $("preModule").value;
  if (!pre || pre === "other") {
    state.apiCatalog = [];
    state.pickedApis = [];
    renderApiPicker();
    return;
  }
  const d = await api("/api/apis?module=" + encodeURIComponent(pre));
  const catalog = (d.apis || []).filter((a) => !a.kind || a.kind === "external");
  state.apiCatalog = catalog;
  const allow = new Set(catalog.map((a) => a.id));
  state.pickedApis = state.pickedApis.filter((id) => allow.has(id));
  renderApiPicker();
}

function collectHtml(collect, emptyText) {
  const regex = collect && (collect.regex || ((collect.queries || [])[0] && collect.queries[0].regex));
  if (!regex) {
    return `<p class="k">${escapeHtml(emptyText || "该模块 YAML 未提供 collect 正则")}</p>`;
  }
  return `<div class="k">${escapeHtml(collect.title || "搜集日志")}</div>
    <p class="meta">${escapeHtml(collect.hint || "复制下面正则到 BetaClub 搜集日志，把结果完整粘贴到阶段二")}</p>
    <div class="collect-row">
      <pre class="collect-regex">${escapeHtml(regex)}</pre>
      <button type="button" class="ghost" data-copy-regex="${escapeHtml(regex)}">复制正则</button>
    </div>`;
}

function bindCopyRegex(root) {
  (root || document).querySelectorAll("[data-copy-regex]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const text = btn.getAttribute("data-copy-regex") || "";
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      const old = btn.textContent;
      btn.textContent = "已复制";
      setTimeout(() => { btn.textContent = old; }, 1400);
    });
  });
}

function foreignHtml(hits) {
  const list = (hits || []).filter((h) => h.to_module_name || h.to_module);
  if (!list.length) return "";
  const rows = list.map((h) =>
    `<div class="v">${escapeHtml(h.log_id || "")} → ${escapeHtml(h.to_module_name || h.to_module)}${h.to_module ? ` (${escapeHtml(h.to_module)})` : "（该模块 YAML 未接入）"} · ${escapeHtml(h.reason || "")}</div>`
  ).join("");
  return `<div class="k">日志黑名单（指向 to_module 对应模块）</div>${rows}`;
}

function scoresHtml(scores) {
  const list = (scores || []).slice().sort((a, b) => Number(b.score) - Number(a.score));
  if (!list.length) return "";
  const rows = list.map((s) =>
    `<div class="v">${escapeHtml(s.name || s.module_id)} · ${escapeHtml(s.score)}${s.reason ? " · " + escapeHtml(s.reason) : ""}</div>`
  ).join("");
  return `<div class="k">模块打分</div>${rows}`;
}

function chainHtml(chain) {
  if (!chain || !chain.length) return "";
  const steps = chain.map((c, i) => {
    const ex = c.exception;
    const fns = (c.symbols || c.entry_symbols || []).join(" → ");
    return `<div class="chain-step${ex ? " ex" : ""}">
      <span class="n">${i + 1}</span>
      <div>
        <div class="v">${escapeHtml(c.name || c.layer_id)}${ex ? " · 异常点（调用在此断开）" : ""}</div>
        <div class="meta">${escapeHtml(c.layer_id || "")}${fns ? " · " + escapeHtml(fns) : ""}</div>
        ${c.do ? `<p class="meta">${escapeHtml(c.do)}</p>` : ""}
        ${c.locate ? `<p class="meta">${escapeHtml(c.locate)}</p>` : ""}
      </div>
    </div>`;
  }).join("");
  return `<div class="k">该场景调用链（自上而下；标红层即异常点）</div>${steps}`;
}

function startBusy(outId, title, steps) {
  const el = $(outId);
  el.classList.remove("hidden");
  el.innerHTML = `
    <div class="busy" aria-busy="true">
      <span class="busy-spin"></span>
      <div>
        <div class="busy-title">${escapeHtml(title)}</div>
        <div class="busy-step">${escapeHtml(steps[0] || "处理中…")}</div>
      </div>
    </div>
    <div class="busy-bar"><i></i></div>`;
  let i = 0;
  const timer = setInterval(() => {
    i = (i + 1) % steps.length;
    const s = el.querySelector(".busy-step");
    if (s) s.textContent = steps[i];
  }, 1100);
  return () => clearInterval(timer);
}

function reassignHtml(buttons, registered) {
  const extra = (registered || [])
    .filter((m) => !buttons.some((b) => b.module_id === m.module_id) && m.module_id !== state.module_id)
    .map((m) => ({ module_id: m.module_id, label: "改到：" + (m.name || m.module_id), highlight: false }));
  const all = buttons.concat(extra);
  if (!all.length) {
    return `<div class="block"><div class="k">改模块</div>
      <p class="meta">目前只有一份 YAML。新文件放到 modules/&lt;id&gt;/module.yaml 后会出现按钮。</p></div>`;
  }
  const btns = all.map((b) =>
    `<button type="button" class="ghost${b.highlight ? " hl" : ""}" data-reassign="${escapeHtml(b.module_id)}">${escapeHtml(b.label)}</button>`
  ).join("");
  return `<div class="block"><div class="k">改到其他模块（人工）</div><div class="btns">${btns}</div></div>`;
}

function setStage2Collect(collect) {
  state.lastCollect = collect || null;
  const box = $("stage2Collect");
  if (!box) return;
  box.innerHTML = collectHtml(collect);
  bindCopyRegex(box);
}

function goStage(n) {
  const ok2 = Boolean(state.module_id && state.module_id !== "unknown" && state.module_id !== "out_of_scope");
  if (n === 2 && !ok2) return;
  state.stage = n === 2 ? 2 : 1;
  $("stageRoute").classList.toggle("hidden", state.stage !== 1);
  $("stageLocalize").classList.toggle("hidden", state.stage !== 2);
  $("stepTab1").classList.toggle("on", state.stage === 1);
  $("stepTab2").classList.toggle("on", state.stage === 2);
  $("stepTab2").disabled = !ok2;
  if (state.stage === 2) setStage2Collect(state.lastCollect);
}

function setModule(id, name) {
  state.module_id = id;
  $("curModule").textContent = name ? `${name} (${id})` : id || "—";
  const ok = Boolean(id && id !== "unknown" && id !== "out_of_scope");
  $("btnLocalize").disabled = !ok;
  $("stepTab2").disabled = !ok;
}

function setProblemMeta(p) {
  if (!p || !p.id) {
    $("problemMeta").textContent = "未保存";
    return;
  }
  const t = (p.updated_at || p.created_at || "").replace("T", " ").slice(0, 19);
  $("problemMeta").textContent = p.id + " · " + t;
}

function bindReassign(root) {
  root.querySelectorAll("[data-reassign]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const to = btn.getAttribute("data-reassign");
      const reason = window.prompt("改模块原因（写入误分流记忆）", "") || "人工改模块";
      try {
        const r = await api("/api/reassign", {
          from_module: state.module_id,
          to_module: to,
          reason,
          input: state.lastInput
        });
        setModule(r.to_module, r.module_name);
        $("preModule").value = r.to_module;
        setStage2Collect(r.collect);
        const box = $("routeOut");
        box.classList.remove("hidden");
        box.innerHTML = `<div class="k">已改到</div>
          <div class="v">${escapeHtml(r.module_name || r.to_module)} · ${escapeHtml(r.misroute_id)}</div>
          ${collectHtml(r.collect)}`;
        bindCopyRegex(box);
        await persist({
          module_id: r.to_module,
          module_name: r.module_name,
          status: "routed"
        });
      } catch (e) {
        alert(e.message);
      }
    });
  });
}

function renderDropdown(mods) {
  const sel = $("preModule");
  const prev = sel.value || "other";
  const yamlOpts = (mods || []).map((m) =>
    `<option value="${escapeHtml(m.module_id)}">${escapeHtml(m.name || m.module_id)}</option>`
  ).join("");
  sel.innerHTML = yamlOpts + `<option value="other">其他（自动分流）</option>`;
  const ids = new Set((mods || []).map((m) => m.module_id));
  sel.value = ids.has(prev) || prev === "other" ? prev : "other";
  const fm = $("fModule");
  const cur = fm.value;
  fm.innerHTML = `<option value="">全部模块</option>` + (mods || []).map((m) =>
    `<option value="${escapeHtml(m.module_id)}">${escapeHtml(m.name || m.module_id)}</option>`
  ).join("");
  fm.value = cur;
}

async function refreshModules() {
  const d = await api("/api/modules");
  state.modules = d.modules || [];
  renderDropdown(state.modules);
  await refreshApiChoices();
  return state.modules;
}

async function persist(extra) {
  const input = gatherInput();
  const body = {
    id: state.problem_id || undefined,
    text: input.text,
    apis: input.apis,
    errors: input.errors,
    snippet: input.logs,
    logs: $("logs").value,
    module_id: state.module_id || "",
    ...extra
  };
  const saved = await api(state.problem_id ? "/api/problems/" + state.problem_id : "/api/problems", body, state.problem_id ? "PUT" : "POST");
  state.problem_id = saved.id;
  setProblemMeta(saved);
  return saved;
}

async function applyPickedModule(id) {
  const r = await api("/api/module/" + encodeURIComponent(id));
  setModule(r.module_id, r.module_name);
  const el = $("routeOut");
  el.classList.remove("hidden");
  el.innerHTML = `
    <div class="k">预分流</div>
    <div class="v">${escapeHtml(r.module_name || r.module_id)}</div>
    ${collectHtml(r.collect)}
    ${reassignHtml(r.reassign_buttons || [], r.registered_modules || [])}
  `;
  bindReassign(el);
  bindCopyRegex(el);
  setStage2Collect(r.collect);
  await persist({ module_id: r.module_id, module_name: r.module_name, status: "routed", confidence: "" });
}

function showView(name) {
  state.view = name;
  $("viewWork").classList.toggle("hidden", name !== "work");
  $("viewList").classList.toggle("hidden", name !== "list");
  $("tabWork").classList.toggle("on", name === "work");
  $("tabList").classList.toggle("on", name === "list");
  if (name === "list") loadList();
}

function statusLabel(s) {
  return { draft: "草稿", routed: "已分流", localized: "已定位" }[s] || s || "草稿";
}

function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "").slice(0, 19);
}

async function loadList() {
  const q = new URLSearchParams({
    q: $("q").value.trim(),
    module: $("fModule").value,
    status: $("fStatus").value,
    sort: $("fSort").value
  });
  const d = await api("/api/problems?" + q.toString());
  const items = d.problems || [];
  $("listCount").textContent = items.length ? `共 ${items.length} 条，按时间排序` : "暂无问题";
  const body = $("listBody");
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty">还没有记录。在工单里分流或保存后会出现在这里。</td></tr>`;
    return;
  }
  body.innerHTML = items.map((p) => `<tr data-id="${escapeHtml(p.id)}">
    <td>${escapeHtml(fmtTime(p.updated_at || p.created_at))}</td>
    <td>${escapeHtml(p.title || p.text || "—")}</td>
    <td>${escapeHtml(p.module_name || p.module_id || "—")}</td>
    <td><span class="st st-${escapeHtml(p.status || "draft")}">${escapeHtml(statusLabel(p.status))}</span></td>
    <td>${escapeHtml((p.errors || []).join(", ") || "—")}</td>
    <td>${escapeHtml(p.scenario_title || p.exception_layer || "—")}</td>
  </tr>`).join("");
  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => openProblem(tr.getAttribute("data-id")));
  });
}

async function openProblem(id) {
  const p = await api("/api/problems/" + encodeURIComponent(id));
  state.problem_id = p.id;
  $("text").value = p.text || "";
  $("errors").value = (p.errors || []).join(", ");
  $("snippet").value = p.snippet || "";
  $("logs").value = p.logs || "";
  setProblemMeta(p);
  if (p.module_id) {
    $("preModule").value = p.module_id;
    setModule(p.module_id, p.module_name);
  } else {
    $("preModule").value = "other";
    setModule(null, "");
  }
  state.pickedApis = p.apis || [];
  await refreshModules();
  $("routeOut").classList.add("hidden");
  $("locOut").classList.add("hidden");
  if (p.hypothesis || p.scenario_title) {
    $("locOut").classList.remove("hidden");
    $("locOut").innerHTML = `<div class="k">上次定位</div>
      <div class="v">${escapeHtml(p.scenario_title || "")} ${escapeHtml(p.exception_layer || "")}</div>
      <p>${escapeHtml(p.hypothesis || "")}</p>`;
  }
  showView("work");
  if (p.module_id && p.module_id !== "unknown") {
    try {
      const picked = await api("/api/module/" + encodeURIComponent(p.module_id));
      setStage2Collect(picked.collect);
    } catch {
      setStage2Collect(null);
    }
    goStage(p.status === "draft" ? 1 : 2);
  } else {
    goStage(1);
  }
}

function resetWork() {
  state.problem_id = null;
  state.module_id = null;
  $("text").value = "";
  $("errors").value = "";
  $("snippet").value = "";
  $("logs").value = "";
  $("preModule").value = "other";
  $("routeOut").classList.add("hidden");
  $("locOut").classList.add("hidden");
  setModule(null, "");
  setProblemMeta(null);
  setStage2Collect(null);
  goStage(1);
  refreshApiChoices().catch(() => renderApiPicker());
}

function exportUrl(kind) {
  const q = new URLSearchParams({
    q: $("q").value.trim(),
    module: $("fModule").value,
    status: $("fStatus").value,
    sort: $("fSort").value
  });
  return "/api/problems/export." + kind + "?" + q.toString();
}

$("tabWork").addEventListener("click", () => showView("work"));
$("tabList").addEventListener("click", () => showView("list"));
$("btnNew").addEventListener("click", () => { resetWork(); showView("work"); });
$("stepTab1").addEventListener("click", () => goStage(1));
$("stepTab2").addEventListener("click", () => goStage(2));
$("btnBackStage1").addEventListener("click", () => goStage(1));
$("btnSave2").addEventListener("click", async () => {
  try { await persist({ status: state.module_id ? "routed" : "draft" }); } catch (e) { alert(e.message); }
});
$("preModule").addEventListener("focus", () => { refreshModules().catch(() => {}); });
$("preModule").addEventListener("change", async () => {
  await refreshApiChoices();
});
$("apiTrigger").addEventListener("click", (e) => {
  e.stopPropagation();
  if ($("apiTrigger").disabled) return;
  $("apiMenu").classList.toggle("hidden");
});
document.addEventListener("click", (e) => {
  if (!$("apiPicker").contains(e.target)) closeApiMenu();
});

async function uploadYaml(text, overwrite) {
  try {
    const r = await api("/api/modules", { yaml: text, overwrite: Boolean(overwrite) });
    await refreshModules();
    $("preModule").value = r.module_id;
    await refreshApiChoices();
    const warn = r.validate && !r.validate.ok ? "\n校验未通过: " + (r.validate.errors || []).join("; ") : "";
    alert("已接入模块 " + (r.name || r.module_id) + warn);
  } catch (e) {
    if (e.code === "EXISTS" && !overwrite) {
      if (window.confirm(e.message + "\n是否覆盖？")) return uploadYaml(text, true);
      return;
    }
    alert(e.message);
  }
}

$("btnTpl").addEventListener("click", () => { window.location = "/api/modules/template"; });
$("btnUpload").addEventListener("click", () => $("yamlFile").click());
$("yamlFile").addEventListener("change", async () => {
  const file = $("yamlFile").files && $("yamlFile").files[0];
  $("yamlFile").value = "";
  if (!file) return;
  const text = await file.text();
  await uploadYaml(text, false);
});

$("btnSave").addEventListener("click", async () => {
  try { await persist({ status: state.module_id ? "routed" : "draft" }); } catch (e) { alert(e.message); }
});

$("btnRoute").addEventListener("click", async () => {
  const input = gatherInput();
  state.lastInput = input;
  const btn = $("btnRoute");
  const stop = startBusy("routeOut", "正在分流", [
    "扫描已接入模块 YAML",
    "匹配日志白名单 / 黑名单",
    "按现象与各模块描述打分",
    "汇总分流结果"
  ]);
  btn.disabled = true;
  btn.classList.add("busy-btn");
  btn.textContent = "分流中…";
  try {
    await refreshModules();
    const r = await api("/api/route", input);
    const enter = canEnterStage2(r);
    setModule(enter ? r.module_id : (r.out_of_scope ? "out_of_scope" : r.module_id), r.module_name);
    if (enter) {
      $("preModule").value = r.module_id;
      await refreshApiChoices();
    }
    const d = r.decision || {};
    const el = $("routeOut");
    el.classList.remove("hidden");
    const cand = (r.candidates || []).filter((c) => c.collect && c.collect.regex);
    const candHtml = r.collect
      ? collectHtml(r.collect)
      : (cand.length
        ? cand.map((c) => `<div class="block"><div class="k">候选 ${escapeHtml(c.name || c.module_id)}（分 ${escapeHtml(c.score)}）</div>${collectHtml(c.collect)}</div>`).join("")
        : "");
    const hint = (r.next_actions && r.next_actions[0]) || "";
    const showHint = !enter && hint && hint !== d.reason;
    el.innerHTML = `
      <div class="k">分流结果</div>
      <div class="v">${escapeHtml(r.module_name || r.module_id)}
        <span class="conf-${escapeHtml(r.confidence)}"> · ${escapeHtml(r.confidence)}</span>
      </div>
      <div class="k">决策依据</div>
      <div class="v">${escapeHtml(decisionLabel(d.rule))}${d.ai_used ? " · 已用 AI" : ""}${d.overridden_pre ? " · 已覆盖预分流" : ""}</div>
      <p class="meta">${escapeHtml(d.reason || "")}</p>
      <div class="k">证据</div>
      <div class="v">${escapeHtml((r.evidence || []).join(", ") || "无")}</div>
      ${scoresHtml(r.scores)}
      ${showHint ? `<p class="meta">${escapeHtml(hint)}</p>` : ""}
      ${foreignHtml(r.foreign_hits)}
      ${candHtml}
      ${reassignHtml(r.reassign_buttons || [], r.registered_modules || [])}
    `;
    bindReassign(el);
    bindCopyRegex(el);
    setStage2Collect(r.collect);
    await persist({
      module_id: enter ? r.module_id : (r.out_of_scope ? "out_of_scope" : ""),
      module_name: r.module_name || "",
      status: "routed",
      confidence: r.confidence,
      route_evidence: r.evidence || [],
      route_rule: d.rule || "",
      route_reason: d.reason || ""
    });
    if (enter) goStage(2);
  } catch (e) {
    $("routeOut").classList.remove("hidden");
    $("routeOut").innerHTML = `<p class="err">${escapeHtml(e.message)}</p>`;
  } finally {
    stop();
    btn.disabled = false;
    btn.classList.remove("busy-btn");
    btn.textContent = "开始分流";
  }
});

$("btnLocalize").addEventListener("click", async () => {
  if (!state.module_id) return;
  const btn = $("btnLocalize");
  const stop = startBusy("locOut", "正在定位", [
    "对照本模块场景关键日志",
    "映射命中场景",
    "在调用链上标异常点"
  ]);
  btn.disabled = true;
  btn.classList.add("busy-btn");
  btn.textContent = "定位中…";
  try {
    const r = await api("/api/localize", { module_id: state.module_id, logs: $("logs").value });
    const el = $("locOut");
    el.classList.remove("hidden");
    const pt = r.callchain_exception_point;
    const sc = r.exception_scenario;
    const hits = (r.matched_logs || []).slice(0, 20).map((h) =>
      `${h.line_no}  [${h.log_id}] ${h.layer_id} ${h.function || ""}${h.meaning ? "  · " + h.meaning : ""}\n    ${h.line}`
    ).join("\n");
    el.innerHTML = `
      <div class="k">场景</div>
      <div class="v">${sc ? `${escapeHtml(sc.title)} · ${escapeHtml(sc.id)}` : "未映射到场景"}</div>
      <p>${escapeHtml(r.hypothesis || "")}</p>
      ${sc && sc.locate ? `<p class="meta">${escapeHtml(sc.locate)}</p>` : ""}
      ${chainHtml(r.scenario_callchain)}
      <div class="point">
        <div class="k">调用链异常点</div>
        <div class="v">${pt ? `${escapeHtml(pt.layer_id)} / ${(pt.functions || []).map(escapeHtml).join(", ") || "—"}` : "无"}</div>
        ${pt && pt.logs && pt.logs.length ? `<pre>${escapeHtml(pt.logs.map((l) => (l.meaning ? l.meaning + "\n" : "") + l.log_id + "  " + l.line).join("\n")).trim()}</pre>` : ""}
      </div>
      <div class="k">命中的关键日志</div>
      <pre>${escapeHtml(hits || "场景关键日志 0 命中")}</pre>
      ${foreignHtml(r.foreign_hits)}
      ${reassignHtml(r.reassign_buttons || [], [])}
    `;
    bindReassign(el);
    const mods = await refreshModules();
    const name = (mods.find((m) => m.module_id === state.module_id) || {}).name;
    await persist({
      status: "localized",
      module_id: state.module_id,
      module_name: name || "",
      confidence: r.confidence,
      scenario_id: sc && sc.id,
      scenario_title: sc && sc.title,
      exception_layer: pt && pt.layer_id,
      exception_functions: pt && pt.functions,
      hypothesis: r.hypothesis
    });
  } catch (e) {
    $("locOut").classList.remove("hidden");
    $("locOut").innerHTML = `<p class="err">${escapeHtml(e.message)}</p>`;
  } finally {
    stop();
    btn.disabled = !state.module_id || state.module_id === "unknown" || state.module_id === "out_of_scope";
    btn.classList.remove("busy-btn");
    btn.textContent = "开始定位";
  }
});

["q", "fModule", "fStatus", "fSort"].forEach((id) => {
  $(id).addEventListener("input", () => { if (state.view === "list") loadList(); });
  $(id).addEventListener("change", () => { if (state.view === "list") loadList(); });
});
$("btnExportXls").addEventListener("click", () => { window.location = exportUrl("xlsx"); });
$("btnExportJson").addEventListener("click", () => { window.location = exportUrl("json"); });

refreshModules().catch(() => renderDropdown([]));
goStage(1);
