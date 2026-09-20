# -*- coding: UTF-8 -*-
"""界面层。

业务逻辑（main.py）只依赖 createWindow() 返回的对象，
它必须提供下面这套接口：

    取值器      inYsddMode / normAudio / reverseAudio / pitchMultOption /
                speedMultOption / volumeMultOption / iflivemodeon /
                ischuanhuaon / iskeywordspoton / isgifton / iswelcomeon
                每个都要有 .get()（部分需要 .set()）
    文本        getInputText() / appendOutput(文本)
                顶部那个框同时是本地模式的输入框（要播报的文字）和输出框
                （日志、弹幕）。程序自己的诊断信息千万别 print 进去，
                会被当成待播报内容读出来——用 logToConsole() 打到控制台。
    调度        callLater(回调, *参数)
    状态切换    setLiveMode(是否进入) / setBroadcastRunning(是否开播) /
                setLoginBusy(是否登录中) / toggleTipWindow()
    对话框      showInfo(标题, 内容) / showWarning(标题, 内容) /
                showLoginCode(二维码PNG或None, 状态文字, 是否结束) /
                askSaveFileName(标题, 过滤器, 默认文件名) / askYesNo(标题, 内容) -> 是否点"是"
                过滤器用 tkinter 那套写法（(("描述", "*.wav"),)），后端自己转成
                各自需要的格式；默认文件名一定要给（保存面板留空时 macOS 会
                返回目录本身，写文件就炸）
    生命周期    layout() / redirectStdout() / run()
    注入的回调  onDirectPlay / onExport / onTrytologin / onToggleLiveMode /
                onStartLive / onStopLive / onSettingsSaved

改接口时记得同步 tools/checkGuiContract.py 里那份清单。

界面状态（每个后端都要实现同一套语义）：

    页面 page     local / live / settings 三页，同一时间只显示一页
                  切到 local/live 会切换"直播模式"（触发线程和事件），
                  切到 settings 只是翻页，不影响直播状态
    liveMode      是否处于直播模式；决定直播相关开关是否可用
    running       是否正在开播；开播时页面栏和高级设置禁用，
                  主按钮在"启动/停止"之间切换

    页面栏右侧两个按钮的文字和动作跟着页面变：
                  次按钮  导出 / 重新登录 / 恢复默认
                  主按钮  播放 / 启动·停止 / 保存

    设置页的改动先在内存里暂存（pendingConfig），
    只有按"保存"才写回 settings.json；有未保存改动时
    "高级设置"按钮上会显示一个小圆点。

三套界面，每个平台两套：
    Windows  经典界面（tk）+ 新版界面（pywebview / WebView2）
    macOS    经典界面（tk）+ 原生界面（mac/ 里的 SwiftUI 程序）

    原生界面是和主程序装在一起的另一个可执行文件（一个 .app 里两套界面，
    见 nativeapp.py）：它启动时用 main.py --engine 起一个引擎进程，通过
    gui/rpc_backend.py 的 JSON 行协议收发消息。所以 macOS 上不提供网页
    界面——那边的新版界面就是原生那套，网页后端整个只在 Windows 上跑。

    两套界面之间可以互相切，选择记在 settings.json 的 newUi 里：
        Windows 同一个进程里换后端（重启自己），tk ⇄ webview
        macOS   同一个 .app 里换可执行文件（execv），tk ⇄ 原生界面

后端目录：
    tk_backend.py      经典界面（Tkinter，全平台可用，也是兜底）
    webview_ui.html    新版网页界面（HTML/CSS/JS）
    webview_backend.py 上面这套网页界面的 Python 侧（仅 Windows）
    rpc_backend.py     原生界面（SwiftUI）用的协议后端
    win_dwm.py         Windows 窗口效果（标题栏深浅色 / 圆角 / Mica 底板）
    layout.py          各后端共用的页面与分区结构
    settings_draft.py  设置页的暂存模型（保存前不落盘）

网页界面的组件按 macOS 官方样式来做（系统蓝、发丝描边、原生质感的分段控件/
开关/滑杆/按钮），三个页签是带滑动玻璃药丸的分段控件；窗口底色取系统的
窗口背景色，和标题栏连成一整块，窗口本身不透明。

窗口标题栏和最大化/最小化/关闭按钮一律用系统原生的（Windows 在右上角，
macOS 是左上角的红黄绿），界面层不自己画窗口按钮——这样拖动、双击最大化、
贴边分屏这些行为都不用自己实现，也不会和系统打架。

界面后端的选择（只决定这个 Python 进程里跑 tk 还是 webview 那两套）：
    settings.json 里的 newUi：
        false（默认）= 旧版，也就是经典界面（tk）
        true          = 新版：Windows 上是网页界面，macOS 上是原生界面
    留默认的 false 是为了让老配置文件升级上来时不会突然换界面。
    用户可以在「高级设置 → 界面」里切「新版效果」：切换会立刻写进
    settings.json，再换成那套界面；下次启动照样按这个选择来。
    这张卡片只在有两套界面可换的时候出现：经典界面那边看 canOfferNewLook()
    （macOS 上找得到原生界面的可执行文件才摆），新版界面那边看
    canGoBackToClassic()。
    Windows 上如果没检测到可用的 WebView2 运行时，即使选了新版也会自动
    退回经典界面（pywebview 在那种机器上会悄悄用 IE 内核，界面直接坏掉）。
"""

import importlib.util
import os
import sys
import threading
import webbrowser

# 布局参数：外部可以直接 import gui.layout 取坐标
from . import layout

__all__ = [
    "createWindow",
    "availableBackends",
    "preferredBackend",
    "backendModule",
    "logToConsole",
    "webview2Available",
    "newLookAvailable",
    "nativeUiAvailable",
    "canOfferNewLook",
    "canGoBackToClassic",
    "switchBackendLater",
    "restartIfPending",
    "startUpdateCheck",
    "layout",
    "BACKEND_ENV",
    "BACKEND_LABELS",
]

# 各平台默认用哪个后端：前面的不可用就顺延，最后兜底 tk。
# macOS 只列 tk：那边的新版界面是 mac/ 里的原生程序，不经过这里。
# 新后端把 gui/<名字>_backend.py 放进来即可自动启用，不需要改这里。
#
# 平台差异：Windows 的 pywebview 走 WinForms，无边框透明窗口上 DWM 铺不出
# Mica，所以 Windows 用不透明的界面底色 + 圆角窗口
# （想要 Mica 可以 HZYS_BACKDROP=mica 试）。
PREFERRED_BACKENDS = {
    "darwin": ("tk",),
    "win32": ("webview", "tk"),
}
OTHER_PLATFORM_ORDER = ("webview", "tk")

BACKEND_ENV = "HZYS_GUI"  # 用环境变量强制指定，比如 HZYS_GUI=tk

# 后端的界面文字（给提示信息用）
BACKEND_LABELS = {"tk": "经典", "webview": "新版"}

# 用户在设置页点了「新版效果」之后，要把自己重启成哪个后端。
# 只对本次运行有效：不写进 settings.json，所以下次启动还是按平台默认（新版）。
pendingBackend = None


def backendModule(name):
    """后端名 -> 模块名（约定：gui/<name>_backend.py）。"""
    return "hzys.gui.{}_backend".format(name)


def logToConsole(*parts):
    """把开发期的诊断信息打到真正的控制台，而不是界面里的文本框。

    界面顶部那个框在本地模式下就是「要播报的文字」，程序日志混进去会被
    当成待播报内容一起读出来，所以这类消息不能走 print（print 已经被重定向
    到界面上了）。窗口用 pythonw 启动时没有控制台，这时直接丢掉。
    """
    stream = sys.__stdout__
    if stream is None:
        return
    try:
        print(*parts, file=stream, flush=True)
    except Exception:
        pass  # 控制台已经关了（比如窗口模式下被关掉），丢掉就行


def webview2Available():
    """这台机器上有没有能用的 WebView2 运行时（Windows 专用问题）。

    pywebview 在 Windows 上找不到 WebView2 时不会报错，而是悄悄退回 IE11
    内核，界面会直接坏掉、也看不出原因。所以这里提前问一次 pywebview
    自己的判断（它认 WebView2 的注册表项，也认自定义运行时目录），
    拿不到就改用经典界面。

    非 Windows 平台一律返回 True：网页后端只在 Windows 上跑，
    别的平台（macOS / Linux）根本不会走到这个判断里。
    """
    if sys.platform != "win32":
        return True
    try:
        from webview.platforms.winforms import _is_chromium

        return bool(_is_chromium())
    except Exception:
        return False


def newLookAvailable():
    """新版界面在这台机器上能不能用（真要切过去的时候问这个）。

    macOS  新版 = mac/ 里的原生界面（另一个 .app）。找得到那个 .app 就能切。
    Windows 新版 = 网页界面，三个条件缺一不可：网页后端在、WebView2 在
           （缺失时 pywebview 会悄悄退回 IE 内核、界面直接坏掉）。

    Windows 上这个判断要导入 pywebview 才问得出来，得一秒多，所以只用在
    真正要切界面的时候（点「新版效果」、建窗口时的兜底）。摆不摆那张卡片
    另有便宜的办法，见 canOfferNewLook()。
    """
    if sys.platform == "darwin":
        return nativeUiAvailable()
    return (
        sys.platform == "win32"
        and "webview" in availableBackends()
        and webview2Available()
    )


def nativeUiAvailable():
    """macOS：这台机器上能不能切到原生界面（有可执行文件、系统版本也够）。"""
    if sys.platform != "darwin":
        return False
    from . import nativeapp

    return nativeapp.nativeUiAvailable()


def canOfferNewLook():
    """经典界面上，「新版效果」那张卡片该不该摆出来。

    macOS  找得到原生 .app 才摆（没有就点了也没用）。判断只是几个目录探测，
           不导入 pywebview，够快。
    Windows 两套界面都在同一个包里，除了 WebView2 缺不缺之外没有别的变数，
           所以先摆出来（问 WebView2 要一秒多，不值得卡在启动路径上）；
           真去点的时候再由 newLookAvailable() 判一次，不可用就提示。
    """
    if sys.platform == "darwin":
        return nativeUiAvailable()
    return sys.platform == "win32" and "webview" in availableBackends()


def canGoBackToClassic():
    """新版界面上，「新版效果」那张卡片该不该摆出来。

    新版界面里这个开关的含义反过来：关掉 = 换回经典界面，所以问的是
    "有没有经典界面能起"。macOS 上一定有：源码在就直接跑 main.py，
    打包了就是自己旁边的那个 .app。Windows 上还是那两套后端的事。
    """
    if sys.platform == "darwin":
        return True
    return canOfferNewLook()


def wantsNewUi():
    """设置里是不是选了新版（网页）界面；没写过这个键就是旧版。"""
    from ..config import readConfig

    return bool(readConfig().get("newUi"))


def setNewUi(enabled):
    """把界面版本写进 settings.json（切换界面时会重启，必须先落盘）。"""
    from ..config import setConfigValue

    setConfigValue("newUi", bool(enabled))


def switchBackendLater(name):
    """记下要换成的界面后端。

    真正重启在界面退出、main() 收完尾之后做（见 restartIfPending），
    这样音频、直播线程、窗口都能干净地结束，不会留下半截状态。
    """
    global pendingBackend
    pendingBackend = name


def restartIfPending():
    """用户点了「切换界面」就按新后端把自己重启一遍；返回是否重启了。"""
    backend = pendingBackend
    if backend is None:
        return False

    env = dict(os.environ)
    env[BACKEND_ENV] = backend
    # PyInstaller 的 onefile 引导程序会把这些变量留给子进程。不清掉的话，
    # 重启出来的进程会以为自己是"父进程已经解过包"的子进程，直接去用上一个
    # 进程的解包目录（_MEIxxxx）——那个目录马上就要被删，结果就是
    # "ModuleNotFoundError: No module named '_tkinter'"。
    for key in [
        name for name in env if name.startswith("_PYI_") or name == "_MEIPASS2"
    ]:
        env.pop(key, None)
    if getattr(sys, "frozen", False):
        args = [sys.executable, *sys.argv[1:]]  # 打包后 sys.executable 就是本程序
    else:
        args = [sys.executable, *sys.argv]

    logToConsole("正在切换到{}界面…".format(BACKEND_LABELS.get(backend, backend)))
    for stream in (sys.__stdout__, sys.__stderr__):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass
    try:
        os.execve(sys.executable, args, env)  # 直接换掉当前进程，不留孤儿
    except Exception as exc:
        logToConsole("切换界面失败（{}），请手动重开程序".format(exc))
    return True


def availableBackends():
    """返回这台机器上真正可用的后端名（模块存在、且平台合适）。"""
    backends = []
    for name in ("tk", "webview"):
        if importlib.util.find_spec(backendModule(name)) is None:
            continue  # 这个后端还没写
        backends.append(name)
    return backends


def preferredBackend():
    """按平台优先级挑一个可用的后端。"""
    available = availableBackends()

    # 设置里选了旧版就用经典界面（默认就是旧版）
    if not wantsNewUi():
        if "tk" in available:
            return "tk"
        return available[0] if available else "tk"

    order = PREFERRED_BACKENDS.get(sys.platform, OTHER_PLATFORM_ORDER)
    for name in order:
        if name in available:
            return name
    return available[0] if available else "tk"


def createWindow(handlers, backend=None):
    """创建主窗口。backend 为空时按平台优先级和环境变量决定。"""
    backend = backend or os.environ.get(BACKEND_ENV) or preferredBackend()

    # Windows 上没有 WebView2 时，pywebview 会悄悄退回 IE11 内核、界面直接坏掉，
    # 这种机器上改用经典界面（设置页里的「新版效果」会显示成关闭状态）
    if backend == "webview" and not webview2Available():
        logToConsole("没检测到可用的 WebView2 运行时，自动改用经典界面")
        backend = "tk"

    if backend == "webview":
        from .webview_backend import WebviewWindow

        return WebviewWindow(handlers)

    from .tk_backend import MainWindow

    return MainWindow(handlers)


def askAndOpenRelease(window, latest, url):
    """（在主线程里跑）把检查结果告诉用户；有新版就问要不要打开下载页。"""
    from ..update import isDifferent

    current = layout.APP_VERSION
    if not isDifferent(latest, current):
        window.showInfo("检查更新", "已经是最新版（{}）".format(current))
        return
    question = "发布页上是 {}，你当前是 {}。\n要打开下载页吗？".format(latest, current)
    if window.askYesNo("发现新版本", question):
        webbrowser.open_new(url)


def startUpdateCheck(window):
    """点「更新」按钮：去问一次有没有新版本。

    网络请求丢到工作线程里，界面调用一律经 callLater 回主线程——
    既不会卡住窗口，也不会在 Tk 里跨线程碰控件。
    """
    from ..update import fetchLatest

    def worker():
        try:
            latest, url = fetchLatest()
        except Exception as exc:
            window.callLater(window.showWarning, "检查更新失败", str(exc))
            return
        window.callLater(askAndOpenRelease, window, latest, url)

    threading.Thread(target=worker, daemon=True).start()
