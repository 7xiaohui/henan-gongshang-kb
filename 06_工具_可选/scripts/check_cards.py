# -*- coding: utf-8 -*-
"""
正向核对（程序层）：抓取卡片里的法条引用，验证条号在条文 md 里是否存在

它只回答一个问题：**这个条号在这份文件的抽取稿里存在吗？**
它回答不了"这一条讲的是不是卡片说的那件事"——那是人读的活。

输出（写到 out/ 或 KB_OUT）：
  正向核对_程序报告.md       每条引用：存在 / 不存在 / 待人工
  正向核对_引用条文对照.md   每条引用附条文原文，供**含义**比对

怎么认"这条引用属于哪份文件"：
  从条文 md 的**文件名**自动建索引，不需要手写映射表。
  文件名约定：`<编号>_<文件主名>_<文号或年份>[_备注].md`
  例：`C1_某某省某领域条例_2026施行.md` → 主名「某某省某领域条例」

  卡片里写简称（"55 号令""意见二"）时自动认不出，会标成【库外/未识别】——
  想让它认出来，就写一份 aliases.json（格式见 README）。

用法：
  python check_cards.py
  KB_ROOT=/path/to/kb python check_cards.py
  python check_cards.py --aliases aliases.json
  python check_cards.py --allow-outside      # 允许引用库里没有的文件（默认也算"待人工"，不算错）
"""
import glob
import json
import os
import re
import sys
import argparse
import datetime

# ===== 配置：目录约定，一般不用改 =====
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument('--root', default=os.environ.get('KB_ROOT', os.getcwd()))
_ap.add_argument('--md', default=None, help='条文 md 目录（默认自动识别 条文文本 / 2抽取MD条文）')
_ap.add_argument('--cards', default=None, help='卡片目录（默认自动识别 02_知识卡片 / B_知识卡片）')
_ap.add_argument('--aliases', default=None, help='简称表 JSON（可选）')
_KNOWN, _ = _ap.parse_known_args()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import require, out_dir                             # noqa: E402

KB_ROOT = _KNOWN.root
MD = require(KB_ROOT, 'text', _KNOWN.md, flag='--md')
CARDS = require(KB_ROOT, 'cards', _KNOWN.cards, flag='--cards')
OUT_DIR = out_dir(KB_ROOT)
STAMP = datetime.date.today().strftime('%Y%m%d')
OUT1 = os.path.join(OUT_DIR, '正向核对_程序报告.md')
OUT2 = os.path.join(OUT_DIR, '正向核对_引用条文对照.md')
print(f'知识库根：{KB_ROOT}')
print(f'条文 md ：{MD}')
print(f'卡片目录：{CARDS}')


# ---------- 中文数字 ----------
_U = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def c2n(s):
    if not s:
        return 0
    if s in _U:
        return _U[s]
    if s == '十':
        return 10
    if all(ch in _U or ch == '〇' for ch in s) and any(ch == '〇' for ch in s):
        return int(''.join('0' if ch == '〇' else str(_U[ch]) for ch in s))
    s = s.replace('零', '')
    if '千' in s:
        a, r = s.split('千', 1)
        return (_U.get(a, 1) if a else 1) * 1000 + (c2n(r) if r else 0)
    if '百' in s:
        a, r = s.split('百', 1)
        return (_U.get(a, 1) if a else 1) * 100 + (c2n(r) if r else 0)
    if '十' in s:
        a, b = s.split('十', 1)
        return (_U.get(a, 1) if a else 1) * 10 + (_U.get(b, 0) if b else 0)
    if all(ch in _U for ch in s):
        return int(''.join(str(_U[ch]) for ch in s))
    return 0


# ---------- 1. 从 md 目录自动建索引 ----------
ART_NUM = r'第\s*(\d{1,4})\s*条'
ART_CN = r'第\s*([一二三四五六七八九十百千零〇]{1,8})\s*条'


def parse_md(text):
    """抽条号结构：优先 `## 第X条` / `### 第X条`；没有则试 `### 一、` 这种项式编号。"""
    idx = {}
    heads = list(re.finditer(r'^#{2,4}\s*第([一二三四五六七八九十百千零〇\d]{1,9})条\s*$', text, re.M))
    item_mode = False
    if not heads:
        heads = list(re.finditer(r'^#{2,4}\s*([一二三四五六七八九十]{1,3})、', text, re.M))
        item_mode = bool(heads)
    for i, m in enumerate(heads):
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else c2n(raw)
        if not n:
            continue
        start = m.end()
        nxt = re.match(r'^#{2,4}\s', text[start:], re.M)
        end = start + (nxt.start() if nxt else len(text) - start)
        idx[n] = text[start:end].strip()
    return idx, item_mode


def stem_core(stem):
    """文件名 → 文件主名。`C1_某某条例_2026施行` → 某某条例

    注意：主名可能很短（「民法典」3 个字），门槛别设成 4 字——
    否则会退化成整个文件名，卡片里写《民法典》就认不出来了。
    """
    parts = re.split(r'[_—]', stem)
    body = parts[1:] if len(parts) > 1 else parts
    for p in body:
        if len(re.findall(r'[\u4e00-\u9fa5]', p)) >= 2:
            return p
    return stem


def aliases_from_stem(stem):
    """从文件名推文号别名：某某发〔2025〕14号 / 某某发2025-14号 / 某某令第8号"""
    out = set()
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,10})\s*[〔\[]?(\d{4})[〕\]]?\s*[-—－]?\s*(\d{1,3})\s*号', stem):
        org, y, n = m.groups()
        out.add(f'{org}〔{y}〕{n}号')
        out.add(f'{org}{y}-{n}号')
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,10})\s*令\s*第?\s*(\d{1,3})\s*号', stem):
        org, n = m.groups()
        out.add(f'{org}令第{n}号')
    return out


LAWS = {}        # code(=stem) -> {'title':..., 'arts':{...}, 'item':bool}
REFS = set()     # 无条号结构的 md（参考文本）
BOOK_MAP = []    # (书名号内片段, code)      —— 强锚点
STRONG_MAP = []  # (法律简称, code)          —— 强锚点，可以"管到后面"
WEAK_MAP = []    # (文号, code)              —— 弱锚点，只管紧跟的一两个条号

for path in sorted(glob.glob(os.path.join(MD, '*.md'))):
    stem = os.path.basename(path)[:-3]
    if stem.startswith(('_', '.')) or stem.endswith('清单'):
        continue
    text = open(path, encoding='utf-8').read()
    arts, item_mode = parse_md(text)
    core = stem_core(stem)
    h1 = re.search(r'^#\s+(.+)$', text, re.M)
    title = h1.group(1).strip() if h1 else core
    if len(arts) >= 3:
        LAWS[stem] = {'title': title, 'arts': arts, 'item': item_mode}
    else:
        REFS.add(stem)
    if len(re.findall(r'[\u4e00-\u9fa5]', core)) >= 3:
        BOOK_MAP.append((core, stem))
        STRONG_MAP.append((core, stem))
    for a in aliases_from_stem(stem):
        BOOK_MAP.append((a, stem))
        WEAK_MAP.append((a, stem))

# 简称表（可选）：{"55号令": "B9_...55号...", "意见二": "B5_..."}
# 简称表里的一律当强锚点——你自己写的简称，你负责它指谁
if _KNOWN.aliases:
    for alias, stem in json.load(open(_KNOWN.aliases, encoding='utf-8')).items():
        STRONG_MAP.append((alias, stem))
        BOOK_MAP.append((alias, stem))

if not LAWS:
    raise SystemExit(f'在 {MD} 里没找到带条号结构的 md。\n'
                     f'先跑 extract_all.py 抽条文，或确认 md 里条头是 "## 第X条" 这种独立一行。')

BOOK_MAP.sort(key=lambda x: -len(x[0]))     # 长名优先，避免短名吃掉长名
STRONG_MAP.sort(key=lambda x: -len(x[0]))
WEAK_MAP.sort(key=lambda x: -len(x[0]))
CODE_TITLE = {c: v['title'] for c, v in LAWS.items()}
CODE_TITLE.update({c: c for c in REFS})
print(f'条文型 {len(LAWS)} 份 ｜ 参考文本 {len(REFS)} 份 ｜ 强锚点 {len(STRONG_MAP)} ｜ 弱锚点 {len(WEAK_MAP)}\n')


# ---------- 2. 引用解析 ----------
EV_RANGE = r'第\s*(\d{1,4})\s*条?\s*[-—–~～至到]\s*(\d{1,4})\s*条'
EV_CN_RANGE = (r'第\s*([一二三四五六七八九十百千零〇]{1,8})\s*条\s*[至到]\s*第?\s*'
               r'([一二三四五六七八九十百千零〇]{1,8})\s*条')


def parse_citations(card):
    text = re.sub(r'\s+', '', open(card, encoding='utf-8').read())
    events = []

    for m in re.finditer(r'《([^》]+)》', text):
        inner = m.group(1)
        code = next((c for name, c in BOOK_MAP if name in inner), None)
        events.append((m.start(), 'law', (code, inner)))

    masked = re.sub(r'《[^》]*》', lambda m: '\u3001' * len(m.group(0)), text)

    def collect(items):
        """把别名表编译成一个正则，长名优先（items 已按长度降序）。"""
        if not items:
            return
        alt, gmap = [], {}
        for i, (pat, c) in enumerate(items):
            g = f'g{i}'
            gmap[g] = c
            alt.append(f'(?P<{g}>{re.escape(pat)})')
        for m in re.finditer('|'.join(alt), masked):
            yield m, gmap[m.lastgroup]

    # 强锚点：法律简称。出现过一次，后面没换锚点的条号都归它
    for m, c in collect(STRONG_MAP):
        events.append((m.start(), 'anchor', (c, m.group(0))))
    # 弱锚点：文号。只对紧跟其后的条号有效，超过 15 字就失效，不改全局锚点
    for m, c in collect(WEAK_MAP):
        events.append((m.start(), 'weak', (c, m.group(0), m.end() + 15)))

    for m in re.finditer(EV_RANGE, text):
        events.append((m.start(), 'range', (int(m.group(1)), int(m.group(2)))))
    for m in re.finditer(EV_CN_RANGE, text):
        events.append((m.start(), 'range', (c2n(m.group(1)), c2n(m.group(2)))))
    for m in re.finditer(r'第(\d{1,4})((?:、\d{1,4})+)条', text):
        events.append((m.start(), 'list', [int(m.group(1))] + [int(x) for x in m.group(2).split('、')[1:]]))
    for m in re.finditer(r'第([一二三四五六七八九十百千零〇]{1,8})((?:、[一二三四五六七八九十百千零〇]{1,8})+)条', text):
        events.append((m.start(), 'list', [c2n(m.group(1))] + [c2n(x) for x in m.group(2).split('、')[1:]]))
    for m in re.finditer(r'第(\d{1,4})条|' + ART_CN, text):
        g1, g2 = m.group(1), m.group(2)
        n = int(g1) if g1 else c2n(g2 or '')
        if n:
            events.append((m.start(), 'art', n))

    events.sort(key=lambda e: e[0])
    cites, cur, cur_range, pending = {}, None, ('?', 0, 0), None
    for pos, kind, payload in events:
        if kind == 'law':
            code, title = payload
            cur = code if code else f'《{title.strip("《》")}》'
            pending = None
            continue
        if kind == 'anchor':
            cur, pending = payload[0], None
            continue
        if kind == 'weak':
            pending = (payload[0], payload[2])      # (code, 失效位置)
            continue

        key2 = cur or '《?》'
        if pending and pos <= pending[1]:
            key2 = pending[0]
        if kind == 'range':
            lo, hi = payload
            cur_range = (key2, lo, hi)
            for n in range(lo, hi + 1):
                cites.setdefault((key2, n), text[max(0, pos - 30):pos + 40])
        elif kind == 'list':
            for n in payload:
                cites.setdefault((key2, n), text[max(0, pos - 30):pos + 40])
        else:
            if cur_range[0] not in ('?', key2) and cur_range[1] <= payload <= cur_range[2]:
                key2 = cur_range[0]
            cites.setdefault((key2, payload), text[max(0, pos - 30):pos + 40])

    return cites


# ---------- 3. 验证 ----------
cards = sorted(glob.glob(os.path.join(CARDS, '*.md')))
cards = [c for c in cards if not os.path.basename(c).startswith(('_', '.'))]

rep = ['# 正向核对 · 程序报告（条号存在性）', '',
       f'> 生成：{STAMP} ｜ 条文型 {len(LAWS)} 份 / 参考文本 {len(REFS)} 份 / 卡片 {len(cards)} 张', '',
       '> 图例：✅ 条号在该文件抽取稿中存在 ｜ ❌ 条号不存在（超范围）',
       '> ｜ ⚠️ 需要人工（库外文件 / 参考文本 / 归属存疑）', '',
       '> 🔴 **⚠️ 不等于错**：多半是卡片写了简称，脚本没认出来。补 `aliases.json` 就能进 ✅ 或 ❌。', '']
dig = ['# 正向核对 · 引用×条文对照（含义核对底稿）', '',
       '> 用途：逐条读"卡片上下文 vs 条文原文"，判断**含义**对不对。脚本判不了这一步。', '']
stat = {'ok': 0, 'bad': 0, 'manual': 0}

for card in cards:
    name = os.path.basename(card)[:-3]
    cites = parse_citations(card)
    rep.append(f'## {name}')
    dig.append(f'## {name}')
    if not cites:
        rep += ['- （未检出可解析的条文引用）', '']
        dig += ['- （无）', '']
        continue

    for code, n in sorted(cites, key=lambda x: (str(x[0]), x[1])):
        ctx = cites[(code, n)]
        title = CODE_TITLE.get(code, str(code).strip('《》'))

        if code not in LAWS:
            kind = '参考文本（无条号结构）' if code in REFS else '库外/未识别'
            rep.append(f'- ⚠️ 【{kind}】{title} 第{n}条 ｜ 上下文：{ctx}')
            dig.append(f'- 【{kind}】{title} 第{n}条 ｜ {ctx}')
            stat['manual'] += 1
            continue

        law = LAWS[code]
        art = law['arts'].get(n)
        if art:
            note = ''
            if law['item']:
                note = f' ⚡️注：该文件原件用"一、二、"编号，无"第X条"，卡片宜写"第{n}项"'
            rep.append(f'- ✅ {title} 第{n}条{note}')
            dig.append(f'### {title} 第{n}条\n**卡片上下文**：{ctx}\n\n**条文原文**：\n\n{art}\n')
            stat['ok'] += 1
            continue

        # 当前文件没这条：先看是不是挂错了名（别的文件里有同号条目）
        alt = sorted(c for c, v in LAWS.items() if c != code and n in v['arts'])
        if alt:
            names = '、'.join(f'【{CODE_TITLE[a]}】' for a in alt[:4])
            more = f' 等 {len(alt)} 份' if len(alt) > 4 else ''
            rep.append(f'- ⚠️ 归属存疑：挂在【{title}】名下，该文件无第{n}条；'
                       f'{names}{more} 有第{n}条。**机器判不了该归谁，需人工确认**。 ｜ 上下文：{ctx}')
            dig.append(f'### ⚠️ 归属存疑 第{n}条：锚点=【{title}】（该文件无此条）\n'
                       f'**候选**：{names}{more}\n\n**卡片上下文**：{ctx}\n')
            stat['manual'] += 1
        else:
            # 所有文件都没有这个条号 → 这才是能断定的"条号不存在"
            top = max((len(v['arts']) for v in LAWS.values()), default=0)
            rep.append(f'- ❌ 【{title}】第{n}条 —— 该文件共 {max(law["arts"]) if law["arts"] else 0} 条，'
                       f'且全部 {len(LAWS)} 份条文都没有第{n}条（最长的一份 {top} 条）。'
                       f'**条号本身有问题**。 ｜ 上下文：{ctx}')
            dig.append(f'### ❌ 【{title}】第{n}条 —— 全部条文都没有这个条号\n**卡片上下文**：{ctx}\n')
            stat['bad'] += 1
    rep.append('')
    dig.append('')

open(OUT1, 'w', encoding='utf-8').write('\n'.join(rep))
open(OUT2, 'w', encoding='utf-8').write('\n'.join(dig))

print('✅存在 %d ｜ ❌不存在 %d ｜ ⚠️待人工 %d' % (stat['ok'], stat['bad'], stat['manual']))
print('报告：', OUT1)
print('底稿：', OUT2)
print('\n下一步：打开底稿，逐条读"卡片上下文 vs 条文原文"。'
      '⚠️ 里凡写【库外/未识别】的，先补 aliases.json 再判，别直接当成卡片错。')
