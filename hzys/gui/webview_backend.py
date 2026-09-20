# -*- coding: UTF-8 -*-
"""pywebview 后端：原生窗口 + 网页界面（Windows）。

窗口是 WinForms 原生窗口 + WebView2 内核，界面是 gui/webview_ui.html，
控件由 gui/layout.py 的结构生成。macOS 上不装这套：那边的"新版界面"是
mac/ 里的 SwiftUI 原生程序（见 gui/__init__.py 的模块文档）。

和 Tk 后端的几处不同：
  * Python 侧没有"只能在主线程碰控件"的限制，状态改完按批推给 JS
  * 「置顶弹幕输出」直接用窗口置顶实现，不再开第二个窗口
  * 设置页的改动暂存在 SettingsDraft 里，按「保存」才落盘
"""

import os
import sys
import threading
import time

from ..config import isBuiltinAssetPath
from ..update import checkupdate, openAuthorPage
from . import (
    canOfferNewLook,
    layout,
    logToConsole,
    setNewUi,
    startUpdateCheck,
    switchBackendLater,
)
from .settings_draft import SettingsDraft

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webview_ui.html")
WINDOW_TITLE = layout.WINDOW_TITLE
WINDOW_SIZE = (560, 880)

# 窗口不做无边框：最大化/最小化/关闭直接用系统标题栏上那三个原生按钮，
# 系统还会顺带把拖动、双击最大化、贴边分屏这些行为一起给到。
#
# 窗口也不做透明：内容区的底色和系统窗口底（也就是标题栏）同色，
# 这样看上去是一整块，而不是"标题栏一块、内容区又透又亮"。
# 底色由 systemLooks() 取系统真实值，再交给网页自己画。
TRANSPARENT_WINDOW = False

# 窗口底色：和系统标题栏同一个颜色，上下连成一整块。
# 取的是 Windows 系统标题栏的值：浅色 ≈ #F3F3F3，深色 ≈ #202020。
WINDOW_COLORS = {"light": "#f3f3f3", "dark": "#202020"}

PUSH_INTERVAL = 0.1  # 每 100ms 把攒下的更新一次性推给 JS（弹幕洪峰靠这个扛）


# pywebview 的文件对话框返回的可能是元组也可能是字符串（版本之间不一样），
# 照着一种写就会拿到路径的第一个字符，表现是导出写成 "/.wav" 报错、
# 或者被当成"没填文件名"。这里两种都认。
def firstPath(result):
    """从 create_file_dialog 的返回值里取出路径，字符串和元组都兼容。"""
    if not result:
        return ""
    if isinstance(result, str):
        return result
    return result[0] if result else ""


def dialogType(name):
    """取对话框类型常量（SAVE / OPEN / FOLDER）。

    新版 pywebview 把它们放在 webview.FileDialog 里，顶层的 SAVE_DIALOG /
    OPEN_DIALOG / FOLDER_DIALOG 是旧别名，用的时候会打弃用警告。
    """
    import webview

    dialogs = getattr(webview, "FileDialog", None)
    value = getattr(dialogs, name, None) if dialogs is not None else None
    return value if value is not None else getattr(webview, name + "_DIALOG")


def systemLooks():
    """返回 (是不是深色, 窗口底色)。

    窗口底色取系统的"窗口背景色"——Windows 上标题栏用的就是它，
    所以内容区用同一个颜色，看上去才是完整一块。
    """
    from . import win_dwm

    dark = win_dwm.systemDarkMode()
    return dark, WINDOW_COLORS["dark" if dark else "light"]


# 界面上的文字（勾选项、滑块、路径行、输入框、页脚）统一放在 gui/layout.py，
# 经典界面用的是同一份，改文案只用改一个地方
CHECKS = layout.CHECKS
SLIDERS = layout.SLIDERS
SLIDER_TEXTS = layout.SLIDER_TEXTS
PATHS = layout.PATHS
EDITORS = layout.EDITORS
ENTRIES = layout.ENTRIES
UPDATE_INFO_TEXT = layout.FOOTER_INFO_TEXT

# 右侧两个按钮在各页面上触发的动作名
SECONDARY_ACTIONS = {
    layout.PAGE_LOCAL: "export",
    layout.PAGE_LIVE: "relogin",
    layout.PAGE_SETTINGS: "resetSettings",
}
PRIMARY_ACTIONS = {
    layout.PAGE_LOCAL: "play",
    layout.PAGE_LIVE: "startLive",
    layout.PAGE_SETTINGS: "saveSettings",
}


class ValueHolder:
    """对应 Tk 的 BooleanVar / DoubleVar（取值器）。"""

    __slots__ = ("backend", "name", "value")

    def __init__(self, backend, name, value):
        self.backend = backend
        self.name = name
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.backend.pushValue(self.name, value)


class WebviewWindow:
    """pywebview 后端的窗口对象（接口见 gui/__init__.py 的模块文档）。"""

    def __init__(self, handlers, windowFactory=None):
        self.handlers = handlers
        self.onDirectPlay = handlers.onDirectPlay
        self.onExport = handlers.onExport
        self.onTrytologin = handlers.onTrytologin
        self.onToggleLiveMode = handlers.onToggleLiveMode
        self.onStartLive = handlers.onStartLive
        self.onStopLive = handlers.onStopLive
        self.onSettingsSaved = handlers.onSettingsSaved

        # 界面状态（语义与 Tk 后端保持一致）
        self.page = layout.PAGE_LOCAL
        self.liveMode = False
        self.running = False
        self.busy = False
        self.tipWindow = False
        self.hideLog = False
        self.inputText = ""
        self.draft = SettingsDraft()
        self.messages = []  # 待推送的更新
        self.lock = threading.Lock()
        self.started = False
        self._window = None
        self._windowFactory = windowFactory
        # 窗口底色和深浅色：建窗口之前就定下来，页面要靠它跟标题栏对齐
        self.dark, self.windowColor = systemLooks()

        self.values = {
            "inYsddMode": ValueHolder(self, "inYsddMode", False),
            "normAudio": ValueHolder(self, "normAudio", False),
            "reverseAudio": ValueHolder(self, "reverseAudio", False),
            "pitchMultOption": ValueHolder(self, "pitchMultOption", 1.0),
            "speedMultOption": ValueHolder(self, "speedMultOption", 1.0),
            "volumeMultOption": ValueHolder(self, "volumeMultOption", 1.0),
            "iflivemodeon": ValueHolder(self, "iflivemodeon", False),
            "ischuanhuaon": ValueHolder(self, "ischuanhuaon", True),
            "iskeywordspoton": ValueHolder(self, "iskeywordspoton", False),
            "iswelcomeon": ValueHolder(self, "iswelcomeon", True),
            "isgifton": ValueHolder(self, "isgifton", True),
            "ishidemsgon": ValueHolder(self, "ishidemsgon", False),
            "istipWindowon": ValueHolder(self, "istipWindowon", False),
            "isNewLookOn": ValueHolder(
                self, "isNewLookOn", True
            ),  # 网页界面本身就是新版
        }

    def __getattr__(self, name):
        """让 ui.inYsddMode.get() 这种写法直接可用。"""
        values = self.__dict__.get("values") or {}
        if name in values:
            return values[name]
        raise AttributeError(name)

    # ---------------- 窗口生命周期 ----------------

    def createWindow(self):
        """建原生窗口（此时还没显示，等 run()）。"""
        import webview

        factory = self._windowFactory or webview.create_window
        with open(UI_PATH, encoding="utf8") as handle:
            html = handle.read()
        self._window = factory(
            WINDOW_TITLE,
            html=html,
            js_api=self,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=(480, 620),
            frameless=False,  # 用系统原生标题栏和窗口按钮
            transparent=TRANSPARENT_WINDOW,
            vibrancy=False,
            background_color=self.windowColor,  # 和标题栏同色，不透明
        )
        return self._window

    def close(self):
        """关闭窗口（契约检查等外部调用用）。"""
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass

    def run(self):
        """进入 GUI 主循环（阻塞）。"""
        import webview

        if self._window is None:
            self.createWindow()
        # 图标只在 Windows 上有用（Windows 后端会拿它当标题栏和任务栏图标）。
        # 图标嵌在代码里，这里只是解出一个临时文件给 pywebview 用。
        from .icon import iconPath

        try:
            icon = iconPath()
        except Exception as exc:
            logToConsole("解图标失败（不影响使用）: {}".format(exc))
            icon = None
        webview.start(self.onStart, icon=icon)

    def onStart(self):
        """GUI 起来之后：套窗口效果 + 开始批量推送。"""
        self.started = True
        # 先把界面推送跑起来：套窗口效果可能要等窗口就绪，别让它拖住界面
        threading.Thread(target=self.flushLoop, daemon=True).start()
        self.pushState()

        try:
            applied = self.applyPlatformEffects()
        except Exception as exc:
            # 窗口效果只是锦上添花，出问题不能让界面推送也跟着停掉
            logToConsole("套用窗口效果失败（不影响使用）: {}".format(exc))
        else:
            if applied:
                logToConsole("已启用窗口效果: " + ", ".join(applied))

    def applyPlatformEffects(self):
        """按平台套窗口效果，返回实际生效的项目。"""
        if sys.platform == "win32":
            return self.applyWindowsEffects()
        return []

    def applyWindowsEffects(self):
        """Windows：玻璃标题栏配色 + 圆角窗口。

        Mica 底板默认不开：pywebview 的无边框透明窗口上 DWM 铺不出 Mica，
        只会变成一块能看见后面窗口的玻璃。想试可以用 HZYS_BACKDROP=mica|acrylic。
        """
        import ctypes

        from . import win_dwm

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高 DPI 下网页才不糊
        except Exception:
            pass

        # pywebview 的启动回调比窗口创建更早，原生窗口要等一下才拿得到
        hwnd = self._waitForHwnd()
        if not hwnd:
            logToConsole("找不到窗口句柄，跳过 Windows 窗口效果")
            return []

        backdrops = {
            "mica": win_dwm.BACKDROP_MICA,
            "acrylic": win_dwm.BACKDROP_ACRYLIC,
            "none": win_dwm.BACKDROP_NONE,
        }
        chosen = backdrops.get(os.environ.get("HZYS_BACKDROP", "none").lower())
        return win_dwm.applyToHwnd(
            hwnd,
            backdrop=chosen or win_dwm.BACKDROP_NONE,
            captionColor=self.windowColor,  # 标题栏和底板同色，看着是一整块
        )

    def _waitForHwnd(self, timeout=8.0):
        """等窗口句柄出现；超时返回 0。"""
        deadline = time.time() + timeout
        while True:
            hwnd = self._findOwnHwnd()
            if hwnd:
                return hwnd
            if time.time() >= deadline:
                return 0
            time.sleep(0.2)

    def _findOwnHwnd(self):
        """拿本窗口的句柄。

        pywebview 6 把原生窗口对象挂在 window.native 上（Windows 后端是 WinForms
        的 BrowserForm），正常情况下从这里取就行；取不到再枚举本进程的可见顶层窗口。
        """
        try:
            handle = getattr(getattr(self._window, "native", None), "Handle", None)
            if handle is not None:
                return int(handle)
        except Exception:
            pass  # 跨线程访问 WinForms 控件可能报错，退回枚举

        return self._enumOwnHwnd()

    def _enumOwnHwnd(self):
        """枚举本进程的可见顶层窗口，作为兜底。"""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        pid = os.getpid()
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, lparam):
            windowPid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(windowPid))
            if windowPid.value == pid and user32.IsWindowVisible(hwnd):
                found.append(int(hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return found[0] if found else 0

    # ---------------- 推送（Python -> JS，按批）----------------

    def push(self, kind, **payload):
        """把一条更新排进队列，稍后一次性推给 JS。"""
        # 勾了「隐藏日志」就直接不推输出：经典界面是把这个框置灰，
        # 网页版也只有不发弹幕才会真的省下渲染开销。
        if kind == "output" and self.hideLog:
            return
        with self.lock:
            self.messages.append(dict(kind=kind, **payload))

    def pushValue(self, name, value):
        self.push("value", name=name, value=value)

    def pathTexts(self):
        """设置页里各条路径的显示文字。

        素材目录还是默认值（程序自带的那份）时，显示成"程序自带"，
        而不是打包后那串又长又没用的包内路径。
        """
        texts = {}
        for option, _title in PATHS.values():
            value = self.draft.get(option)
            if isBuiltinAssetPath(option, value):
                texts[option] = layout.BUILTIN_ASSETS_TEXT
            else:
                texts[option] = value or ""
        return texts

    def pushState(self):
        """把界面状态整包推一遍（页面、运行状态、设置页的路径和输入框）。"""
        self.push(
            "state",
            page=self.page,
            running=self.running,
            busy=self.busy,
            liveMode=self.liveMode,
            hideLog=self.hideLog,
            dirty=self.isDirty(),
            windowColor=self.windowColor,
            paths=self.pathTexts(),
            entries={
                option: str(self.draft.get(option)) for option, _ in ENTRIES.values()
            },
        )

    def flushLoop(self):
        """后台线程：每 100ms 把攒下的更新推一次（弹幕洪峰靠这个扛）。"""
        while self.started:
            time.sleep(PUSH_INTERVAL)
            self.flush()

    def flush(self):
        """把攒下的更新一次性交给 JS。"""
        import json

        if not self.started or self._window is None:
            return
        with self.lock:
            if not self.messages:
                return
            batch, self.messages = self.messages, []
        try:
            script = "window.hzys && window.hzys.apply({})".format(
                json.dumps(batch, ensure_ascii=False)
            )
            self._window.evaluate_js(script)
        except Exception as exc:
            logToConsole("推送界面更新失败: {}".format(exc))

    # ---------------- 界面接口（main.py 调用）----------------

    def layout(self):
        """界面初始化：让 JS 开始渲染（结构和初始状态由下面的方法提供）。"""
        self.push("init")
        self.pushState()

    def getInputText(self):
        return self.inputText

    def appendOutput(self, text):
        self.push("output", text=text)

    def callLater(self, func, *args):
        """pywebview 里没有 Tk 那种线程限制，直接执行就行。"""
        func(*args)

    def setLiveMode(self, entering):
        """切到本地/直播模式（main.py 处理完线程和事件后回调这里）。"""
        self.liveMode = entering
        self.running = False
        self.page = layout.PAGE_LIVE if entering else layout.PAGE_LOCAL
        self.ishidemsgon.set(False)
        self.istipWindowon.set(False)
        self.push("clearOutput")
        self.pushState()

    def setBroadcastRunning(self, running):
        self.running = running
        self.pushState()

    def setLoginBusy(self, busy):
        self.busy = busy
        self.pushState()

    def toggleTipWindow(self):
        """把「置顶弹幕输出」「隐藏日志」的勾选状态作用到窗口和输出上。

        置顶不再单开一个窗口，直接把主窗口挂到系统最上层；
        隐藏日志则是不再往下推输出（见 push）。
        """
        self.tipWindow = bool(self.istipWindowon.get())
        self.hideLog = bool(self.ishidemsgon.get())
        if self.started and self._window is not None:
            try:
                self._window.on_top = self.tipWindow
            except Exception as exc:
                logToConsole("设置窗口置顶失败: {}".format(exc))
        self.pushState()

    def showInfo(self, title, text):
        self.push("toast", text=text, title=title, warn=False)

    def showWarning(self, title, text):
        self.push("toast", text=text, title=title, warn=True)

    def showLoginCode(self, imageBytes, status, done):
        """扫码登录的二维码：在界面里弹面板显示（各后端接口一致）。

        imageBytes 为 None 表示只更新状态文字（比如"已扫码，请确认"）。
        """
        image = None
        if imageBytes:
            import base64

            image = "data:image/png;base64," + base64.b64encode(imageBytes).decode(
                "ascii"
            )
        self.push("qrcode", image=image, status=status, done=bool(done))

    def askSaveFileName(self, title, filetypes, defaultName=""):
        """弹系统保存对话框，返回路径；用户取消返回空字符串。

        filetypes 用的是经典界面那套写法（(("描述", "*.wav"),)，tkinter 要求的格式），
        pywebview 要的是 "描述 (*.wav)" 这样的字符串——直接把它那套传过去会在
        parse_file_type 里抛 TypeError（导出的「另存为」就是这么炸的）。

        defaultName 是预填的文件名：给个名字用户就不用自己敲了，
        也免得某些系统在留空时把目录本身返回回来（见 firstPath）。
        """
        if self._window is None:
            return ""

        # pywebview 没有"对话框标题"参数，它只认窗口上的 localization
        try:
            self._window.localization["global.saveFile"] = title
        except Exception:
            pass  # 换别的 pywebview 版本时没这个字段也不影响选文件

        filters = tuple(
            "{} ({})".format(description, pattern) for description, pattern in filetypes
        )
        result = self._window.create_file_dialog(
            dialogType("SAVE"), save_filename=defaultName, file_types=filters
        )
        return firstPath(result)

    def askYesNo(self, title, text):
        """弹系统确认框；pywebview 自己会把对话框丢回主线程，所以哪儿调都行。"""
        if self._window is None:
            return False
        return bool(self._window.create_confirmation_dialog(title, text))

    def redirectStdout(self):
        """把 print 接到界面的输出区。"""
        redirector = StdoutRedirector(self)
        sys.stdout = redirector
        return redirector

    def isDirty(self):
        """设置页有没有未保存的改动（输入框的值会同步进 draft）。"""
        return self.draft.isDirty()

    # ---------------- JS 调用的接口（js_api）----------------

    def getLayout(self):
        """把 layout.py 的结构转成 JS 能直接渲染的 JSON。"""
        return {
            "windowTitle": WINDOW_TITLE,
            "opaque": not TRANSPARENT_WINDOW,  # 不透明时由网页自己画底色
            "windowColor": self.windowColor,  # 和系统标题栏同色的窗口底
            "dark": self.dark,
            # 结构和原生界面共用同一份；「界面」卡片按平台决定要不要
            "pages": layout.buildPages(canOfferNewLook()),
            "secondary": layout.SECONDARY_TEXT,
            "primary": layout.PRIMARY_TEXT,
            "secondaryActions": SECONDARY_ACTIONS,
            "primaryActions": PRIMARY_ACTIONS,
            "buttons": layout.BUTTONS,  # 子界面（词典编辑/关于）的按钮文字
            "outputTitle": layout.OUTPUT_CARD_TITLE,
            "placeholder": layout.INPUT_PLACEHOLDER,
        }

    def rowPayload(self, row):
        """把一行结构描述转成 JS 用的对象。"""
        return layout.rowPayload(row)

    def getState(self):
        """JS 启动时拉一次初始状态。"""
        return {
            "windowTitle": WINDOW_TITLE,
            "page": self.page,
            "running": self.running,
            "busy": self.busy,
            "liveMode": self.liveMode,
            "dirty": self.isDirty(),
            "windowColor": self.windowColor,
            "values": {name: holder.get() for name, holder in self.values.items()},
            "paths": self.pathTexts(),
            "entries": {
                option: str(self.draft.get(option)) for option, _ in ENTRIES.values()
            },
        }

    def setValue(self, name, value):
        """JS 侧改了复选框 / 滑块。"""
        if name == "isNewLookOn":
            self.toggleNewLook(bool(value))
            return
        holder = self.values.get(name)
        if holder is not None:
            holder.value = value
        # 「置顶弹幕输出」「隐藏日志」不只是记个值，得真的作用到窗口和输出上
        if name in ("istipWindowon", "ishidemsgon"):
            self.toggleTipWindow()

    # ---------------- 新版 / 经典界面切换 ----------------

    def toggleNewLook(self, enabled):
        """设置页的「新版效果」：关掉就换回经典界面（会重启一次）。

        这个选择只对本次运行有效，不写进 settings.json，
        所以下次启动还是默认走新版。
        """
        if enabled:
            return  # 已经在新版界面上了
        if not self.canSwitchNow():
            self.isNewLookOn.set(True)  # 切不了就把开关拨回去
            return
        self.isNewLookOn.set(False)
        self.showInfo("切换界面", "正在换回经典界面，程序会重启一次")
        # 先写进 settings.json：重启出来的进程要靠它决定用哪个界面
        setNewUi(False)
        switchBackendLater("tk")
        # 停一下再关，让上面的提示能被看见
        threading.Timer(0.8, self.close).start()

    def canSwitchNow(self):
        """直播中、登录中不让换界面：换界面要重启，会把这些状态一起打断。"""
        if self.running or self.busy:
            self.showWarning("暂时不能切换", "正在直播或登录，先停掉再换界面")
            return False
        return True

    def setEditorValue(self, option, value):
        """JS 侧改了设置页的输入框（线程数 / 房间号）。"""
        self.draft.set(option, value)
        self.push("dirty", dirty=self.isDirty())

    def inputChanged(self, text):
        """JS 侧改了本地播放的文本框。"""
        self.inputText = text

    def selectPage(self, page):
        """点了页面栏。本地/直播会切换直播模式，高级设置只是翻页。"""
        if page == layout.PAGE_SETTINGS:
            self.page = layout.PAGE_SETTINGS
            self.pushState()
            return
        self.iflivemodeon.set(page == layout.PAGE_LIVE)
        self.onToggleLiveMode()

    def pickPath(self, option):
        """选一个文件或目录，先记进暂存（按保存才写回）。"""
        if self._window is None:
            return
        if option in ("sourceDirectory", "ysddSourceDirectory"):
            chosen = firstPath(self._window.create_file_dialog(dialogType("FOLDER")))
            if not chosen:
                return
            chosen = chosen.replace("\\", "/").rstrip("/") + "/"
        else:
            chosen = firstPath(
                self._window.create_file_dialog(
                    dialogType("OPEN"), file_types=("JSON 配置文件 (*.json)",)
                )
            )
            if not chosen:
                return

        self.draft.set(option, chosen)
        self.pushState()

    def openEditor(self, mode):
        """打开词典编辑器。

        新版界面在自己的窗口里编（下面几个 get/save 接口）；这一条是
        "用经典窗口打开"的兜底，给老调用留的。
        """
        from ..jsonloader import runjsonloader

        runjsonloader(int(mode))

    # ---------------- 子界面：关于 / 词典编辑 ----------------

    def getAbout(self):
        """「关于」弹层的内容（和经典界面用的是同一份文字）。"""
        from ..update import getupdateinfo

        return {"title": layout.FOOTER_CARD_TITLE, "text": getupdateinfo()}

    def getDictionary(self, mode):
        """取某本词典的定义和内容，给网页里的编辑器渲染。"""
        from ..jsonloader import dictionaryInfo, readDictionary

        info = dictionaryInfo(int(mode))
        info["mode"] = int(mode)
        info["rows"] = readDictionary(int(mode))
        return info

    def saveDictionary(self, mode, rows):
        """把编辑器里的内容写回词典文件。"""
        from ..jsonloader import writeDictionary

        try:
            count = writeDictionary(int(mode), rows)
        except Exception as exc:
            self.showWarning("保存失败", str(exc))
            return {"ok": False, "error": str(exc)}
        self.showInfo("已保存", "已保存 {} 条".format(count))
        return {"ok": True, "count": count}

    def action(self, name):
        """右侧两个按钮和「关于」等入口的转发。"""
        if name == "play":
            self.onDirectPlay()
        elif name == "export":
            self.onExport()
        elif name == "relogin":
            self.onTrytologin()
        elif name == "startLive":
            self.onStartLive()
        elif name == "stopLive":
            self.onStopLive()
        elif name == "saveSettings":
            self.saveSettings()
        elif name == "resetSettings":
            self.setConfigtodef()
        elif name == "checkUpdate":
            startUpdateCheck(self)
        elif name == "update":
            checkupdate()
        elif name == "author":
            openAuthorPage()
        elif name == "minimize":
            if self._window is not None:
                self._window.minimize()
        elif name == "close":
            if self._window is not None:
                self._window.destroy()
        elif name == "about":
            from ..update import getupdateinfo

            self.showInfo(layout.FOOTER_CARD_TITLE, getupdateinfo())
        else:
            logToConsole("未知的界面动作: {}".format(name))

    # ---------------- 设置页 ----------------

    def saveSettings(self):
        """保存设置页：把暂存值写回 settings.json 并重建音频引擎。"""
        self.draft.save()
        self.pushState()
        self.onSettingsSaved()
        self.showInfo("保存设置", "设置已保存")

    def setConfigtodef(self):
        """恢复默认值（同样只是暂存，按保存才写回）。"""
        self.draft.resetToDefault()
        self.pushState()
        self.showInfo("恢复默认设置", "已填回默认值，按【保存】生效")


class StdoutRedirector:
    """把 print 输出送进界面的输出区（各线程调用都安全）。"""

    def __init__(self, window):
        self.window = window
        self.stdoutbak = sys.stdout
        self.stderrbak = sys.stderr

    def write(self, text):
        self.window.appendOutput(text)

    def restoreStd(self):
        sys.stdout = self.stdoutbak
        sys.stderr = self.stderrbak

    def flush(self):
        pass
