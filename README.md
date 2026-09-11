# Watchman

YAML 插件式问题分流 / 定位。引擎每次请求扫描 `modules/<id>/module.yaml`（跳过 `_template`、`enabled: false`），新模块放进目录即可出现在预分流下拉，不必改配置、也不必重启。

```bash
cd Watchman && npm install && npm start
```

浏览器打开 http://127.0.0.1:3847

问题列表可搜索、筛选，导出 JSON / Excel。错误码可选。

---

## 总约定

1. **两阶段**：先分流到模块，再在该模块内回放原子时间线。分流错了不自动纠正，用「改到：xxx」人工改派。
2. **正则只来自 YAML**，引擎不自编。阶段二只给用户 **一条** `collect.regex`，复制到 BetaClub 搜集后把命中行完整贴回。
3. **给人看的字段一律简体中文**（`title` / `meaning` / `do` / `locate` / `when` / `kind` / `description` / `role`）。英文只留：API 符号、路径、日志原文与正则、错误码、稳定 ID、tag。
4. **阶段二单位是原子**（一次对外操作：创建 / 启动 / 停止），不是「第二次 start 失败」这种故障故事。组合路径由日志时间线拼出来。

---

## 阶段一：分流

有日志才跑白/黑名单。没日志：**不扫正则**。

| 优先级 | 何时 | 做什么 |
| --- | --- | --- |
| 1 白名单 | 填了日志片段 | 「这是我的问题」。命中给本模块 ×100。只命中 1 个模块 → 立刻采用 |
| 2 黑名单 | 白名单认领不了 | 「这是别人的问题」。票投给 `to_module` ×80。已接入 → 分到对方；未接入 → `非窗口问题：{中文名}` |
| 3 预分流 | 白/黑都 0，且下拉选了具体模块 | 直接用该模块 |
| 4 「其他」 | 白/黑都 0，且选其他 | 按现象打分（可选 1 次模型） |

**白名单优先于黑名单。** 同分时仍是白名单赢。同一份 YAML 默认 `unless_whitelist: true`：本模块白名单已命中，则忽略**本模块**黑名单（例如既有本模块主 tag 又有邻居关键字，仍归本模块）。

白名单写几乎只有本模块才会打的 tag，避免多模块同时命中。黑名单必须带 `to_module` / `to_module_name`。

多模块匹配不调模型：先扫全部白名单（每模块通常 1～3 条），0 或 ≥2 命中再看黑名单计票。只有「没日志 + 其他」才可能调 **1 次** 模型（模块 >12 时先启发式预筛 Top 12）。日志命中或指定了预分流，与模块数量几乎无关。

「其他」打分：第一名 ≥40 且领先第二 ≥15 才采用；否则 `非窗口问题：{能识别的领域名}` 或 `非窗口问题：other`，不进阶段二。

---

## 阶段二：原子回放

每个原子三类日志，调用链只写这次调用真实经过的层（**不要预先标** `exception`）：

| | 进入 `enter` | 成功 `success` | 已知失败 `failures` |
| --- | --- | --- | --- |
| 含义 | 这次调用已经进框架 | 这次调用走完了 | 按设计失败 |
| 用来 | 发现「进了但没下文」 | 时间线上打 ✓ | 时间线上打 ✗，标红该失败所在层 |

判定：

- 按行顺序还原，例如：`创建✓ → 启动✓ → 停止✗`
- 命中已知失败 → 按设计失败（`kind` 只能是 **应用误用** / **依赖失败** / **框架缺陷**）
- 有进入、既无成功也无已知失败 → **未知，更像真 bug**
- 禁止在 YAML 里写组合故事；未登记的失败不要硬编，留给「未知」

`collect.regex` = 各原子 enter / success / failures 的并集，只此一条。

---

## 模块 YAML（schema 2.3）

模板：`modules/_template/module.yaml`（页头下载，或 `GET /api/modules/template`）。上传：`POST /api/modules`。

| # | 字段 | 作用 |
| --- | --- | --- |
| 1 | `log_whitelist` | 确认归本模块 |
| 2 | `log_blacklist` | 指向其他模块 |
| 3 | `apis.internal` | 对内，仅定位，不进前端 |
| 4 | `apis.external` | 对外，前端唯一可勾选 |
| 5 | `apis.dependencies` | 外部依赖，仅定位 |
| 6 | `atoms` | 原子（中文 `title`） |
| 7 | `atoms[].callchain` + `enter` / `success` / `failures` | 路径图 + 三类探针 |
| 8 | `collect.regex` | 复制到 BetaClub 的唯一正则 |

接口字段：`id` 给机器；`label` 给展示名（可省略，默认等于 `id`）；`role` 给中文职责（可省略，仅界面提示，不参与匹配）。

`meta.description` 用中文写清做什么 / 典型现象 / 不要分流，并参与「其他」现象匹配。

复制 `modules/_template/` 为 `modules/<id>/`，改 `module_id` 与 `enabled: true` 后刷新即可。

---

## 接入 AI（可选）

仅用于预分流「其他」且白/黑名单未命中。日志路径和指定预分流不调模型。

```bash
LLM_ENABLED=true
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=...
LLM_MODEL=deepseek-v4-flash
LLM_MODELS=deepseek-v4-flash:DeepSeek-V4-Flash,qwen3.8-flash:Qwen3.8-Flash
LLM_TIMEOUT_MS=60000
```

未开、Key 无效、超时或失败：回落启发式（名称 / 函数 / 描述词重叠），不阻断分流。仍兼容 `WATCHMAN_AI_*` / `ARK_*`；写了 `LLM_ENABLED` 以它为准。

邮件：`EMAIL_ENABLED=false` 时只写站内列表，当前版本不发信。

---

## 界面

- 预分流下拉 = 已扫描 YAML + 最后一项「其他（自动分流）」
- 故障接口随预分流模块的 `apis.external` 变化；选「其他」时不可选
- 非窗口问题停在阶段一，可人工改到已接入模块
