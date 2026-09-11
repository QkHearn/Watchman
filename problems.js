"use strict";

const fs = require("fs");
const path = require("path");

const DIR = path.join(__dirname, "memory", "problems");

function ensureDir() {
  fs.mkdirSync(DIR, { recursive: true });
}

function fileOf(id) {
  if (!/^P-[A-Za-z0-9-]+$/.test(id)) throw new Error("非法问题 id");
  return path.join(DIR, id + ".json");
}

function readAll() {
  ensureDir();
  const list = [];
  for (const name of fs.readdirSync(DIR)) {
    if (!name.endsWith(".json")) continue;
    try {
      list.push(JSON.parse(fs.readFileSync(path.join(DIR, name), "utf8")));
    } catch {
      /* skip broken */
    }
  }
  return list;
}

function nextId() {
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const prefix = "P-" + day + "-";
  let n = 1;
  for (const p of readAll()) {
    if (!p.id || !p.id.startsWith(prefix)) continue;
    const num = parseInt(p.id.slice(prefix.length), 10);
    if (num >= n) n = num + 1;
  }
  return prefix + String(n).padStart(3, "0");
}

function titleOf(p) {
  const t = String(p.text || p.title || "").trim().split(/\n/)[0];
  return t.slice(0, 80) || "未填写现象";
}

function normalize(p, id) {
  const now = new Date().toISOString();
  return {
    id: id || p.id,
    created_at: p.created_at || now,
    updated_at: now,
    title: titleOf(p),
    text: p.text || "",
    apis: Array.isArray(p.apis) ? p.apis : [],
    errors: Array.isArray(p.errors) ? p.errors : [],
    snippet: p.snippet || "",
    logs: p.logs || "",
    module_id: p.module_id || "",
    module_name: p.module_name || "",
    status: p.status || "draft",
    confidence: p.confidence || "",
    scenario_id: p.scenario_id || "",
    scenario_title: p.scenario_title || "",
    exception_layer: p.exception_layer || "",
    exception_functions: Array.isArray(p.exception_functions) ? p.exception_functions : [],
    hypothesis: p.hypothesis || "",
    route_evidence: Array.isArray(p.route_evidence) ? p.route_evidence : []
  };
}

function get(id) {
  const f = fileOf(id);
  if (!fs.existsSync(f)) throw new Error("问题不存在: " + id);
  return JSON.parse(fs.readFileSync(f, "utf8"));
}

function save(p) {
  ensureDir();
  const id = p.id || nextId();
  const prev = fs.existsSync(fileOf(id)) ? get(id) : { created_at: p.created_at };
  const rec = normalize({ ...prev, ...p, created_at: prev.created_at || p.created_at }, id);
  fs.writeFileSync(fileOf(id), JSON.stringify(rec, null, 2), "utf8");
  return rec;
}

function matches(p, q, moduleId, status) {
  if (moduleId && p.module_id !== moduleId) return false;
  if (status && p.status !== status) return false;
  if (!q) return true;
  const blob = [
    p.id, p.title, p.text, p.module_id, p.module_name, p.hypothesis,
    p.scenario_title, p.scenario_id, p.exception_layer,
    (p.apis || []).join(" "), (p.errors || []).join(" ")
  ].join(" ").toLowerCase();
  return blob.includes(String(q).toLowerCase());
}

function list(query) {
  const q = (query.q || "").trim();
  const moduleId = query.module || "";
  const status = query.status || "";
  const sort = query.sort === "time_asc" ? "time_asc" : "time_desc";
  const items = readAll().filter((p) => matches(p, q, moduleId, status));
  items.sort((a, b) => {
    const ta = a.updated_at || a.created_at || "";
    const tb = b.updated_at || b.created_at || "";
    return sort === "time_asc" ? ta.localeCompare(tb) : tb.localeCompare(ta);
  });
  return items;
}

function xmlEscape(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toExcel(items) {
  const cols = [
    ["id", "ID"],
    ["created_at", "创建时间"],
    ["updated_at", "更新时间"],
    ["title", "现象"],
    ["module_id", "模块ID"],
    ["module_name", "模块"],
    ["status", "状态"],
    ["errors", "错误码"],
    ["apis", "故障接口"],
    ["scenario_title", "场景"],
    ["exception_layer", "异常层"],
    ["hypothesis", "结论"]
  ];
  const header = cols.map(([, label]) =>
    `<Cell><Data ss:Type="String">${xmlEscape(label)}</Data></Cell>`
  ).join("");
  const rows = items.map((p) => {
    const row = {
      ...p,
      errors: (p.errors || []).join(";"),
      apis: (p.apis || []).join(";")
    };
    const cells = cols.map(([key]) =>
      `<Cell><Data ss:Type="String">${xmlEscape(row[key])}</Data></Cell>`
    ).join("");
    return `<Row>${cells}</Row>`;
  }).join("");
  return `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="problems">
<Table>
<Row>${header}</Row>
${rows}
</Table>
</Worksheet>
</Workbook>`;
}

module.exports = { list, get, save, toExcel, DIR };
