# -*- coding: UTF-8 -*-
# 主窗口界面：控件创建、布局，以及不涉及业务逻辑的界面操作

import ctypes
import os
import sys
import tkinter as tk
from tkinter import (
    HORIZONTAL,
    BooleanVar,
    DoubleVar,
    Toplevel,
    filedialog,
    font,
    messagebox,
    scrolledtext,
    ttk,
)

from PIL import Image, ImageTk

from ..config import isBuiltinAssetPath
from ..jsonloader import runjsonloader
from ..update import checkupdate, getupdateinfo, openAuthorPage
from . import (
    canOfferNewLook,
    layout,
    logToConsole,
    nativeapp,
    newLookAvailable,
    setNewUi,
    startUpdateCheck,
    switchBackendLater,
    win_dwm,
)
from .icon import iconImage
from .settings_draft import SettingsDraft

# 页脚那行更新信息
UPDATE_INFO_TEXT = layout.FOOTER_INFO_TEXT


class MainWindow:
    """活字印刷弹幕姬的主窗口。

    按钮点击后要做什么由 handlers 提供（main.py 里的业务逻辑），
    界面自己只负责控件、布局和状态切换。
    """

    def __init__(self, handlers):
        # 高 DPI：必须在创建窗口之前声明，否则 Windows 会按 96 DPI 处理，
        # 界面在 125%/150%/200% 缩放的屏幕上会显得很小
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 系统 DPI 感知
            except Exception:
                pass

        self.handlers = handlers

        # 按钮点下去要执行什么，由业务逻辑（main.py）提供
        self.onDirectPlay = handlers.onDirectPlay
        self.onExport = handlers.onExport
        self.onTrytologin = handlers.onTrytologin
        self.onToggleLiveMode = handlers.onToggleLiveMode
        self.onStartLive = handlers.onStartLive
        self.onStopLive = handlers.onStopLive
        self.onSettingsSaved = handlers.onSettingsSaved

        # 界面自己用到的几个句柄
        self.textWindow = None
        self.textArea2 = None
        self.page = layout.PAGE_LOCAL  # 当前页：本地 / 直播 / 高级设置
        self.draft = SettingsDraft()  # 设置页的暂存，按"保存"才写回
        self.liveMode = False  # 是否处于直播模式
        self.running = False  # 是否正在直播（决定主按钮是"启动"还是"停止"）
        self.busy = False  # 是否正在扫码登录（登录中不让换界面）
        # 这台机器上有没有第二套界面可换（只有 Windows 有）。没有的话
        # 设置页里那张「界面」卡片整个不摆，和原生界面保持一致。
        self.hasUiSwitch = canOfferNewLook()

        self.root = tk.Tk()
        self.scale = self._uiScale()
        self.root.title(layout.WINDOW_TITLE)
        self.root.resizable(True, True)  # 卡片布局随窗口拉伸
        self._setIcon(self.root)

        self._createVariables()
        self._setupStyles()  # 先备好主题/字体：卡片容器要用到主题信息
        self._createWidgets()
        self.textArea = self.textArea1  # 当前输出指向的文本框
        self._styleTextView(self.textArea1)

    def _setIcon(self, window):
        try:
            # 图标是嵌在代码里的（gui/icon.py），不需要外部的 lizi.ico
            img = ImageTk.PhotoImage(iconImage())
            window.tk.call("wm", "iconphoto", window._w, img)
        except Exception:
            messagebox.showwarning("警告", "缺失图标")

    def _uiScale(self):
        """高 DPI 下的界面缩放系数（96 DPI 为 1.0）。

        Tk 在 Windows 上不会自己做 DPI 缩放（winfo_fpixels 恒返回 96），
        所以这里直接问系统要真实 DPI：布局坐标按它放大，
        同时把 Tk 的 scaling 调对，字号才会跟着一起变大。
        其它平台保持 1.0，界面和以前完全一致。
        """
        if sys.platform != "win32":
            return 1.0

        dpi = 96
        try:
            dpi = int(ctypes.windll.user32.GetDpiForSystem()) or 96
        except Exception:
            dpi = 96

        # tk scaling = 每个 point 对应多少像素，100% 缩放时是 96/72
        try:
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        return max(1.0, dpi / 96.0)

    def _place(self, widget, position):
        """按缩放系数摆放控件。"""
        widget.place(x=int(position[0] * self.scale), y=int(position[1] * self.scale))

    def _scaledSize(self, size):
        """按缩放系数换算窗口尺寸字符串。"""
        return "{}x{}".format(int(size[0] * self.scale), int(size[1] * self.scale))

    # ---------------- 创建控件 ----------------

    def _createVariables(self):
        self.inYsddMode = BooleanVar(master=self.root)
        self.normAudio = BooleanVar(master=self.root)
        self.reverseAudio = BooleanVar(master=self.root)
        self.pitchMultOption = DoubleVar(master=self.root)
        self.speedMultOption = DoubleVar(master=self.root)
        self.volumeMultOption = DoubleVar(master=self.root)
        self.iflivemodeon = BooleanVar(master=self.root)
        self.iskeywordspoton = BooleanVar(master=self.root)
        self.iswelcomeon = BooleanVar(master=self.root)
        self.ischuanhuaon = BooleanVar(master=self.root)
        self.ishidemsgon = BooleanVar(master=self.root)
        self.isgifton = BooleanVar(master=self.root)
        self.istipWindowon = BooleanVar(master=self.root)
        self.isNewLookOn = BooleanVar(master=self.root)  # 经典界面：新版效果默认关

    # ---------------- 创建控件 ----------------

    def _createWidgets(self):
        """建控件：顶部固定输出区 + 页面栏 + 三个页面。"""
        # ---- 顶部输出区（固定不动，带滚动条）----
        self.outputCard = self._makeCard(self.root)
        self.outputTitle = ttk.Label(
            self.outputCard, text=layout.OUTPUT_CARD_TITLE, style="Section.TLabel"
        )
        self.textArea1 = scrolledtext.ScrolledText(
            self.outputCard,
            width=52,
            height=9,
            font=font.Font(family="微软雅黑", size=10),
        )

        # ---- 页面栏：三个页面 + 右侧两个按钮（文字和动作跟着页面变）----
        self.bar = ttk.Frame(self.root)
        self.pageLocal = ttk.Button(
            self.bar,
            text=layout.PAGE_BAR_TEXT[layout.PAGE_LOCAL],
            command=lambda: self.selectPage(layout.PAGE_LOCAL),
        )
        self.pageLive = ttk.Button(
            self.bar,
            text=layout.PAGE_BAR_TEXT[layout.PAGE_LIVE],
            command=lambda: self.selectPage(layout.PAGE_LIVE),
        )
        self.pageSettings = ttk.Button(
            self.bar,
            text=layout.PAGE_BAR_TEXT[layout.PAGE_SETTINGS],
            command=lambda: self.selectPage(layout.PAGE_SETTINGS),
        )
        self.secondaryButton = ttk.Button(
            self.bar,
            text=layout.SECONDARY_TEXT[layout.PAGE_LOCAL],
            command=self.onExport,
        )
        self.primaryButton = ttk.Button(
            self.bar,
            text=layout.PRIMARY_TEXT[layout.PAGE_LOCAL],
            command=self.onDirectPlay,
            style="Accent.TButton",
        )
        self.bar.columnconfigure(3, weight=1)  # 中间留空，把右侧按钮推到最右

        # ---- 三个页面 ----
        self.pages = {}
        self.pageCards = {}
        for page, sections in (
            (layout.PAGE_LOCAL, layout.PAGE_SECTIONS[layout.PAGE_LOCAL]),
            (layout.PAGE_LIVE, layout.PAGE_SECTIONS[layout.PAGE_LIVE]),
            (layout.PAGE_SETTINGS, layout.settingsSections(self.hasUiSwitch)),
        ):
            pageFrame = ttk.Frame(self.root)
            self.pages[page] = pageFrame
            self.pageCards[page] = {}
            for title, _ in sections:
                card = self._makeCard(pageFrame)
                self._addCardTitle(card, title)
                self.pageCards[page][title] = card

        # ---- 本地模式：音频效果 ----
        audio = self.pageCards[layout.PAGE_LOCAL]["音频效果"]
        self.ysddCkBt = ttk.Checkbutton(
            audio,
            text=layout.CHECKS["ysddCkBt"][0],
            variable=self.inYsddMode,
            onvalue=True,
            offvalue=False,
        )
        self.normCkBt = ttk.Checkbutton(
            audio,
            text=layout.CHECKS["normCkBt"][0],
            variable=self.normAudio,
            onvalue=True,
            offvalue=False,
        )
        self.reverseCkBt = ttk.Checkbutton(
            audio,
            text=layout.CHECKS["reverseCkBt"][0],
            variable=self.reverseAudio,
            onvalue=True,
            offvalue=False,
        )

        self.pitchMultLabel = ttk.Label(
            audio, text=layout.SLIDER_TEXTS["pitchMultLabel"]
        )
        self.pitchMultValue = ttk.Label(audio, text="", width=5, anchor="e")
        self.pitchMultScale = ttk.Scale(
            audio,
            from_=0.5,
            to=2.0,
            orient=HORIZONTAL,
            length=int(layout.SLIDER_LENGTH * self.scale),
            variable=self.pitchMultOption,
            command=lambda raw: self._showSliderValue(
                self.pitchMultOption, self.pitchMultValue, 1
            ),
        )

        self.speedMultLable = ttk.Label(
            audio, text=layout.SLIDER_TEXTS["speedMultLable"]
        )
        self.speedMultValue = ttk.Label(audio, text="", width=5, anchor="e")
        self.speedMultScale = ttk.Scale(
            audio,
            from_=0.5,
            to=2.0,
            orient=HORIZONTAL,
            length=int(layout.SLIDER_LENGTH * self.scale),
            variable=self.speedMultOption,
            command=lambda raw: self._showSliderValue(
                self.speedMultOption, self.speedMultValue, 1
            ),
        )

        self.volumeMultLable = ttk.Label(
            audio, text=layout.SLIDER_TEXTS["volumeMultLable"]
        )
        self.volumeMultValue = ttk.Label(audio, text="", width=5, anchor="e")
        self.volumeMultScale = ttk.Scale(
            audio,
            from_=0,
            to=3,
            orient=HORIZONTAL,
            length=int(layout.SLIDER_LENGTH * self.scale),
            variable=self.volumeMultOption,
            command=lambda raw: self._showSliderValue(
                self.volumeMultOption, self.volumeMultValue, 2
            ),
        )

        # ---- 直播模式：播报内容 + 直播与窗口 ----
        danmu = self.pageCards[layout.PAGE_LIVE]["播报内容"]
        self.chuanhuaCkBt = ttk.Checkbutton(
            danmu,
            text=layout.CHECKS["chuanhuaCkBt"][0],
            variable=self.ischuanhuaon,
            onvalue=True,
            offvalue=False,
        )
        self.keywordCkBt = ttk.Checkbutton(
            danmu,
            text=layout.CHECKS["keywordCkBt"][0],
            variable=self.iskeywordspoton,
            onvalue=True,
            offvalue=False,
        )
        self.welcomeCkBt = ttk.Checkbutton(
            danmu,
            text=layout.CHECKS["welcomeCkBt"][0],
            variable=self.iswelcomeon,
            onvalue=True,
            offvalue=False,
        )
        self.giftCkBt = ttk.Checkbutton(
            danmu,
            text=layout.CHECKS["giftCkBt"][0],
            variable=self.isgifton,
            onvalue=True,
            offvalue=False,
        )

        liveWindow = self.pageCards[layout.PAGE_LIVE]["直播与窗口"]
        self.hidemsgCkBt = ttk.Checkbutton(
            liveWindow,
            text=layout.CHECKS["hidemsgCkBt"][0],
            variable=self.ishidemsgon,
            onvalue=True,
            offvalue=False,
            command=self.hidemsg,
        )
        self.tipWindowCkBt = ttk.Checkbutton(
            liveWindow,
            text=layout.CHECKS["tipWindowCkBt"][0],
            variable=self.istipWindowon,
            onvalue=True,
            offvalue=False,
            command=self.toggleTipWindow,
        )

        # ---- 高级设置页 ----
        sound = self.pageCards[layout.PAGE_SETTINGS]["音频素材"]
        self.text1_1 = ttk.Label(sound, text=layout.PATHS["configButton1"][1] + "：")
        self.text1_2 = ttk.Label(sound, text="", style="Hint.TLabel")
        self.configButton1 = ttk.Button(
            sound,
            text=layout.BUTTONS["chooseFolder"],
            command=lambda: self.setConfig("sourceDirectory"),
        )
        self.text2_1 = ttk.Label(sound, text=layout.PATHS["configButton2"][1] + "：")
        self.text2_2 = ttk.Label(sound, text="", style="Hint.TLabel")
        self.configButton2 = ttk.Button(
            sound,
            text=layout.BUTTONS["chooseFolder"],
            command=lambda: self.setConfig("ysddSourceDirectory"),
        )

        words = self.pageCards[layout.PAGE_SETTINGS]["词典文件"]
        self.text3_1 = ttk.Label(words, text=layout.PATHS["configButton3"][1] + "：")
        self.text3_2 = ttk.Label(words, text="", style="Hint.TLabel")
        self.configButton3 = ttk.Button(
            words,
            text=layout.BUTTONS["chooseFile"],
            command=lambda: self.setConfig("dictFile"),
        )
        self.configButton3_1 = ttk.Button(
            words,
            text=layout.BUTTONS["editDictionary"],
            command=lambda: runjsonloader(2),
        )
        self.text4_1 = ttk.Label(words, text=layout.PATHS["configButton4"][1] + "：")
        self.text4_2 = ttk.Label(words, text="", style="Hint.TLabel")
        self.configButton4 = ttk.Button(
            words,
            text=layout.BUTTONS["chooseFile"],
            command=lambda: self.setConfig("ysddTableFile"),
        )
        self.configButton4_1 = ttk.Button(
            words,
            text=layout.BUTTONS["editDictionary"],
            command=lambda: runjsonloader(3),
        )
        self.text5_1 = ttk.Label(words, text=layout.PATHS["configButton5"][1] + "：")
        self.text5_2 = ttk.Label(words, text="", style="Hint.TLabel")
        self.configButton5 = ttk.Button(
            words,
            text=layout.BUTTONS["chooseFile"],
            command=lambda: self.setConfig("keywordDir"),
        )
        self.configButton5_1 = ttk.Button(
            words,
            text=layout.BUTTONS["editDictionary"],
            command=lambda: runjsonloader(1),
        )

        run = self.pageCards[layout.PAGE_SETTINGS]["运行参数"]
        self.text6_1 = ttk.Label(run, text=layout.ENTRIES["numberArea1"][1] + "：")
        self.numberArea1 = ttk.Entry(run, width=8)
        self.text7_1 = ttk.Label(run, text=layout.ENTRIES["numberArea2"][1] + "：")
        self.numberArea2 = ttk.Entry(run, width=12)
        # 打字时实时更新"未保存"小圆点
        for entry in (self.numberArea1, self.numberArea2):
            entry.bind("<KeyRelease>", lambda event: self._refreshSettingsDot())

        # ---- 界面：新版效果（网页界面）开关，只有 Windows 上才有这张卡片 ----
        if self.hasUiSwitch:
            look = self.pageCards[layout.PAGE_SETTINGS][layout.UI_SWITCH_CARD_TITLE]
            self.newLookCkBt = ttk.Checkbutton(
                look,
                text=layout.CHECKS["newLookCkBt"][0],
                variable=self.isNewLookOn,
                onvalue=True,
                offvalue=False,
                command=self.toggleNewLook,
            )

        # ---- 关于（原来的页脚，收进设置页）----
        about = self.pageCards[layout.PAGE_SETTINGS][layout.FOOTER_CARD_TITLE]
        self.checkupdateinfo = ttk.Label(
            about, text=UPDATE_INFO_TEXT, style="Hint.TLabel"
        )
        self.checkupdateCkBt = ttk.Button(
            about, text=layout.BUTTONS["footerUpdate"], command=self.onCheckUpdate
        )
        self.updateinfoCkBt = ttk.Button(
            about, text=layout.BUTTONS["footerAbout"], command=self.showAbout
        )

    def _addCardTitle(self, card, title):
        ttk.Label(card, text=title, style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        card.columnconfigure(1, weight=1)

    def _fillCard(self, card, rows):
        """按结构描述往卡片里摆行。"""
        gridRow = 1
        for row in rows:
            if row[0] == "row":
                for column, name in enumerate(row[1]):
                    getattr(self, name).grid(
                        row=gridRow, column=column, sticky="w", padx=(0, 24), pady=3
                    )
            elif row[0] == "slider":
                _, labelName, scaleName, valueName = row
                getattr(self, labelName).grid(row=gridRow, column=0, sticky="w", pady=3)
                getattr(self, scaleName).grid(
                    row=gridRow, column=1, sticky="ew", padx=10
                )
                getattr(self, valueName).grid(row=gridRow, column=2, sticky="e")
            elif row[0] == "path":
                _, titleName, valueName, buttonName, editName = row
                getattr(self, titleName).grid(row=gridRow, column=0, sticky="w", pady=3)
                getattr(self, valueName).grid(
                    row=gridRow, column=1, sticky="w", padx=10
                )
                getattr(self, buttonName).grid(row=gridRow, column=2, sticky="e")
                if editName:
                    getattr(self, editName).grid(
                        row=gridRow, column=3, sticky="e", padx=(6, 0)
                    )
            elif row[0] == "entry":
                _, titleName, entryName = row
                getattr(self, titleName).grid(row=gridRow, column=0, sticky="w", pady=3)
                getattr(self, entryName).grid(
                    row=gridRow, column=1, sticky="w", padx=10
                )
            elif row[0] == "footer":
                _, infoName, updateName, aboutName = row
                getattr(self, infoName).grid(
                    row=gridRow, column=0, columnspan=2, sticky="w", pady=3
                )
                getattr(self, updateName).grid(
                    row=gridRow, column=2, sticky="e", padx=(6, 0)
                )
                getattr(self, aboutName).grid(
                    row=gridRow, column=3, sticky="e", padx=(6, 0)
                )
            gridRow += 1

    def _makeCard(self, parent):
        """卡片容器。

        Windows 上有 sv-ttk，直接用主题的卡片样式（自带背景和描边）；
        其它平台的 ttk 原生主题会忽略 frame 背景，所以改用经典 Frame 自己上色，
        否则卡片和窗口底色一样，看不出分区。
        """
        if self.themeName:
            return ttk.Frame(parent, style="Card.TFrame", padding=layout.CARD_PADDING)
        # 其它平台用"描边卡片"：底色和窗口一致（这样卡片里的 ttk 控件不会
        # 出现颜色不搭的方块），靠 1px 描边划分区域
        return tk.Frame(
            parent,
            background=self.root.cget("background"),
            padx=layout.CARD_PADDING,
            pady=layout.CARD_PADDING,
            highlightthickness=1,
            highlightbackground="#d8d8d8",
        )

    def _showSliderValue(self, variable, label, digits):
        """滑块的数值没有内置显示（tk.Scale 有，ttk.Scale 没有），这里补一个标签。"""
        try:
            label.configure(text=format(float(variable.get()), ".{}f".format(digits)))
        except (ValueError, tk.TclError):
            pass

    def _setupStyles(self):
        """套用界面主题：Windows 上用 Windows 11 风格，其它平台保持系统默认。

        顺带把字体和经典控件的配色统一好——ttk 控件不接受 font 选项，
        经典控件（文本框）不跟着主题变色，两件事都要在这里补。
        """
        self.style = ttk.Style(self.root)

        if sys.platform == "win32":
            try:
                import sv_ttk

                theme = "light"
                try:
                    import darkdetect

                    theme = darkdetect.theme() or "light"
                except ImportError:
                    pass
                sv_ttk.set_theme(theme.lower())
                self.themeName = theme.lower()
            except ImportError:
                self.themeName = ""  # 没装主题包就退回系统默认，程序照常能用
        else:
            self.themeName = ""

        # 字体：Windows 上用微软雅黑（原来是每个控件单独指定，现在统一走样式）
        for name, size in (("TButton", 11), ("TCheckbutton", 10), ("TLabel", 10)):
            self.style.configure(name, font=font.Font(family="微软雅黑", size=size))

        # 卡片标题、页脚提示的层级
        self.style.configure(
            "Section.TLabel", font=font.Font(family="微软雅黑", size=11, weight="bold")
        )
        self.style.configure("Hint.TLabel", font=font.Font(family="微软雅黑", size=9))

        # 卡片底色：Windows 上 sv-ttk 已经带 Card.TFrame；其它平台给个浅色，
        # 让卡片和窗口底色区分开
        if not self.themeName:
            self.style.configure("Card.TFrame", background="#f2f2f2")

    def _styleTextView(self, textWidget):
        """让经典 tk 的文本框跟上主题配色（ttk 没有文本框控件）。"""
        if not self.themeName:
            return
        try:
            background = self.style.lookup("TFrame", "background")
            foreground = self.style.lookup("TLabel", "foreground")
            if background and foreground:
                textWidget.configure(
                    background=background,
                    foreground=foreground,
                    insertbackground=foreground,
                )
        except tk.TclError:
            pass

    def layout(self):
        """摆好固定区域、页面栏和三个页面，并设置初始状态。"""
        pad = layout.OUTER_PADDING

        self.outputCard.pack(fill="both", expand=True, padx=pad, pady=(pad, 6))
        self.outputTitle.pack(anchor="w", pady=(0, 6))
        self.textArea1.pack(fill="both", expand=True)

        self.bar.pack(fill="x", padx=pad, pady=6)
        self.pageLocal.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.pageLive.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.pageSettings.grid(row=0, column=2, sticky="ew", padx=(0, 12))
        self.secondaryButton.grid(row=0, column=4, padx=6)
        self.primaryButton.grid(row=0, column=5, padx=(6, 0))

        # 各页卡片的内容只填一次
        for page, sections in (
            (layout.PAGE_LOCAL, layout.PAGE_SECTIONS[layout.PAGE_LOCAL]),
            (layout.PAGE_LIVE, layout.PAGE_SECTIONS[layout.PAGE_LIVE]),
            (layout.PAGE_SETTINGS, layout.settingsSections(self.hasUiSwitch)),
        ):
            for title, rows in sections:
                card = self.pageCards[page][title]
                self._fillCard(card, rows)
                card.pack(fill="x", padx=pad, pady=6)

        self.pitchMultOption.set(layout.SLIDER_DEFAULT)
        self.speedMultOption.set(layout.SLIDER_DEFAULT)
        self.volumeMultOption.set(layout.SLIDER_DEFAULT)
        self._showSliderValue(self.pitchMultOption, self.pitchMultValue, 1)
        self._showSliderValue(self.speedMultOption, self.speedMultValue, 1)
        self._showSliderValue(self.volumeMultOption, self.volumeMultValue, 2)

        self.iswelcomeon.set(True)
        self.ischuanhuaon.set(True)
        self.isgifton.set(True)
        self.refreshSettingsLabels()
        self.setLiveMode(False)  # 默认本地模式

    # ---------------- 新版 / 经典界面切换 ----------------

    def toggleNewLook(self):
        """设置页的「新版效果」：打开就换成新版界面，然后关掉这个窗口。

        两套界面都在同一个程序里，只是换法不同：
            Windows 换同一个进程里的网页后端：记下目标后端、让 main() 重启；
            macOS   换同一个 .app 里的另一个可执行文件（SwiftUI 原生界面）：
                    直接 execv 过去，进程号不变，Dock 上还是这个 app。

        卡片摆出来不等于真的能切（Windows 缺 WebView2、macOS 上原生界面
        没编译或者系统版本不够都可能），所以真点下去的时候再确认一次，
        切不了就提示并把开关拨回去。
        """
        if not self.isNewLookOn.get():
            return  # 已经是经典界面了

        if not newLookAvailable():
            self.isNewLookOn.set(False)
            self.showWarning("新版界面用不了", self.newLookHint())
            return

        if not self.canSwitchNow():
            self.isNewLookOn.set(False)
            return

        # 先记下选择：重启/下次启动要靠它决定进哪套界面
        setNewUi(True)

        if sys.platform == "darwin":
            self.showInfo("切换界面", "正在打开原生界面…")
            self.root.update()  # 先把那句提示画出来，再交班
            if not nativeapp.execIntoNativeUi():
                setNewUi(False)
                self.isNewLookOn.set(False)
                self.showWarning("新版界面用不了", self.newLookHint())
                return
            return  # execv 成功就换过去了；能往下走说明没换成

        self.showInfo("切换界面", "正在换成新版界面，程序会重启一次")
        switchBackendLater("webview")
        self.root.destroy()

    def newLookHint(self):
        """切不过去时告诉用户缺什么。"""
        if sys.platform == "darwin":
            return (
                "没找到原生界面（SwiftUI）的可执行文件，或者系统版本低于 "
                "macOS 26。\n打包好的程序里它和主程序放在一起；源码运行时先在 "
                "mac/ 里执行 swift build -c release，"
                "也可以用 HZYS_NATIVE_APP 指定它的位置。"
            )
        return "这台机器上没检测到可用的 WebView2 运行时，只能用经典界面。"

    def canSwitchNow(self):
        """直播中、登录中不让换界面：换界面要换进程，会把这些状态一起打断。"""
        if self.running or self.busy:
            self.showWarning("暂时不能切换", "正在直播或登录，先停掉再换界面")
            return False
        return True

    def selectPage(self, page):
        """用户点了页面栏。本地/直播会改变直播模式，高级设置只是切页。"""
        if page == layout.PAGE_SETTINGS:
            self.page = layout.PAGE_SETTINGS
            self._refreshBar()
            self._showPage(self.page)
            return

        # 本地/直播这两个页面就是直播模式的开关
        self.iflivemodeon.set(page == layout.PAGE_LIVE)
        self.onToggleLiveMode()  # 线程和事件由 main.py 处理，完了会回调 setLiveMode

    def setLiveMode(self, entering):
        """直播模式的界面表现（main.py 处理完线程/事件后回调这里）。"""
        self.liveMode = entering
        self.running = False
        self.page = layout.PAGE_LIVE if entering else layout.PAGE_LOCAL

        state = "normal" if entering else "disabled"
        for name in (
            "keywordCkBt",
            "welcomeCkBt",
            "hidemsgCkBt",
            "chuanhuaCkBt",
            "giftCkBt",
            "tipWindowCkBt",
        ):
            getattr(self, name).config(state=state)

        if not entering:
            self.textArea1.config(state="normal")  # 自动重置文本框
            self.ishidemsgon.set(False)
            self.istipWindowon.set(False)
        self.textArea1.delete("1.0", "end")

        self._refreshBar()
        self._showPage(self.page)

    def setBroadcastRunning(self, running):
        """开播/停播：主按钮在 启动/停止 之间切换。"""
        self.running = running
        for widget in (self.pageLocal, self.pageLive, self.pageSettings):
            widget.config(state="disable" if running else "normal")
        self._refreshBar()

    def setLoginBusy(self, busy):
        """扫码登录过程中禁用相关按钮。"""
        self.busy = bool(busy)
        state = "disable" if busy else "normal"
        for widget in (
            self.primaryButton,
            self.secondaryButton,
            self.pageLocal,
            self.pageLive,
        ):
            widget.config(state=state)

    def _refreshBar(self):
        """按当前页面刷新：选中态 + 右侧两个按钮的文字与动作。"""
        active = "Accent.TButton" if self.themeName else "Selected.TButton"
        for page, widget in (
            (layout.PAGE_LOCAL, self.pageLocal),
            (layout.PAGE_LIVE, self.pageLive),
            (layout.PAGE_SETTINGS, self.pageSettings),
        ):
            widget.configure(style=active if page == self.page else "TButton")

        secondaryActions = {
            layout.PAGE_LOCAL: self.onExport,
            layout.PAGE_LIVE: self.onTrytologin,
            layout.PAGE_SETTINGS: self.setConfigtodef,
        }
        self.secondaryButton.configure(
            text=layout.SECONDARY_TEXT[self.page],
            command=secondaryActions[self.page],
        )

        if self.running:
            text, command = layout.PRIMARY_TEXT["running"], self.onStopLive
        elif self.page == layout.PAGE_LIVE:
            text, command = layout.PRIMARY_TEXT[layout.PAGE_LIVE], self.onStartLive
        elif self.page == layout.PAGE_SETTINGS:
            text, command = layout.PRIMARY_TEXT[layout.PAGE_SETTINGS], self.saveSettings
        else:
            text, command = layout.PRIMARY_TEXT[layout.PAGE_LOCAL], self.onDirectPlay
        self.primaryButton.configure(text=text, command=command)
        self._refreshSettingsDot()

    def _showPage(self, page):
        """内容区只显示当前页。"""
        pad = layout.OUTER_PADDING
        for frame in self.pages.values():
            frame.pack_forget()
        self.pages[page].pack(fill="both", expand=True, padx=pad, pady=6)

    def callLater(self, func, *args):
        """把回调排进主线程的事件循环（工作线程里调用也安全）。

        业务逻辑不直接碰 Tk 的 after；换成别的界面实现时，
        这里对应换成向主线程投递任务即可。
        """
        try:
            self.root.after(0, func, *args)
        except Exception:
            pass  # 窗口已经销毁（比如正在退出），丢掉这次刷新就行

    def getInputText(self):
        """读取输入框里的内容。

        Tk 的 Text 取出来结尾总多一个换行（空的时候就是 "\\n"），
        去掉它，和另外两个后端保持一致，也免得空输入被当成一个待播报字符。
        """
        text = self.textArea1.get("1.0", "end")
        return text[:-1] if text.endswith("\n") else text

    def appendOutput(self, text):
        """往当前输出框追加一行内容（弹幕上屏、程序日志都走这里）。"""
        try:
            self.textArea.insert("end", text)
            self.textArea.see("end")
        except Exception:
            pass

    def redirectStdout(self):
        """把 print 的输出接到界面文本框上。"""
        sys.stdout = StdoutRedirector(self)
        return sys.stdout

    def hidemsg(self):
        """勾选后禁用输出文本框，缓解大量弹幕时的卡顿。"""
        state = "disabled" if self.ishidemsgon.get() else "normal"
        self.textArea1.config(state=state)
        if self.textArea2 is not None and self.textArea2.winfo_exists():
            self.textArea2.config(state=state)

    def toggleTipWindow(self):
        if self.istipWindowon.get():
            self.textWindow = Toplevel(self.root)
            self.textWindow.geometry(self._scaledSize(layout.OUTPUT_WINDOW_SIZE))
            self.textWindow.title("输出")
            self.textArea2 = scrolledtext.ScrolledText(
                self.textWindow,
                width=55,
                height=60,
                font=font.Font(family="微软雅黑", size=10),
            )
            self._styleTextView(self.textArea2)
            self.textArea = self.textArea2
            self._place(self.textArea2, (10, 0))
            self.textWindow.attributes("-topmost", True)
        else:
            self.textArea = self.textArea1
            if self.textWindow is not None and self.textWindow.winfo_exists():
                self.textWindow.destroy()
            self.textWindow = None
            self.textArea2 = None

    # ---------------- 关于 ----------------

    def onCheckUpdate(self):
        """「更新」按钮：真去查一次有没有新版本（网络在后台线程跑）。"""
        startUpdateCheck(self)

    def showAbout(self):
        """关于窗口：内容和按钮跟新版界面的同名弹层保持一致。"""
        self.aboutWindow = Toplevel(self.root)
        self.aboutWindow.geometry(self._scaledSize(layout.ABOUT_WINDOW_SIZE))
        self.aboutWindow.title(layout.FOOTER_CARD_TITLE)
        self.aboutWindow.resizable(False, False)
        aboutText = scrolledtext.ScrolledText(
            self.aboutWindow,
            width=55,
            height=20,
            font=font.Font(family="微软雅黑", size=10),
        )
        self._place(aboutText, (10, 0))
        aboutText.insert("end", getupdateinfo())
        aboutText.config(state="disabled")

        buttons = ttk.Frame(self.aboutWindow)
        self._place(buttons, (10, 300))
        ttk.Button(
            buttons, text=layout.BUTTONS["aboutAuthor"], command=openAuthorPage
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons, text=layout.BUTTONS["aboutUpdate"], command=checkupdate
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons, text=layout.BUTTONS["aboutClose"], command=self.aboutWindow.destroy
        ).pack(side="left")

    def close(self):
        """关闭窗口（契约检查等外部调用用）。"""
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.update()  # 先让窗口真正映射出来，DWM 需要真实窗口句柄
        self.applyPlatformEffects()
        self.root.mainloop()

    def applyPlatformEffects(self):
        """套用平台专有的窗口效果，返回实际生效的项目。

        目前只有 Windows：深色标题栏 / 圆角 / Mica 底板。
        底板类型可以用 HZYS_BACKDROP=mica|acrylic|none 临时切换，方便对比效果。
        """
        if sys.platform != "win32":
            return []

        backdrops = {
            "mica": win_dwm.BACKDROP_MICA,
            "acrylic": win_dwm.BACKDROP_ACRYLIC,
            "none": win_dwm.BACKDROP_NONE,
        }
        chosen = backdrops.get(os.environ.get("HZYS_BACKDROP", "mica").lower())
        # 深浅色跟随系统，和 sv-ttk 的主题保持一致
        applied = win_dwm.applyWindowEffects(
            self.root, backdrop=chosen or win_dwm.BACKDROP_MICA
        )
        if applied:
            logToConsole("已启用窗口效果: " + ", ".join(applied))
        return applied

    # ---------------- 设置窗口 ----------------

    def askSaveFileName(self, title, filetypes, defaultName=""):
        """弹"另存为"对话框；用户取消时返回空字符串。"""
        return filedialog.asksaveasfilename(
            title=title, filetypes=filetypes, initialfile=defaultName
        )

    def askYesNo(self, title, text):
        """问一句"要不要"；只能在主线程里调（检查更新会经 callLater 回来）。"""
        return bool(messagebox.askyesno(title, text))

    def showInfo(self, title, text):
        """提示对话框。"""
        messagebox.showinfo(title, text)

    def showWarning(self, title, text):
        """警告对话框。"""
        messagebox.showwarning(title, text)

    def showLoginCode(self, imageBytes, status, done):
        """扫码登录：在窗口里显示二维码和状态（和网页界面那个面板对齐）。"""

        def apply():
            if (
                getattr(self, "loginWindow", None) is None
                or not self.loginWindow.winfo_exists()
            ):
                self._buildLoginWindow()
            if imageBytes:
                from io import BytesIO

                image = Image.open(BytesIO(imageBytes))
                self.loginImage = ImageTk.PhotoImage(image)
                self.loginImageLabel.configure(image=self.loginImage)
            self.loginStatus.configure(text=status or "")
            if done and "成功" in (status or ""):
                self.root.after(1200, self._closeLoginWindow)

        self.callLater(apply)

    def _buildLoginWindow(self):
        self.loginWindow = Toplevel(self.root)
        self.loginWindow.title("扫码登录")
        self.loginWindow.resizable(False, False)
        frame = ttk.Frame(self.loginWindow, padding=14)
        frame.pack(fill="both", expand=True)
        self.loginImageLabel = ttk.Label(frame)
        self.loginImageLabel.pack()
        self.loginStatus = ttk.Label(
            frame, text="", style="Hint.TLabel", wraplength=240
        )
        self.loginStatus.pack(pady=(10, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(pady=(12, 0))
        ttk.Button(buttons, text="重新获取二维码", command=self.onTrytologin).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(
            buttons, text=layout.BUTTONS["aboutClose"], command=self._closeLoginWindow
        ).pack(side="left")

    def _closeLoginWindow(self):
        try:
            self.loginWindow.destroy()
        except Exception:
            pass
        self.loginWindow = None

    def refreshSettingsLabels(self):
        """把设置页上的控件刷新成暂存里的值。"""
        for option, labelName in (
            ("sourceDirectory", "text1_2"),
            ("ysddSourceDirectory", "text2_2"),
            ("dictFile", "text3_2"),
            ("ysddTableFile", "text4_2"),
            ("keywordDir", "text5_2"),
        ):
            value = self.draft.get(option)
            # 素材还是程序自带的那份时，显示"程序自带"，不显示长路径
            if isBuiltinAssetPath(option, value):
                value = layout.BUILTIN_ASSETS_TEXT
            getattr(self, labelName).configure(text=value)

        self.numberArea1.delete(0, "end")
        self.numberArea1.insert(0, str(self.draft.get("numOfThreads")))
        self.numberArea2.delete(0, "end")
        self.numberArea2.insert(0, str(self.draft.get("roomID")))

    def _entryValues(self):
        """输入框里的当前值（还没进暂存，但算不算改动要看它们）。"""
        return {
            "numOfThreads": self.numberArea1.get().strip(),
            "roomID": self.numberArea2.get().strip(),
        }

    def hasPendingChanges(self):
        """设置页上是否有还没保存的改动（登录信息不算）。"""
        return self.draft.isDirty(self._entryValues())

    def _refreshSettingsDot(self):
        """有未保存改动时，在"高级设置"按钮上加个小圆点提示。"""
        text = layout.PAGE_BAR_TEXT[layout.PAGE_SETTINGS]
        if self.hasPendingChanges():
            text += "  ●"
        self.pageSettings.configure(text=text)

    def setConfig(self, option):
        """选一个文件或目录，先记进设置页的暂存，按"保存"才写回。"""
        if option in ("sourceDirectory", "ysddSourceDirectory"):
            chosen = filedialog.askdirectory(title="选择文件夹")
            if not chosen:
                return  # 用户取消
            chosen += "/"
        else:
            chosen = filedialog.askopenfilename(
                title="选择文件", filetypes=(("json配置文件", "*.json"),)
            )
            if not chosen:
                return

        self.draft.set(option, chosen)
        self.refreshSettingsLabels()
        self._refreshSettingsDot()

    def setConfigtodef(self):
        """把设置页恢复成默认值（同样只是暂存，按"保存"才写回）。"""
        self.draft.resetToDefault()
        self.refreshSettingsLabels()
        self._refreshSettingsDot()
        self.showInfo("恢复默认设置", "已填回默认值，按【保存】生效")

    def saveSettings(self):
        """保存设置页：把输入框里的值收进来，写回 settings.json 并重建音频引擎。"""
        self.draft.save(self._entryValues())
        self.refreshSettingsLabels()
        self._refreshSettingsDot()
        self.onSettingsSaved()
        self.showInfo("保存设置", "设置已保存")


class StdoutRedirector:
    """把 print/stderr 送进界面文本框；工作线程调用也安全。"""

    def __init__(self, window):
        self.window = window
        self.stdoutbak = sys.stdout
        self.stderrbak = sys.stderr

    def write(self, text):
        try:
            self.window.root.after(0, self.window.appendOutput, text)
        except Exception:
            pass

    def restoreStd(self):
        sys.stdout = self.stdoutbak
        sys.stderr = self.stderrbak

    def flush(self):
        pass
