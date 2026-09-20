# -*- coding: UTF-8 -*-
"""原生界面后端（rpc_backend）自检：用 Python 冒充界面，把协议跑一遍。

    python tools/checkRpcBackend.py

做的事：
  * 起一个 `python main.py --engine` 子进程
  * 收 ready 消息，检查里面有没有结构和初始状态
  * 走一遍真实流程：输入文字 -> 导出（引擎会反过来要求界面弹保存框）
    -> 检查文件真的写出来了、并且引擎发了成功提示
  * 再试设置页：改线程数、保存、恢复默认
  * 最后让引擎退出，确认进程干净结束

退出码 0 表示通过。
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

problems = []


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


class FakeUI:
    """假界面：按协议回答引擎的请求，并把收到的事件记下来。"""

    def __init__(self, process, savePath):
        self.process = process
        self.savePath = savePath
        self.events = []
        self.ready = threading.Event()
        self.info = threading.Event()
        self.nextId = 1
        self.lock = threading.Lock()

    def send(self, payload):
        with self.lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def call(self, method, *args):
        callId = self.nextId
        self.nextId += 1
        self.send(dict(type="call", id=callId, method=method, args=list(args)))
        return callId

    def readLoop(self):
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                problems.append("引擎发来的不是合法 JSON: {!r}".format(line[:80]))
                continue
            kind = message.get("type")
            if kind == "event":
                name = message.get("name")
                self.events.append(name)
                if name == "ready":
                    self.readyData = message
                    self.ready.set()
                elif name == "info":
                    self.info.set()
                elif name == "login":
                    pass
            elif kind == "call":
                # 引擎请界面做事：这里全都答应下来
                method = message.get("method")
                if method == "askSaveFileName":
                    self.send(
                        dict(type="return", id=message["id"], result=self.savePath)
                    )
                elif method == "askYesNo":
                    self.send(dict(type="return", id=message["id"], result=True))
                elif method in ("pickFolder", "pickFile"):
                    self.send(
                        dict(type="return", id=message["id"], result=self.savePath)
                    )
                else:
                    self.send(dict(type="return", id=message["id"], result=None))


def main():
    outDir = tempfile.mkdtemp(prefix="hzys-rpc-")
    savePath = os.path.join(outDir, "rpc-export.wav")
    # 让引擎把配置写到临时目录，别动项目里真正的 settings.json
    dataDir = os.path.join(outDir, "data")
    os.makedirs(dataDir, exist_ok=True)
    # 新数据目录要有一份出厂词典，否则引擎读不到词典、合成会失败
    import shutil

    for name in ("dictionary.json", "ysddTable.json", "keyword.json"):
        shutil.copy2(os.path.join(PROJECT, "data", name), os.path.join(dataDir, name))
    env = dict(os.environ)
    env["HZYS_DATA_DIR"] = dataDir

    process = subprocess.Popen(
        [sys.executable, "main.py", "--engine"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=PROJECT,
        env=env,
    )
    ui = FakeUI(process, savePath)
    ui.readLoopThread = threading.Thread(target=ui.readLoop, daemon=True)
    ui.readLoopThread.start()

    check(ui.ready.wait(30), "引擎没有发 ready（协议没通）")
    if hasattr(ui, "readyData"):
        payload = ui.readyData
        check(bool(payload.get("title")), "ready 里没有窗口标题")
        check(
            len(payload.get("layout", {}).get("pages", [])) == 3,
            "ready 里的页面数量不对",
        )
        state = payload.get("state") or {}
        check("values" in state and "paths" in state, "ready 里没有初始状态")

    # 输入文字（界面推给引擎），再点导出
    ui.call("inputChanged", "大家好啊")
    ui.call("action", "export")

    deadline = time.time() + 60
    while time.time() < deadline and not os.path.exists(savePath):
        time.sleep(0.5)
    check(os.path.exists(savePath), "导出没有生成文件：{}".format(savePath))
    if os.path.exists(savePath):
        size = os.path.getsize(savePath)
        check(size > 10000, "导出的文件太小（{} 字节）".format(size))
        check("info" in ui.events, "导出成功后没有收到提示事件")

    # 设置页：改线程数 -> 保存 -> 恢复默认
    ui.call("setEditorValue", "numOfThreads", "5")
    ui.call("action", "saveSettings")
    time.sleep(1.0)
    ui.call("action", "resetSettings")
    time.sleep(1.0)
    check(
        ui.events.count("state") >= 2,
        "设置页改动后没有收到状态推送",
    )

    # 退出
    ui.send(dict(type="quit"))
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        problems.append("发了 quit 之后引擎没有退出")

    if problems:
        print("发现 {} 个问题：".format(len(problems)))
        for item in problems:
            print("  -", item)
        print("\n引擎 stderr（最后几行）：")
        print((process.stderr.read() or "")[-800:])
        return 1
    print("全部通过：原生界面后端协议正常（ready / 导出 / 设置 / 退出）")
    print("   收到的事件：{}".format(", ".join(sorted(set(ui.events)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
