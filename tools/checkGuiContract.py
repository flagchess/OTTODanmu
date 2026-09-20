# -*- coding: UTF-8 -*-
"""检查界面后端是否满足 main.py 需要的接口，并跑一遍状态切换冒烟测试。

用法（需要有图形环境，macOS 上要在普通终端里跑，不能在无窗口的沙箱里跑）：

    python tools/checkGuiContract.py

退出码 0 表示通过；任何一项不满足会打印出来并返回 1。
改界面接口时，记得同步改下面这几份清单和后端的实现。
"""

import os
import sys
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from hzys import gui  # noqa: E402

# main.py 用到的全部接口
VALUE_HOLDERS = [
    "inYsddMode",
    "normAudio",
    "reverseAudio",
    "pitchMultOption",
    "speedMultOption",
    "volumeMultOption",
    "iflivemodeon",
    "ischuanhuaon",
    "iskeywordspoton",
    "isgifton",
    "iswelcomeon",
]
METHODS = [
    "getInputText",
    "appendOutput",
    "callLater",
    "setLiveMode",
    "setBroadcastRunning",
    "setLoginBusy",
    "toggleTipWindow",
    "showInfo",
    "showWarning",
    "showLoginCode",
    "askSaveFileName",
    "askYesNo",
    "layout",
    "redirectStdout",
    "run",
]
CALLBACKS = [
    "onDirectPlay",
    "onExport",
    "onTrytologin",
    "onToggleLiveMode",
    "onStartLive",
    "onStopLive",
    "onSettingsSaved",
]

problems = []


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


def makeHandlers():
    def noop(*args, **kwargs):
        pass

    return SimpleNamespace(**{name: noop for name in CALLBACKS + ["onSettingsSaved"]})


def checkMembers(window, backend):
    for name in VALUE_HOLDERS:
        if check(hasattr(window, name), f"[{backend}] 缺少取值器 {name}"):
            check(
                hasattr(getattr(window, name), "get"),
                f"[{backend}] {name} 没有 .get() 方法",
            )
    for name in METHODS:
        check(
            callable(getattr(window, name, None)),
            f"[{backend}] 缺少方法 {name}()",
        )
    for name in CALLBACKS:
        check(
            callable(getattr(window, name, None)),
            f"[{backend}] 回调 {name} 没有挂上",
        )


def smokeTest(window, backend):
    """按一遍状态切换，确认不抛异常；Tk 特有的控件检查单独做。"""
    window.layout()

    # 这些是所有后端都必须能承受的调用
    window.setLiveMode(True)
    window.setLiveMode(False)
    window.setBroadcastRunning(True)
    window.setBroadcastRunning(False)
    window.setLoginBusy(True)
    window.setLoginBusy(False)

    window.istipWindowon.set(True)
    window.toggleTipWindow()
    window.istipWindowon.set(False)
    window.toggleTipWindow()

    window.appendOutput("契约测试写入\n")
    check(
        isinstance(window.getInputText(), str),
        f"[{backend}] getInputText() 应该返回字符串",
    )
    window.callLater(lambda: None)  # 只确认调用本身不报错

    if backend == "tk":
        # Tk 后端能直接查控件状态，顺带验证得更细一点
        check(
            window.textArea1.winfo_manager() != "",
            f"[{backend}] 输入框没有布局出来",
        )
        window.istipWindowon.set(True)
        window.toggleTipWindow()
        check(
            window.textArea is window.textArea2,
            f"[{backend}] 置顶输出框没有接管输出",
        )
        window.istipWindowon.set(False)
        window.toggleTipWindow()
        check(
            window.textArea is window.textArea1,
            f"[{backend}] 关闭置顶框后没切回主框",
        )

    # 收尾：能关就关（Tk 用 root，pywebview 用 close）
    try:
        window.close()
    except Exception:
        try:
            window.root.destroy()
        except Exception:
            pass


def main():
    backends = gui.availableBackends()
    print("本机可用的界面后端:", ", ".join(backends))

    for backend in backends:
        print(f"--- 检查后端 {backend} ---")
        try:
            window = gui.createWindow(makeHandlers(), backend=backend)
        except Exception as exc:
            problems.append(f"[{backend}] 创建窗口失败: {type(exc).__name__}: {exc}")
            continue
        checkMembers(window, backend)
        try:
            smokeTest(window, backend)
        except Exception as exc:
            problems.append(f"[{backend}] 冒烟测试抛异常: {type(exc).__name__}: {exc}")

    if problems:
        print("\n发现 {} 个问题：".format(len(problems)))
        for item in problems:
            print("  -", item)
        return 1

    print("\n全部通过：{} 个后端都满足接口契约".format(len(backends)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
