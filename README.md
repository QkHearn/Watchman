# Watchman

YAML 插件式问题分流 / 定位软件。引擎每次请求扫描 `modules/<id>/module.yaml`，新模块放进目录就会出现在预分流下拉框，不必改配置、也不必重启。

启动：

```bash
cd Watchman
npm install
npm start
```

浏览器打开 http://127.0.0.1:3847

---

## 两阶段用法

1. **阶段一分流**：填问题现象、可选日志片段与故障接口，选预分流模块（或「其他」），点「开始分流」。引擎按下方决策树判定模块。
2. **阶段二定位**：复制该模块 YAML 里的**一条** `collect.regex` 到 BetaClub 搜集日志，把完整命中行贴进去，对照场景调用链标异常点。
3. 分流错了不自动纠正，用「改到：xxx」人工改派并落盘。
4. 日志正则只来自 YAML，引擎不自编。

问题列表按时间排序，可搜索、按模块/状态筛选，导出 **JSON** 或 **Excel**（`.xls`）。错误码为可选字段。

---

## 分流决策（阶段一）

参与决策的信息与置信度，从高到低：

| 优先级 | 信息 | 何时用 |
| --- | --- | --- |
| 1 | 日志白名单 + 日志黑名单（都匹配） | **仅当填了日志片段**。扫全部已接入 YAML |
| 2 | 用户预分流 | 无日志，或日志白/黑名单都未命中，且下拉选了具体模块 |
| 3 | AI / 启发式对全部模块打分 | 无日志（或日志未命中），且预分流为「其他」 |

没填日志：**不走黑白名单**。有日志才同时匹配白名单和黑名单。

### 日志白名单 / 黑名单

两者都会跑，语义不同：

- **白名单** = **当前这份 YAML 的模块问题**。命中则给该 `module_id` 投票（每条 ×100）。
- **黑名单** = **其他模块的问题**，必须写 `to_module`（对方的 `module_id`）。命中则给 `to_module` 投票（每条 ×80）。对方已接入 → 分流到该模块；尚未接入 → `非窗口问题：{to_module_name}`。

同一模块 YAML 里 `unless_whitelist: true`（默认）：本模块白名单已命中时，忽略**本模块**黑名单（例如既有 `WMS_PIP` 又有 `createSubWindow`，仍算画中画）。其他模块的黑名单仍会匹配。

投票最高的已接入模块胜出；同分时白名单优于黑名单。可覆盖预分流。

画中画 YAML 已把黑名单指向 `subwindow` / `split` / `media`。这些目录还不存在时，命中黑名单会显示「非窗口问题：子窗/悬浮窗」等；以后放入对应 `module.yaml` 即自动改派过去。

### 没日志 +「其他」：按现象给每个模块打分

把问题现象和**每一个**已接入模块的名称、完整描述（含做什么/不做）、函数交给模型，输出 0～100 分。第一名 ≥40 且比第二名高至少 15 分才采用。否则：能判断对应领域（现象命中某 YAML 黑名单 `to_module_name`，或 AI 给出 `oos_name`）→ **`非窗口问题：{模块名}`**；无法判断 → **`非窗口问题：other`**。不进入阶段二。

`LLM_ENABLED=true` 时走 AI 打分；未开或失败则用启发式（名称 +50、函数 +18/+30、描述词 +20，阈值 18）。模块超过 12 个时，先启发式预筛 Top 12 再交给模型（仍只发 **1 次** 请求）。

没日志但预分流选了具体模块：仍直接用预分流，不打分。

### 模块很多时会不会慢？

不会线性变慢到不可用。YAML 扫描和白/黑名单正则都是本地、毫秒级。真正可能慢的只有「没日志 + 预分流选其他」这条路的 **一次** 模型请求：

| 路径 | 调模型？ | 和模块数量的关系 |
| --- | --- | --- |
| 填了日志且白/黑名单命中 | 否 | 扫全部 YAML 正则，很快 |
| 没日志，预分流选了具体模块 | 否 | 直接用该模块 |
| 没日志 +「其他」 | **1 次** | catalog 变大时描述会截断；超过 12 个模块先启发式预筛 Top 12 |

所以接入几十个模块时，日志分流和指定预分流几乎无感；只有「其他」自动分流会等那一次模型返回。

---

## 接入 AI（可选）

仅用于预分流「其他」且日志白/黑名单未命中：对候选模块打 0～100 分（模块很多时先启发式预筛 Top 12）。规则 1–2（日志）和预分流不调用模型。

OpenAI 兼容 `/v1/chat/completions`（火山 AI 网关等同理）：

```bash
LLM_ENABLED=true
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=...
LLM_MODEL=deepseek-v4-flash
# 非空时，LLM_MODEL 必须是其中某个 id
LLM_MODELS=deepseek-v4-flash:DeepSeek-V4-Flash,qwen3.8-flash:Qwen3.8-Flash
LLM_TIMEOUT_MS=60000
# LLM_MAX_TOKENS=2048
```

- `LLM_ENABLED=false`（默认）：不调模型，用启发式打分。
- 第一名须 ≥40 分且领先第二名 ≥15 分，否则归为非窗口问题（能识别领域则带模块名，否则 `other`）。
- `LLM_MODELS` 非空且 `LLM_MODEL` 不在列表内：同样回落启发式。
- 分流请求固定 `temperature=0.1`（分类要稳）；`.env` 里的 `LLM_TEMPERATURE` / `LLM_POLISH_MODEL` 留给后续润色，当前分流不用。
- 无 Key、超时或接口失败：回落词重叠，不阻断分流。

仍兼容旧变量 `WATCHMAN_AI_KEY` / `ARK_API_KEY`、`WATCHMAN_AI_MODEL` / `ARK_MODEL`、`WATCHMAN_AI_BASE` / `ARK_BASE_URL`。若写了 `LLM_ENABLED`，以它为准。

## 邮件

`EMAIL_ENABLED=false` 时只写站内问题列表，不发信。163 SMTP 字段见 `.env.example`；当前版本尚未发邮件，打开开关也不会外发。

---

## 模块 YAML（schema 2.2）

别人给一份 `modules/<id>/module.yaml` 即可适配。八类关键信息：

1. `log_whitelist` — 命中即可确认归本模块
2. `log_blacklist` — 命中指向其他模块（`to_module` / `to_module_name`）；目标未接入则为「非窗口问题」
3. `apis.internal` — 对内接口，仅引擎/AI 定位用，不进前端
4. `apis.external` — 对外故障接口，前端唯一可勾选
5. `apis.dependencies` — 外部依赖，仅定位
6. `scenarios` — 场景
7. `scenarios[].callchain` + `key_logs` — 场景调用链与关键日志
8. `collect.regex` — **只给用户一条正则**，复制到 BetaClub 搜集日志（不要多条、不要自编 grep）

`meta.description` 给人看，也参与「其他」自动分流时的现象匹配。

### 调用链 × 关键日志（定位约定）

二者分工，不要写成两份重复的链：

| | 调用链 `scenarios[].callchain` | 关键日志 `scenarios[].key_logs` |
| --- | --- | --- |
| 是什么 | 该场景的**路径图**（应用 API → NAPI → 控制器 → 可选依赖） | 该场景的**探针**（BetaClub 捞回的日志里能钉死断点的那几句） |
| 怎么写 | 只写本场景真实经过的层和符号；**有且仅有一层** `exception: true` | 每条绑定 `layer_id` + `function`，必须落在调用链某一层；`exception: true` 用来钉死异常点 |
| 引擎怎么用 | 命中场景后原样画出，标红断开层 | 用正则扫用户从 BetaClub 贴来的日志 → 命中哪条就进哪个场景 |
| 给人看 | `do`（这层干什么）、`locate`（怎么从日志确认断在这） | `meaning`（命中 = 断在哪、什么原因） |

不要把整条链每一层的所有日志都堆进一个场景；只放能**区分场景、钉死异常点**的探针。

阶段二流程：BetaClub 一条正则捞日志 → 引擎只拿 `key_logs` 去匹配 → 选出场景 → 画出该场景调用链并标红 `exception` 层。

模板：页头「下载 YAML 模板」，或 `GET /api/modules/template`。  
上传：页头「上传模块 YAML」，或 `POST /api/modules`（已存在返回 409，可覆盖）。

复制 `modules/_template/` 为 `modules/<id>/`，改 `module_id` 与 `enabled: true` 后刷新页面即可。

---

## 加模块后的界面行为

- 预分流下拉 = 已扫描到的 YAML + 最后一项「其他（自动分流）」。
- 故障接口随所选预分流模块的 `apis.external` 变化；选「其他」时不可选接口。
- 非窗口问题 / 未能确定模块时停在阶段一，可人工改到已接入模块。
