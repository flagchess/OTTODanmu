import base64
import json
import time
import timeit
import zlib
from functools import partial
from hashlib import md5
from threading import Thread
from urllib.parse import urlencode

import brotli
import requests
import websocket

from .config import readCookie

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.25 Safari/537.36 Core/1.70.3880.400 QQBrowser/10.8.4554.400 "
}


# 获取真实房间号
def _getRealRoomId(roomId):
    roomInfo = requests.get(
        "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + str(roomId),
        headers=headers,
        timeout=10,
    ).json()
    realRoomId = roomInfo["data"]["room_id"]
    return realRoomId


# wbi 签名用的置换表（B站接口风控校验用，社区通行的算法）
_WBI_MIXIN_TABLE = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]


def _wbiMixinKey(userSESSDATA):
    """取 wbi 的 mixin key：B站大部分接口的签名都靠它。"""
    try:
        nav = requests.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers,
            cookies={"SESSDATA": userSESSDATA},
            timeout=10,
        ).json()
        wbi = nav["data"]["wbi_img"]
        imgKey = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
        subKey = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
        if not imgKey or not subKey:
            return ""
        return "".join((imgKey + subKey)[i] for i in _WBI_MIXIN_TABLE)[:32]
    except Exception:
        return ""


# 获取key
def _getKey(realRoomId, userSESSDATA):
    """取弹幕服务器要的 token。

    B站 2023 年起给这个接口加了风控：不带 wbi 签名会返回 -352
    （"风控校验失败"），看起来像登录失效，其实换个签名就好。
    """
    cookies = {"SESSDATA": userSESSDATA}
    params = {"id": realRoomId, "type": 0, "wts": int(time.time())}
    query = urlencode(sorted(params.items()))

    mixinKey = _wbiMixinKey(userSESSDATA)
    if mixinKey:
        signature = md5((query + mixinKey).encode("utf8")).hexdigest()
        query = query + "&w_rid=" + signature

    url = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?" + query
    keyInfo = requests.get(
        url,
        headers=headers,
        cookies=cookies,
        timeout=10,
    ).json()
    if "data" not in keyInfo:
        raise RuntimeError(
            "取弹幕 token 失败：code={} message={}（-352 是风控，通常重试或重新登录即可）".format(
                keyInfo.get("code"), keyInfo.get("message")
            )
        )
    return keyInfo["data"]["token"]


# 按B站直播协议切分数据包
#
# 每个包的结构固定为：
#   4字节 包长度 | 2字节 头长度 | 2字节 协议版本 | 4字节 操作码 | 4字节 序列号 | 内容
# 必须按长度切，不能靠数大括号配对——弹幕正文里出现“{”或“}”会把配对算乱，
# 导致整个包（可能含十几条弹幕）解析失败。
def _iterPackets(raw):
    """切分数据包，返回 [(操作码, 内容bytes), ...]。"""
    packets = []
    offset = 0
    total = len(raw)

    while offset + 16 <= total:
        packetLength = int.from_bytes(raw[offset : offset + 4], "big")
        headerLength = int.from_bytes(raw[offset + 4 : offset + 6], "big")
        operation = int.from_bytes(raw[offset + 8 : offset + 12], "big")

        # 长度不合法说明数据不完整，丢弃剩余部分
        if packetLength < headerLength or offset + packetLength > total:
            break

        packets.append((operation, raw[offset + headerLength : offset + packetLength]))
        offset += packetLength

    return packets


# 转换byte array为json dictionary
def _raw2Json(raw):
    jsonList = []
    for _, body in _iterPackets(raw):
        if not body:
            continue
        try:
            jsonList.append(json.loads(body))
        except ValueError:
            continue  # 不是JSON的包（心跳等）直接跳过

    return jsonList  # 输出


# 解读处理好的数据
def _pbDecode(text):
    """把 data.pb 里的 base64 还原成字节（长度不是 4 的倍数时补个位）。"""
    return base64.b64decode(text + "=" * (-len(text) % 4))


def _pbFields(data):
    """把 protobuf 正文拆成 {字段号: [值...]}（只认 varint 和字符串/嵌套）。

    B站新版协议里 INTERACT_WORD_V2 / SEND_GIFT_V2 的正文是 protobuf，
    包在 data.pb 里（base64）。这里不引第三方库，按 protobuf 的线格式走一遍，
    取出我们关心的那几个字段就够了（用户名、类型这类）。
    """
    fields = {}
    index = 0
    total = len(data)

    def readVarint(pos):
        value = 0
        shift = 0
        while pos < total:
            byte = data[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        return value, pos

    while index < total:
        try:
            key, index = readVarint(index)
            field, wire = key >> 3, key & 7
            if wire == 0:
                value, index = readVarint(index)
            elif wire == 2:
                length, index = readVarint(index)
                value = data[index : index + length]
                index += length
            elif wire == 5:
                value = data[index : index + 4]
                index += 4
            elif wire == 1:
                value = data[index : index + 8]
                index += 8
            else:
                break
            fields.setdefault(field, []).append(value)
        except Exception:
            break
    return fields


def _pbString(fields, number):
    """从拆好的字段里取一个字符串字段。"""
    try:
        return fields[number][0].decode("utf8")
    except Exception:
        return ""


def _interpreteJson(
    data, onReceiveDanmu, onAudienceEnter, giftStat, onReceiveSuperChat=None
):
    for info in data:
        try:
            match info["cmd"]:
                # 弹幕
                case "DANMU_MSG":
                    speaker = info["info"][2][1]
                    content = info["info"][1]
                    onReceiveDanmu(speaker, content)

                # 礼物
                case "SEND_GIFT":
                    sender = info["data"]["uname"]
                    quantity = info["data"]["num"]
                    giftName = info["data"]["giftName"]
                    giftStat.add(sender, giftName, quantity)

                # 礼物（新版协议：正文是 protobuf）
                case "SEND_GIFT_V2":
                    top = _pbFields(_pbDecode(info["data"]["pb"]))
                    sender = _pbString(top, 2)
                    detail = _pbFields(top[10][0]) if top.get(10) else {}
                    giftName = _pbString(detail, 2)
                    quantity = detail.get(3, [1])[0] or 1
                    if sender and giftName:
                        giftStat.add(sender, giftName, int(quantity))

                # 进入直播间
                case "INTERACT_WORD":
                    audience = info["data"]["uname"]
                    onAudienceEnter(audience)

                # 进入直播间（新版协议：正文是 protobuf）
                case "INTERACT_WORD_V2":
                    fields = _pbFields(_pbDecode(info["data"]["pb"]))
                    uname = _pbString(fields, 2)
                    msgType = fields.get(4, [b"\x01"])[0]
                    # 1=进入直播间，2=关注，3=分享；其它（比如点赞）不提示
                    if uname and msgType in (b"\x01", b"\x02", b"\x03"):
                        onAudienceEnter(uname)

                # 醒目留言（Super Chat）
                # 只认 SUPER_CHAT_MESSAGE：B站对每条 SC 还会发一条 _JPN
                # （日文翻译版），两条都收会重复播报
                case "SUPER_CHAT_MESSAGE":
                    if onReceiveSuperChat is None:
                        break
                    sc = info["data"]
                    onReceiveSuperChat(
                        sc["user_info"]["uname"],
                        sc.get("message", ""),
                        sc.get("price", 0),
                    )

        except Exception:  # 无关信息
            pass


# 收到数据
def _onMessage(
    onReceiveDanmu, onAudienceEnter, giftStat, onReceiveSuperChat, ws, message
):
    if message[7] == 3:  # 用brotli解压缩
        # 解压出来的内容本身就是一串完整的包（各自带16字节包头），不用再截
        rawData = brotli.decompress(message[16:])

    elif message[7] == 2:  # 老客户端用 zlib 压的，也认一下
        rawData = zlib.decompress(message[16:])

    elif message[7] == 0:  # 无需解压缩
        rawData = message[16:]

    else:  # 与直播间内容无关
        return

    try:
        data = _raw2Json(rawData)  # 转换为json词典
    except Exception as e:
        print("解析弹幕数据失败: {}".format(e))
        return

    # 解读数据
    _interpreteJson(data, onReceiveDanmu, onAudienceEnter, giftStat, onReceiveSuperChat)


# 处理错误
def _onError(ws, error):
    print("出现错误")
    print(error)


# 断开连接
def _onClose(ws, close_status_code, close_msg):
    print("已断开连接")


# 发送心跳包
def _sendHeartBeat(stoplivemode, ws):
    # 每30秒发送一次；Event.wait 在停止时会立刻返回，避免停播后还发心跳
    while not stoplivemode.wait(30):
        # 这个连接已经断了就收工：不然每次重连都会多留一个心跳线程
        sock = getattr(ws, "sock", None)
        if sock is None or not getattr(sock, "connected", False):
            return
        try:
            ws.send(
                bytearray.fromhex(
                    "0000001f0010000100000002000000015b6f626a656374204f626a6563745d"
                )
            )
        except Exception:
            return  # 连接已断开


# 统计收到的礼物
def _collectGiftReceived(giftStat, onReceiveGift, stoplivemode):
    while not stoplivemode.wait(1):
        # 统计
        giftList = giftStat.extractData()

        for gift in giftList:
            onReceiveGift(gift[0], gift[2], gift[1])  # 用户自定义函数


# 已连接上
def _buvid():
    """握手要带 buvid，而且要和 cookie 里的一致。

    写死一个别人的 buvid 时，服务器会把连接当成低权客户端：
    实测只给你零星几条弹幕，进场 / 礼物 / SC 一条都不发。
    """
    cookie = readCookie()
    return (
        cookie.get("buvid3")
        or cookie.get("buvid4")
        or "XY87B558B729BA2CD745A4FB711BC37C3139D"
    )


def _onOpen(realRoomId, userUID, key, giftStat, onReceiveGift, stoplivemode, ws):
    # 编辑确认信息
    verification = (
        b'{"uid":'
        + bytes(str(userUID), "utf-8")
        + b',"roomid":'
        + bytes(str(realRoomId), "utf-8")
        + b',"protover":3,"buvid":"'
        + bytes(_buvid(), "utf-8")
        + b'","platform":"web","type":2,"key":"'
        + bytes(key, "utf-8")
        + b'"}'
    )
    dataToSend = (
        (len(verification) + 16).to_bytes(4, "big")
        + bytearray.fromhex("001000010000000700000001")
        + verification
    )

    # 发送确认信息
    ws.send(dataToSend)

    # 开启心跳包定时
    heartbeatThread = Thread(
        target=_sendHeartBeat,
        args=(
            stoplivemode,
            ws,
        ),
    )
    heartbeatThread.start()

    print("已连接")


# 收到的礼物列表
class _giftInfoArray:
    def __init__(self):
        self.__data = []  # 所有收到的礼物

    # 向列表中添加礼物
    def add(self, sender, giftName, quantity):
        # 寻找相同用户赠送的相同礼物并叠加
        for i in range(0, len(self.__data)):
            if self.__data[i][0:2] == [sender, giftName]:
                self.__data[i][2] += quantity
                self.__data[i][3] = timeit.default_timer()
                return
        # 否则新建一个元素
        self.__data.append([sender, giftName, quantity, timeit.default_timer()])

    # 提取数据
    def extractData(self):
        currentTime = timeit.default_timer()
        listToReturn = []
        stillComboing = []

        for info in self.__data:
            # 超过3秒未赠送同样的礼物（连击停止）
            if currentTime - info[3] > 3:
                listToReturn.append(info)
            else:
                stillComboing.append(info)

        # 不能在遍历的同时 remove（会漏掉一半），遍历完再整体替换
        self.__data = stillComboing

        return listToReturn


class biliLiveBroadcaster:
    def __init__(
        self,
        roomId,
        userUID,
        userSESSDATA,
        onReceiveDanmu,
        onReceiveGift,
        onAudienceEnter,
        stoplivemode,
        onReceiveSuperChat=None,
    ):
        self.__giftStat = _giftInfoArray()
        self.__roomId = roomId
        self.__userUID = userUID  # 新
        self.__userSESSDATA = userSESSDATA  # 新
        self.__onReceiveDanmu = onReceiveDanmu
        self.__onReceiveGift = onReceiveGift
        self.__onAudienceEnter = onAudienceEnter
        self.__onReceiveSuperChat = onReceiveSuperChat
        self.__stoplivemode = stoplivemode

    def startBroadcasting(self):
        """连上弹幕服务器开始接收；断了就重连，直到停止直播。

        注意每次重连都要重新取一遍 roomid 和 key：key 是会过期的，
        拿旧的 key 直接重连通常会被服务器立刻踢掉。所以这里不是靠
        run_forever 的自动重连，而是自己在外面套一层。
        """
        websocket.enableTrace(False)
        attempt = 0

        # 礼物统计只开一个线程，跨重连一直用同一个（别每次重连都开一个）
        Thread(
            target=_collectGiftReceived,
            args=(self.__giftStat, self.__onReceiveGift, self.__stoplivemode),
        ).start()

        while not self.__stoplivemode.is_set():
            attempt += 1
            try:
                # 获取真实房间号和 key
                self.__realRoomId = _getRealRoomId(self.__roomId)
                self.__key = _getKey(self.__realRoomId, self.__userSESSDATA)

                print("连接中" if attempt == 1 else "第 {} 次重连…".format(attempt))
                ws = websocket.WebSocketApp(
                    "wss://broadcastlv.chat.bilibili.com/sub",
                    on_open=partial(
                        _onOpen,
                        self.__realRoomId,
                        self.__userUID,
                        self.__key,
                        self.__giftStat,
                        self.__onReceiveGift,
                        self.__stoplivemode,
                    ),
                    on_message=partial(
                        _onMessage,
                        self.__onReceiveDanmu,
                        self.__onAudienceEnter,
                        self.__giftStat,
                        self.__onReceiveSuperChat,
                    ),
                    on_error=_onError,
                    on_close=_onClose,
                )
                ws.run_forever()  # 阻塞到连接结束
                attempt = 0  # 连上又正常断开的，重新从第 1 次算
            except Exception as exc:
                print("连接弹幕服务器失败：{}".format(exc))

            if self.__stoplivemode.is_set():
                break

            # 逐渐拉长重试间隔，最多 30 秒一次
            wait = min(5 * (attempt or 1), 30)
            print("{} 秒后重连…".format(wait))
            if self.__stoplivemode.wait(wait):
                break

        print("弹幕连接已停止")
