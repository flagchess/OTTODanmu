"""把界面切到指定模式并停在那儿，方便截图对比。"""

import os
import sys
from types import SimpleNamespace

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

from hzys import gui
from hzys.gui import layout


def noop(*args, **kwargs):
    pass


handlers = SimpleNamespace(
    onDirectPlay=noop,
    onExport=noop,
    onTrytologin=noop,
    onToggleLiveMode=noop,
    onStartLive=noop,
    onStopLive=noop,
    onSettingsSaved=noop,
)

ui = gui.createWindow(handlers, backend="tk")
ui.layout()

# 想看的页面：local / live / settings / running
mode = sys.argv[1] if len(sys.argv) > 1 else "live"
if mode == "live":
    ui.iflivemodeon.set(True)  # 模拟 main.py 处理完事件后的回调
    ui.setLiveMode(True)
elif mode == "running":
    ui.iflivemodeon.set(True)
    ui.setLiveMode(True)
    ui.setBroadcastRunning(True)
elif mode == "settings":
    ui.selectPage("settings")
else:
    ui.setLiveMode(False)

ui.root.title(layout.WINDOW_TITLE)
ui.root.mainloop()
