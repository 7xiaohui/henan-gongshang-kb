# -*- coding: utf-8 -*-
"""
反向核对：资料库里每份原件 ← 被哪些卡片 / 规则文件引用。零引用 → 待删除建议。

为什么要做反向：只做正向（卡 → 资料）会留下"资料冗余"——买回来没人用的文件；
只做反向（资料 → 卡）会留下"引用错配"。**两个方向都做，才算核过。**

找"某份原件有没有被引用"靠**识别键**：文件名里的关键片段 + 文号 + 长数字。
本脚本默认从文件名**自动生成**识别键，命中率不够时用 `--keys keys.json` 手写覆盖。

keys.json 格式（手写时）：
  {
    "A1_示例文件_示例文号": ["示例文件", "示例文号"],
    "C2_示例数据_20XX": ["1234.5", "示例〔20XX〕1号"]
  }
键写成"文件名去掉扩展名后的前缀"，值是该文件在卡片里可能出现的几种写法。

用法：
  python reverse_check.py
  KB_ROOT=/path/to/kb python reverse_check.py
  python reverse_check.py --keys keys.json
"""
import os, re, sys, glob, json, argparse, unicodedata

_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument('--root', default=os.environ.get('KB_ROOT', os.getcwd()))
_ap.add_argument('--keys', default=None)
_ap.add_argument('--src', default=None, help='原件目录（默认自动识别 1原始资料 / 03_权威资料）')
_ap.add_argument('--cards', default=None, help='卡片目录（默认自动识别）')
_ap.add_argument('--rules', default=None, help='规则目录（默认自动识别）')
_KNOWN, _ = _ap.parse_known_args()
ROOT = _KNOWN.root

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import require                                       # noqa: E402

# ===== 目录：两套命名都认（工作区 A/B/C / 交付包 01/02/03） =====
SRC_DIR = require(ROOT, 'raw', _KNOWN.src, flag='--src')
_CARD_DIR = require(ROOT, 'cards', _KNOWN.cards, flag='--cards')
_RULE_DIR = require(ROOT, 'rules', _KNOWN.rules, flag='--rules')
CARD_GLOB = os.path.join(_CARD_DIR, '*.md')
RULE_GLOB = os.path.join(_RULE_DIR, '*.md')

CARDS = glob.glob(CARD_GLOB)
RULES = glob.glob(RULE_GLOB)


def norm(s):
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'(?<=\d),(?=\d)', '', s)      # 86,199 = 86199：千分位不许挡住匹配
    for a, b in [('（', '('), ('）', ')'), ('〔', '('), ('〕', ')'), ('【', '['), ('】', ']'),
                 ('《', ''), ('》', ''), ('—', '-'), ('–', '-'), ('～', '~'), ('、', '')]:
        s = s.replace(a, b)
    return s.lower()


def _is_year(s):
    """1900–2099 之间的四位纯数字当成年份，不能做识别键——几乎每张卡都有年份，会全表命中。"""
    return len(s) == 4 and s.isdigit() and '1900' <= s <= '2099'


def auto_keys(stem):
    """从文件名推识别键：拆分隔符 → 丢掉字母数字前缀 → 保留长片段 + 文号 + 长数字。"""
    tokens = re.split(r'[_—\-\s]+', stem)
    keys = []
    for i, t in enumerate(tokens):
        if i == 0 and re.fullmatch(r'[A-Za-z]{1,4}\d{0,6}', t):
            continue                      # A1 / GBT16180 / S2 这类前缀不进键
        t = t.strip()
        if len(t) >= 3 and not _is_year(t):
            keys.append(t)
    # 文号：〔2025〕14号 / 2025-14号 / 2025〕14号
    for m in re.finditer(r'(\d{4})[〕\-\)]*\s*(\d{1,4})\s*号', stem):
        keys.append(f'{m.group(1)}〕{m.group(2)}号')
        keys.append(f'{m.group(1)}-{m.group(2)}号')
    # 长数字（基数、金额、电话）——排除年份
    for m in re.finditer(r'\d{4,}', stem):
        if not _is_year(m.group(0)):
            keys.append(m.group(0))
    out = []
    for k in keys:
        kk = norm(k)
        if len(kk) >= 3 and kk not in out:
            out.append(kk)
    return out


MANUAL = {}
if _KNOWN.keys:
    with open(_KNOWN.keys, encoding='utf-8') as fh:
        MANUAL = json.load(fh)

card_texts = {os.path.basename(p): norm(open(p, encoding='utf-8').read()) for p in CARDS}
rule_texts = {os.path.basename(p): norm(open(p, encoding='utf-8').read()) for p in RULES}

print(f'知识库根：{ROOT}')
print(f'卡片 {len(card_texts)} 份 / 规则 {len(rule_texts)} 份 / 原件目录：{SRC_DIR}\n')


def scan(keys, text_map):
    hits = []
    for fname, text in text_map.items():
        for k in keys:
            kk = norm(k)
            if kk and kk in text:
                hits.append(fname)
                break
    return hits


def pick_keys(fname, stem):
    """手写覆盖优先；否则自动生成。返回 (键组名, 键列表)。"""
    for grp, keys in MANUAL.items():
        base = grp.split('_')[0]
        if stem == base or stem.startswith(base + '_') or stem.startswith(base + '—'):
            return grp, keys
    return stem, auto_keys(stem)


rows = []
if not os.path.isdir(SRC_DIR):
    sys.exit(f'找不到原件目录：{SRC_DIR}\n请用 --root 指向知识库根，或直接改文件头部的目录约定。')

for f in sorted(os.listdir(SRC_DIR)):
    if f.startswith('.') or f.startswith('_'):
        continue
    stem = f.rsplit('.', 1)[0]
    grp, keys = pick_keys(f, stem)
    if not keys:
        rows.append((f, grp, [], [], '无可用识别键'))
        continue
    rows.append((f, grp, scan(keys, card_texts), scan(keys, rule_texts), ''))

print('| 资料文件 | 卡片直接引用 | 前置规则间接引用 | 判定 |')
print('|---|---|---|---|')
zero = []
for f, grp, ch, rh, note in rows:
    cards = ', '.join(sorted(c[:3] for c in ch)) or '—'
    rules = ', '.join(sorted(r[:2] for r in rh)) or '—'
    if note:
        verdict = '⚠️ 需手工指定键'
    else:
        verdict = '✅ 在用' if (ch or rh) else '❌ 零引用'
        if not (ch or rh):
            zero.append(f)
    print('| %s | %s | %s | %s |' % (f, cards, rules, verdict))

print('\n零引用清单：', len(zero))
for z in zero:
    print(' -', z)

if zero:
    print('\n⚠️ 零引用不等于可以删。上面这些文件当时用的识别键是：')
    for f, grp, ch, rh, note in rows:
        if f in zero:
            _, keys = pick_keys(f, f.rsplit('.', 1)[0])
            print(f'  {f}\n    键：{keys or "（无）"}')
    print('   若键太严（整串文件名当键），用 --keys keys.json 改成卡片里真实出现的写法。')
    print('   键看着没问题却仍零引用 → 这文件确实没人用，逐条人工确认后再移入待删除目录。')
