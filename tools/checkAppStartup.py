# -*- coding: UTF-8 -*-
"""真程序启动体检：按 main.py 的流程把界面起起来，再看启动后的实际状态。

    python tools/checkAppStartup.py

主要防的是「程序自己的日志混进本地模式输入框」这类问题：界面顶部那个框
在本地模式下就是要播报的文字，程序日志混进去会被连着一起读出来。
所以这里显式检查启动后那个框是空的、占位提示还在。

需要在有图形界面的环境里跑；退出码 0 表示通过。
"""

import os
import sys
import threading
import time
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

import main as app  # noqa: E402
from hzys import gui  # noqa: E402

# 界面一起来 stdout 就被重定向到界面上了，体检结果必须直接写控制台
CONSOLE = sys.__stdout__
problems = []


def say(text):
    print(text, file=CONSOLE, flush=True)


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


def inspect():
    time.sleep(6)
    try:
        text = app.ui.getInputText()
        say("启动后输入框内容 = {!r}".format(text))
        check(text == "", "启动后输入框不干净，程序日志混进去了：{!r}".format(text))

        # 网页后端能额外查 DOM；原生后端只查后端自己的状态
        page = getattr(app.ui, "_window", None)
        if page is not None:
            onScreen = page.evaluate_js("document.getElementById('log').value")
            check(onScreen == "", "界面上框里的内容和后端记录的不一致")
            placeholder = page.evaluate_js("document.getElementById('log').placeholder")
            check(bool(placeholder), "输入框没有占位提示，用户看不出这里能打字")
    except Exception as exc:
        problems.append("体检抛异常: {}: {}".format(type(exc).__name__, exc))
    finally:
        try:
            # close() 三个后端都有；关掉窗口体检就结束了
            app.ui.close()
        except Exception:
            pass


def main():
    app.freeze_support()
    app.migrateConfigFile()
    app.HZYS = app.huoZiYinShua(app.SETTINGS_PATH)

    def noop(*args, **kwargs):
        pass

    app.ui = gui.createWindow(
        SimpleNamespace(
            onDirectPlay=noop,
            onExport=noop,
            onTrytologin=noop,
            onToggleLiveMode=noop,
            onStartLive=noop,
            onStopLive=noop,
            onSettingsSaved=noop,
        )
    )
    app.ui.layout()
    app.ui.redirectStdout()

    threading.Thread(target=inspect, daemon=True).start()
    app.ui.run()  # 体检结束会关掉窗口，这里就返回了

    if problems:
        say("发现 {} 个问题：".format(len(problems)))
        for item in problems:
            say("  - " + item)
        return 1
    say("全部通过：启动后输入框是空的，可以放心打字播放")
    return 0


if __name__ == "__main__":
    sys.exit(main())
