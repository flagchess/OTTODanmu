# -*- coding: UTF-8 -*-
"""pywebview 后端探针：直接用真后端 + 桩回调，跑起来看界面。

python tools/ui-probe-webview.py
"""

import os
import sys
import threading
import time
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from hzys import gui


def noop(*args, **kwargs):
    print("[桩] 收到回调:", args)


def runScript(window, script, timeout=20, what="脚本"):
    """等界面就绪后再求值：窗口刚起来时网页还没渲染完，直接问会拿到 null。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            result = window._window.evaluate_js(script)
            if result not in (None, "null", ""):
                return result
        except Exception as exc:
            last = exc
        time.sleep(0.4)
    raise RuntimeError("{} 超时{}".format(what, "：" + str(last) if last else ""))


def selfCheck(window):
    """起来几秒后，直接问 JS：界面到底渲染成什么样了。"""
    bringToFront(window)
    script = """JSON.stringify({
        windowTitle: document.title,
        segs: Array.from(document.querySelectorAll('.seg')).map(s => s.textContent),
        cards: document.querySelectorAll('.card').length,
        switches: document.querySelectorAll('.switch').length,
        sliders: document.querySelectorAll('input[type=range]').length,
        activePage: (document.querySelector('.page.active') || {}).id,
        primary: document.getElementById('primaryButton').textContent,
        secondary: document.getElementById('secondaryButton').textContent,
    })"""
    try:
        print("界面自检:", runScript(window, script, what="界面自检"), flush=True)
    except Exception as exc:
        print("界面自检失败:", exc, flush=True)

    time.sleep(1)
    try:
        # 切到直播页：按钮文案应该跟着变
        window.selectPage("live")
        time.sleep(0.5)
        print(
            "切到直播页:",
            runScript(
                window,
                "JSON.stringify({page:(document.querySelector('.page.active')||{}).id,"
                "primary:document.getElementById('primaryButton').textContent,"
                "secondary:document.getElementById('secondaryButton').textContent})",
                what="直播页",
            ),
            flush=True,
        )

        # 切到高级设置页：应该能看到 5 条路径、2 个输入框，按钮变成 保存/恢复默认
        window.selectPage("settings")
        time.sleep(0.5)
        print(
            "切到设置页:",
            runScript(
                window,
                "JSON.stringify({page:(document.querySelector('.page.active')||{}).id,"
                "paths:document.querySelectorAll('.pathRow').length,"
                "entries:document.querySelectorAll('input[type=text]').length,"
                "primary:document.getElementById('primaryButton').textContent,"
                "secondary:document.getElementById('secondaryButton').textContent})",
                what="设置页",
            ),
            flush=True,
        )

        # 输出与提示
        window.appendOutput("自检测试：一条弹幕\n")
        window.showInfo("提示", "自检测试的消息")
        time.sleep(0.5)
        print(
            "输出与提示:",
            runScript(
                window,
                "JSON.stringify({log:document.getElementById('log').value.trim(),"
                "toasts:document.querySelectorAll('.toast').length})",
                what="输出与提示",
            ),
            flush=True,
        )

        # 本地模式的输入：往输出框里打字，main.py 那边应该能读到
        window._window.evaluate_js(
            "(() => {const box = document.getElementById('log');"
            "box.value = '本地输入测试';"
            "box.dispatchEvent(new Event('input'));})()"
        )
        time.sleep(0.8)
        readBack = window.getInputText()
        print(
            "本地输入回传:",
            (
                "OK"
                if readBack.strip() == "本地输入测试"
                else "失败 -> {!r}".format(readBack)
            ),
            flush=True,
        )

        # 设置页的「新版效果」开关长什么样
        window.selectPage("settings")
        time.sleep(0.5)
        print(
            "设置页卡片:",
            runScript(
                window,
                "JSON.stringify({"
                "cards: Array.from(document.querySelectorAll('.card h3'))"
                ".map(h => h.textContent),"
                "switches: document.querySelectorAll('.switch').length,"
                "newLookOn: document.querySelector('[data-var=isNewLookOn]')"
                ".classList.contains('on')})",
                what="设置页卡片",
            ),
            flush=True,
        )

        # 加 --switch 才真的点掉它（点完窗口会关掉重启，就没法截图了）
        if "--switch" in sys.argv:
            window.setValue("isNewLookOn", False)
            print("点掉新版效果之后请求切换到的后端:", gui.pendingBackend, flush=True)
        else:
            print("（窗口保持打开，方便截图；要看切换效果加 --switch）", flush=True)
    except Exception as exc:
        print("交互自检失败:", exc, flush=True)


def bringToFront(window):
    """把窗口提到最前面（方便截图），顺便列出窗口里的原生子视图（macOS）。"""
    if sys.platform != "darwin":
        return
    try:
        import AppKit

        def scanOnce():
            found = []
            done = threading.Event()

            def run():
                try:
                    native = window._window.native
                    host = native.contentView()
                    native.makeKeyAndOrderFront_(None)
                    for view in host.subviews():
                        name = view.className()
                        found.append(name)  # 全打出来，方便看底板到底叫什么
                        if "Glass" in name or "VisualEffect" in name:
                            found.append("frame -> {}".format(view.frame()))
                            found.append(
                                "hitTest -> {}".format(
                                    view.hitTest_(AppKit.NSMakePoint(10, 10))
                                )
                            )
                finally:
                    done.set()

            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(run)
            done.wait(5)
            return found

        # 内容视图是等网页加载完才换上的，所以这里要给它一点时间
        deadline = time.time() + 12
        found = []
        while time.time() < deadline and not found:
            found = scanOnce()
            if not found:
                time.sleep(0.5)
        print("窗口里的原生视图:", found or "没找到", flush=True)
    except Exception as exc:
        print("提窗口失败（不影响自检）:", exc, flush=True)


if __name__ == "__main__":
    handlers = SimpleNamespace(
        onDirectPlay=lambda: noop("播放"),
        onExport=lambda: noop("导出"),
        onTrytologin=lambda: noop("重新登录"),
        onToggleLiveMode=None,  # 下面单独接，需要模拟 main.py 的回调
        onStartLive=lambda: noop("启动直播"),
        onStopLive=lambda: noop("停止直播"),
        onSettingsSaved=lambda: noop("重建音频引擎"),
    )
    window = gui.createWindow(handlers, backend="webview")
    window.layout()
    # 模拟 main.py：切换直播模式后回调界面
    handlers.onToggleLiveMode = lambda: window.setLiveMode(window.iflivemodeon.get())
    window.onToggleLiveMode = handlers.onToggleLiveMode
    threading.Thread(target=selfCheck, args=(window,), daemon=True).start()
    window.run()
