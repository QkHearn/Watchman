#!/usr/bin/env python3
"""Rewrite pip scenario callchains (per-scenario path) and add key_log meaning."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "modules/pip/module.yaml"
text = p.read_text()

CHAINS = {
    "SC-CREATE-PARAM": """    summary: create 时 pipOption 非法。命中 pipOption param error → 断在 NAPI，请求未进窗口控制器。
    callchain:
      - layer_id: L-JS
        name: 应用调用 create
        do: 组装 pipOption（context / 内容节点 / template / controlGroup）
        symbols: [PiPWindow.create]
      - layer_id: L-NAPI
        name: NAPI 参数校验
        do: JsPipWindowManager 校验 pipOption
        locate: 命中 pipOption param error 即停在本层，看后续短语定位原因（context / XComponent / template）
        symbols: [JsPipWindowManager]
        exception: true
""",
    "SC-CREATE-INTERNAL": """    summary: NAPI 已通过，创建主窗/pipOption 在 WM 客户端失败。命中 Main window is null 等 → 断在 PictureInPictureController。
    callchain:
      - layer_id: L-JS
        name: 应用调用 create
        symbols: [PiPWindow.create]
      - layer_id: L-NAPI
        name: NAPI 已放行
        do: 参数合法，转发到窗口侧
        symbols: [JsPipWindowManager]
      - layer_id: L-WM-CLIENT
        name: 创建 PiP 控制器/主窗
        locate: 命中 mainWindow is null / not shown / invalid pipOption → 断在本层
        symbols: [PictureInPictureController]
        exception: true
""",
    "SC-REPEAT-START": """    summary: 已在 STARTING/STARTED 时再次 startPiP。命中 pipWindow is starting / Repeated PiP → 断在控制器状态机。
    callchain:
      - layer_id: L-JS
        name: 再次 startPiP
        symbols: [PiPController.startPiP]
      - layer_id: L-NAPI
        name: NAPI 转发
        symbols: [JsPipController]
      - layer_id: L-WM-CLIENT
        name: 状态机拒绝重复 start
        locate: 看 pipWindow is starting 的 state 值，确认当前已在启动中
        symbols: [PictureInPictureController]
        exception: true
""",
    "SC-REPEAT-STOP": """    summary: STOPPING/STOPPED/RESTORING 时再次 stopPiP。命中 Repeat stop request → 断在控制器状态机。
    callchain:
      - layer_id: L-JS
        name: 再次 stopPiP
        symbols: [PiPController.stopPiP]
      - layer_id: L-NAPI
        name: NAPI 转发
        symbols: [JsPipController]
      - layer_id: L-WM-CLIENT
        name: 状态机拒绝重复 stop
        locate: Repeat stop request 带 curState，对照当前状态
        symbols: [PictureInPictureController]
        exception: true
""",
    "SC-TIMING": """    summary: 启停/还原过渡态交叉调用。命中 starting + Repeat stop / window nullptr when stop → 断在状态机时序。
    callchain:
      - layer_id: L-JS
        name: 交叉调用 start/stop
        symbols: [PiPController.startPiP, PiPController.stopPiP]
      - layer_id: L-NAPI
        name: NAPI 转发
        symbols: [JsPipController]
      - layer_id: L-WM-CLIENT
        name: 过渡态被打断
        locate: 同时出现 starting 与 Repeat stop / stop 时 window nullptr，按时间线看谁先谁后
        symbols: [PictureInPictureController]
        exception: true
""",
    "SC-UPDATE-SIZE": """    summary: PiP 未激活时 UpdateContentSize。命中 UpdateContentSize is disabled when state → 断在控制器。
    callchain:
      - layer_id: L-JS
        name: 改内容尺寸
        symbols: [PiPController.startPiP]
      - layer_id: L-WM-CLIENT
        name: 非激活态拒绝改尺寸
        locate: 日志中的 state 数字即当前 PiPWindowState
        symbols: [PictureInPictureController]
        exception: true
""",
    "SC-RESTORE-NAV": """    summary: stop/还原时拿不到 Navigation。命中 Get navController error / Navigation operate failed → 断在还原原页（依赖 ArkUI Navigation）。
    callchain:
      - layer_id: L-JS
        name: stopPiP / 还原
        symbols: [PiPController.stopPiP]
      - layer_id: L-WM-CLIENT
        name: 发起还原原页
        do: PictureInPictureController 取 navController 并 operate
        symbols: [PictureInPictureController]
      - layer_id: L-NAV
        name: Navigation 依赖
        locate: navController 失败则本层为异常点，单子打 ArkUI-Navigation；WMS-PiP 为 involved
        symbols: [navController]
        exception: true
""",
    "SC-BLACK-SCREEN": """    summary: start 路径绑定内容节点失败。命中 setXController / xComponent not set / typeNode / surface → 断在内容节点（可 CROSS ArkUI）。
    callchain:
      - layer_id: L-JS
        name: startPiP
        symbols: [PiPController.startPiP]
      - layer_id: L-WM-CLIENT
        name: 绑定内容节点
        do: setXController / surface / typeNode
        symbols: [PictureInPictureController]
      - layer_id: L-ARKUI
        name: XComponent / typeNode
        locate: 这批日志出现在 start 过程中；若 start 已成功只是画面黑，优先 ArkUI
        symbols: [XComponentController, typeNode]
        exception: true
""",
    "SC-FW-CONTROLLER": """    summary: 框架拿不到/写不了 PiP controller。命中 Failed to get pictureInPictureController / controller is nullptr → 断在 WM 客户端。
    callchain:
      - layer_id: L-JS
        name: start/stop 或控件事件
        symbols: [PiPController.startPiP, PiPController.stopPiP]
      - layer_id: L-NAPI
        name: NAPI 转发
        symbols: [JsPipController]
      - layer_id: L-WM-CLIENT
        name: 获取/持有 controller
        locate: Failed to get pictureInPictureController 或 controller is nullptr 即停在本层
        symbols: [PictureInPictureManager, PictureInPictureController]
        exception: true
""",
    "SC-INVALID-SCREEN": """    summary: 多屏 screenId 非法。命中 invalid screenId → 断在 Session/PipController。
    callchain:
      - layer_id: L-JS
        name: 带 screen 的 PiP 操作
        symbols: [PiPController.startPiP]
      - layer_id: L-WM-CLIENT
        name: 控制器
        symbols: [PictureInPictureController]
      - layer_id: L-SESSION
        name: 多屏策略
        locate: invalid screenId 即停在 PipController / SceneSession
        symbols: [PipController]
        exception: true
""",
    "SC-START-FAIL": """    summary: startPiP 失败（埋点原因或非法状态）。命中 OPERATION_ERROR_REASON 看失败原因；PiPWindowState STOPPING/STOPPED 说明在停/已停时还 start。
    callchain:
      - layer_id: L-JS
        name: startPiP
        symbols: [PiPController.startPiP]
      - layer_id: L-NAPI
        name: NAPI 转发
        symbols: [JsPipController]
      - layer_id: L-WM-CLIENT
        name: 启动状态机
        locate: 先看是否有 OPERATION_ERROR_REASON；再看 PiPWindowState 是否 STOPPING/STOPPED
        symbols: [PictureInPictureController]
        exception: true
      - layer_id: L-OBS
        name: HiSysEvent 埋点
        do: PiPReporter 上报 START_PIP / OPERATION_ERROR_REASON，辅助定因不是断点本身
        symbols: [PiPReporter]
""",
}

MEANING = {
    "LOG-PARAM": "NAPI 校验失败，create 未进窗口控制器",
    "LOG-CTX-NULL": "没传 Ability context，断在 NAPI",
    "LOG-XCC-NULL": "没传 XComponentController，断在 NAPI",
    "LOG-CG-MISMATCH": "controlGroup 与模板不匹配，断在 NAPI",
    "LOG-TPL-MISSING": "pipTemplateType 不存在，断在 NAPI",
    "LOG-TPL-UNSUPPORTED": "当前设备/应用不支持该模板，断在 NAPI",
    "LOG-TPL-SYSTEM": "该模板仅系统应用可用，断在 NAPI",
    "LOG-CG-CONFLICT": "controlGroups 内部冲突，断在 NAPI",
    "LOG-INVALID-SIZE-TYPE": "defaultWindowSizeType 非法，断在 NAPI",
    "LOG-MAIN-WIN-NULL": "主窗指针空，断在 PictureInPictureController 创建",
    "LOG-MAIN-WIN-NOT-SHOWN": "主窗未 show，create 失败，断在控制器",
    "LOG-CREATE-INVALID-OPTION": "控制器侧 pipOption 仍非法，断在创建",
    "LOG-STARTING": "窗口已在启动中，重复 start，断在状态机",
    "LOG-PIP-STARTING-ALT": "同上，Pip window is starting 文案变体",
    "LOG-REPEAT-OP": "重复 PiP 操作被拒，断在状态机",
    "LOG-REPEAT-STOP": "重复 stop，日志 curState 即当前状态",
    "LOG-STOP-WIN-NULL": "stop 时 window 已空，时序/生命周期问题",
    "LOG-STOP-CLIENT-NULL": "客户端 stop 时 window 为空",
    "LOG-DELETE-BEFORE-STOP": "未 stop 就 delete，断在销毁时序",
    "LOG-STATE-STOPPING": "当前已是 STOPPING/STOPPED，不能再按「启动中」处理",
    "LOG-UPDATE-SIZE": "当前 state 不允许 UpdateContentSize，看 state 数字",
    "LOG-NAV-GET": "取 navController 失败，还原原页断在 Navigation 依赖",
    "LOG-NAV-OPERATE": "Navigation operate 失败，还原原页失败",
    "LOG-NAV-TOP": "栈顶不是 navDestination，还原目标不对",
    "LOG-NAV-NULL": "navController 指针空，应用未配 Navigation",
    "LOG-XCC-SET": "setXController 失败，内容节点绑定断开",
    "LOG-XCOMP-NOT-SET": "主窗未设置 xComponent，画面无法呈现",
    "LOG-SURFACE": "参数转 surface 失败，内容节点/图形侧",
    "LOG-TYPENODE": "typeNode 非法，内容节点错误",
    "LOG-GET-CTRL": "拿不到 pictureInPictureController，断在 WM 客户端",
    "LOG-CTRL-NULL": "controller 为空，后续启停都会失败",
    "LOG-ACTION-MISSING": "控件 actionEvent 未注册，埋点/控件路径",
    "LOG-HISYS-WRITE-FAIL": "HiSysEvent 写入失败，辅助信息，一般不是根因",
    "LOG-SCREEN": "screenId 非法，断在多屏 Session/PipController",
    "LOG-HISYS-REASON": "START_PIP 失败原因码，配合同段 WMS_PIP 日志看断在哪一层",
}

import re

# Replace callchain blocks per scenario (from summary: through key_logs:)
for sid, block in CHAINS.items():
    pat = re.compile(
        rf"(  - id: {sid}\n(?:    title: .*\n)?(?:    boundary: .*\n)?(?:    priority: .*\n)?)(?:    summary: .*\n    callchain:\n(?:(?:      .*\n)|(?:        .*\n))+)(    key_logs:\n)",
        re.M,
    )
    m = pat.search(text)
    if not m:
        raise SystemExit(f"no match for {sid}")
    text = text[: m.start()] + m.group(1) + block + m.group(2) + text[m.end() :]

# Insert meaning after function: line of each log id, once
for lid, meaning in MEANING.items():
    # skip if already has meaning in that log block
    pat = re.compile(rf"(      - id: {lid}\n(?:        .*\n)+?)")

    def inject(m, meaning=meaning, lid=lid):
        block = m.group(1)
        if "meaning:" in block:
            return block
        if "function:" in block:
            return re.sub(
                r"(        function: .*\n)",
                r"\1        meaning: " + meaning + "\n",
                block,
                count=1,
            )
        return block.replace(
            f"      - id: {lid}\n",
            f"      - id: {lid}\n        meaning: {meaning}\n",
            1,
        )

    ntext, n = pat.subn(inject, text)
    if n == 0:
        print("WARN no log", lid)
    text = ntext

p.write_text(text)
print("updated", p, "len", len(text.splitlines()))
