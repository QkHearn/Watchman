# Watchman

YAML 插件式问题分流 / 定位。引擎每次请求扫描 `modules/<id>/module.yaml`（跳过 `_template`、`enabled: false`），新模块放进目录即可，不必改配置。

日常跑编译好的单个程序：

```bash
cd Watchman
./dist/watchman-py
```

改了 Python 或模块 YAML 之后再打包一次：

```bash
.venv/bin/python python/build.py
```

源码调试：`.venv/bin/python python/cli.py`。只问问题现象。能对上已接入模块就给出正则并等日志；对不上时先对照 `memory/non-window/` 里的历史黑名单（极相似才引用），再用各模块黑名单里的领域名，最后才判「非窗口问题」，并把新现象记进历史。两个窗口模块分数接近时不记成非窗口。

---

## 总约定

1. **两阶段**：先分流到模块，再在该模块内回放原子时间线。
2. **正则只来自 YAML**，引擎不自编。阶段二只给用户 **一条** `collect.regex`，复制到 BetaClub 搜集后把命中行完整贴回。
3. **给人看的字段一律简体中文**（`title` / `meaning` / `do` / `locate` / `when` / `kind` / `description` / `role`）。英文只留：API 符号、路径、日志原文与正则、错误码、稳定 ID、tag。
4. **阶段二单位是原子**（一次对外操作：创建 / 启动 / 停止），不是「第二次 start 失败」这种故障故事。组合路径由日志时间线拼出来。

---

## 阶段一：分流

离线只收问题现象。现象里已经出现某个已接入模块的名称时，直接按模块说明打分。

| 顺序 | 何时 | 做什么 |
| --- | --- | --- |
| 1 历史黑名单 | 现象没点名已接入模块，且和 `memory/non-window/` 极相似 | `非窗口问题：{领域名}`，引用那条历史 |
| 2 模块黑名单 | 现象命中某条 `log_blacklist` 的领域名 | `to_module` 已接入则分到该责任模块；未接入则 `非窗口问题：{领域名}`，并记入历史 |
| 3 模块说明 | 以上都未命中 | 按名称、接口、描述打分（可选 1 次模型） |

黑名单必须带 `to_module` / `to_module_name`。确认是本模块靠现象与模块名称、接口、描述。

模块超过 12 个时，先启发式预筛 Top 12，再调 **1 次** 模型。第一名 ≥40 且领先第二 ≥15 才采用。两个窗口模块分数接近时判「窗口问题，模块未分开」，不进阶段二，也不记入非窗口历史。仍然对不上才是 `非窗口问题：{能识别的领域名}` 或 `非窗口问题：other`。

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

贴回日志后还要对照现象写成三类：用户行为（点击、滑动）、应用行为（调用了哪个接口）、系统行为（事件或接口之后框架做了什么）。`window_window_manager` 或 `scene_board_ext` 路径已配置且目录存在时，分析会带上源码里对得上的日志和符号；都没配置时只按 YAML。日志若命中黑名单，责任模块改记到 `to_module`。

---

## 模块 YAML（schema 2.3）

模板：`modules/_template/module.yaml`。

| # | 字段 | 作用 |
| --- | --- | --- |
| 1 | `log_blacklist` | 指向其他模块 |
| 2 | `apis.internal` | 对内，仅定位 |
| 3 | `apis.external` | 对外接口 |
| 4 | `apis.dependencies` | 外部依赖，仅定位 |
| 5 | `atoms` | 原子（中文 `title`） |
| 6 | `atoms[].callchain` + `enter` / `success` / `failures` | 路径图 + 三类探针 |
| 7 | `collect.regex` | 复制到 BetaClub 的唯一正则 |

接口字段：`id` 给机器；`label` 给展示名（可省略，默认等于 `id`）；`role` 给中文职责（可省略，不参与匹配）。

`meta.description` 用中文写清做什么 / 典型现象 / 不要分流，并参与现象匹配。

复制 `modules/_template/` 为 `modules/<id>/`，改 `module_id` 与 `enabled: true` 即可。引擎每次启动都会扫描目录。

---

## 接入 AI

分流命令在 `config/runner.yaml`。默认用其中的 `test`，本机是 `cursor-agent -p --mode ask --trust --output-format text`，提示词接在命令最后。`WATCHMAN_ENV=production` 时改用文件里的 `production`（当前是 `nga run`）。`WATCHMAN_RUN` 可以整条覆盖。全局提示词在 `config/agent.md`。命令找不到、超时或输出不是 JSON 时，回落名称/描述匹配，不阻断分流。超时用 `LLM_TIMEOUT_MS`（默认 120000）。
