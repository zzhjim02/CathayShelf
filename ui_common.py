# -*- coding: utf-8 -*-
"""三个选项卡共用的小工具：拖放支持、路径解析、共享「待处理」来源。"""
import os
import tkinter as tk

HAS_DND = False
DND_FILES = None
TkinterDnD = None
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    pass


def tk_splitlist(root, data):
    """解析拖拽数据（含空格路径用 {} 包裹）。"""
    try:
        return [p for p in root.tk.splitlist(data) if p]
    except Exception:
        return [p.strip('{}') for p in str(data).split() if p]


class Shared:
    """三个选项卡共用一份「待处理」来源。"""

    def __init__(self):
        self.paths = []
        self.dirty = False      # 某页产生了新文件时置位，切页时强制重扫


def bind_drop(root, widgets, handler):
    if not HAS_DND:
        return
    for w in widgets:
        try:
            w.drop_target_register(DND_FILES)
            w.dnd_bind('<<Drop>>', handler)
        except Exception:
            pass
