#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识卡片 · 结构质检

用途：每次改完卡片后跑一遍，确认所有卡片结构统一、没有退化。
检查项：
  1. 连续 11 个管道符行（表头 + 分隔符 + 9 字段，且字段顺序正确）
  2. 正文只允许「展开说明 / 相关」两个二级标题
  3. 正文小节编号从「一、」开始且连续
  4. 必备尾部：相关章节 + 免责声明
  5. 每张卡至少 1 个可点出处 URL 或本地权威资料路径
  6. 弱表述扫描（大概/可能/一般来说 等）

用法：
  python card_qc.py                      # 默认以当前目录为知识库根
  python card_qc.py --strict             # 有错时退出码 1（可用于自动化）
  python card_qc.py --inner "口径基准,使用规范"   # 追加"内部底稿"名单
  KB_ROOT=/path/to/kb python card_qc.py
"""
import os
import re
import sys
import argparse

_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument('--root', default=os.environ.get('KB_ROOT', os.getcwd()))
_ap.add_argument('--cards', default=None, help='卡片目录（默认自动识别 02_知识卡片 / B_知识卡片）')
_ap.add_argument('--inner', default=None,
                 help='内部底稿文件名片段，逗号分隔；出现在「出处链接」里即报错')
_KNOWN, _ = _ap.parse_known_args()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import require                                    # noqa: E402

# ===== 卡片目录：两套命名都认（工作区 B_知识卡片 / 交付包 02_知识卡片） =====
BASE = require(_KNOWN.root, 'cards', _KNOWN.cards, flag='--cards')

# 九字段：结论 / 依据 / 适用条件 / 计算口径 / 易错点 / 待核实 / 出处链接 / 口径提示 / 更新日期
FIELDS = ["结论", "依据", "适用条件", "计算口径", "易错点", "待核实", "出处链接", "口径提示", "更新日期"]
CN_DIGIT = "一二三四五六七八九十"
ALLOWED_H2 = {"展开说明", "相关"}
WEAK_WORDS = ["大概", "可能是", "估计", "应该是"]


def cn_to_int(s):
    if s in CN_DIGIT:
        return CN_DIGIT.index(s) + 1
    if s == "十一":
        return 11
    return None


def check_one(path):
    """返回 (问题列表, 统计字典)"""
    issues = []
    name = os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")

    # --- 1. 十行连续表 ---
    head_idx = None
    for i, line in enumerate(lines):
        if line.strip().replace(" ", "") == "|字段|内容|":
            head_idx = i
            break
    if head_idx is None:
        issues.append("没有标准表头 | 字段 | 内容 |")
    else:
        block = lines[head_idx:head_idx + 11]
        if len(block) < 11:
            issues.append("表格不足 11 行（实际 %d 行）" % len(block))
        elif any(not x.strip().startswith("|") for x in block):
            issues.append("11 行内混入非表格行（表格被截断）")
        else:
            joined = "\n".join(block)
            missing = [f for f in FIELDS if ("**%s**" % f) not in joined]
            if missing:
                issues.append("缺字段：%s" % "、".join(missing))
            else:
                pos = [joined.index("**%s**" % f) for f in FIELDS]
                if pos != sorted(pos):
                    issues.append("字段顺序错乱")

    # --- 2. 二级标题白名单 ---
    h2 = [x.strip() for x in re.findall(r"^##\s+(.+?)\s*$", text, re.M)]
    extra_h2 = [x for x in h2 if x not in ALLOWED_H2]
    if extra_h2:
        issues.append("出现非白名单二级标题：%s" % "、".join(extra_h2))
    if "展开说明" not in h2:
        issues.append("缺 ## 展开说明")
    if "相关" not in h2:
        issues.append("缺 ## 相关")

    # --- 3. 小节编号连续性 ---
    seg = re.search(r"^## 展开说明(.*?)(?=^## |\Z)", text, re.M | re.S)
    if seg:
        nums = [cn_to_int(x) for x in
                re.findall(r"^###\s+([一二三四五六七八九十]+)、", seg.group(1), re.M)]
        if nums and nums != list(range(1, len(nums) + 1)):
            issues.append("小节编号不连续：%s" % nums)

    # --- 4. 尾部必备 ---
    if "不构成法律意见" not in text:
        issues.append("缺免责声明（不构成法律意见）")

    # --- 5. 出处 ---
    n_url = len(re.findall(r"https?://", text))
    n_local = len(re.findall(r"`\.\./", text))
    if n_url == 0 and n_local == 0:
        issues.append("全卡无可点出处（既无 URL 也无 ../ 路径）")

    # --- 5b. 出处链接不得引用内部工作底稿 ---
    src_line = ""
    for l in lines:
        if l.startswith("| **出处链接** |"):
            src_line = l; break
    # 只拦「内部 .md 工作底稿」；`../原件目录/xxx.pdf` 属正当原件，放行
    # 内部底稿名单按项目不同，用 --inner 传入（逗号分隔）；不传就只靠下面的 .md 兜底规则
    inner_names = [x.strip() for x in (_KNOWN.inner or '').split(',') if x.strip()]
    bad_inner = [n for n in inner_names if n in src_line]
    # 兜底：出处链接里出现任何 ../ 且以 .md 结尾
    if re.search(r"`\.\./[^`]*\.md`", src_line):
        bad_inner.append("内部md路径")
    if bad_inner:
        issues.append("出处链接混入内部文件：%s" % "、".join(bad_inner))

    # --- 5c. 不得残留过程痕迹 ---
    trace_pats = [r"用户\s*2026", r"用户原话", r"补八字段", r"正文内容未改"]
    for tp in trace_pats:
        if re.search(tp, text):
            issues.append("残留过程痕迹：%s" % tp)

    # --- 6. 弱表述 ---
    weak = [w for w in WEAK_WORDS if w in text]

    # --- 7. 死链检查：反引号内的 .md/.pdf/.html/.txt 引用必须真实存在 ---
    # 跳过：URL 写法、命名示例占位符（xx / yy / ...）
    PLACEHOLDER = re.compile(r"(xx|yy|XX|YY|\.\.\.|https?:|^rsj\.|^www\.)|^\S+ \S+ / ", re.I)
    here = os.path.dirname(path)
    dead = []
    for m in re.finditer(r"`([^`\n]*?\.(?:md|pdf|html|txt))`", text):
        ref = m.group(1).strip()
        if PLACEHOLDER.search(ref):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(here, ref))):
            dead.append(ref)
    if dead:
        issues.append("死链 %d 处：%s" % (len(dead), "、".join(dead[:3])))

    # --- 统计 ---
    stat = {
        "字数": len(text),
        "URL": n_url,
        "本地资料": n_local,
        "小节数": len(re.findall(r"^###\s+", text, re.M)),
        "弱表述": weak,
        "死链": len(dead),
    }
    return issues, stat


def main():
    strict = "--strict" in sys.argv
    if not os.path.isdir(BASE):
        print("目录不存在：%s" % BASE)
        return 2

    files = sorted(f for f in os.listdir(BASE) if f.endswith(".md"))
    failed = 0
    print("检查目录：%s" % BASE)
    print("文件数：%d\n" % len(files))

    for f in files:
        issues, stat = check_one(os.path.join(BASE, f))
        if issues:
            failed += 1
            print("x %s" % f)
            for it in issues:
                print("    - %s" % it)
        else:
            print(". %-44s %5d 字  小节 %d" % (f[:44], stat["字数"], stat["小节数"]))
        if stat["弱表述"]:
            print("    ~ 弱表述待人工判断：%s" % "、".join(stat["弱表述"]))

    print("\n通过 %d / %d" % (len(files) - failed, len(files)))
    if failed:
        print("未通过 %d 个" % failed)
        return 1 if strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
