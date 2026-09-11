"use strict";

require("./env").load();

const http = require("http");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");
const engine = require("./engine");
const problems = require("./problems");

const PORT = Number(process.env.WATCHMAN_PORT || 3847);
const PUBLIC = path.join(__dirname, "public");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".svg": "image/svg+xml"
};

function send(res, code, body, type) {
  const data = typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body, null, 2);
  res.writeHead(code, {
    "Content-Type": type || "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function qs(req) {
  try {
    return Object.fromEntries(new URL(req.url, "http://127.0.0.1").searchParams);
  } catch {
    return {};
  }
}

function serveStatic(req, res) {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (urlPath === "/") urlPath = "/index.html";
  const file = path.normalize(path.join(PUBLIC, urlPath));
  if (!file.startsWith(PUBLIC)) return send(res, 403, { error: "forbidden" });
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return send(res, 404, { error: "not found" });
  const ext = path.extname(file);
  const data = fs.readFileSync(file);
  res.writeHead(200, {
    "Content-Type": MIME[ext] || "application/octet-stream",
    "Cache-Control": "no-store"
  });
  res.end(data);
}

const server = http.createServer(async (req, res) => {
  try {
    const u = (req.url || "").split("?")[0];
    const q = qs(req);

    if (req.method === "GET" && u === "/api/modules") return send(res, 200, { modules: engine.listModules() });
    if (req.method === "GET" && u === "/api/modules/template") {
      const file = engine.templatePath();
      if (!fs.existsSync(file)) return send(res, 404, { error: "template missing" });
      res.writeHead(200, {
        "Content-Type": "text/yaml; charset=utf-8",
        "Content-Disposition": 'attachment; filename="module-template.yaml"',
        "Cache-Control": "no-store"
      });
      return res.end(fs.readFileSync(file));
    }
    if (req.method === "POST" && u === "/api/modules") {
      const b = await readBody(req);
      try {
        return send(res, 200, engine.installModuleYaml(b.yaml, Boolean(b.overwrite)));
      } catch (e) {
        if (e.code === "EXISTS") return send(res, 409, { error: e.message, code: "EXISTS" });
        throw e;
      }
    }
    if (req.method === "GET" && u === "/api/apis") {
      return send(res, 200, { apis: engine.listApis(q.module) });
    }
    if (req.method === "GET" && /^\/api\/module\/[^/]+$/.test(u)) {
      const id = decodeURIComponent(u.slice("/api/module/".length));
      return send(res, 200, engine.pick(id));
    }
    if (req.method === "POST" && u === "/api/route") {
      const b = await readBody(req);
      return send(res, 200, await engine.route(b));
    }
    if (req.method === "POST" && u === "/api/localize") {
      const b = await readBody(req);
      if (!b.module_id) return send(res, 400, { error: "module_id required" });
      if (!b.logs) return send(res, 400, { error: "logs required" });
      return send(res, 200, engine.localize(b.module_id, b.logs));
    }
    if (req.method === "POST" && u === "/api/reassign") {
      const b = await readBody(req);
      return send(res, 200, engine.reassign(b));
    }
    if (req.method === "GET" && u.startsWith("/api/validate/")) {
      const id = u.slice("/api/validate/".length);
      return send(res, 200, engine.validate(id));
    }

    if (req.method === "GET" && u === "/api/problems/export.xlsx") {
      const items = problems.list(q);
      res.writeHead(200, {
        "Content-Type": "application/vnd.ms-excel; charset=utf-8",
        "Content-Disposition": 'attachment; filename="watchman-problems.xls"',
        "Cache-Control": "no-store"
      });
      return res.end("\uFEFF" + problems.toExcel(items));
    }
    if (req.method === "GET" && u === "/api/problems/export.json") {
      const items = problems.list(q);
      res.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Disposition": 'attachment; filename="watchman-problems.json"',
        "Cache-Control": "no-store"
      });
      return res.end(JSON.stringify(items, null, 2));
    }
    if (req.method === "GET" && u === "/api/problems") {
      const items = problems.list(q);
      return send(res, 200, { problems: items, total: items.length });
    }
    if (req.method === "GET" && u.startsWith("/api/problems/")) {
      return send(res, 200, problems.get(u.slice("/api/problems/".length)));
    }
    if (req.method === "POST" && u === "/api/problems") {
      const b = await readBody(req);
      return send(res, 200, problems.save(b));
    }
    if (req.method === "PUT" && u.startsWith("/api/problems/")) {
      const b = await readBody(req);
      b.id = u.slice("/api/problems/".length);
      return send(res, 200, problems.save(b));
    }

    if (req.method === "GET") return serveStatic(req, res);
    send(res, 404, { error: "not found" });
  } catch (e) {
    send(res, 400, { error: e.message || String(e) });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log("Watchman  http://127.0.0.1:" + PORT);
  console.log("插件目录  " + path.join(__dirname, "modules"));
});
