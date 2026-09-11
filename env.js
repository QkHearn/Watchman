"use strict";

const fs = require("fs");
const path = require("path");

const ENV_FILE = path.join(__dirname, ".env");
let loaded = false;

function stripQuotes(v) {
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    return v.slice(1, -1);
  }
  return v;
}

function load() {
  if (loaded) return;
  loaded = true;
  if (!fs.existsSync(ENV_FILE)) return;
  const lines = fs.readFileSync(ENV_FILE, "utf8").split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) continue;
    const key = line.slice(0, i).trim();
    if (!key || process.env[key] != null) continue;
    process.env[key] = stripQuotes(line.slice(i + 1).trim());
  }
}

function truthy(v) {
  const s = String(v || "").trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

function parseModels(s) {
  return String(s || "").split(",").map((part) => {
    const t = part.trim();
    if (!t) return null;
    const i = t.indexOf(":");
    if (i < 0) return { id: t, name: t };
    return { id: t.slice(0, i).trim(), name: t.slice(i + 1).trim() || t.slice(0, i).trim() };
  }).filter(Boolean);
}

function llm() {
  load();
  const models = parseModels(process.env.LLM_MODELS);
  const model = String(process.env.LLM_MODEL || process.env.WATCHMAN_AI_MODEL || process.env.ARK_MODEL || "").trim();
  const polishModel = String(process.env.LLM_POLISH_MODEL || "").trim() || model;
  const allow = models.length ? new Set(models.map((m) => m.id)) : null;
  const modelAllowed = !allow || (model && allow.has(model));
  const key = String(process.env.LLM_API_KEY || process.env.WATCHMAN_AI_KEY || process.env.ARK_API_KEY || "").trim();
  const base = String(
    process.env.LLM_BASE_URL ||
    process.env.WATCHMAN_AI_BASE ||
    process.env.ARK_BASE_URL ||
    "https://api.openai.com/v1"
  ).replace(/\/$/, "");
  const rawEnabled = process.env.LLM_ENABLED;
  let enabled;
  if (rawEnabled == null || String(rawEnabled).trim() === "") {
    enabled = Boolean(key) && process.env.WATCHMAN_AI !== "0" && process.env.WATCHMAN_AI !== "false";
  } else {
    enabled = truthy(rawEnabled);
  }
  const maxTok = process.env.LLM_MAX_TOKENS || process.env.WATCHMAN_AI_MAX_TOKENS;
  return {
    enabled,
    baseUrl: base,
    apiKey: key,
    model,
    polishModel,
    models,
    modelAllowed,
    timeoutMs: Number(process.env.LLM_TIMEOUT_MS || process.env.WATCHMAN_AI_TIMEOUT_MS || 60000),
    temperature: Number(process.env.LLM_TEMPERATURE || 0.7),
    maxTokens: maxTok ? Number(maxTok) : undefined
  };
}

function email() {
  load();
  return {
    enabled: truthy(process.env.EMAIL_ENABLED),
    host: process.env.SMTP_HOST || "smtp.163.com",
    port: Number(process.env.SMTP_PORT || 465),
    user: process.env.SMTP_USER || "",
    pass: process.env.SMTP_PASS || "",
    from: process.env.EMAIL_FROM || process.env.SMTP_USER || ""
  };
}

module.exports = { load, llm, email };
