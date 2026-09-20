# -*- coding: UTF-8 -*-
# 电棍棍活字：业务逻辑与程序入口
# 界面在 gui.py，配置读写见 config.py

import ctypes
import inspect
import json
import os
import queue
import sys
import threading
from functools import partial
from multiprocessing import Process, freeze_support
from time import sleep
from types import SimpleNamespace

# 引擎模式（原生界面用）下 stdout 是 JSON 协议通道，任何 print 混进去都会
# 把协议冲坏。这里在导入其它模块之前就先把它引到 stderr；等界面后端建好，
# redirectStdout() 会再把它接到界面的"输出"上。
if "--engine" in sys.argv:
    sys.stdout = sys.stderr

from hzys import config, gui
from hzys.biliLiveBroadcaster import biliLiveBroadcaster
from hzys.config import SETTINGS_PATH, migrateConfigFile, readConfig
from hzys.getcookie import getcookienow, load_cookie, load_UID
from hzys.gui import layout
from hzys.huoZiYinShua import huoZiYinShua

# 主窗口实例，在 main() 里创建
ui = None

liveactionflag = 0  # 检测是否处于播报模式

# 直播线程 / 扫码登录线程的句柄，未使用时为 None
livethread = None
cookieProcess = None

# 打断线程用的事件
stoplivemode = threading.Event()
stopcookie = threading.Event()

# 新建活字印刷类实例
HZYS = huoZiYinShua(SETTINGS_PATH)

# 本地"播放"点出去的进程。可以同时存在好几个：
# 连着点几下就是几段音频叠在一起响（以前就是这样，别在这里打断上一条）。
# 每条播放各用一个自己的临时文件，所以同时播不会互相覆盖。
playProcesses = []


def refreshAudioEngine():
    """配置文件改动后重建音频引擎实例。"""
    global HZYS
    HZYS = huoZiYinShua(SETTINGS_PATH)


def onDirectPlay():
    textToRead = ui.getInputText()
    process = Process(
        target=HZYS.directPlay,
        kwargs={
            "rawData": textToRead,
            "inYsddMode": ui.inYsddMode.get(),
            "pitchMult": ui.pitchMultOption.get(),
            "speedMult": ui.speedMultOption.get(),
            "norm": ui.normAudio.get(),
            "reverse": ui.reverseAudio.get(),
            "volumeMult": ui.volumeMultOption.get(),
        },
    )
    process.start()
    playProcesses.append(process)
    # 把已经放完的清理掉，免得越攒越多
    playProcesses[:] = [item for item in playProcesses if item.is_alive()]


def stopDirectPlay():
    """打断所有还在响的本地播放（切模式、退出程序时用）。"""
    for process in playProcesses:
        try:
            process.terminate()
        except Exception:
            pass
    playProcesses.clear()


# 套个壳来禁用启动，直到getcookienow返回值
def beforegetcookie(stopcookie):
    ui.setLoginBusy(True)
    try:
        # 二维码和状态交给界面显示（新版界面弹面板、经典界面弹窗口）
        loginstatecode = getcookienow(
            stopcookie, onState=ui.showLoginCode
        )  # 开启代理软件时无法获取cookie
        if loginstatecode == 0:
            ui.showInfo("登录成功", "登录成功, 请手动关闭二维码图片")
        elif loginstatecode == 86038:
            ui.showInfo("登录失败", "登录失败, 原因: 超时, 请尝试重启整个程序")
    except BaseException:
        # 这里必须连 SystemExit 一起接住：打断上一次登录是靠往线程里抛 SystemExit，
        # 接不住的话下面的按钮就无法恢复可用了
        ui.showInfo(
            "登录失败",
            "登录失败, 无法建立连接\n警告: 请关闭所有代理软件(加速器、VPN等), 否则无法正常登录！！\n\n",
        )
        pass
    ui.setLoginBusy(False)


# 尝试获取cookie
def onTrytologin():
    global cookieProcess
    # 停止上次点击时尝试获取的cookie
    if cookieProcess is not None and cookieProcess.is_alive():
        stop_thread(cookieProcess)
        print("打断了上一次登录……")
    print(
        '请使用哔哩哔哩APP扫描二维码\n如果二维码没有弹出, 请手动打开此目录下"Qrcode.png"'
    )
    cookieProcess = threading.Thread(target=beforegetcookie, args=(stopcookie,))
    cookieProcess.start()
    # cookieButton.config(state="disable")


def _async_raise(tid, exctype):
    """raises the exception, performs cleanup if needed"""
    tid = ctypes.c_long(tid)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
    if res == 0:
        raise ValueError("invalid thread id")
    elif res != 1:
        # """if it returns a number greater than one, you're in trouble,
        # and you should call it again with exc=NULL to revert the effect"""
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


def stop_thread(thread):
    _async_raise(thread.ident, SystemExit)


def stopLivethread():
    """打断正在运行的直播线程；没在跑就什么都不做。"""
    global livethread
    if (
        livethread is not None
        and livethread.is_alive()
        and livethread is not threading.current_thread()
    ):
        stop_thread(livethread)
    livethread = None


# 素材目录（配置项 -> 界面上怎么说）
ASSET_DIRS = (
    ("sourceDirectory", "单字音频"),
    ("ysddSourceDirectory", "原声大碟"),
)


def warnMissingAssets():
    """素材目录不存在时提示一次。

    打包版最容易踩的坑：素材路径被写成了失效的目录（比如 onefile 的解包
    临时目录），程序本身能启动，点「播放」却只会是一片安静——以前这种
    情况没有任何提示，只往控制台打一行，窗口版根本看不到。
    """
    configuration = readConfig()
    for option, label in ASSET_DIRS:
        path = str(configuration.get(option) or "")
        if path and not os.path.isdir(path):
            ui.showWarning(
                "找不到{}素材".format(label),
                "设置里的{}目录不存在：\n{}\n\n"
                "可以去「高级设置 → 音频素材」重新选目录，"
                "或者点「恢复默认」用程序自带的素材。".format(label, path),
            )


def defaultExportName(text):
    """给「另存为」想个默认文件名：用要导出的文字开头几个字。

    必须给个默认名字：macOS 的保存面板在文件名留空时，返回的是目录本身
    （比如 "/"），后面再补 .wav 就变成 "/.wav"，写文件直接报错。
    """
    firstLine = (text or "").strip().split("\n")[0]
    cleaned = "".join(ch for ch in firstLine if ch not in '\\/:*?"<>|').strip()
    return (cleaned[:12] or "弹幕播报") + ".wav"


# 导出的监听事件
def onExport():
    textToRead = ui.getInputText()
    outputFile = ui.askSaveFileName(
        "选择导出路径", (("wav音频文件", "*.wav"),), defaultExportName(textToRead)
    )
    if not outputFile:
        return  # 用户取消了
    if not os.path.basename(outputFile):
        # 保存框里没填文件名时，macOS 会把目录本身返回回来（如 "/"）
        ui.showWarning(
            "没有导出",
            "保存时没填文件名，这次没有导出。\n再点一次「导出」，把文件名填上就行。",
        )
        return
    if not outputFile.endswith(".wav"):
        outputFile += ".wav"
    HZYS.export(
        textToRead,
        filePath=outputFile,
        inYsddMode=ui.inYsddMode.get(),
        pitchMult=ui.pitchMultOption.get(),
        speedMult=ui.speedMultOption.get(),
        norm=ui.normAudio.get(),
        reverse=ui.reverseAudio.get(),
        volumeMult=ui.volumeMultOption.get(),
    )
    ui.showInfo("疑似是成功了", "已导出到" + outputFile + "下")


# 读取设定文件

_keywordCache = {}


def loadKeywords():
    """读取敏感词表；文件没改动就沿用上次的解析结果。"""
    path = readConfig()["keywordDir"]
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []

    if _keywordCache.get("key") != (path, mtime):
        try:
            with open(path, encoding="utf8") as keywordFile:
                keywords = list(json.load(keywordFile).keys())
        except (OSError, ValueError):
            return []
        _keywordCache["key"] = (path, mtime)
        _keywordCache["keywords"] = keywords

    return _keywordCache["keywords"]


def huichuan(huichuantext):
    if ui.iflivemodeon.get():
        ui.appendOutput(huichuantext)


# 语音播报器
class voiceBroadcaster:
    # 初始化
    def __init__(self, numThread):
        self.numThread = int(numThread)
        self.hzysProcesser = huoZiYinShua(SETTINGS_PATH)
        self.listToRead = queue.Queue()

    # 添加需要朗读的文本
    def appendText(self, data):
        self.listToRead.put(data)

    # 丢还没播报的内容
    def clearQueue(self):
        while not self.listToRead.empty():
            try:
                self.listToRead.get_nowait()
            except queue.Empty:
                break

    # 单个线程的播报
    def __broadcast(self, filePath, stoplivemode):
        while True:
            # 队列空的时候阻塞等待，避免空转吃满 CPU
            try:
                data = self.listToRead.get(timeout=0.2)
            except queue.Empty:
                data = None

            if data is not None:
                # 用活字印刷播报
                self.hzysProcesser.directPlay(
                    rawData=data,
                    tempPath=filePath,
                    inYsddMode=ui.inYsddMode.get(),
                    pitchMult=ui.pitchMultOption.get(),
                    speedMult=ui.speedMultOption.get(),
                    norm=ui.normAudio.get(),
                    reverse=ui.reverseAudio.get(),
                    volumeMult=ui.volumeMultOption.get(),
                )

            if stoplivemode.is_set() or liveactionflag == 0:
                self.clearQueue()
                break

    # 开始播报
    def startOperation(self):

        for n in range(1, self.numThread + 1):
            if ui.iflivemodeon.get():
                threading.Thread(
                    target=self.__broadcast,
                    args=(
                        config.dataPath("tempOutput", str(n) + ".wav"),
                        stoplivemode,
                    ),
                ).start()
            else:
                break


# 感谢礼物
def thank(voiceBroad, sender, quantity, giftName):
    if liveactionflag == 1:
        text = "感谢{}的{}个{}\n".format(sender, quantity, giftName)
        ui.callLater(huichuan, text)
        if ui.isgifton.get():
            voiceBroad.appendText(text)


# 欢迎观众
def welcome(voiceBroad, audience):
    if liveactionflag == 1:
        text = "欢迎{}进入直播间\n".format(audience)
        ui.callLater(huichuan, text)
        if ui.iswelcomeon.get():
            voiceBroad.appendText(text)


# 醒目留言（Super Chat）
def superChat(voiceBroad, sender, content, price):
    if liveactionflag == 1:
        text = "感谢{}的{}元醒目留言：{}\n".format(sender, price, content)
        ui.callLater(huichuan, text)
        voiceBroad.appendText(text)  # SC 花了钱，不管开关都念


# 传话太监
def chuanHua(voiceBroad, speaker, content):
    if liveactionflag == 1:
        text = '"{}"说"{}"'.format(speaker, content)
        ui.callLater(huichuan, text)
        chuanhuaswitch = 1
        if ui.ischuanhuaon.get():
            # 关键词过滤
            if ui.iskeywordspoton.get():
                for keyword in loadKeywords():
                    if keyword in text:
                        chuanhuaswitch = 0

            if chuanhuaswitch:
                ui.callLater(huichuan, "\n")
                voiceBroad.appendText(text)
            else:
                ui.callLater(huichuan, ", 但被屏蔽了\n")

        else:
            ui.callLater(huichuan, "\n")


#############################################
# 创建设定窗口


# 直播模式开关（勾选/取消"直播模式"复选框）
def onToggleLiveMode():
    if ui.iflivemodeon.get():  # 进入直播模式
        ui.setLiveMode(True)
        stoplivemode.clear()
        stopcookie.clear()
        try:
            stopDirectPlay()  # 停掉可能还在播的直接播放
        except Exception:
            pass
    else:  # 退出直播模式
        ui.setLiveMode(False)
        stopcookie.set()
        stoplivemode.set()
        stopLivethread()
        ui.toggleTipWindow()  # 上面已把 istipWindowon 置为 False，这里关掉置顶窗口


# 开始直播（"启动！"按钮），解决按钮卡住问题
def startLive():
    global livethread, liveactionflag

    if ui.iflivemodeon.get():
        # 没登录过就不让开播：先扫码（页面上那个按钮这时显示"首次登录"）
        if not config.isLoggedIn():
            ui.showWarning(
                layout.NEED_LOGIN_TEXT, "第一次用直播模式得先扫码登录，点【登录】。"
            )
            print("还没登录过，先扫码登录")
            print("\n")
            ui.callLater(stopLive)
            return

        stoplivemode.clear()
        stopcookie.set()
        stopLivethread()
        if cookieProcess is not None and cookieProcess.is_alive():
            stop_thread(cookieProcess)
            print("登录被打断……")
        else:
            print("使用储存的信息登录…")

        # 先开闸再起线程：播报线程一起来就会检查 liveactionflag，
        # 要是等线程起来之后再置位，它们会立刻以为自己该退出了（直播就不出声了）
        liveactionflag = 1
        livethread = threading.Thread(target=livemodePlay)
        livethread.start()

    ui.setBroadcastRunning(True)


# 停止直播（"停止！"按钮）
def stopLive():
    global liveactionflag

    print("已停止\n")
    print("\n")
    ui.setBroadcastRunning(False)
    stopcookie.clear()
    stoplivemode.set()
    stopLivethread()
    liveactionflag = 0
    sleep(2)  # 缓一缓先


# 直播模式主函数，在livethread线程中运行


def livemodePlay():
    # 读取设置
    configuration = readConfig()
    numOfThreads = configuration["numOfThreads"]  # 线程数
    roomId = configuration["roomID"]
    userUID = load_UID()  # 用户的UID
    userSESSDATA = load_cookie()
    # b站cookie获取方式可以参考：https://zmtblog.xdkd.ltd/2021/10/06/Get_bilibili_cookie/
    # 1.1更新：新增扫码登录，旧方法已废弃

    if userUID is None or userSESSDATA is None:
        config.setConfigValue("loggedIn", False)  # 标记成未登录，开播会被拦住
        print("未登录或登录已失效，请先点【登录】扫码")
        print("\n")
        ui.callLater(stopLive)  # 把界面恢复成未开播的样子
        return
    userUID = int(userUID)

    vb = voiceBroadcaster(numOfThreads)

    broadcaster = biliLiveBroadcaster(
        roomId,
        userUID,  # 新增
        userSESSDATA,  # 新增
        partial(chuanHua, vb),
        partial(thank, vb),
        partial(welcome, vb),
        stoplivemode,
        onReceiveSuperChat=partial(superChat, vb),  # 醒目留言
    )

    # 开始运行
    vb.startOperation()
    broadcaster.startBroadcasting()


# 更新日志


# -------------------------------------------
# 程序入口
# -------------------------------------------
def handOffToNativeUi():
    """macOS：上次选了新版界面，就把进程交给同一个 .app 里的原生界面。

    原生界面不在这个进程里跑，所以要把当前进程整个换过去（execv）；
    换不出去（没编译原生界面、系统版本不够）就照常开经典界面。
    只有非引擎模式调用——原生界面自己的引擎进程不能再往外交班。
    """
    if sys.platform != "darwin" or not readConfig().get("newUi"):
        return False
    from hzys.gui import nativeapp

    if not nativeapp.nativeUiAvailable():
        return False
    print("按上次的选择进入原生界面（想回经典界面：在里面关掉「新版效果」）")
    nativeapp.execIntoNativeUi()
    return False  # 只有 execv 失败才会走到这儿


def main():
    # multiprocess和Windows的兼容
    freeze_support()

    # 补全旧版配置文件缺失的字段，再按配置建好音频引擎
    migrateConfigFile()
    global HZYS
    HZYS = huoZiYinShua(SETTINGS_PATH)

    # 建好界面并铺上控件
    global ui
    handlers = SimpleNamespace(
        onDirectPlay=onDirectPlay,
        onExport=onExport,
        onTrytologin=onTrytologin,
        onToggleLiveMode=onToggleLiveMode,
        onStartLive=startLive,
        onStopLive=stopLive,
        onSettingsSaved=refreshAudioEngine,
    )
    if "--engine" in sys.argv:
        # 原生界面（Swift）用的后端：不建窗口，改用标准输入输出收发消息
        from hzys.gui.rpc_backend import RpcWindow

        ui = RpcWindow(handlers)
    else:
        # macOS：上次选了新版界面就交给原生界面（同一个 .app 里的另一个
        # 可执行文件）。换过去了这里就不返回了，没换成才接着开经典界面
        handOffToNativeUi()
        ui = gui.createWindow(handlers)
    ui.layout()
    ui.redirectStdout()  # 之后 print 的内容都进界面文本框

    warnMissingAssets()

    # 检查活字印刷实例是否配置正确
    if not HZYS.configSucceed():
        ui.showWarning("初始化活字印刷实例失败", "请检查设置的文件路径是否正确")

    ui.run()

    # 退出前收尾
    stoplivemode.set()
    stopcookie.set()
    try:
        stopDirectPlay()
    except Exception:
        pass

    # 用户在设置页点了「新版效果」：按新界面把自己重启一遍
    # （只对本机这次运行有效，不会写进 settings.json）
    gui.restartIfPending()


if __name__ == "__main__":
    main()
