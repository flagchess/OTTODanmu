# -*- coding: UTF-8 -*-
"""Windows 窗口效果：深色标题栏、圆角、Mica 底板。

全部通过 DWM 的公开 API 实现，不依赖第三方库；只在 Windows 上生效，
其它平台调用会直接返回。每一项都按系统版本做能力判断，
老系统上不支持的就静默跳过（Win10 没有圆角和 Mica）。
"""

import ctypes
import sys

# DwmSetWindowAttribute 的属性编号
DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win10 1809+ / Win11
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # 更老的 Win10 预览版
DWMWA_BORDER_COLOR = 34  # 仅 Win11 22000+
DWMWA_CAPTION_COLOR = 35  # 仅 Win11 22000+
DWMWA_TEXT_COLOR = 36  # 仅 Win11 22000+
DWMWA_WINDOW_CORNER_PREFERENCE = 33  # 仅 Win11 22000+
DWMWA_SYSTEMBACKDROP_TYPE = 38  # 仅 Win11 22621+

# 圆角取值（只用到"圆角"这一档）
CORNER_ROUND = 2

# 底板取值
BACKDROP_AUTO = 0
BACKDROP_NONE = 1
BACKDROP_MICA = 2
BACKDROP_ACRYLIC = 3
BACKDROP_TABBED = 4

# 底板编号 -> 名字（打日志用）
BACKDROP_NAMES = {
    BACKDROP_AUTO: "auto",
    BACKDROP_NONE: "none",
    BACKDROP_MICA: "mica",
    BACKDROP_ACRYLIC: "acrylic",
    BACKDROP_TABBED: "tabbed",
}


def windowsBuild():
    """返回 Windows 内部版本号（例如 Win11 22H2 是 22621）；非 Windows 返回 0。"""
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def systemDarkMode():
    """系统当前是不是深色主题。

    Mica 底板和标题栏会跟着这个取值走：只有和系统一致，
    界面才不会出现"深色底板配浅色文字"这种别扭的组合。
    """
    if sys.platform != "win32":
        return False
    try:
        import darkdetect

        return (darkdetect.theme() or "Light").lower() == "dark"
    except Exception:
        pass
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False


def windowHandle(tkWindow):
    """取 Tk 窗口对应的顶层窗口句柄（HWND）。

    Tk 的 winfo_id() 给的是内层子窗口，DWM 需要的是顶层窗口，
    所以先取一次父窗口，取不到就退回自身。
    """
    if sys.platform != "win32":
        return 0
    try:
        hwnd = int(tkWindow.winfo_id())
        parent = ctypes.windll.user32.GetParent(hwnd)
        return parent or hwnd
    except Exception:
        return 0


def _setIntAttribute(hwnd, attribute, value):
    """调一次 DwmSetWindowAttribute，返回是否成功。"""
    try:
        data = ctypes.c_int(value)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(attribute),
            ctypes.byref(data),
            ctypes.sizeof(data),
        )
        return result == 0
    except Exception:
        return False


def _colorRef(hexColor):
    """#RRGGBB -> COLORREF（DWM 要的是 0x00BBGGRR）。"""
    text = str(hexColor).lstrip("#")
    red, green, blue = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    return (blue << 16) | (green << 8) | red


def _setColorAttribute(hwnd, attribute, hexColor):
    """给窗口的某个"颜色"属性赋值，返回是否成功。"""
    return _setIntAttribute(hwnd, attribute, _colorRef(hexColor))


def applyWindowEffects(tkWindow, dark=None, backdrop=BACKDROP_MICA):
    """给窗口套上 Windows 的效果，返回实际生效的项目。

    tkWindow 必须是已经映射出来的 Tk 窗口（先 update_idletasks 或 deiconify）。
    dark 留空表示跟随系统主题。
    """
    if sys.platform != "win32":
        return []

    hwnd = windowHandle(tkWindow)
    if not hwnd:
        return []

    return applyToHwnd(hwnd, dark=dark, backdrop=backdrop)


def applyToHwnd(hwnd, dark=None, backdrop=BACKDROP_MICA, captionColor=None):
    """给指定句柄的窗口套上效果（pywebview 后端直接用这个）。

    返回实际生效的项目列表；dark 留空表示跟随系统主题。
    captionColor 给了就把标题栏刷成这个颜色（默认是系统自己挑的颜色，
    和网页画的底板经常对不上，看上去是上下两块）。
    """
    applied = []

    if sys.platform != "win32" or not hwnd:
        return applied

    if dark is None:
        dark = systemDarkMode()

    # 深浅色标题栏：Win10 1809+ 和 Win11 都支持。
    # 浅色时也要显式写 0，否则会留着上一次的深色设置。
    ok = _setIntAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    if not ok:
        ok = _setIntAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, 1 if dark else 0)
    if ok:
        applied.append("dark-titlebar" if dark else "light-titlebar")

    build = windowsBuild()

    # 圆角：仅 Win11
    if build >= 22000:
        if _setIntAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, CORNER_ROUND):
            applied.append("rounded-corners")

        # 标题栏底色 = 网页底板色（DWM 要的是 COLORREF；Win11 22000+ 才有）
        if captionColor:
            if _setColorAttribute(hwnd, DWMWA_CAPTION_COLOR, captionColor):
                applied.append("caption-color")
            if _setColorAttribute(hwnd, DWMWA_BORDER_COLOR, captionColor):
                applied.append("border-color")
            textColor = "#000000" if not dark else "#ffffff"
            if _setColorAttribute(hwnd, DWMWA_TEXT_COLOR, textColor):
                applied.append("caption-text-color")

    # 底板：仅 Win11 22H2+
    if build >= 22621 and backdrop:
        if _setIntAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, backdrop):
            applied.append(BACKDROP_NAMES.get(backdrop, "backdrop"))

    return applied
