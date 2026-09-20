# -*- coding: UTF-8 -*-
"""把 lizi.ico 压进 gui/icon_data.py，运行时就再不需要那个图标文件了。

    python tools/make-icon.py

换了图标（改 lizi.ico）之后跑一次就行；生成出来的 icon_data.py 不要手改。
lizi.ico 本身留着——打包脚本（generateExeWin.bat）还要用它。
"""

import base64
import os
import sys
import textwrap
import zlib

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(PROJECT, "assets", "lizi.ico")
TARGET = os.path.join(PROJECT, "hzys", "gui", "icon_data.py")

HEADER = '''# -*- coding: UTF-8 -*-
"""程序图标的字节数据（自动生成，别手改）。

来源：lizi.ico，用 tools/make-icon.py 生成。
用法见 gui/icon.py：iconImage() / iconPath()。
"""

# zlib 压缩后再 base64，省得往源码里塞一大坨二进制
ICON_ZLIB_BASE64 = (
'''


def main():
    if not os.path.exists(SOURCE):
        print("找不到 {}".format(SOURCE))
        return 1

    with open(SOURCE, "rb") as handle:
        raw = handle.read()
    packed = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")

    lines = textwrap.wrap(packed, 96)
    body = "".join('    "{}"\n'.format(line) for line in lines)

    with open(TARGET, "w", encoding="utf8") as handle:
        handle.write(HEADER)
        handle.write(body)
        handle.write(")\n")

    print(
        "{} → {}：{} 字节 → {} 字节（源码约 {} KB）".format(
            os.path.basename(SOURCE),
            os.path.relpath(TARGET, PROJECT),
            len(raw),
            len(packed),
            round(len(packed) / 1024),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
