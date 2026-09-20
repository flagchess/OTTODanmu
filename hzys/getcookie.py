import io
import json
import os
from time import sleep

import httpx
import qrcode
import requests

from .config import dataPath, readCookie, updateConfig


def get_qrurl() -> list:
    """返回qrcode链接以及token"""
    with httpx.Client() as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 QIHU 360SE"
        }
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header"
        data = client.get(url=url, headers=headers)
    total_data = data.json()
    qrcode_url = total_data["data"]["url"]
    qrcode_key = total_data["data"]["qrcode_key"]
    data = {}
    data["url"] = qrcode_url
    data["qrcode_key"] = qrcode_key
    return data


def make_qrcode(data, onState=None):
    """制作二维码。

    onState 是界面回调：(png字节, 提示文字, 是否结束)。给了回调就把二维码交给
    界面去显示（新版界面弹面板、经典界面弹窗口）；没给就还是老样子——
    存一份 Qrcode.png 再用系统看图程序打开。
    """
    qr = qrcode.QRCode(
        version=5,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=4,
    )
    qr.add_data(data["url"])
    qr.make(fit=True)
    img = qr.make_image(fill_color="black")
    try:
        img.save(dataPath("Qrcode.png"))
    except Exception:
        pass

    png = None
    if onState is not None:
        try:
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            png = buffer.getvalue()
        except Exception:
            png = None

    if png is not None:
        onState(png, "请用哔哩哔哩 App 扫码登录", False)
    else:
        try:
            img.show()
        except Exception:
            pass
    print("\n")


def sav_cookie(cookie):
    """把登录信息写进 settings.json（以前是单独的 data/cookie.json）。

    顺便把"登录过"标记记上：界面靠它决定显示"首次登录"还是"重新登录"。
    """
    updateConfig({"cookie": cookie, "loggedIn": True})


def getcookienow(stopcookie, onState=None):
    """扫码登录。

    返回 0 表示登录成功，86038 表示二维码超时，None 表示被中断或出错。

    onState(png字节或None, 提示文字, 是否结束) 用来把二维码和状态送到界面；
    不传就保持老行为（只打日志、弹系统图片窗口）。
    """

    def report(png=None, status="", done=False):
        if onState is None:
            return
        try:
            onState(png, status, done)
        except Exception:
            pass  # 界面已经关了之类的，不影响登录流程

    data = get_qrurl()
    token = data["qrcode_key"]
    make_qrcode(data, onState=onState)
    print("等待扫码中")
    print("\n")
    check_login_url = f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={token}&source=main-fe-header"
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    scanned = False  # 已扫码的提示只打一次，避免每 3 秒刷屏
    while True:
        datack = session.get(url=check_login_url, headers=headers, timeout=10).json()
        code = datack["data"]["code"]

        # 登录成功
        if code == 0:
            print("登录成功")
            print("\n")
            session.get("https://www.bilibili.com/", headers=headers, timeout=10)
            cookie = session.cookies.get_dict()
            sav_cookie(cookie)
            print("成功保存了新的登录状态")
            print("\n")
            report(status="登录成功", done=True)
            return 0

        # 二维码失效
        if code == 86038:
            print("登录失败，二维码超时")
            print("\n")
            report(status="二维码超时了，点「重新获取二维码」再来一次", done=True)
            return 86038

        # 已扫码，等待手机确认：必须继续轮询，确认之后才会返回 0
        if code == 86090 and not scanned:
            print("已扫码，请在手机上确认登录")
            print("\n")
            report(status="已扫码，请在手机上确认登录", done=False)
            scanned = True

        if stopcookie.is_set():
            report(status="登录已中断", done=True)
            return None

        sleep(3)


def _loadCookieField(field):
    """从 settings.json 的 cookie 里取一个字段，读不到就返回 None。

    老版本把登录信息单独放在 data/cookie.json，这里会顺手搬一次家：
    读到了就并进 settings.json，然后把旧文件删掉。
    """
    cookie = readCookie()
    if not cookie:
        cookie = _migrateLegacyCookie()
    try:
        return cookie[field]
    except (KeyError, TypeError):
        return None


def _migrateLegacyCookie():
    """把老的 data/cookie.json 并进 settings.json（只做一次）。"""
    path = dataPath("cookie.json")
    try:
        with open(path, "r", encoding="utf8") as handle:
            cookie = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(cookie, dict) or not cookie:
        return {}

    sav_cookie(cookie)
    try:
        os.remove(path)
        print("已把登录信息从 cookie.json 并进 settings.json")
    except OSError:
        pass
    return cookie


def load_cookie():
    """读取 SESSDATA，未登录时返回 None。"""
    return _loadCookieField("SESSDATA")


def load_UID():
    """读取 DedeUserID，未登录时返回 None。"""
    return _loadCookieField("DedeUserID")
