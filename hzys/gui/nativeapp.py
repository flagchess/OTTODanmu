# -*- coding: UTF-8 -*-
"""macOS：经典界面和原生界面在同一个 .app 里互相切换。

一个 .app 里装着两套界面（.app 本身的名字带版本号，见 tools/build-mac-app.sh）：

    电棍棍活字.app/Contents/
        MacOS/电棍棍活字       经典界面（tk），同时也是 --engine 引擎
        MacOS/hzys-native      原生界面（SwiftUI）

两个可执行文件在同一个 bundle 里，所以不管当前跑的是哪一套，App 的身份、
Dock 图标、菜单栏名字都是同一个——不会冒出第二个 app。

切换用的是 execv：把当前进程整个换成另一个可执行文件。这样：
    * 不会有一瞬间"两个 app 都开着"（音频设备、settings.json 也不会打架）
    * 不用先退出再等新进程起来，窗口切换是接着发生的
    * 进程号不变，Dock 上看不出换过

原生界面那边要回到经典界面时，是 Swift 侧自己 execv 回 Contents/MacOS 里的
主程序（那边知道引擎是怎么起的），所以这里只负责"经典 → 原生"这个方向。

找原生界面可执行文件的顺序：
    1. 环境变量 HZYS_NATIVE_APP 指定的路径
    2. 和当前可执行文件同一个目录（打包好的 .app 里就是这样）
    3. 源码运行：<项目>/mac/.build/release/HZYS（cd mac && swift build -c release）
"""

import os
import platform
import re
import sys

NATIVE_BINARY = "hzys-native"  # .app 里那个原生界面可执行文件
DEV_BUILD = os.path.join("mac", ".build", "release", "HZYS")  # 源码运行时的产物

ENV_NATIVE = "HZYS_NATIVE_APP"  # 手动指定原生界面可执行文件的路径

# 原生界面用的 SwiftUI 材质要求 macOS 26 起
NATIVE_MIN_MACOS = 26


def projectRoot():
    """源码运行时的项目根目录；打包（frozen）之后没有源码，返回 None。"""
    if getattr(sys, "frozen", False):
        return None
    here = os.path.abspath(__file__)  # <项目>/hzys/gui/nativeapp.py
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _isExecutable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def nativeBinary():
    """原生界面那个可执行文件的路径；这台机器上没有就返回 None。"""
    if sys.platform != "darwin":
        return None

    override = os.environ.get(ENV_NATIVE)
    if _isExecutable(override):
        return override

    # 打包在一起：就在自己旁边（Contents/MacOS/）
    sibling = os.path.join(
        os.path.dirname(os.path.abspath(sys.executable)), NATIVE_BINARY
    )
    if _isExecutable(sibling):
        return sibling

    # 源码运行：swift build 的产物
    root = projectRoot()
    if root:
        built = os.path.join(root, DEV_BUILD)
        if _isExecutable(built):
            return built
    return None


def macosVersion():
    """系统版本号的主版本（取不到返回 0）。"""
    try:
        return int(re.match(r"(\d+)", platform.mac_ver()[0] or "0").group(1))
    except Exception:
        return 0


def nativeUiAvailable():
    """这台机器上能不能切到原生界面（有那个可执行文件、系统版本也够）。"""
    if sys.platform != "darwin":
        return False
    if macosVersion() < NATIVE_MIN_MACOS:
        return False
    return nativeBinary() is not None


def execIntoNativeUi():
    """把当前进程换成原生界面；成功就不会返回，失败返回 False。

    换过去的进程要自己知道去哪里找引擎：打包时它是 bundle 里的可执行文件
    （Contents/MacOS/电棍棍活字），源码运行时它按可执行文件位置往上找
    项目根目录——两条路 Swift 侧都认，见 EngineClient.locateEngine()。
    """
    binary = nativeBinary()
    if not binary:
        return False
    return execInto(binary, [binary])


def execInto(path, args):
    """execv 的包装：成功不返回，失败返回 False（绝不抛异常给调用方）。"""
    try:
        # 交接之前把缓冲区清掉，免得半行日志卡在管道里
        for stream in (sys.__stdout__, sys.__stderr__):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass
        clearBundlerEnv()
        os.execv(path, args)
    except Exception as exc:
        print("换界面失败（{}）：{}".format(path, exc), file=sys.__stderr__)
        return False
    return False


def clearBundlerEnv():
    """清掉 PyInstaller 引导程序留给子进程的环境变量。

    打包后这两个界面会互相 execv，环境变量是一路带过去的：不清的话，下一个
    再跑起来的 PyInstaller 程序会以为自己是"父进程已经解过包"的子进程，跑去
    用上一个进程的运行时目录——现象就是界面起来了却画不出内容（或者直接报
    No module named '_tkinter'）。和 gui.restartIfPending() 里清的是同一批。
    """
    for name in [
        key for key in os.environ if key.startswith("_PYI_") or key == "_MEIPASS2"
    ]:
        os.environ.pop(name, None)
