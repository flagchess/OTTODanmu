# -*- coding: UTF-8 -*-
"""pywebview 后端的无窗口自检：不需要图形环境，也能验证逻辑。

专门覆盖那些「跑起来点一下才走得到」的路径：
设置页的暂存/保存/恢复默认、选路径的规范化、右侧按钮的动作转发、
复选框与输入框的回传、布局描述转 JSON。

    python tools/checkWebviewLogic.py

退出码 0 表示通过。
"""

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from hzys import config, gui, jsonloader, update  # noqa: E402
from hzys.gui import layout, webview_backend  # noqa: E402
from hzys.gui.webview_backend import EDITORS, WebviewWindow  # noqa: E402

problems = []


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


class StubWindow:
    """替掉真窗口：create_file_dialog 直接返回预设答案，顺便记下调用参数。"""

    def __init__(self, answer=None):
        self.answer = answer or []
        self.calls = []
        self.localization = {}
        self.minimized = False
        self.destroyed = False

    def create_file_dialog(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.answer

    def minimize(self):
        self.minimized = True

    def destroy(self):
        self.destroyed = True


def makeWindow():
    """建一个后端对象（不会创建真窗口），同时记录回调被谁调用过。"""
    calls = []

    def recorder(name):
        def record(*args, **kwargs):
            calls.append(name)

        return record

    handlers = SimpleNamespace(
        onDirectPlay=recorder("play"),
        onExport=recorder("export"),
        onTrytologin=recorder("relogin"),
        onToggleLiveMode=recorder("toggle"),
        onStartLive=recorder("startLive"),
        onStopLive=recorder("stopLive"),
        onSettingsSaved=recorder("refreshEngine"),
    )
    return WebviewWindow(handlers), calls


def readSettings():
    with open(config.SETTINGS_PATH, encoding="utf8") as handle:
        return json.load(handle)


def testSettingsDraft(window):
    """设置页：改动先暂存，按保存才落盘；恢复默认也只改暂存。"""
    original = readSettings()
    check(not window.isDirty(), "刚打开设置页不该显示未保存状态")

    window.setEditorValue("numOfThreads", "5")
    check(window.isDirty(), "改了线程数应该进入未保存状态")
    check(
        readSettings()["numOfThreads"] == original["numOfThreads"],
        "还没按保存就把线程数写进文件了",
    )

    window.saveSettings()
    check(not window.isDirty(), "按了保存之后不该还显示未保存")
    check(readSettings()["numOfThreads"] == "5", "按保存后没把线程数写回文件")

    window.setConfigtodef()
    check(window.isDirty(), "恢复默认之后应该还是未保存状态")
    check(
        readSettings()["numOfThreads"] == "5",
        "恢复默认不该直接写文件，等按保存才对",
    )

    # 恢复默认后直接保存：写回文件的值要和界面一致（字符串），
    # 否则下次打开会出现"明明没改过却显示未保存"
    window.saveSettings()
    check(
        isinstance(readSettings()["numOfThreads"], str),
        "恢复默认后保存，线程数被写成了数字而不是字符串",
    )
    check(not window.isDirty(), "刚保存完不该还显示未保存")

    # 收尾：把配置恢复成原样
    window.draft.values = original
    window.saveSettings()


def testPickPath(window):
    """选路径：目录统一成正斜杠 + 结尾斜杠，文件原样使用。"""
    window._window = StubWindow([r"C:\Users\test\Music\sources"])
    window.pickPath("sourceDirectory")
    check(
        window.draft.get("sourceDirectory") == "C:/Users/test/Music/sources/",
        "目录路径没有规范成 C:/.../ 的形式",
    )

    window._window = StubWindow([r"C:\Users\test\dict.json"])
    window.pickPath("dictFile")
    check(
        window.draft.get("dictFile") == r"C:\Users\test\dict.json",
        "文件路径不该被改写",
    )

    # 用户按取消：什么都不该变
    before = window.draft.get("dictFile")
    window._window = StubWindow([])
    window.pickPath("dictFile")
    check(window.draft.get("dictFile") == before, "取消选择不该改动路径")


def testAssetPaths():
    """素材路径：打包版绝不能把解包临时目录写进配置。

    写进去的下场是：这次运行正常，下次启动那个 _MEIxxxx 目录已经没了，
    素材一个都加载不到——点「播放」只剩一片安静（窗口版连提示都看不到）。
    """
    with tempfile.TemporaryDirectory() as workspace:
        realPackaged = config.isPackaged
        realResource = config._resourceDir
        realSettings = config.SETTINGS_PATH
        realDefaults = dict(config.DEFAULT_CONFIG)
        try:
            config.SETTINGS_PATH = os.path.join(workspace, "settings.json")
            config.isPackaged = lambda: True
            config._resourceDir = lambda: "/tmp/_MEI123456"
            config.DEFAULT_CONFIG["sourceDirectory"] = "/tmp/_MEI123456/assets/sources/"
            config.DEFAULT_CONFIG["ysddSourceDirectory"] = (
                "/tmp/_MEI123456/assets/ysddSources/"
            )

            # 老配置里存着上一轮运行留下的解包临时路径
            with open(config.SETTINGS_PATH, "w", encoding="utf8") as handle:
                json.dump(
                    {
                        "sourceDirectory": "/tmp/_MEI999999/assets/sources/",
                        "roomID": "1",
                    },
                    handle,
                )

            loaded = config.readConfig()
            check(
                loaded["sourceDirectory"] == "/tmp/_MEI123456/assets/sources/",
                "失效的解包临时路径没有被当回「程序自带」",
            )
            check(
                loaded["ysddSourceDirectory"] == "/tmp/_MEI123456/assets/ysddSources/",
                "缺失的素材路径没有回落到「程序自带」",
            )
            check(
                config.isBuiltinAssetPath("sourceDirectory", loaded["sourceDirectory"]),
                "程序自带的素材路径没被认出来",
            )

            config.writeConfig(loaded)
            with open(config.SETTINGS_PATH, encoding="utf8") as handle:
                onDisk = json.load(handle)
            check(
                onDisk["sourceDirectory"] == "",
                "打包版又把解包临时目录写进配置了：{!r}".format(
                    onDisk["sourceDirectory"]
                ),
            )

            # 用户自己选的目录必须原样保留
            loaded["sourceDirectory"] = "D:/我的素材/"
            config.writeConfig(loaded)
            with open(config.SETTINGS_PATH, encoding="utf8") as handle:
                onDisk = json.load(handle)
            check(
                onDisk["sourceDirectory"] == "D:/我的素材/",
                "用户自己选的素材目录被改写了",
            )
        finally:
            config.isPackaged = realPackaged
            config._resourceDir = realResource
            config.SETTINGS_PATH = realSettings
            config.DEFAULT_CONFIG.clear()
            config.DEFAULT_CONFIG.update(realDefaults)


def testSaveDialog(window):
    """导出的「另存为」对话框：过滤器要转成 pywebview 认的写法。

    以前直接把 tkinter 那套 (("描述", "*.wav"),) 传过去，pywebview 的
    parse_file_type 收到元组会抛 TypeError，点「导出」就报错。
    """
    from webview.util import parse_file_type

    stub = StubWindow(["C:/tmp/out.wav"])
    window._window = stub
    result = window.askSaveFileName(
        "选择导出路径", (("wav音频文件", "*.wav"),), "大家好.wav"
    )
    check(result == "C:/tmp/out.wav", "保存对话框选中的路径没有返回出来")
    check(bool(stub.calls), "没有真的去调 create_file_dialog")

    filters = stub.calls[0][1].get("file_types", ())
    check(
        filters == ("wav音频文件 (*.wav)",),
        "文件过滤器没转成 pywebview 的写法：{!r}".format(filters),
    )
    # 真拿这个过滤器去问 pywebview，确认它认得（以前就是在这里炸的）
    try:
        parsed = parse_file_type(filters[0])
    except Exception as exc:
        check(False, "过滤器格式还是不对：{}: {}".format(type(exc).__name__, exc))
    else:
        check(parsed == ("wav音频文件", "*.wav"), "过滤器内容丢了：{!r}".format(parsed))

    check(
        stub.localization.get("global.saveFile") == "选择导出路径",
        "保存对话框的标题没有设上",
    )
    # 预填的文件名必须传过去：留空时 macOS 会返回目录本身，后面补 .wav 就炸
    check(
        stub.calls[0][1].get("save_filename") == "大家好.wav",
        "默认文件名没有传给保存对话框：{!r}".format(stub.calls[0][1]),
    )

    # 两个平台返回的形态不一样：Windows 给元组、macOS 直接给字符串。
    # 以前照着元组写 result[0]，macOS 上拿到的是路径的第一个字符 "/"。
    stub = StubWindow("/Users/test/Desktop/大家好.wav")  # macOS 形态
    window._window = stub
    check(
        window.askSaveFileName("选择导出路径", (("wav音频文件", "*.wav"),), "x.wav")
        == "/Users/test/Desktop/大家好.wav",
        "macOS 那种「直接返回字符串」的形态没处理对",
    )
    stub = StubWindow(("C:\\Users\\test\\Desktop\\x.wav",))  # Windows 形态
    window._window = stub
    check(
        window.askSaveFileName("选择导出路径", (("wav音频文件", "*.wav"),), "x.wav")
        == "C:\\Users\\test\\Desktop\\x.wav",
        "Windows 那种「返回元组」的形态没处理对",
    )
    stub = StubWindow("/")  # 用户没填文件名时 macOS 会返回目录本身
    window._window = stub
    check(
        window.askSaveFileName("选择导出路径", (("wav音频文件", "*.wav"),), "x.wav")
        == "/",
        "返回目录本身时不该把路径切碎",
    )
    stub = StubWindow(None)  # 取消
    window._window = stub
    check(
        window.askSaveFileName("选择导出路径", (("wav音频文件", "*.wav"),), "x.wav")
        == "",
        "取消保存时应该返回空字符串",
    )


def testActions():
    """右侧按钮和窗口按钮的转发。"""
    for name in ("play", "export", "relogin", "startLive", "stopLive"):
        window, calls = makeWindow()
        window._window = StubWindow()
        window.action(name)
        check(name in calls, "动作 {} 没有转发给 main.py".format(name))

    window, calls = makeWindow()
    window._window = StubWindow()
    window.action("saveSettings")
    check("refreshEngine" in calls, "保存设置后没有重建音频引擎")

    window, calls = makeWindow()
    window._window = StubWindow()
    window.action("minimize")
    check(window._window.minimized, "最小化没有传给窗口")
    window.action("close")
    check(window._window.destroyed, "关闭没有传给窗口")

    # 「作者主页」按钮：转发到打开主页（这里桩掉，别真开浏览器）
    window, _calls = makeWindow()
    window._window = StubWindow()
    realOpen = webview_backend.openAuthorPage
    opened = []
    webview_backend.openAuthorPage = lambda: opened.append("author")
    try:
        window.action("author")
    finally:
        webview_backend.openAuthorPage = realOpen
    check(opened == ["author"], "「作者主页」按钮没有转发到打开主页")


def testValuesAndState(window):
    """复选框/滑块/输入框的回传，以及切页时的按钮文案。"""
    window.setValue("isgifton", False)
    check(window.isgifton.get() is False, "复选框的取值没有回传")

    window.setValue("pitchMultOption", 1.5)
    check(window.pitchMultOption.get() == 1.5, "滑块的取值没有回传")

    window.inputChanged("测试文本")
    check(window.getInputText() == "测试文本", "输入框内容没有回传")

    window.selectPage(layout.PAGE_LIVE)
    check(window.iflivemodeon.get() is True, "切到直播页没有打开直播模式")

    window.selectPage(layout.PAGE_SETTINGS)
    check(window.page == layout.PAGE_SETTINGS, "没能切到高级设置页")

    window.setBroadcastRunning(True)
    check(window.running is True, "开播状态没有记下来")

    window.setLoginBusy(True)
    check(window.busy is True, "登录中状态没有记下来")


def testWindowSwitches(window):
    """置顶 / 隐藏日志：勾了要真的生效，不能只是把开关图形拨过去。"""
    window._window = StubWindow()
    window.started = True

    window.setValue("istipWindowon", True)
    check(window.tipWindow is True, "勾了「置顶弹幕输出」但状态没记下来")
    check(
        getattr(window._window, "on_top", False) is True,
        "勾了「置顶弹幕输出」但窗口没有置顶",
    )
    window.setValue("istipWindowon", False)
    check(
        getattr(window._window, "on_top", True) is False,
        "取消「置顶弹幕输出」后窗口还按在最上层",
    )

    window.setValue("ishidemsgon", True)
    check(window.hideLog is True, "勾了「隐藏日志」但状态没记下来")
    check(
        any(msg["kind"] == "state" and msg["hideLog"] for msg in window.messages),
        "「隐藏日志」的状态没有推给界面，网页那边看不到效果",
    )
    with window.lock:
        window.messages = []
    window.appendOutput("这行不该被推给界面\n")
    check(
        not any(msg["kind"] == "output" for msg in window.messages),
        "勾了「隐藏日志」之后还在往界面推输出",
    )

    window.setValue("ishidemsgon", False)
    with window.lock:
        window.messages = []
    window.appendOutput("恢复显示\n")
    check(
        any(msg["kind"] == "output" for msg in window.messages),
        "取消「隐藏日志」之后输出没有恢复",
    )

    # 收尾：别让这些状态影响后面的用例
    window.started = False
    window._window = None


class FakeWindow:
    """只记录调用、不弹窗的假窗口：用来跑「检查更新」的完整流程。"""

    def __init__(self, answer=True):
        self.answer = answer
        self.infos = []
        self.warnings = []
        self.asked = []
        self.done = threading.Event()
        self.opened = []

    def callLater(self, func, *args):
        func(*args)

    def showInfo(self, title, text):
        self.infos.append((title, text))
        self.done.set()

    def showWarning(self, title, text):
        self.warnings.append((title, text))
        self.done.set()

    def askYesNo(self, title, text):
        self.asked.append((title, text))
        self.done.set()
        return self.answer


def testUpdateCheck():
    """检查更新：版本号比较（纯逻辑，不联网）。"""
    check(update.isDifferent("v2026.10.1", "2026.9.20"), "版本号不同就该提示更新")
    check(
        update.isDifferent("2026.9.2", "2026.9.20"),
        "比当前旧的版本号也该提示（按需求不比大小）",
    )
    check(update.isDifferent("1.2.3.4", "1.2.3"), "段数不同也算版本号对不上")
    check(
        not update.isDifferent("2026.09.20", "2026.9.20"),
        "只是前导零不同，数字是一样的，不该提示",
    )
    check(not update.isDifferent("2026.9.20", "2026.9.20"), "版本号一样不该提示")
    check(
        update.isDifferent("release-latest", "2026.9.20"),
        "发布页写不出数字版本号时，也该提示让人去看一眼",
    )
    check(update.parseVersion("v1.2.3-beta") == (1, 2, 3), "版本号里的前缀后缀没剥掉")


def testUpdateCheckFlow():
    """检查更新：有新版 / 已最新 / 网络失败，三条路都要走到。"""
    realFetch = update.fetchLatest
    realOpen = gui.webbrowser.open_new
    try:
        # 1) 有新版本：应该问一句，点"是"就去打开下载页
        update.fetchLatest = lambda: ("v2026.10.1", "https://example.com/dl")
        window = FakeWindow(answer=True)
        gui.webbrowser.open_new = window.opened.append
        gui.startUpdateCheck(window)
        check(window.done.wait(5), "[有新版本] 检查完没有回调界面")
        deadline = time.time() + 2
        while not window.opened and time.time() < deadline:
            time.sleep(0.05)
        check(bool(window.asked), "[有新版本] 没有问用户要不要去下载")
        check(
            window.asked and "2026.10.1" in window.asked[0][1],
            "[有新版本] 提示里没写清新版本号",
        )
        check(
            window.opened == ["https://example.com/dl"],
            "[有新版本] 用户点了「是」却没打开下载页",
        )

        # 2) 已经是最新：只提示，不该问、更不该开浏览器
        update.fetchLatest = lambda: ("2026.9.20", "https://example.com/dl")
        window = FakeWindow(answer=True)
        gui.webbrowser.open_new = window.opened.append
        gui.startUpdateCheck(window)
        check(window.done.wait(5), "[已最新] 检查完没有回调界面")
        check(
            window.infos and "最新" in window.infos[0][1],
            "[已最新] 没有提示「已经是最新版」",
        )
        check(not window.asked, "[已最新] 不该问用户要不要下载")
        check(not window.opened, "[已最新] 不该打开浏览器")

        # 3) 网络失败：把原因告诉用户，别静默
        def boom():
            raise RuntimeError("连不上 GitHub：测试用")

        update.fetchLatest = boom
        window = FakeWindow()
        gui.startUpdateCheck(window)
        check(window.done.wait(5), "[失败] 检查完没有回调界面")
        check(
            window.warnings and "测试用" in window.warnings[0][1],
            "[失败] 没把失败原因告诉用户",
        )
    finally:
        update.fetchLatest = realFetch
        gui.webbrowser.open_new = realOpen


def testLayoutPayload(window):
    """布局描述要能完整转成 JS 用的 JSON，一个行型都不能漏。"""
    payload = window.getLayout()
    check(len(payload["pages"]) == 3, "页面数量不对")

    kinds = set()

    def walk(rows):
        for row in rows:
            data = window.rowPayload(row)
            kinds.add(data["kind"])
            if data["kind"] == "row":
                check(
                    all(item["text"] for item in data["items"]),
                    "有复选框没配上显示文字",
                )

    sections = list(layout.PAGE_SECTIONS[layout.PAGE_LOCAL])
    sections += list(layout.PAGE_SECTIONS[layout.PAGE_LIVE])
    sections += list(layout.settingsSections())

    for title, rows in sections:
        check(rows, "卡片 {} 是空的".format(title))
        walk(rows)

    check(
        kinds == {"row", "slider", "path", "entry", "footer"},
        "行型覆盖不全: {}".format(sorted(kinds)),
    )

    for mode in EDITORS.values():
        check(mode in jsonloader.EDITORS, "词典编辑器类型 {} 不存在".format(mode))


def main():
    # 配置读写走临时文件，别动项目自带的 settings.json。
    # 注意不能靠 chdir：pywebview 是按启动脚本目录算 base_uri 的，换工作目录会让它炸。
    with tempfile.TemporaryDirectory() as workspace:
        config.SETTINGS_PATH = os.path.join(workspace, "settings.json")
        with open(config.SETTINGS_PATH, "w", encoding="utf8") as handle:
            json.dump(
                {
                    "sourceDirectory": "./assets/sources/",
                    "ysddSourceDirectory": "./assets/ysddSources/",
                    "dictFile": "./data/dictionary.json",
                    "ysddTableFile": "./data/ysddTable.json",
                    "keywordDir": "./data/keyword.json",
                    "numOfThreads": 2,
                    "roomID": "22603245",
                },
                handle,
            )

        window, _ = makeWindow()
        try:
            testSettingsDraft(window)
            testPickPath(window)
            testAssetPaths()
            testSaveDialog(window)
            testValuesAndState(window)
            testWindowSwitches(window)
            testUpdateCheck()
            testUpdateCheckFlow()
            testLayoutPayload(window)
            testActions()
        except Exception as exc:
            problems.append("自检抛异常: {}: {}".format(type(exc).__name__, exc))
            traceback.print_exc()

    if problems:
        print("发现 {} 个问题：".format(len(problems)))
        for item in problems:
            print("  -", item)
        return 1
    print("全部通过：设置暂存、选路径、动作转发、状态回传、布局转换")
    return 0


if __name__ == "__main__":
    sys.exit(main())
