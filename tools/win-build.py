# -*- coding: UTF-8 -*-
"""把程序打成 Windows 的 exe，产物带版本号和架构，放进 release/。

    python tools/win-build.py          # 在 Windows 上跑（虚拟机里也行）

产物位置：
    在 Parallels 虚拟机里跑（项目通过 \\\\Mac\\HZYS 共享过来）时，直接写进
    Mac 项目目录的 release/win-x86_64/；在真实 Windows 机器上跑就写本工程的
    release/win-x86_64/。文件名就是版本号 + 平台架构：

        2026.9.20-win-x86_64.exe

    名字里不带时间戳：同一个版本重新编译就是覆盖同一个文件，目录里不会越攒越多。
    同目录下别的 *-win-*.exe（以前版本编的）会被顺手删掉。

架构标签是按**解释器**判断的，不是按系统：Windows on ARM 上装 x64 版 Python
时 platform.machine() 会说 ARM64，但打出来的 exe 其实是 x64——
所以这里看 sysconfig 的平台标签，并在打完后再读一次 PE 头确认。
"""

import os
import shutil
import struct
import subprocess
import sys
import sysconfig

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

from hzys import __version__  # noqa: E402  版本号只有这一处

NAME = "hzys"  # PyInstaller 的产物名（dist\hzys.exe），对外文件名另算
SHARE = r"\\Mac\HZYS"  # 虚拟机里这个路径指向 Mac 上的项目目录

PE_MACHINES = {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86"}
X86_64_TAG = "win-x86_64"  # 唯一带 PE 头校验的那个架构


def peMachine(path):
    """读 PE 头的 Machine 字段，用来确认产物到底是什么架构。"""
    with open(path, "rb") as handle:
        if handle.read(2) != b"MZ":
            return None
        handle.seek(0x3C)
        offset = struct.unpack("<I", handle.read(4))[0]
        handle.seek(offset)
        if handle.read(4) != b"PE\0\0":
            return None
        return struct.unpack("<H", handle.read(2))[0]


def archTag():
    """产物的架构标签，取自解释器：win-amd64 -> win-x86_64。"""
    tag = sysconfig.get_platform()
    if tag.endswith("amd64"):
        return X86_64_TAG
    if tag.endswith("arm64"):
        return "win-arm64"
    return "win-" + tag.rsplit("-", 1)[-1]


def cleanOldBuilds(folder, keep):
    """删掉同一个目录里以前编出来的 exe（只认我们自己的命名）。

    名字固定成"版本号-架构"之后，同一个版本重编是覆盖；换了版本号时
    旧文件就会留在那儿，这里顺手清掉，省得像以前那样攒一堆时间戳产物。
    """
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        if path == keep or not name.endswith(".exe"):
            continue
        if "-win-" not in name or not name.startswith(__version__):
            continue  # 不是我们编的产物就别动
        try:
            os.remove(path)
            print("[打包] 清掉旧产物：{}".format(name))
        except OSError as exc:
            print("[打包] 清不掉旧产物 {}：{}".format(name, exc))


def releaseDir():
    """产物放哪：在虚拟机里就把 exe 直接放到 Mac 项目目录里。"""
    if os.path.isdir(SHARE):
        return os.path.join(SHARE, "release", archTag())
    return os.path.join(PROJECT, "release", archTag())


def build(console=False):
    print("[打包] 解释器: {} ({})".format(sys.executable, sysconfig.get_platform()))
    if not _hasPyInstaller():
        print("[打包] 先装 PyInstaller…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], check=True
        )

    print("[打包] 开始（第一次会慢一点）…")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--console" if console else "--windowed",
            "--onefile",
            "--name",
            NAME + ("-console" if console else ""),
            "--icon",
            r"assets\lizi.ico",
            "--add-data",
            r"assets;assets",
            "--add-data",
            r"data\dictionary.json;defaults",
            "--add-data",
            r"data\ysddTable.json;defaults",
            "--add-data",
            r"data\keyword.json;defaults",
            "--add-data",
            r"hzys\gui\webview_ui.html;hzys\gui",
            "--collect-all",
            "webview",
            "--collect-all",
            "pythonnet",
            "--collect-all",
            "tkinter",
            "--hidden-import",
            "_tkinter",
            "--hidden-import",
            "clr",
            "--hidden-import",
            "webview.platforms.winforms",
            "--hidden-import",
            "webview.platforms.edgechromium",
            "--hidden-import",
            "PIL.IcoImagePlugin",
            "main.py",
        ],
        check=True,
    )


def _hasPyInstaller():
    return (
        subprocess.run(
            [sys.executable, "-c", "import PyInstaller"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def main():
    # --console：打一个带控制台窗口的版本，用来排查"窗口版里看不到的报错"
    # （子进程和 Tk 回调的 traceback 都会打到控制台/重定向文件里）
    console = "--console" in sys.argv[1:]
    build(console=console)

    built = os.path.join("dist", NAME + ("-console" if console else "") + ".exe")
    if not os.path.exists(built):
        print("[打包] 失败：没找到 {}".format(built))
        return 1

    suffix = "-console" if console else ""
    target = os.path.join(
        releaseDir(),
        "{}-{}{}.exe".format(__version__, archTag(), suffix),
    )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(built, target)
    cleanOldBuilds(os.path.dirname(target), target)

    machine = peMachine(target)
    size = os.path.getsize(target) / 1024.0 / 1024.0
    print()
    print("[打包] 完成：{}".format(target))
    print(
        "[打包] {:.1f} MB，PE 架构 {}（{}）".format(
            size,
            hex(machine) if machine else "读不到",
            PE_MACHINES.get(machine, "未知"),
        )
    )
    if archTag() == X86_64_TAG and machine != 0x8664:
        print("[打包] 警告：产物不是 x64，架构标签和 PE 头对不上")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
