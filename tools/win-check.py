# -*- coding: UTF-8 -*-
"""在 Windows 上体检：解释器架构、关键依赖能否导入。

注意 platform.machine() 在 Windows 上报的是**系统**架构：在 Windows on ARM 上
跑 x64 版 Python 时它也会说 ARM64。要判断解释器本身是什么架构，看下面这两行：
    sysconfig.get_platform()   win-amd64 = x64 版，win-arm64 = ARM64 版
    PE 头 Machine              0x8664 = x64，0xAA64 = ARM64
（PyInstaller 打出来的 exe 架构，跟跑它的解释器一致。）
"""

import os
import platform
import struct
import sys

print("machine:", platform.machine())
print("platform tag:", __import__("sysconfig").get_platform())
print("version:", sys.version)
print("executable:", sys.executable)


def peMachine(path):
    """读 PE 头的 Machine 字段：0x8664 = x64，0xAA64 = ARM64。"""
    try:
        with open(path, "rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            offset = struct.unpack("<I", handle.read(4))[0]
            handle.seek(offset)
            if handle.read(4) != b"PE\0\0":
                return None
            return struct.unpack("<H", handle.read(2))[0]
    except OSError:
        return None


names = {0x8664: "x86-64", 0xAA64: "ARM64", 0x14C: "x86"}
machine = peMachine(sys.executable)
print(
    "解释器 PE 架构: {} ({})".format(
        hex(machine) if machine else "读不到", names.get(machine, "未知")
    )
)

# 顺手看一眼上次打出来的 exe 是什么架构（有的话）
distExe = os.path.join(
    os.path.dirname(sys.executable), "..", "..", "..", "dist", "hzys.exe"
)
for candidate in ("hzys.exe", os.path.join("dist", "hzys.exe")):
    if os.path.exists(candidate):
        exeMachine = peMachine(candidate)
        print(
            "{}: {} ({})".format(
                candidate,
                hex(exeMachine) if exeMachine else "读不到",
                names.get(exeMachine, "未知"),
            )
        )

for module in [
    "numpy",
    "soundfile",
    "pypinyin",
    "requests",
    "brotli",
    "sv_ttk",
    "parselmouth",
    "psola",
]:
    try:
        __import__(module)
        print("OK   ", module)
    except Exception as exc:
        print("FAIL ", module, "->", type(exc).__name__, exc)
