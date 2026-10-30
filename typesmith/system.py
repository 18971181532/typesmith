"""在系统里找字体。

不同平台装的东西天差地别，所以这里只做"按文件名候选表逐个试"，
失败了再退回扫描目录。CI 上一般只有 DejaVu 系列，本机有微软全家桶。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

__all__ = ["font_dirs", "scan", "find", "pick_defaults", "DEFAULT_CHAINS"]

DEFAULT_CHAINS: Dict[str, List[str]] = {
    "sans": ["arial", "dejavusans", "segoeui", "helvetica", "liberationsans",
             "notosans", "freesans", "calibri", "verdana"],
    "sans_bold": ["arialbd", "dejavusans-bold", "segoeuib", "liberationsans-bold",
                  "notosans-bold", "freesansbold", "calibrib", "verdanab"],
    "serif": ["georgia", "dejavuserif", "times", "liberationserif", "notoserif",
              "freeserif", "cambria"],
    "serif_bold": ["georgiab", "dejavuserif-bold", "timesbd", "liberationserif-bold",
                   "notoserif-bold", "freeserifbold", "cambriab"],
    "mono": ["consola", "dejavusansmono", "cour", "liberationmono", "notosansmono",
             "freemono", "cascadiamono"],
    "cjk": ["simhei", "msyh", "pingfang", "notosanscjksc", "notosanssc",
            "sourcehansanssc", "simsun", "deng"],
}


def font_dirs() -> List[str]:
    home = os.path.expanduser("~")
    out = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.join(home, ".fonts"),
        os.path.join(home, ".local", "share", "fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
        os.path.join(home, "Library", "Fonts"),
    ]
    return [d for d in out if os.path.isdir(d)]


def scan(limit: Optional[int] = None) -> List[str]:
    """递归列出所有 .ttf/.ttc/.otf 文件。"""
    found: List[str] = []
    for root_dir in font_dirs():
        for root, _dirs, files in os.walk(root_dir):
            for name in files:
                if name.lower().endswith((".ttf", ".ttc", ".otf")):
                    found.append(os.path.join(root, name))
            if limit and len(found) >= limit:
                return sorted(found)
    return sorted(found)


def find(names: List[str]) -> Optional[str]:
    """按候选文件名（不含扩展名，小写）找第一个存在的字体。"""
    index = {}
    for path in scan():
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        index.setdefault(stem, path)
        flat = stem.replace(" ", "").replace("_", "").replace("-", "")
        index.setdefault(flat, path)
    for name in names:
        key = name.lower()
        if key in index:
            return index[key]
        flat = key.replace(" ", "").replace("_", "").replace("-", "")
        if flat in index:
            return index[flat]
    return None


def pick_defaults() -> Dict[str, Optional[str]]:
    out = {}
    for role, chain in DEFAULT_CHAINS.items():
        out[role] = find(chain)
    if out.get("sans") is None:
        any_font = (scan() or [None])[0]
        out["sans"] = any_font
        out["sans_bold"] = out["sans_bold"] or any_font
    if out.get("serif") is None:
        out["serif"] = out["sans"]
    if out.get("serif_bold") is None:
        out["serif_bold"] = out["serif"]
    if out.get("mono") is None:
        out["mono"] = out["sans"]
    return out
