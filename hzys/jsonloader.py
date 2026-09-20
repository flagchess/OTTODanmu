# -*- coding: UTF-8 -*-
"""词典编辑器：敏感词词库 / 非中文字符读法字典 / 原声大碟对照表。

三本词典的结构和操作完全一样，差别只有"表头叫什么、值能不能留空"，
所以定义集中在 DICTIONARIES 里；读取、写回、界面都围着它转。
两个界面后端（新版网页 / 经典 Tk）共用这里的 dictionaryInfo / readDictionary /
writeDictionary，所以字段、文案、保存行为不会各写一套跑到两边去。
"""

import json
import tkinter as tk
from tkinter import messagebox, ttk

from .config import readConfig
from .gui import layout

# 模式编号 -> 词典定义。name/value 是两列的表头，valueRequired 表示值能不能留空。
DICTIONARIES = {
    1: {
        "title": "敏感词词库",
        "name": "敏感词",
        "value": "备注",
        "valueRequired": False,
        "configKey": "keywordDir",
    },
    2: {
        "title": "非中文字符读法字典",
        "name": "字符",
        "value": "读法",
        "valueRequired": True,
        "configKey": "dictFile",
    },
    3: {
        "title": "原声大碟关键词与音频对照表",
        "name": "关键词",
        "value": "音频",
        "valueRequired": True,
        "configKey": "ysddTableFile",
    },
}


def dictionaryInfo(mode):
    """取某本词典的定义（给界面用；顺带把 configKey 藏起来，界面不需要）。"""
    info = dict(DICTIONARIES[int(mode)])
    info.pop("configKey", None)
    return info


def dictionaryPath(mode):
    """词典文件在哪儿（路径从 settings.json 读）。"""
    return readConfig()[DICTIONARIES[int(mode)]["configKey"]]


def readDictionary(mode):
    """读出词典内容，返回 [[名称, 值], ...]。文件坏了就当空词典。"""
    path = dictionaryPath(mode)
    try:
        with open(path, encoding="utf8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [
        [str(key), "" if value is None else str(value)] for key, value in data.items()
    ]


def writeDictionary(mode, rows):
    """把 [[名称, 值], ...] 写回词典文件。"""
    data = {}
    for row in rows:
        name = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
        value = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        if not name:
            continue
        if not value and DICTIONARIES[int(mode)]["valueRequired"]:
            raise ValueError("「{}」不能留空".format(DICTIONARIES[int(mode)]["value"]))
        data[name] = value

    with open(dictionaryPath(mode), "w", encoding="utf8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent="\t")
    return len(data)


# ---------------- 经典（Tk）编辑器 ----------------


class jsonTableEditor:
    """Tk 版词典编辑窗口。

    两个后端的行为要一致，所以这里的表头、按钮、校验都从 DICTIONARIES 来；
    按钮文字和网页那版共用 gui/layout.py 的 BUTTONS。
    （原来那个"常驻输入框 + 修改选中"的做法，点几次就会叠出好几层控件，已经去掉。）
    """

    mode = 1  # 子类覆盖

    def __init__(self):
        self.info = dictionaryInfo(self.mode)
        self.windowTitle = self.info["title"]
        self.nameHeading = self.info["name"]
        self.valueHeading = self.info["value"]

    def start(self):
        self.rows = [list(row) for row in readDictionary(self.mode)]
        self.root = tk.Toplevel()
        self.root.title(self.windowTitle)
        self.root.geometry("560x420")
        self._build()
        self._refresh()

    # ---------------- 界面 ----------------

    def _build(self):
        body = ttk.Frame(self.root, padding=12)
        body.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            body, columns=("name", "value"), show="headings", height=11
        )
        self.tree.heading("name", text=self.nameHeading)
        self.tree.heading("value", text=self.valueHeading)
        self.tree.column("name", width=220, anchor="w")
        self.tree.column("value", width=240, anchor="w")
        self.tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=4, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda event: self.edit_item())

        ttk.Label(body, text="双击某一行可以修改").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(8, 4)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=5, sticky="ew")
        for column, (text, command) in enumerate(
            (
                (layout.BUTTONS["dictAdd"], self.add_item),
                (layout.BUTTONS["dictDelete"], self.delete_item),
            )
        ):
            ttk.Button(buttons, text=text, command=command).grid(
                row=0, column=column, padx=(0, 6)
            )
        ttk.Button(
            buttons, text=layout.BUTTONS["dictSave"], command=self.save_data
        ).grid(row=0, column=3, sticky="e")
        buttons.columnconfigure(3, weight=1)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows, 1):
            self.tree.insert("", tk.END, iid=str(index - 1), values=row)

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一行", parent=self.root)
            return None
        return int(selection[0])

    def _check(self, name, value):
        if not name:
            messagebox.showinfo(
                "提示", "「{}」不能为空".format(self.nameHeading), parent=self.root
            )
            return False
        if not value and self.info["valueRequired"]:
            messagebox.showinfo(
                "提示", "「{}」不能为空".format(self.valueHeading), parent=self.root
            )
            return False
        return True

    # ---------------- 增删改 ----------------

    def _ask(self, title, name="", value=""):
        """弹一个两栏的小输入框：确定返回 (名称, 值)，取消返回 None。"""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        nameVar = tk.StringVar(value=name)
        valueVar = tk.StringVar(value=value)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.nameHeading).grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=nameVar, width=22).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Label(frame, text=self.valueHeading).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(frame, textvariable=valueVar, width=22).grid(
            row=1, column=1, padx=(8, 0), pady=(8, 0)
        )

        answer = {}

        def confirm():
            answer["value"] = (nameVar.get().strip(), valueVar.get().strip())
            dialog.destroy()

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="确定", command=confirm).pack(side="left", padx=(0, 6))
        ttk.Button(
            actions, text=layout.BUTTONS["dictCancel"], command=dialog.destroy
        ).pack(side="left")

        self.root.wait_window(dialog)
        return answer.get("value")

    def add_item(self):
        answer = self._ask("添加" + self.nameHeading)
        if answer is None:
            return
        name, value = answer
        if not self._check(name, value):
            return
        if any(row[0] == name for row in self.rows):
            messagebox.showinfo(
                "提示", "「{}」已经存在了".format(name), parent=self.root
            )
            return
        self.rows.append([name, value])
        self._refresh()

    def edit_item(self):
        index = self._selected()
        if index is None:
            return
        answer = self._ask("修改" + self.nameHeading, *self.rows[index])
        if answer is None:
            return
        name, value = answer
        if not self._check(name, value):
            return
        self.rows[index] = [name, value]
        self._refresh()

    def delete_item(self):
        index = self._selected()
        if index is None:
            return
        del self.rows[index]
        self._refresh()

    def save_data(self):
        try:
            count = writeDictionary(self.mode, self.rows)
        except ValueError as exc:
            messagebox.showinfo("提示", str(exc), parent=self.root)
            return
        messagebox.showinfo(
            "保存" + self.windowTitle, "已保存 {} 条".format(count), parent=self.root
        )
        self.root.destroy()


class GUI1(jsonTableEditor):
    mode = 1


class GUI2(jsonTableEditor):
    mode = 2


class GUI3(jsonTableEditor):
    mode = 3


# 编辑器类型：1=敏感词 2=字符读法 3=原声大碟
EDITORS = {1: GUI1, 2: GUI2, 3: GUI3}


def runjsonloader(mode):
    """打开对应的词典编辑窗口（经典界面用）。"""
    editor = EDITORS.get(int(mode))
    if editor is None:
        messagebox.showinfo("提示", "未知的词典类型：{}".format(mode))
        return
    editor().start()
