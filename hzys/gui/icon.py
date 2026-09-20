# -*- coding: UTF-8 -*-
"""程序图标。

图标已经压进代码里了（数据在 icon_data.py，用 tools/make-icon.py 生成），
所以跑程序、打包出来的程序都**不需要**旁边再放一个 lizi.ico。
lizi.ico 只留给打包脚本用（Nuitka 的 --windows-icon-from-ico）。

界面要图标时用这两个：
    iconImage()  → PIL Image，Tk 的 iconphoto 用
    iconPath()   → 需要文件路径的地方用（pywebview 的 icon=），解到临时目录一次
"""

import base64
import io
import os
import tempfile
import zlib

from .icon_data import ICON_ZLIB_BASE64

_cachedPath = None


def iconBytes():
    """图标的原始字节（.ico 内容）。"""
    return zlib.decompress(base64.b64decode(ICON_ZLIB_BASE64))


def iconImage():
    """给 Tk 用的 PIL Image（Pillow 能直接读 ico）。"""
    from PIL import Image

    return Image.open(io.BytesIO(iconBytes()))


def iconPath():
    """解出一个真实的 .ico 文件并返回路径（给要路径的接口用）。

    放在系统临时目录里，同一个进程里只解一次；文件缺失会自动重解。
    """
    global _cachedPath

    if _cachedPath and os.path.exists(_cachedPath):
        return _cachedPath

    path = os.path.join(tempfile.gettempdir(), "hzys-icon.ico")
    with open(path, "wb") as handle:
        handle.write(iconBytes())
    _cachedPath = path
    return path
