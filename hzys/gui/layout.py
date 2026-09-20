# -*- coding: UTF-8 -*-
"""界面布局参数。

所有后端（Tk / pywebview / SwiftUI 原生界面）共用这一份结构描述，
这样各套界面的分区、顺序和文案由数据结构保证一致，而不是靠各处手写对齐。
"""

from .. import __version__

# ---------------- 窗口尺寸（像素；后端按自己的 DPI 处理方式使用）----------------

OUTPUT_WINDOW_SIZE = (480, 600)  # 置顶输出窗口
ABOUT_WINDOW_SIZE = (480, 400)

# ---------------- 模式与分区结构 ----------------
#
# 界面分三个页面：本地播放&导出 / 直播模式 / 高级设置。
# 顶部是固定的输出框，中间是页面栏，下半区的内容随页面切换。
#
# 主窗口按"卡片"组织：每个分区是一张卡片，卡片里是若干行。
# 行的几种写法：
#   ("row", [控件名, ...])                一行里并排若干控件
#   ("slider", 标签名, 滑轨名, 数值名)     标签 + 滑轨 + 数值
#   ("path", 标题名, 当前值名, 选择按钮名, 编辑按钮名或None)
#   ("entry", 标题名, 输入框名)
#   ("footer", 信息名, 更新按钮名, 更多按钮名)
#
# 各套界面都读这份结构，保证分区、顺序、分组完全一致。

# 三个页面：本地播放&导出 / 直播模式 / 高级设置
PAGE_LOCAL = "local"
PAGE_LIVE = "live"
PAGE_SETTINGS = "settings"

PAGE_SECTIONS = {
    PAGE_LOCAL: [
        (
            "音频效果",
            [
                # 一行一个开关：macOS 的设置面板就是这么排的
                ("row", ["ysddCkBt"]),
                ("row", ["normCkBt"]),
                ("row", ["reverseCkBt"]),
                ("slider", "pitchMultLabel", "pitchMultScale", "pitchMultValue"),
                ("slider", "speedMultLable", "speedMultScale", "speedMultValue"),
                ("slider", "volumeMultLable", "volumeMultScale", "volumeMultValue"),
            ],
        ),
    ],
    PAGE_LIVE: [
        (
            "播报内容",
            [
                ("row", ["chuanhuaCkBt"]),
                ("row", ["keywordCkBt"]),
                ("row", ["welcomeCkBt"]),
                ("row", ["giftCkBt"]),
            ],
        ),
        (
            "直播与窗口",
            [
                ("row", ["hidemsgCkBt"]),
                ("row", ["tipWindowCkBt"]),
            ],
        ),
    ],
}

# 页面栏上的文字
PAGE_BAR_TEXT = {
    PAGE_LOCAL: "本地播放&导出",
    PAGE_LIVE: "直播模式",
    PAGE_SETTINGS: "高级设置",
}

# 右侧两个按钮的文字：跟着当前页面变
SECONDARY_TEXT = {
    PAGE_LOCAL: "导出",
    PAGE_LIVE: "登录",
    PAGE_SETTINGS: "恢复默认",
}

PRIMARY_TEXT = {
    PAGE_LOCAL: "播放",
    PAGE_LIVE: "启动",
    PAGE_SETTINGS: "保存",
    "running": "停止",
}

# 没登录过就点"启动"时的提示
NEED_LOGIN_TEXT = "请先登录"

# 设置页最后那张卡片的名字：它是卡片标题，也是点开后的弹层标题。
# 打开它的那个按钮文字见 BUTTONS["footerAbout"]。
# 后端不要按文字去找卡片（改个名字就会 KeyError），一律用这个常量。
FOOTER_CARD_TITLE = "关于"

# 设置页里「新版效果」那张卡片的名字。只有 Windows 上才有这张卡片
# （见 gui.canOfferNewLook），macOS 上整张卡片都不出现。
UI_SWITCH_CARD_TITLE = "界面"


# 各个按钮的文案：两个界面后端都从这里取。
# 之前 Tk 写"选择目录/编辑字典"、网页写"选择/编辑"，两边对不上，
# 现在统一放这儿，避免以后再各写各的。
BUTTONS = {
    "chooseFolder": "选择目录",  # 设置页里选目录
    "chooseFile": "选择文件",  # 设置页里选文件
    "editDictionary": "编辑",  # 打开词典编辑器
    "dictAdd": "添加",  # 词典编辑器：新增一条
    "dictDelete": "删除",  # 词典编辑器：删掉一条
    "dictSave": "保存",  # 词典编辑器：写回文件
    "dictCancel": "取消",
    "aboutAuthor": "作者主页",  # FOOTER_CARD_TITLE 那个窗口/弹层
    "aboutUpdate": "打开更新页",
    "aboutClose": "关闭",
    "footerUpdate": "更新",  # 设置页页脚
    # 省略号表示"点了还会再弹一层"，跟 macOS 的习惯一致
    "footerAbout": "更多…",
}

# ---------------- 界面上的文字：两个后端共用 ----------------
#
# 下面这些以前在两个后端里各写一份，改一处就得记得改另一处，
# 现在统一放这里，两边都从这里取。

# 版本号在 hzys/__init__.py 里，窗口标题从这里拼
APP_VERSION = __version__
WINDOW_TITLE = "电棍棍活字 ver." + APP_VERSION
OUTPUT_CARD_TITLE = "弹幕输出"
INPUT_PLACEHOLDER = "在这里输入要播报的文字"

# 素材路径还是默认值时，设置页里显示这个，不显示一串长路径
BUILTIN_ASSETS_TEXT = "程序自带"

# 页脚那行更新信息（完整的说明在 update.getupdateinfo() 的「关于」里）
FOOTER_INFO_TEXT = "最后更新于 2026.09.20  by 襄肠\n"

# 勾选项：控件名 -> (显示文字, 取值器名)
CHECKS = {
    "chuanhuaCkBt": ("读弹幕", "ischuanhuaon"),
    "keywordCkBt": ("敏感词屏蔽", "iskeywordspoton"),
    "welcomeCkBt": ("进场欢迎", "iswelcomeon"),
    "giftCkBt": ("感谢礼物", "isgifton"),
    "ysddCkBt": ("匹配到特定文字时使用原声大碟", "inYsddMode"),
    "normCkBt": ("音量统一", "normAudio"),
    "reverseCkBt": ("频音放倒", "reverseAudio"),
    "hidemsgCkBt": ("隐藏日志(用于缓解大量弹幕时的卡顿问题)", "ishidemsgon"),
    "tipWindowCkBt": ("置顶弹幕输出", "istipWindowon"),
    "newLookCkBt": ("新版效果", "isNewLookOn"),
}

# 滑块：标签控件名 -> (取值器名, 最小, 最大, 步长, 小数位)
SLIDERS = {
    "pitchMultLabel": ("pitchMultOption", 0.5, 2.0, 0.1, 1),
    "speedMultLable": ("speedMultOption", 0.5, 2.0, 0.1, 1),
    "volumeMultLable": ("volumeMultOption", 0.0, 3.0, 0.01, 2),
}
SLIDER_TEXTS = {
    "pitchMultLabel": "音调偏移",
    "speedMultLable": "播放速度",
    "volumeMultLable": "音量增益",
}

# 设置页：选择按钮 -> (settings.json 字段, 标题)
PATHS = {
    "configButton1": ("sourceDirectory", "活字印刷单字音频存放文件夹"),
    "configButton2": ("ysddSourceDirectory", "活字印刷原声大碟音频文件夹"),
    "configButton3": ("dictFile", "非中文字符读法字典"),
    "configButton4": ("ysddTableFile", "原声大碟关键词对照表"),
    "configButton5": ("keywordDir", "敏感词词库"),
}

# 词典编辑按钮 -> jsonloader 的模式编号
EDITORS = {
    "configButton3_1": 2,  # 读法字典
    "configButton4_1": 3,  # 原声大碟对照表
    "configButton5_1": 1,  # 敏感词词库
}

# 运行参数输入框：控件名 -> (settings.json 字段, 标题)
ENTRIES = {
    "numberArea1": ("numOfThreads", "线程数(1-5)"),
    "numberArea2": ("roomID", "房间号"),
}

# ---------------- 高级设置页（内嵌，不再是弹窗）----------------
#
# 行里多两种写法：
#   ("path", 标题名, 当前值名, 选择按钮名, 编辑按钮名或None)
#   ("entry", 标题名, 输入框名)
#   ("footer", 信息名, 更新按钮名, 关于按钮名)
#
# 设置页上的改动都是暂存的，只有按右上角「保存」才写回 settings.json。

# 设置页的前三张卡片：音频素材 / 词典文件 / 运行参数。每个平台都有。
SETTINGS_CORE_SECTIONS = [
    (
        "音频素材",
        [
            ("path", "text1_1", "text1_2", "configButton1", None),
            ("path", "text2_1", "text2_2", "configButton2", None),
        ],
    ),
    (
        "词典文件",
        [
            ("path", "text3_1", "text3_2", "configButton3", "configButton3_1"),
            ("path", "text4_1", "text4_2", "configButton4", "configButton4_1"),
            ("path", "text5_1", "text5_2", "configButton5", "configButton5_1"),
        ],
    ),
    (
        "运行参数",
        [
            ("entry", "text6_1", "numberArea1"),
            ("entry", "text7_1", "numberArea2"),
        ],
    ),
]

# 「新版效果」这张卡片：新版 = 网页界面（WebView2），关掉就是经典界面。
# 这个开关只影响本次运行，不写进 settings.json，所以不管怎么切，
# 下次启动还是按平台默认来。它只在 Windows 上出现。
UI_SWITCH_SECTION = (
    UI_SWITCH_CARD_TITLE,
    [
        ("row", ["newLookCkBt"]),
    ],
)

# 收进设置页的页脚（更新信息 + 更新/更多按钮）
ABOUT_SECTION = (
    FOOTER_CARD_TITLE,
    [
        ("footer", "checkupdateinfo", "checkupdateCkBt", "updateinfoCkBt"),
    ],
)


def settingsSections(includeUiSwitch=True):
    """高级设置页的卡片结构（顺序：素材 → 词典 → 参数 → [界面] → 关于）。

    includeUiSwitch 由后端按平台给（见 gui.canOfferNewLook）：Windows 上给
    True，macOS 上跑 tk 时给 False，让设置页和原生界面对齐（原生界面本身
    就是新版，摆一个"要不要用新版"的开关只会让人困惑）。
    """
    sections = list(SETTINGS_CORE_SECTIONS)
    if includeUiSwitch:
        sections.append(UI_SWITCH_SECTION)
    sections.append(ABOUT_SECTION)
    return sections


# 卡片内边距、窗口外边距、滑块最小宽度（像素，DPI 缩放后使用）
CARD_PADDING = 12
OUTER_PADDING = 12

# 滑块初值
SLIDER_DEFAULT = 1

# 滑块长度（像素，按 DPI 缩放后使用）
SLIDER_LENGTH = 200


# ---------------- 结构描述（各界面后端共用）----------------
#
# 下面两个函数把上面的结构表转成"能直接渲染"的 JSON：
# 网页后端拿它生成 DOM，原生界面（Swift）拿它生成 SwiftUI 视图。
# 放在这里是为了让几套界面的控件、顺序、文案必然一致——各写一份迟早会漂。


def rowPayload(row):
    """一行结构描述 -> 渲染用的对象。"""
    kind = row[0]
    if kind == "row":
        return {
            "kind": "row",
            "items": [
                {"name": name, "text": CHECKS[name][0], "var": CHECKS[name][1]}
                for name in row[1]
            ],
        }
    if kind == "slider":
        _, labelName, _, _ = row
        var, low, high, step, digits = SLIDERS[labelName]
        return {
            "kind": "slider",
            "label": SLIDER_TEXTS[labelName],
            "var": var,
            "min": low,
            "max": high,
            "step": step,
            "digits": digits,
        }
    if kind == "path":
        _, _, _, buttonName, editName = row
        option, title = PATHS[buttonName]
        return {
            "kind": "path",
            "title": title,
            "option": option,
            "editor": EDITORS.get(editName) if editName else None,
            "choose": BUTTONS[
                (
                    "chooseFolder"
                    if option in ("sourceDirectory", "ysddSourceDirectory")
                    else "chooseFile"
                )
            ],
            "editText": BUTTONS["editDictionary"],
        }
    if kind == "entry":
        _, _, entryName = row
        option, title = ENTRIES[entryName]
        return {"kind": "entry", "title": title, "option": option}
    if kind == "footer":
        return {"kind": "footer", "text": FOOTER_INFO_TEXT}
    raise ValueError("未知的行类型: {}".format(kind))


def buildPages(includeUiSwitch=True):
    """三个页面的完整结构（卡片 + 行），各后端都渲染这一份。

    includeUiSwitch 只在"这台机器上有没有第二套界面可换"时给 True
    （见 gui.canOfferNewLook），其余情况那张「界面」卡片不出现。
    """
    pages = []
    for page in (PAGE_LOCAL, PAGE_LIVE, PAGE_SETTINGS):
        sections = (
            settingsSections(includeUiSwitch)
            if page == PAGE_SETTINGS
            else PAGE_SECTIONS[page]
        )
        pages.append(
            {
                "id": page,
                "title": PAGE_BAR_TEXT[page],
                "cards": [
                    {"title": title, "rows": [rowPayload(row) for row in rows]}
                    for title, rows in sections
                ],
            }
        )
    return pages
