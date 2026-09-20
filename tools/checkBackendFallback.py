# -*- coding: UTF-8 -*-
"""界面后端的自检：平台配对、缺东西时的兜底、切换命令对不对。

    python tools/checkBackendFallback.py

三件事：
  1. 各平台默认后端的配对（Windows = 网页 / 经典，macOS = 经典 / 原生）
  2. 缺 WebView2 时自动换回经典界面；设置页那张「界面」卡片摆得对不对
  3. 点了切换之后，重启出来的命令行和环境变量要对

第 1 项会真的创建一个 Tk 窗口再关掉，需要有图形界面。
"""

import os
import sys
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from hzys import gui  # noqa: E402

problems = []
CONSOLE = sys.__stdout__


def say(text):
    print(text, file=CONSOLE, flush=True)


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


def makeHandlers():
    def noop(*args, **kwargs):
        pass

    return SimpleNamespace(
        onDirectPlay=noop,
        onExport=noop,
        onTrytologin=noop,
        onToggleLiveMode=noop,
        onStartLive=noop,
        onStopLive=noop,
        onSettingsSaved=noop,
    )


def testFallbackToTk():
    """没有 WebView2 时，要自动落到经典界面。"""
    original = gui.webview2Available
    gui.webview2Available = lambda: False
    try:
        window = gui.createWindow(makeHandlers(), backend="webview")
        name = type(window).__name__
        check(
            name == "MainWindow",
            "没有 WebView2 时应该用经典界面，实际是 {}".format(name),
        )
        # 「新版效果」开关会用到 canSwitchNow()，后端漏了属性会在这里炸出来
        check(
            window.canSwitchNow() is True,
            "空闲状态下 canSwitchNow() 不该返回 False",
        )
        try:
            window.close()
        except Exception:
            try:
                window.root.destroy()
            except Exception:
                pass
    finally:
        gui.webview2Available = original


def testNewLookAvailability():
    """平台配对：卡片摆不摆看 canOfferNewLook()，真能不能用看 newLookAvailable()。"""
    if sys.platform == "darwin":
        from hzys.gui import nativeapp

        # macOS 的新版界面是同 bundle 里的原生可执行文件
        check(
            gui.newLookAvailable() == nativeapp.nativeUiAvailable(),
            "macOS 上的新版判断和后端模块对不上",
        )
        check(
            gui.canOfferNewLook() == gui.newLookAvailable(),
            "macOS 上「摆不摆卡片」和「能不能切」应该一致",
        )
        check(gui.canGoBackToClassic(), "macOS 上原生界面应该能切回经典界面")
        check(gui.preferredBackend() == "tk", "macOS 上默认后端应该是 tk")
        return

    if sys.platform != "win32":
        check(not gui.canOfferNewLook(), "非 Windows / macOS 上不该出现「界面」卡片")
        return

    check(gui.canOfferNewLook(), "Windows 上应该有「界面」切换卡片")

    original = gui.webview2Available
    try:
        gui.webview2Available = lambda: True
        check(gui.newLookAvailable(), "有 WebView2 时新版界面却被判为不可用")
        gui.webview2Available = lambda: False
        check(not gui.newLookAvailable(), "没有 WebView2 时新版界面仍然被判为可用")
        # 没有 WebView2 时卡片照样摆（问一次要一秒多，不卡启动），
        # 点了之后由 toggleNewLook 用 newLookAvailable() 拦下来
        check(gui.canOfferNewLook(), "Windows 上卡片不该跟着 WebView2 一起消失")
    finally:
        gui.webview2Available = original


def testSettingsCards():
    """设置页那张「界面」卡片要跟着平台走，且和 layout 的结构一致。"""
    from hzys.gui import layout

    def settingsTitles(withSwitch):
        pages = layout.buildPages(withSwitch)
        return [card["title"] for card in pages[2]["cards"]]

    def sectionTitles(withSwitch):
        return [title for title, _ in layout.settingsSections(withSwitch)]

    check(
        settingsTitles(True) == sectionTitles(True),
        "设置页的结构和 settingsSections() 对不上",
    )
    check(
        settingsTitles(False) == sectionTitles(False),
        "不带「界面」卡片时结构和 settingsSections() 对不上",
    )

    # 卡片摆不摆看 canOfferNewLook()：真去问 WebView2 在 Windows 上要一秒多，
    # 那条路只在点「新版效果」的时候走
    canSwitch = gui.canOfferNewLook()
    expected = settingsTitles(canSwitch)
    if canSwitch:
        check("界面" in expected, "能切到新版界面，设置页却没有「界面」卡片")
    else:
        check("界面" not in expected, "切不到新版界面，设置页却摆出了「界面」卡片")


def testRestartCommand():
    """点切换之后，重启命令里的后端参数要对。"""
    originalExec = os.execve
    originalPending = gui.pendingBackend
    captured = {}

    def fakeExecve(path, args, env):
        captured["path"] = path
        captured["args"] = args
        captured["env"] = env
        raise SystemExit  # 模拟"当前进程被替换掉"

    os.execve = fakeExecve
    try:
        gui.pendingBackend = "tk"
        try:
            gui.restartIfPending()
        except SystemExit:
            pass
        check(captured, "点了切换却没有重启")
        check(
            captured.get("env", {}).get(gui.BACKEND_ENV) == "tk",
            "重启时没有把目标后端传给新进程",
        )
        check(captured.get("path") == sys.executable, "重启用的解释器路径不对")

        # 没点切换时不该重启
        gui.pendingBackend = None
        check(not gui.restartIfPending(), "没点切换也重启了")
    finally:
        os.execve = originalExec
        gui.pendingBackend = originalPending


def main():
    try:
        testFallbackToTk()
        testNewLookAvailability()
        testSettingsCards()
        testRestartCommand()
    except Exception as exc:
        import traceback

        traceback.print_exc(file=CONSOLE)
        problems.append("自检抛异常: {}: {}".format(type(exc).__name__, exc))

    if problems:
        say("发现 {} 个问题：".format(len(problems)))
        for item in problems:
            say("  - " + item)
        return 1
    say("全部通过：缺 WebView2 会自动用经典界面，切换命令也正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
