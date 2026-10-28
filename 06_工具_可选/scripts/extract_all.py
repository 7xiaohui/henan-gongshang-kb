# -*- coding: utf-8 -*-
"""
原件全量抽取：原始资料 → 条文 md

做两件事：
  1. **条文型**（法规/规章/标准/办法）：顺序递增切条，逐条成节
  2. 其余（通知、指南、问答、表格、截图型）：清洗后整篇作"参考文本"，标注不作依据

顺序递增切条的原理：下一个条号必须严格 = 上一个 + 1。
正文里"依照本办法第八条处理"这类**引用式条号**天然断开序号，被自动跳过——
这是不用人工判断就能过滤掉大部分假条号的办法。

四道校验：缺号 / 重号 / 乱码（汉字占比 < 0.3）/ 过短。

用法：
  python extract_all.py                          # 以当前目录为知识库根
  python extract_all.py --root /path/to/kb
  python extract_all.py --src 原件目录 --out 输出目录
  KB_ROOT=/path/to/kb python extract_all.py

依赖：pymupdf（PDF）、python-docx（docx）
"""
import os
import re
import sys
import glob
import argparse
import datetime

sys.stdout.reconfigure(encoding='utf-8')

try:
    import pymupdf
except ImportError:
    pymupdf = None
try:
    import docx as docxlib
except ImportError:
    docxlib = None

# ===== 配置：目录约定，一般不用改 =====
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument('--root', default=os.environ.get('KB_ROOT', os.getcwd()))
_ap.add_argument('--src', default=None, help='原件目录（默认自动识别 1原始资料 / 03_权威资料）')
_ap.add_argument('--out', default=None, help='输出目录（默认自动识别 条文文本 / 2抽取MD条文）')
_KNOWN, _ = _ap.parse_known_args()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import resolve                                        # noqa: E402

SRC = resolve(_KNOWN.root, 'raw', _KNOWN.src)
OUT = resolve(_KNOWN.root, 'text', _KNOWN.out)
if not SRC:
    raise SystemExit(f'找不到原件目录。请在 {os.path.abspath(_KNOWN.root)} 下放 1原始资料/ 或 '
                     '03_权威资料/，或用 --src 指定。')
if not OUT:
    if _KNOWN.out:
        OUT = os.path.abspath(_KNOWN.out)
    else:
        raise SystemExit(f'找不到条文输出目录。新建一个后用 --out 指定（例：--out "{os.path.join(os.path.abspath(_KNOWN.root), "条文文本")}"）')
os.makedirs(OUT, exist_ok=True)

SUPPORTED = ('.pdf', '.docx', '.txt', '.md', '.html', '.htm')
MIN_ARTICLES = 3           # 少于这个数当"参考文本"处理
MIN_ARTICLE_CHARS = 15     # 单条正文少于这个字数 → 判"过短"
MIN_HAN_RATIO = 0.30       # 汉字占比低于此值 → 判乱码


# ---------- 中文数字 ----------
_CN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def c2n(s):
    """中文数字转阿拉伯数字。

    必须支持的三种写法（少一种就会漏条号）：
      常规：一千二百六十
      含零：一百零九
      省写：第一五三条 / 第一〇三条（部委规章常见，不是"第一百五十三条"）
    正则上限至少要 8 个汉字——"第一千一百一十一条"是 7 个字。
    """
    if not s:
        return 0
    if s in _CN:
        return _CN[s]
    if s == '十':
        return 10
    # 省写式：全部由单位数字或〇组成且含〇 → 逐位映射（一〇三 → 103）
    if all(ch in _CN or ch == '〇' for ch in s) and any(ch == '〇' for ch in s):
        return int(''.join('0' if ch == '〇' else str(_CN[ch]) for ch in s))
    s = s.replace('零', '')
    if '千' in s:
        a, rest = s.split('千', 1)
        return (_CN.get(a, 1) if a else 1) * 1000 + (c2n(rest) if rest else 0)
    if '百' in s:
        a, rest = s.split('百', 1)
        return (_CN.get(a, 1) if a else 1) * 100 + (c2n(rest) if rest else 0)
    if '十' in s:
        a, b = s.split('十', 1)
        return (_CN.get(a, 1) if a else 1) * 10 + (_CN.get(b, 0) if b else 0)
    if all(ch in _CN for ch in s):
        return int(''.join(str(_CN[ch]) for ch in s))   # 一五三 这种省写
    return 0


ART_RE = re.compile(r'第([一二三四五六七八九十百千零〇]{1,9})条')


# ---------- 读文件 ----------
def read_pdf(path):
    if pymupdf is None:
        raise RuntimeError('缺少 pymupdf，请先 pip install pymupdf')
    doc = pymupdf.open(path)
    # sort=True 必须开：否则文本流顺序会错，相邻条内容会串到一起
    return '\n'.join(page.get_text('text', sort=True) for page in doc), len(doc)


def read_docx(path):
    if docxlib is None:
        raise RuntimeError('缺少 python-docx，请先 pip install python-docx')
    d = docxlib.Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:                       # 表格型文件（缴费标准、材料清单）不能漏
        for row in t.rows:
            cells = [c.text.strip().replace('\n', ' ') for c in row.cells]
            if any(cells):
                parts.append(' | '.join(cells))
    return '\n'.join(parts), None


def read_html(path):
    raw = open(path, encoding='utf-8', errors='ignore').read()
    raw = re.sub(r'(?is)<(script|style).*?</\1>', '', raw)
    raw = re.sub(r'(?s)<[^>]+>', '\n', raw)
    raw = raw.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return raw, None


def clean(text):
    text = text.replace('\u3000', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [ln.strip() for ln in text.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def han_ratio(s):
    if not s:
        return 0.0
    han = len(re.findall(r'[\u4e00-\u9fa5]', s))
    return han / max(len(s), 1)


# ---------- 切条 ----------
def _line_start_candidates(text):
    """只收"行首"的条号。

    正文里"依照本办法第八条处理"是引用，不是条头；条头几乎总在行首。
    这一步把大部分假条号直接挡掉，比任何后处理都干净。
    """
    out = []
    for m in ART_RE.finditer(text):
        # 取本行开头到匹配位置的片段，只允许有空白/项目符号
        ls = text.rfind('\n', 0, m.start()) + 1
        prefix = text[ls:m.start()].strip(' \t　·•　-—')
        if prefix:
            continue
        num = c2n(m.group(1))
        if num > 0:
            out.append((num, m.start(), m.end()))
    return out


def split_articles(text):
    """切条。返回 (articles[(num, body)], gaps, dups, skipped)

    先按行首取候选，再按顺序递增认条：只接受 num == expected 的候选。
    行首候选太少（说明这份文件的条文没有独立成行）时，退回全匹配 + 顺序递增。
    """
    cands = _line_start_candidates(text)
    if len(cands) < MIN_ARTICLES:
        cands = [(c2n(m.group(1)), m.start(), m.end()) for m in ART_RE.finditer(text)
                 if c2n(m.group(1)) > 0]

    # 全部候选的起点表，用来确定每条正文的终点
    starts = sorted({s for _, s, _ in cands})

    def body_end(pos):
        for s in starts:
            if s > pos:
                return s
        return len(text)

    articles, gaps, dups, skipped = [], [], [], 0
    expected = 1
    for num, start, end in cands:
        if num == expected:
            articles.append((num, text[end:body_end(start)].strip()))
            expected += 1
        elif num < expected:
            if num == expected - 1:
                dups.append(num)
            else:
                skipped += 1          # 引用式条号，或重复出现的条头
        # num > expected：先不认，等它前面缺的那条出现（正文里跳号引用极为常见）

    # 收尾：文档末尾若整体缺条（如最后一条抽不出来），把已攒下的补进来
    got = {n for n, _ in articles}
    tail = [(n, s, e) for n, s, e in cands if n not in got and n == max(got, default=0) + 1]
    for num, start, end in tail:
        articles.append((num, text[end:body_end(start)].strip()))

    articles.sort(key=lambda x: x[0])
    nums = [n for n, _ in articles]
    if nums:
        seen, gaps = set(), []
        for n in range(1, max(nums) + 1):
            if n not in seen and n not in nums:
                gaps.append(n)
        seen = {n for n in nums if nums.count(n) > 1}
        dups = sorted(seen)
    return articles, gaps, dups, skipped


def render(name, articles, meta_lines):
    head = [f'# {name}', '']
    head += [f'> {ln}' for ln in meta_lines]
    head += ['', '---', '']
    body = []
    for num, text in articles:
        body.append(f'## 第{c2n_str(num)}条\n\n{text}\n')
    return '\n'.join(head) + '\n'.join(body)


def render_ref(name, text, meta_lines):
    head = [f'# {name}', '']
    head += [f'> {ln}' for ln in meta_lines]
    head += ['', '---', '', text, '']
    return '\n'.join(head)


_CNU = '零一二三四五六七八九'


def c2n_str(n):
    """阿拉伯数字 → 规范中文条号（只用于标题排版，不参与比对）。"""
    if n <= 10:
        return '十' if n == 10 else _CNU[n]
    if n < 20:
        return '十' + _CNU[n - 10]
    if n < 100:
        return ('' if n // 10 == 1 else _CNU[n // 10]) + '十' + (_CNU[n % 10] if n % 10 else '')
    if n < 1000:
        h, r = divmod(n, 100)
        return _CNU[h] + '百' + (('零' + c2n_str(r)) if 0 < r < 10 else (c2n_str(r) if r else ''))
    t, r = divmod(n, 1000)
    return _CNU[t] + '千' + (('零' + c2n_str(r)) if 0 < r < 100 else (c2n_str(r) if r else ''))


# ---------- 主流程 ----------
def main():
    if not os.path.isdir(SRC):
        sys.exit(f'找不到原件目录：{SRC}\n用 --src 指定，或先建好目录把原件放进去。')
    os.makedirs(OUT, exist_ok=True)
    files = sorted(f for f in os.listdir(SRC)
                   if f.lower().endswith(SUPPORTED) and not f.startswith(('_', '.')))
    if not files:
        sys.exit(f'{SRC} 里没有可抽取的文件（支持 {" ".join(SUPPORTED)}）。')

    print(f'知识库根：{_KNOWN.root}')
    print(f'读：{SRC}\n写：{OUT}\n文件数：{len(files)}\n')

    # 同一份文件常见"docx + pdf 同名"两份：只抽一份，docx 优先（文字层最干净）
    PRIORITY = {'.docx': 0, '.txt': 1, '.md': 1, '.html': 2, '.htm': 2, '.pdf': 3}
    by_stem = {}
    for fn in files:
        stem = fn.rsplit('.', 1)[0]
        ext = '.' + fn.lower().rsplit('.', 1)[-1]
        by_stem.setdefault(stem, []).append((PRIORITY.get(ext, 9), fn))
    chosen, dropped = [], []
    for stem, lst in by_stem.items():
        lst.sort()
        chosen.append(lst[0][1])
        dropped += [(fn, lst[0][1]) for _, fn in lst[1:]]
    for fn, kept in dropped:
        print(f'同名跳过：{fn}（已用 {kept} 抽取，格式更干净）')
    if dropped:
        print()
    files = sorted(chosen)

    rows = []
    for fn in files:
        path = os.path.join(SRC, fn)
        stem = fn.rsplit('.', 1)[0]
        ext = fn.lower().rsplit('.', 1)[-1]
        try:
            if ext == 'pdf':
                text, extra = read_pdf(path)
            elif ext == 'docx':
                text, extra = read_docx(path)
            elif ext in ('html', 'htm'):
                text, extra = read_html(path)
            else:
                text, extra = open(path, encoding='utf-8', errors='ignore').read(), None
        except Exception as e:
            rows.append((fn, '读取失败', '-', f'❌ {type(e).__name__}: {e}'[:60]))
            continue

        text = clean(text)
        if not text.strip():
            rows.append((fn, '空文本', '-', '❌ 无文字层（扫描件？需 OCR）'))
            continue

        articles, gaps, dups, skipped = split_articles(text)
        today = datetime.date.today().strftime('%Y%m%d')
        src_note = f'来源：`1原始资料/{fn}`'
        if extra:
            src_note += f'（{extra} 页）'

        if len(articles) >= MIN_ARTICLES:
            flags = []
            if gaps:
                flags.append(f'缺号 {len(gaps)}（{gaps[:8]}）')
            if dups:
                flags.append(f'重号 {len(dups)}（{dups[:5]}）')
            short = [n for n, b in articles if len(b) < MIN_ARTICLE_CHARS]
            if short:
                flags.append(f'过短 {len(short)}（{short[:6]}）')
            if han_ratio(text) < MIN_HAN_RATIO:
                flags.append(f'汉字占比 {han_ratio(text):.2f}，疑似乱码')
            meta = [src_note, f'抽取：{today} ｜ 切条：顺序递增',
                    f'条数：{len(articles)}' + (f' ｜ 跳过引用式条号 {skipped} 处' if skipped else ''),
                    '校验：' + ('；'.join(flags) if flags else '通过（无缺号/重号/过短/乱码）'),
                    '⚠️ 机器抽取，落盘后必须人工抽查相邻条号是否衔接']
            open(os.path.join(OUT, stem + '.md'), 'w', encoding='utf-8').write(
                render(stem, articles, meta))
            rows.append((fn, '条文', len(articles), '✅ ' + ('；'.join(flags) if flags else '四验通过')))
        else:
            meta = [src_note, f'抽取：{today}',
                    '类型：参考文本（非条文型，未切条）',
                    '⚠️ 参考文本**不作依据**，引用须另找条文型原件']
            open(os.path.join(OUT, stem + '.md'), 'w', encoding='utf-8').write(
                render_ref(stem, text, meta))
            rows.append((fn, '参考文本', len(text), '— 未切条'))

    print('| 原件 | 类型 | 条数/字数 | 校验 |')
    print('|---|---|---|---|')
    for fn, kind, cnt, note in rows:
        print(f'| {fn} | {kind} | {cnt} | {note} |')

    print(f'\n输出 {len(os.listdir(OUT))} 份 md → {OUT}')
    print('⚠️ 抽取只是第一步。**条号存不存在靠脚本，含义对不对只能人读**——'
          '切条后必须抽查：相邻条号是否衔接、每章第一条是否被排到上一章末尾。')


if __name__ == '__main__':
    main()
