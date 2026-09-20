# -*- coding: UTF-8 -*-
"""配置读写 + 路径解析。

两种运行方式：

* **源码运行**（开发、或者直接 python main.py）——所有路径都是相对当前目录的
  （`./data/...`、`./assets/...`），所以要从项目根目录启动。行为和以前一样。
* **打包后运行**（.app / .exe）——当前目录不再是程序所在目录，相对路径会错，
  所以这里分两类处理：
    只读资源（音频素材、出厂词典）→ 打包进程序里，用 resourcePath() 取；
    可写数据（settings.json、词典、cookie、临时文件）→ 放系统惯例的用户目录，
    用 dataPath() 取。macOS 是 ~/Library/Application Support/，Windows 是 %APPDATA%。

想"配置就放在程序旁边"（便携模式）也可以：设环境变量 HZYS_DATA_DIR，
或者在程序（.app/.exe）旁边放一个 data/settings.json。
"""

import json
import os
import shutil
import sys

APP_NAME = "电棍棍活字"

# 随包带的默认词典：打包后首次运行会铺到可写目录里
SEED_FILES = ("dictionary.json", "ysddTable.json", "keyword.json")


def isPackaged():
    """是不是被打包过（PyInstaller / py2app / Nuitka 都是一样的判断）。"""
    return bool(getattr(sys, "frozen", False))


def _resourceDir():
    """只读资源在哪：打包后是程序内部，源码运行是项目根目录。"""
    if not isPackaged():
        return os.path.abspath(".")
    # PyInstaller：解到临时目录（onefile）或 _internal（onedir）
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    # py2app：Contents/Resources
    env = os.environ.get("RESOURCEPATH")
    if env:
        return env
    return os.path.dirname(os.path.abspath(sys.executable))


def _portableDataDir():
    """便携模式的数据目录；没开就返回 None。"""
    env = os.environ.get("HZYS_DATA_DIR")
    if env:
        return env
    if not isPackaged():
        return None

    # 程序旁边放了 data/settings.json 就用它
    exeDir = os.path.dirname(os.path.abspath(sys.executable))
    for candidate in (
        os.path.join(exeDir, "data"),
        os.path.join(exeDir, "..", "..", "..", "data"),  # macOS: Foo.app/Contents/MacOS
    ):
        candidate = os.path.normpath(candidate)
        if os.path.isfile(os.path.join(candidate, "settings.json")):
            return candidate
    return None


def _userDataDir():
    """可写数据放哪（打包后）。"""
    if sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, APP_NAME)


def _dataDir():
    """最终的数据目录（源码运行 = ./data）。"""
    if not isPackaged():
        return os.path.abspath("./data")
    return _portableDataDir() or _userDataDir()


def resourcePath(*parts):
    """取只读资源（音频素材、出厂词典）的路径。"""
    return os.path.join(_resourceDir(), *parts)


def dataPath(*parts):
    """取可写数据（配置、词典、cookie、临时文件）的路径。"""
    directory = _dataDir()
    if parts:
        return os.path.join(directory, *parts)
    return directory


def _defaultAsset(name):
    """素材目录的默认值：源码运行用相对路径，打包后用包内的绝对路径。"""
    if isPackaged():
        return resourcePath("assets", name).replace(os.sep, "/") + "/"
    return "./assets/{}/".format(name)


def _defaultData(name):
    """可写文件的默认值：源码运行用相对路径，打包后用用户目录里的绝对路径。

    设了 HZYS_DATA_DIR 就用它——这是便携模式（配置文件放哪由用户指定），
    源码运行同样认这个变量，否则测试/多份配置没法互不干扰。
    """
    portable = _portableDataDir()
    if portable:
        return os.path.join(portable, name).replace(os.sep, "/")
    if isPackaged():
        return dataPath(name).replace(os.sep, "/")
    return "./data/{}".format(name)


# 设置文件路径（必须用正斜杠，反斜杠在 macOS/Linux 上不是目录分隔符）
SETTINGS_PATH = _defaultData("settings.json")

# 设置项的默认值：配置文件缺字段时用这里的值补齐
DEFAULT_CONFIG = {
    "sourceDirectory": _defaultAsset("sources"),
    "ysddSourceDirectory": _defaultAsset("ysddSources"),
    "dictFile": _defaultData("dictionary.json"),
    "ysddTableFile": _defaultData("ysddTable.json"),
    "keywordDir": _defaultData("keyword.json"),
    "numOfThreads": 2,
    "roomID": "22603245",
    # 界面版本：False = 旧版（经典界面），True = 新版（网页界面）。
    # 默认走旧版，老配置文件升级上来也不会突然换界面。
    "newUi": False,
    # 登录状态：扫码登录成功后置 True。没登录过时界面提示"首次登录"，
    # 也不让开播（会提示先登录）。
    "loggedIn": False,
    # 登录信息（SESSDATA / DedeUserID / bili_jct ...）。
    # 以前单独放 data/cookie.json，现在并进这里统一管理。
    "cookie": {},
}


def readConfig():
    """读取设置；文件不存在或缺少字段时，用 DEFAULT_CONFIG 补齐。"""
    configuration = dict(DEFAULT_CONFIG)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf8") as configFile:
            configuration.update(json.load(configFile))
    except (OSError, ValueError):
        pass
    return resolveAssets(configuration)


def resolveAssets(configuration):
    """把素材路径补成能直接用的值：空值 / 失效的解包临时路径都算"程序自带"。

    onefile 打包出来的程序，自带素材每次运行都解到不同的 _MEIxxxx 临时目录，
    把那个路径用起来（或写进配置）下次就失效了，所以这里统一兜回当前这份。
    """
    for option in ASSET_OPTIONS:
        value = configuration.get(option)
        if not value or _isBundleTempPath(value):
            configuration[option] = DEFAULT_CONFIG[option]
    return configuration


def writeConfig(configuration):
    """写回设置文件。

    素材路径用的是"程序自带"那份时，写空字符串而不是包内的绝对路径：
    那个路径（打包后）在解包临时目录里，存下来下次启动就失效了。
    """
    saved = dict(configuration)
    for option in ASSET_OPTIONS:
        if isBuiltinAssetPath(option, saved.get(option)):
            saved[option] = ""
    with open(SETTINGS_PATH, "w", encoding="utf8") as configFile:
        json.dump(saved, configFile, ensure_ascii=False, indent="\t")


def setConfigValue(key, value):
    """立刻改一个配置项并写回。

    界面切换这种"改完就要重启"的用它：必须先落盘，重启出来的进程才读得到。
    """
    configuration = readConfig()
    configuration[key] = value
    writeConfig(configuration)
    return configuration


def updateConfig(values):
    """一次改多个配置项（比如登录成功后同时写 cookie 和 loggedIn）。"""
    configuration = readConfig()
    configuration.update(values)
    writeConfig(configuration)
    return configuration


def readCookie():
    """读取登录信息；没登录过返回空字典。"""
    cookie = readConfig().get("cookie")
    return cookie if isinstance(cookie, dict) else {}


def isLoggedIn():
    """是不是登录过（扫码成功过）。"""
    return bool(readConfig().get("loggedIn"))


def ensureDataDir():
    """打包后首次运行：建好可写目录，并把随包的出厂词典铺过去。

    源码运行时数据目录就在项目里，不需要做什么。
    """
    if not isPackaged():
        return
    directory = _dataDir()
    os.makedirs(directory, exist_ok=True)

    for name in SEED_FILES:
        target = os.path.join(directory, name)
        if os.path.exists(target):
            continue
        source = resourcePath("defaults", name)
        if os.path.isfile(source):
            shutil.copyfile(source, target)


# 素材目录这两个字段：值等于默认值（也就是程序自带的素材）时，
# 界面上不显示那串（打包后很长的）路径，直接显示"程序自带"。
ASSET_OPTIONS = ("sourceDirectory", "ysddSourceDirectory")


def _isBundleTempPath(value):
    """这个路径是不是指向 PyInstaller 的解包临时目录（_MEIxxxx）。"""
    return "_MEI" in str(value or "").replace("\\", "/")


def isBuiltinAssetPath(option, value):
    """这个素材路径是不是"程序自带"的那份（空值也算：配置里存空=自带）。"""
    if option not in ASSET_OPTIONS:
        return False
    if not value:
        return True

    default = DEFAULT_CONFIG[option]
    if str(value).rstrip("/") == str(default).rstrip("/"):
        return True
    # 打包后默认值是包内的绝对路径，源码运行是相对路径；
    # 用户也可能手选到同一个目录，所以再比一次真实路径
    try:
        return os.path.realpath(value) == os.path.realpath(default)
    except Exception:
        return False


def migrateConfigFile():
    """旧版 settings.json 没有 roomID 等字段，这里补全后写回。"""
    ensureDataDir()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf8") as configFile:
            onDisk = json.load(configFile)
    except (OSError, ValueError):
        onDisk = {}

    missing = [key for key in DEFAULT_CONFIG if key not in onDisk]
    # 老版本打包版可能把解包临时目录写进了素材路径，那种值也得顺手洗掉
    stale = [key for key in ASSET_OPTIONS if _isBundleTempPath(onDisk.get(key))]
    if missing or stale:
        writeConfig(readConfig())
        if missing:
            print("已补全 {} 缺失的字段：{}".format(SETTINGS_PATH, "、".join(missing)))
        if stale:
            print("已清理失效的素材路径：{}".format("、".join(stale)))
        print("\n")
