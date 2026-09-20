# -*- coding: UTF-8 -*-
"""设置页的暂存模型（各后端共用）。

界面上的改动先记在这里，只有按「保存」才写回 settings.json。
单独成模块是为了让 Tk / pywebview 两个后端共用同一套行为，
避免各写一份导致行为漂移。

一条重要的规矩：**设置页只管这些字段**（路径、线程数、房间号）。
登录信息（cookie / loggedIn）和界面版本（newUi）不归它管——

* 不参与"有没有未保存改动"的判断：不然扫码登录之后，设置页会莫名其妙
  亮起小圆点；
* 按「保存」也不会写它们：不然会把刚登录拿到的 cookie 覆盖成旧的（等于掉线）。
* 只有「恢复默认」是例外：那是有意清掉登录信息（相当于退出登录），
  但同样要按了「保存」才真正生效。
"""

from ..config import DEFAULT_CONFIG, readConfig, writeConfig
from . import layout

# 界面上是输入框的字段：统一按字符串存，
# 免得配置文件里一会儿是数字 2、一会儿是字符串 "2"
STRING_FIELDS = ("numOfThreads", "roomID")

# 设置页真正能改的字段，其余一律不动
EDITABLE_KEYS = tuple(option for option, _ in layout.PATHS.values()) + tuple(
    option for option, _ in layout.ENTRIES.values()
)

# 「恢复默认」时要一起清掉的字段
RESET_EXTRA_KEYS = {"cookie": {}, "loggedIn": False}


def _same(left, right):
    """比较两个配置值；数字和同值的字符串算相等（2 == "2"）。"""
    return str(left).strip() == str(right).strip()


class SettingsDraft:
    """设置项的暂存副本。"""

    def __init__(self):
        self.values = readConfig()
        self.resetToDefaults = False  # 点过「恢复默认」没有

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        self.resetToDefaults = False  # 手动改过就不算"恢复默认"了

    def resetToDefault(self):
        """恢复默认值：只改暂存，不动磁盘（按保存才生效）。"""
        self.values = dict(DEFAULT_CONFIG)
        self.resetToDefaults = True

    def isDirty(self, editorValues=None):
        """设置页上有没有还没保存的改动。

        editorValues 是界面上输入框的当前值（线程数、房间号），
        它们可能还没同步进 values。登录信息不参与比较。
        """
        if self.resetToDefaults:
            return True
        onDisk = readConfig()
        merged = dict(self.values)
        merged.update(editorValues or {})
        # 用 _same 比较：值被写成 2 还是 "2" 都算没改，别误报"未保存"
        return any(not _same(onDisk.get(key), merged.get(key)) for key in EDITABLE_KEYS)

    def save(self, editorValues=None):
        """把设置页上的值写回 settings.json，返回写回后的完整配置。"""
        if editorValues:
            self.values.update(editorValues)

        # 以磁盘上的配置为底：登录信息、界面版本这些不归设置页管的字段
        # 会原样保留，不会被暂存里的旧值覆盖。
        configuration = readConfig()
        for key in EDITABLE_KEYS:
            if key not in self.values:
                continue
            value = self.values[key]
            if key in STRING_FIELDS:
                value = str(value)
            configuration[key] = value

        if self.resetToDefaults:
            # 点了「恢复默认」：连登录信息一起清掉（等于退出登录）
            configuration.update(RESET_EXTRA_KEYS)

        writeConfig(configuration)
        self.values = dict(configuration)
        self.resetToDefaults = False
        return configuration
