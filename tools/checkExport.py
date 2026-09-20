# -*- coding: UTF-8 -*-
"""导出功能自检：走一遍「导出」按钮真正执行的那段代码，再检查生成的 wav。

    python tools/checkExport.py [输出目录]

不需要图形界面：选路径和弹提示这两处用桩接住，合成、写文件、
自动补 .wav 后缀、返回值校验这些真实逻辑照跑。
macOS / Windows 都能跑，用来对比两个平台导出的结果是否一致。
"""

import os
import sys
import tempfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

import soundfile as sf  # noqa: E402

import main  # noqa: E402

TEST_TEXT = "大家好"  # 三个字够验证合成链路，又不用等太久

problems = []


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


class Holder:
    """替掉界面上的取值器（Tk 的 BooleanVar / 新版界面的 ValueHolder）。"""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class StubUi:
    """只接住导出会碰的那几个界面调用，不弹任何窗口。"""

    def __init__(self, dialogResult, text=TEST_TEXT):
        self.dialogResult = dialogResult
        self.text = text
        self.messages = []
        self.askedTitle = None
        self.defaultName = None
        self.inYsddMode = Holder(False)
        self.pitchMultOption = Holder(1.0)
        self.speedMultOption = Holder(1.0)
        self.normAudio = Holder(False)
        self.reverseAudio = Holder(False)
        self.volumeMultOption = Holder(1.0)

    def getInputText(self):
        return self.text

    def askSaveFileName(self, title, filetypes, defaultName=""):
        self.askedTitle = title
        self.defaultName = defaultName
        return self.dialogResult

    def showInfo(self, title, text):
        self.messages.append((title, text))

    def showWarning(self, title, text):
        self.messages.append((title, text))


def exportTo(dialogResult, text=TEST_TEXT):
    """按「导出」按钮的流程跑一次，返回界面桩（里面记着提示文字）。"""
    stub = StubUi(dialogResult, text)
    main.ui = stub
    main.onExport()
    return stub


def inspect(path, label):
    """检查导出的 wav：格式对不对、有没有真的声音。"""
    check(os.path.exists(path), "{}：文件没生成 -> {}".format(label, path))
    if not os.path.exists(path):
        return

    size = os.path.getsize(path)
    check(size > 1000, "{}：文件太小（{} 字节）".format(label, size))

    data, rate = sf.read(path)
    duration = len(data) / float(rate or 1)
    peak = float(abs(data).max()) if len(data) else 0.0
    print(
        "{}: {} | {} 字节 | {} Hz | {:.2f} 秒 | 峰值 {:.3f}".format(
            label, os.path.basename(path), size, rate, duration, peak
        )
    )
    check(rate == 44100, "{}：采样率是 {}，期望 44100".format(label, rate))
    check(
        duration > 0.2, "{}：时长只有 {:.2f} 秒，像是没合成出来".format(label, duration)
    )
    check(peak > 0.01, "{}：整段是静音（峰值 {:.4f}）".format(label, peak))


def mainCheck(outDir):
    os.makedirs(outDir, exist_ok=True)
    print("输出目录:", outDir)

    # 1) 最常见的用法：用户没写 .wav 后缀，程序应该自己补上
    target = os.path.join(outDir, "export-no-suffix")
    stub = exportTo(target)
    expected = target + ".wav"
    check(stub.askedTitle, "导出时没有弹「选择导出路径」")
    check(os.path.exists(expected), "没写后缀时没有自动补成 .wav")
    inspect(expected, "没写后缀")
    check(
        any(expected in text for _title, text in stub.messages),
        "导出成功后没有提示用户文件在哪",
    )

    # 2) 用户自己写了 .wav：不该变成 xxx.wav.wav
    target2 = os.path.join(outDir, "export-with-suffix.wav")
    exportTo(target2)
    check(not os.path.exists(target2 + ".wav"), "用户写了 .wav 又被多补了一次后缀")
    inspect(target2, "自己写后缀")

    # 3) 导出到还不存在的子目录：应该自动建出来
    target3 = os.path.join(outDir, "sub", "dir", "export-nested.wav")
    exportTo(target3)
    inspect(target3, "多级子目录")

    # 4) 空输入：不该崩，文件该是静音/极短——这里只要求不抛异常
    target4 = os.path.join(outDir, "export-empty.wav")
    try:
        exportTo(target4, text="")
        check(True, "")
    except Exception as exc:
        check(False, "空输入导出时抛异常：{}: {}".format(type(exc).__name__, exc))

    # 5) 保存框里没填文件名时，macOS 会把目录本身返回回来（比如 "/"）：
    #    这种情况必须拦下来，不能再往后拼成 "/.wav" 去写文件
    try:
        stub = exportTo("/")
        check(True, "")
    except Exception as exc:
        check(False, "保存框返回目录时抛异常了：{}: {}".format(type(exc).__name__, exc))
    else:
        check(
            any("没有导出" in title for title, _text in stub.messages),
            "保存框没填文件名时，应该提示「没有导出」",
        )

    # 6) 取消（返回空字符串）：什么都不该发生
    stub = exportTo("")
    check(not stub.messages, "取消保存时不该弹任何提示")

    # 7) 默认文件名：拿要导出的文字开头几个字来预填
    stub = exportTo(os.path.join(outDir, "export-name.wav"), text="大家好\n第二行")
    check(
        stub.defaultName == "大家好.wav",
        "默认文件名不对：{!r}".format(stub.defaultName),
    )
    stub = exportTo(os.path.join(outDir, "export-name2.wav"), text="")
    check(
        stub.defaultName == "弹幕播报.wav",
        "没有文字时应该给个兜底的默认文件名：{!r}".format(stub.defaultName),
    )

    if problems:
        print("\n发现 {} 个问题：".format(len(problems)))
        for item in problems:
            print("  -", item)
        return 1
    print(
        "\n全部通过：导出链路正常（补后缀、自动建目录、空输入、没填文件名、取消、默认文件名都对）"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        outDir = os.path.abspath(sys.argv[1])
    else:
        outDir = tempfile.mkdtemp(prefix="hzys-export-")
    sys.exit(mainCheck(outDir))
