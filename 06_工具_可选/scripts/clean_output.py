#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理模型输出里的内部引用标记与过程话。

用途：
    python clean_output.py input.md output.md
    type input.md | python clean_output.py > output.md

处理：
- 去掉 [cite:...] / [citation:...] 这类内部引用 ID；
- 去掉“我会在知识库中查找”“我先查一下”“让我检索”等过程句；
- 把“知识库”替换成“现有资料”；
- 合并多余空行。

注意：这是兜底，不是替代提示词。提示词仍应要求模型不输出这些内容。
"""

import re
import sys
from pathlib import Path

CITE = re.compile(r"\[(?:cite|citation|ref)\s*:[^\]]*\]", re.I)
PROCESS = re.compile(
    r"^(?:"
    r"我(?:会|先|来|去)?(?:在)?(?:知识库|资料库|现有资料|数据库)?(?:中|里)?(?:查找|查询|检索|搜索|看一下|查一下)"
    r"|让我(?:先)?(?:查|检索|搜索|看)"
    r"|正在(?:检索|查询|搜索)"
    r"|根据(?:知识库|资料库|检索结果)"
    r"|(?:知识库|资料库)(?:显示|中|里|没有|有)"
    r").*$",
    re.M,
)


def clean(text: str) -> str:
    text = text.lstrip("\ufeff")
    text = CITE.sub("", text)
    text = PROCESS.sub("", text)
    text = text.replace("知识库里", "现有资料里").replace("知识库中", "现有资料中")
    text = text.replace("知识库", "现有资料")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    args = sys.argv[1:]
    if len(args) >= 1:
        src = Path(args[0])
        text = src.read_text(encoding="utf-8")
        out = clean(text)
        if len(args) >= 2:
            Path(args[1]).write_text(out, encoding="utf-8")
        else:
            sys.stdout.write(out)
        return 0
    text = sys.stdin.read()
    sys.stdout.write(clean(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
