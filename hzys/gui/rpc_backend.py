# -*- coding: UTF-8 -*-
"""原生界面（Swift）用的后端：通过 stdio 上的 JSON 行协议和外界通信。

接口跟网页后端完全一致（见 gui/__init__.py 的模块文档），所以 main.py 的
业务逻辑一行都不用改——把 ui 换成这个后端，它就通过标准输入输出收发消息。

协议（每行一个 JSON 对象，UTF-8）：

    Python -> 界面
        {"type": "ready",   "title": ..., "layout": {...}, "state": {...}}
        {"type": "event",   "name": "output",  "text": "..."}      输出框/日志
        {"type": "event",   "name": "state",   "state": {...}}     界面状态整包
        {"type": "event",   "name": "value",   "name2"?...}        （见 pushValue）
        {"type": "event",   "name": "info"/"warning", "title": ..., "text": ...}
        {"type": "event",   "name": "login",   "image": ..., "status": ..., "done": ...}
        {"type": "call",    "id": N, "method": "askSaveFileName", "args": [...]}
                                                            ← 需要界面回答的调用
        界面回答：{"type": "return", "id": N, "result": ...}
                 {"type": "error",  "id": N, "message": "..."}

    界面 -> Python
        {"type": "call", "id": N, "method": "action", "args": ["play"]}

几个实现上的注意点：
  * 协议只走真正的 stdout（sys.__stdout__）；main.py 里 print 出来的东西会
    被引到"输出"事件上，开发用的日志（logToConsole）改走 stderr，
    这样谁都不会把 JSON 流冲坏；
  * 读输入的线程一路跑着，每条界面调用丢进自己的线程处理，避免"导出弹框"
    这种会阻塞的调用把后面的消息堵住。
"""

import json
import sys
import threading

from .. import __version__
from . import canGoBackToClassic, layout, logToConsole, setNewUi
from .settings_draft import SettingsDraft


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


class _OutputRedirector:
    """把 print 的内容变成界面上的"输出"事件。"""

    def __init__(self, backend):
        self.backend = backend

    def write(self, data):
        if data:
            self.backend.appendOutput(data)

    def flush(self):
        pass

    def isatty(self):
        return False


class RpcWindow:
    """原生界面后端（接口和 WebviewWindow 一致）。"""

    def __init__(self, handlers):
        self.handlers = handlers
        self.onDirectPlay = handlers.onDirectPlay
        self.onExport = handlers.onExport
        self.onTrytologin = handlers.onTrytologin
        self.onToggleLiveMode = handlers.onToggleLiveMode
        self.onStartLive = handlers.onStartLive
        self.onStopLive = handlers.onStopLive
        self.onSettingsSaved = handlers.onSettingsSaved

        self.page = layout.PAGE_LOCAL
        self.liveMode = False
        self.running = False
        self.busy = False
        self.hideLog = False
        self.inputText = ""
        self.draft = SettingsDraft()

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
            # 这两个不给 main.py 用（它们是纯界面行为），但状态里得有：
            # 「隐藏日志」要据此不再推输出、「置顶弹幕输出」要让窗口浮上去
            "ishidemsgon": ValueHolder(self, "ishidemsgon", False),
            "istipWindowon": ValueHolder(self, "istipWindowon", False),
            # 原生界面本身就是新版，所以这个开关是打开的：
            # 关掉它 = 换回经典界面（macOS 上是另一个 .app）
            "isNewLookOn": ValueHolder(self, "isNewLookOn", True),
        }

        # 协议只走这个句柄；logToConsole 用的是 sys.__stdout__，所以把它挪到
        # stderr，免得开发日志混进 JSON 流里
        self.stream = sys.__stdout__ or self._openProtocolStream()
        sys.__stdout__ = sys.stderr

        self.lock = threading.Lock()
        self.pending = {}  # id -> {"event": Event, "result": ..., "error": ...}
        self.nextId = 1
        self.alive = True
        self.stopped = threading.Event()

    def _openProtocolStream(self):
        """sys.__stdout__ 为空时的兜底（打包成无控制台程序时可能拿不到）。

        引擎的 stdout 是界面用来收事件的管道，拿不到它就没法通信；
        直接按文件描述符 1 打开一个，只要管道还在就能用。
        """
        return open(1, "w", encoding="utf-8", buffering=1, closefd=False)

    def __getattr__(self, name):
        values = self.__dict__.get("values") or {}
        if name in values:
            return values[name]
        raise AttributeError(name)

    # ---------------- 传输 ----------------

    def send(self, payload):
        line = json.dumps(payload, ensure_ascii=False)
        with self.lock:
            self.stream.write(line + "\n")
            self.stream.flush()

    def event(self, name, **payload):
        self.send(dict(type="event", name=name, **payload))

    def call(self, method, *args, **kwargs):
        """请界面做一件事并等它回答（弹保存框、确认框这类）。

        超时会返回 None，让调用方按"用户取消"处理，不至于把程序挂死。
        """
        timeout = kwargs.pop("timeout", 600)
        with self.lock:
            callId = self.nextId
            self.nextId += 1
            entry = {"event": threading.Event(), "result": None, "error": None}
            self.pending[callId] = entry
        self.send(dict(type="call", id=callId, method=method, args=list(args)))
        if not entry["event"].wait(timeout):
            self.pending.pop(callId, None)
            logToConsole("界面没有在 {} 秒内回答 {}".format(timeout, method))
            return None
        if entry["error"]:
            logToConsole("界面执行 {} 失败: {}".format(method, entry["error"]))
        return entry["result"]

    # ---------------- 界面调用进来 ----------------

    def dispatch(self, message):
        kind = message.get("type")
        if kind == "return" or kind == "error":
            entry = self.pending.pop(message.get("id"), None)
            if entry is None:
                return
            entry["result"] = message.get("result")
            entry["error"] = message.get("message")
            entry["event"].set()
            return
        if kind == "call":
            # 每条调用单独一个线程：导出那种会弹框的调用不能堵住后面的消息
            threading.Thread(target=self._runCall, args=(message,), daemon=True).start()
            return
        logToConsole("收到不认识的界面消息: {}".format(kind))

    def _runCall(self, message):
        callId = message.get("id")
        method = message.get("method") or ""
        args = message.get("args") or []
        func = getattr(self, method, None)
        if not callable(func):
            self.send(
                dict(type="error", id=callId, message="没有这个方法: {}".format(method))
            )
            return
        try:
            result = func(*args)
        except Exception as exc:
            self.send(
                dict(
                    type="error",
                    id=callId,
                    message="{}: {}".format(type(exc).__name__, exc),
                )
            )
            return
        self.send(dict(type="return", id=callId, result=result))

    def readLoop(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                logToConsole("界面发来的不是合法 JSON，已忽略")
                continue
            if message.get("method") == "quit" or message.get("type") == "quit":
                self.alive = False
                break
            self.dispatch(message)
        self.alive = False

    # ---------------- 生命周期 ----------------

    def layout(self):
        """界面上来先拉一次结构和初始状态。"""
        # 「新版效果」这张卡片在原生界面上也有，只是含义反过来：
        # 关掉它 = 换回经典界面（tk）。摆不摆看有没有经典界面能起。
        pages = layout.buildPages(includeUiSwitch=canGoBackToClassic())
        self.event(
            "ready",
            title=layout.WINDOW_TITLE,
            version=__version__,
            layout={
                # 和网页后端渲染的是同一份结构（layout.buildPages），
                # 这样几套界面的控件、顺序、文案必然一致
                "pages": pages,
                "buttons": layout.BUTTONS,
                "primaryText": layout.PRIMARY_TEXT,
                "secondaryText": layout.SECONDARY_TEXT,
                "outputTitle": layout.OUTPUT_CARD_TITLE,
                "placeholder": layout.INPUT_PLACEHOLDER,
                "dictionaries": self.dictionariesInfo(),
            },
            state=self.getState(),
        )

    def dictionariesInfo(self):
        """词典编辑要用的三本词典（标题、表头、字段名）。"""
        from ..jsonloader import dictionaryInfo

        result = []
        for mode in (1, 2, 3):
            try:
                info = dictionaryInfo(mode)
            except Exception:
                continue
            info["mode"] = int(mode)
            result.append(info)
        return result

    def run(self):
        """进入"事件循环"：读界面发来的消息，直到它让我们退出。"""
        threading.Thread(target=self.readLoop, daemon=True).start()
        while self.alive:
            self.stopped.wait(0.2)
        return

    def redirectStdout(self):
        """把 print 接到界面输出区（协议流用 sys.__stdout__，不受影响）。"""
        sys.stdout = _OutputRedirector(self)
        return sys.stdout

    def callLater(self, func, *args):
        """原生界面后端没有"只能在主线程碰控件"的限制，直接执行。"""
        func(*args)

    def close(self):
        self.alive = False
        self.stopped.set()

    # ---------------- 状态推送 ----------------

    def pushValue(self, name, value):
        self.event("value", var=name, value=value)

    def pushState(self):
        self.event("state", state=self.getState())

    def getState(self):
        return {
            "page": self.page,
            "running": self.running,
            "busy": self.busy,
            "liveMode": self.liveMode,
            "dirty": self.isDirty(),
            "input": self.inputText,
            "values": {name: holder.get() for name, holder in self.values.items()},
            "paths": self.pathTexts(),
            "entries": {
                option: str(self.draft.get(option))
                for option, _ in layout.ENTRIES.values()
            },
        }

    # ---------------- 界面接口（main.py 调用）----------------

    def getInputText(self):
        return self.inputText

    def appendOutput(self, text):
        if self.hideLog:
            return  # 勾了「隐藏日志」就不再往界面推，和网页后端一致
        self.event("output", text=text)

    def setLiveMode(self, entering):
        self.liveMode = entering
        self.running = False
        self.page = layout.PAGE_LIVE if entering else layout.PAGE_LOCAL
        self.pushState()

    def setBroadcastRunning(self, running):
        self.running = running
        self.pushState()

    def setLoginBusy(self, busy):
        self.busy = busy
        self.pushState()

    def toggleTipWindow(self):
        """置顶/隐藏日志由原生窗口自己实现（看状态里的取值），这里同步一下状态。"""
        self.hideLog = bool(self.ishidemsgon.get())
        self.pushState()

    def showInfo(self, title, text):
        self.event("info", title=title, text=text)

    def showWarning(self, title, text):
        self.event("warning", title=title, text=text)

    def showLoginCode(self, imageBytes, status, done):
        image = None
        if imageBytes:
            import base64

            image = "data:image/png;base64," + base64.b64encode(imageBytes).decode(
                "ascii"
            )
        self.event("login", image=image, status=status, done=bool(done))

    def askSaveFileName(self, title, filetypes, defaultName=""):
        """请界面弹保存框；用户取消返回空字符串。"""
        result = self.call("askSaveFileName", title, defaultName)
        return result or ""

    def askYesNo(self, title, text):
        return bool(self.call("askYesNo", title, text))

    # ---------------- 界面调用（界面 -> Python）----------------

    def action(self, name):
        """界面上的按钮/菜单：跟网页后端的 action() 一套语义。"""
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
        elif name == "quit":
            self.close()
        else:
            logToConsole("未知的界面动作: {}".format(name))

    def inputChanged(self, text):
        self.inputText = text

    def setValue(self, name, value):
        # 「新版效果」不是普通开关：关掉它 = 换回经典界面
        if name == "isNewLookOn":
            self.toggleNewLook(bool(value))
            return
        holder = self.values.get(name)
        if holder is not None:
            holder.value = value
        if name == "ishidemsgon":
            self.hideLog = bool(value)
        # 回传一次：网页界面是 JS 自己把控件画成新状态的，原生界面得靠这个
        # 才知道"值已经被接受"，否则开关会弹回去
        self.pushValue(name, value)

    # ---------------- 新版 / 经典界面切换 ----------------

    def toggleNewLook(self, enabled):
        """原生界面上的「新版效果」：关掉就换回经典界面（tk）。

        两套界面在同一个 .app 里，但换可执行文件这件事只有宿主（Swift 那边）
        做得到——它是当前的进程，引擎只是它拉起来的子进程。所以这里写进
        settings.json、发一条事件请宿主换过去，然后自己退出。
        """
        if enabled:
            self.values["isNewLookOn"].value = True
            return  # 已经在新版（原生）界面上了
        if self.running or self.busy:
            self.pushValue("isNewLookOn", True)  # 切不了就把开关拨回去
            self.showWarning("暂时不能切换", "正在直播或登录，先停掉再换界面")
            return

        setNewUi(False)  # 记下选择：宿主换过去之后，下次启动也按它来
        self.values["isNewLookOn"].value = False
        # 宿主收到就 execv 回经典界面（Contents/MacOS 里的主程序）
        self.event("switchUi", target="classic")
        self.close()

    def setEditorValue(self, option, value):
        self.draft.set(option, value)
        self.pushDirty()

    def selectPage(self, page):
        if page == layout.PAGE_SETTINGS:
            self.page = layout.PAGE_SETTINGS
            self.pushState()
            return
        self.iflivemodeon.set(page == layout.PAGE_LIVE)
        self.onToggleLiveMode()

    def pickPath(self, option):
        """选一个文件或目录，先记进暂存（按保存才写回）。"""
        title = ""
        for _button, (name, optionTitle) in layout.PATHS.items():
            if name == option:
                title = optionTitle
                break

        if option in ("sourceDirectory", "ysddSourceDirectory"):
            chosen = self.call("pickFolder", title)
            if not chosen:
                return
            chosen = chosen.replace("\\", "/").rstrip("/") + "/"
        else:
            chosen = self.call("pickFile", title)
            if not chosen:
                return
        self.draft.set(option, chosen)
        self.pushState()

    def getAbout(self):
        from ..update import getupdateinfo

        return {"title": layout.FOOTER_CARD_TITLE, "text": getupdateinfo()}

    def getDictionary(self, mode):
        from ..jsonloader import dictionaryInfo, readDictionary

        info = dictionaryInfo(int(mode))
        info["mode"] = int(mode)
        info["rows"] = readDictionary(int(mode))
        return info

    def saveDictionary(self, mode, rows):
        from ..jsonloader import writeDictionary

        try:
            count = writeDictionary(int(mode), rows)
        except Exception as exc:
            self.showWarning("保存失败", str(exc))
            return {"ok": False, "error": str(exc)}
        self.showInfo("已保存", "已保存 {} 条".format(count))
        return {"ok": True, "count": count}

    def checkUpdate(self):
        from . import startUpdateCheck

        startUpdateCheck(self)

    def openAuthor(self):
        from ..update import openAuthorPage

        openAuthorPage()

    def openReleases(self):
        from ..update import checkupdate

        checkupdate()

    # ---------------- 设置页 ----------------

    def isDirty(self):
        return self.draft.isDirty()

    def pushDirty(self):
        self.event("dirty", dirty=self.isDirty())

    def pathTexts(self):
        from ..config import isBuiltinAssetPath

        texts = {}
        for option, _title in layout.PATHS.values():
            value = self.draft.get(option)
            if isBuiltinAssetPath(option, value):
                texts[option] = layout.BUILTIN_ASSETS_TEXT
            else:
                texts[option] = value or ""
        return texts

    def saveSettings(self):
        self.draft.save()
        self.onSettingsSaved()
        self.pushState()
        self.pushDirty()
        return True

    def setConfigtodef(self):
        self.draft.resetToDefault()
        self.pushState()
        self.pushDirty()
        return True
