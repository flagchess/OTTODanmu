# -*- coding: UTF-8 -*-
"""播放链路自检：音频不能被提前掐断，而且要能同时播多次。

    python tools/checkPlayback.py

三项检查：
  1. 同时播两段时各用各的临时文件，播完自动删掉（不会互相覆盖）
  2. 播放会等到音频放完才返回（提前返回会让进程退出时把尾音丢掉）
  3. main.py 的「播放」可以连着点：几个播放同时响，不会打断上一条

会在最后用一段静音文件试播一次（听不见）。
"""

import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import numpy as np
import soundfile as sf

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

import main as app  # noqa: E402
from hzys import huoZiYinShua as engineModule  # noqa: E402
from hzys.huoZiYinShua import huoZiYinShua  # noqa: E402

problems = []
CONSOLE = sys.__stdout__


def say(text):
    print(text, file=CONSOLE, flush=True)


def check(condition, message):
    if not condition:
        problems.append(message)
    return condition


def testConcurrentTempFiles(engine):
    """两段音频同时播：临时文件必须各用各的，播完都清掉。"""
    seen = []
    release = threading.Event()

    def fakePlay(filePath):
        seen.append(filePath)
        release.wait(30)

    original = engineModule._playWav
    engineModule._playWav = fakePlay
    try:
        threads = [
            threading.Thread(target=engine.directPlay, kwargs={"rawData": text})
            for text in ("你好", "世界")
        ]
        for thread in threads:
            thread.start()

        deadline = time.time() + 30
        while len(seen) < 2 and time.time() < deadline:
            time.sleep(0.05)

        check(len(seen) == 2, "两段音频没能同时进入播放阶段")
        check(len(set(seen)) == 2, "两次播放用了同一个临时文件，音频会互相覆盖")
        check(
            all(os.path.exists(path) for path in seen),
            "还没放完临时文件就没了",
        )

        release.set()
        for thread in threads:
            thread.join(30)
        check(
            not any(os.path.exists(path) for path in seen),
            "播完之后没有清理临时文件：{}".format(seen),
        )
    finally:
        engineModule._playWav = original


def testWaitsForWholeAudio():
    """播放必须等到音频放完才返回，否则进程一退尾音就没了。"""
    duration = 0.6
    handle, path = tempfile.mkstemp(prefix="hzys-check-", suffix=".wav")
    os.close(handle)
    sf.write(path, np.zeros(int(44100 * duration)), 44100)
    try:
        started = time.time()
        engineModule._playWav(path)
        elapsed = time.time() - started
        say("放 %.2fs 的音频，实际等 %.3fs" % (duration, elapsed))
        check(
            elapsed >= duration,
            "播放提前返回了（{:.3f}s < {:.2f}s），末尾会被截断".format(
                elapsed, duration
            ),
        )
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


class FakeHolder:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


PLAY_SECONDS = 1.2


def slowPlay(**kwargs):
    """替真正的播放：在子进程里睡一会儿，好观察有没有被下一条打断。"""
    time.sleep(PLAY_SECONDS)


def testAppKeepsOverlappingPlays():
    """连着点两次「播放」：两个进程要同时在响。"""
    app.ui = SimpleNamespace(
        getInputText=lambda: "你好",
        inYsddMode=FakeHolder(False),
        normAudio=FakeHolder(False),
        reverseAudio=FakeHolder(False),
        pitchMultOption=FakeHolder(1),
        speedMultOption=FakeHolder(1),
        volumeMultOption=FakeHolder(1),
    )
    app.HZYS = SimpleNamespace(directPlay=slowPlay)
    app.playProcesses.clear()

    app.onDirectPlay()
    app.onDirectPlay()
    time.sleep(0.5)

    alive = [process for process in app.playProcesses if process.is_alive()]
    check(
        len(alive) == 2,
        "连着点两次播放只剩 {} 个在响（被上一条打断了）".format(len(alive)),
    )

    app.stopDirectPlay()  # 收尾：别把测试进程留着
    check(not app.playProcesses, "stopDirectPlay() 没有清空播放进程列表")


def main():
    engine = huoZiYinShua(app.SETTINGS_PATH)

    try:
        testConcurrentTempFiles(engine)
        testWaitsForWholeAudio()
        testAppKeepsOverlappingPlays()
    except Exception as exc:
        import traceback

        traceback.print_exc(file=CONSOLE)
        problems.append("自检抛异常: {}: {}".format(type(exc).__name__, exc))

    if problems:
        say("发现 {} 个问题：".format(len(problems)))
        for item in problems:
            say("  - " + item)
        return 1
    say("全部通过：临时文件互不干扰、播放等满整段、多次播放能同时响")
    return 0


if __name__ == "__main__":
    sys.exit(main())
