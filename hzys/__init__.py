# -*- coding: UTF-8 -*-
"""电棍棍活字（B 站弹幕语音播报）。

程序代码都在这个包里：
    config.py               settings.json 的读写
    huoZiYinShua.py         活字印刷引擎（合成、变调变速、播放、导出）
    biliLiveBroadcaster.py  直播间弹幕连接
    getcookie.py            扫码登录、cookie 读写
    jsonloader.py           词典编辑（三本词典共用一套定义和读写）
    update.py               检查更新、更新日志
    gui/                    界面层（后端工厂、各后端实现、共用布局与文案）
    icon.py / icon_data.py  程序图标（图标已嵌进代码）

入口是根目录的 main.py；素材在 assets/，配置和词典在 data/。
"""

# 程序版本号：窗口标题和「检查更新」都读它。发新版本只改这一行。
__version__ = "2026.9.20"
