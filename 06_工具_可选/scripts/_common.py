# -*- coding: utf-8 -*-
"""知识库目录定位：同时认「工作区形态」和「交付包形态」两套命名。

同一个库在两个阶段长成两个样子，内容一样、名字不同：

    工作区（自己改卡用）        交付包（出货给买家）
    A_前置规则/                01_规则前置/
    B_知识卡片/                02_知识卡片/
    C_权威资料/1原始资料/      03_权威资料/          ← 原件平铺
    C_权威资料/2抽取MD条文/    03_权威资料/条文文本/  ← 条文 md
    D_过程与验收/              04_使用说明/ 05_资料索引/

所以脚本不按目录名硬找，按**角色**找：卡片、条文文本、原件各是什么。
两套名字都在候选表里，谁在就用谁；都找不到就报错并告诉你该怎么指。

用法：
    from _common import require
    cards = require(root, 'cards')                     # 自动识别
    cards = require(root, 'cards', args.cards)         # 显式指定优先
"""
import os

# 角色 → 候选目录名（按优先级）
CANDIDATES = {
    'cards': ['02_知识卡片', 'B_知识卡片', '知识卡片', 'cards'],
    'text':  ['条文文本', '2抽取MD条文', '00_MD条文原文本', 'MD条文', '条文md', 'articles'],
    'raw':   ['1原始资料', '原始资料', '03_权威资料', 'C_权威资料', '权威资料', '原件', 'raw'],
    'rules': ['01_规则前置', 'A_前置规则', '规则前置', 'rules'],
}
ALIASES = {
    'card': 'cards', 'cards': 'cards',
    'md': 'text', 'text': 'text', 'articles': 'text', 'article': 'text',
    'src': 'raw', 'source': 'raw', 'raw': 'raw', 'docs': 'raw',
    'rule': 'rules', 'rules': 'rules',
}
ZH = {'cards': '卡片目录', 'text': '条文 md 目录', 'raw': '原件目录', 'rules': '规则目录'}


def _kind(kind):
    return ALIASES.get(kind, kind)


def _walk_dirs(root, max_depth=3):
    """BFS 列目录（深度受限，跳过隐藏目录与 __pycache__）。"""
    cur, out = [(os.path.abspath(root), 0)], []
    while cur:
        nxt = []
        for d, dep in cur:
            out.append(d)
            if dep >= max_depth:
                continue
            try:
                subs = sorted(os.listdir(d))
            except OSError:
                continue
            for s in subs:
                p = os.path.join(d, s)
                if os.path.isdir(p) and not s.startswith(('.', '__')):
                    nxt.append((p, dep + 1))
        cur = nxt
    return out


def _drill(kind, p):
    """命中「权威资料」这类容器目录时，往下钻一层取原件。"""
    if _kind(kind) == 'raw':
        for n in ('1原始资料', '原始资料', '原件'):
            q = os.path.join(p, n)
            if os.path.isdir(q):
                return q
    return p


def resolve(root, kind, explicit=None):
    """返回实际目录；找不到返回 None（不猜、不静默兜底）。"""
    if explicit:
        return os.path.abspath(explicit)
    kind = _kind(kind)
    if kind not in CANDIDATES:
        raise SystemExit(f'未知目录角色：{kind}（可用：{"、".join(CANDIDATES)}）')
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise SystemExit(f'知识库根不存在：{root}')
    names = CANDIDATES[kind]
    for n in names:                                   # 根下命中，最快
        p = os.path.join(root, n)
        if os.path.isdir(p):
            return _drill(kind, p)
    for d in _walk_dirs(root):                        # 再往下找
        if os.path.basename(d) in names:
            return _drill(kind, d)
    return None


def require(root, kind, explicit=None, flag=''):
    """resolve 的严格版：找不到就报错，并提示怎么手动指定。"""
    p = resolve(root, kind, explicit)
    if p:
        return p
    kind = _kind(kind)
    names = ' / '.join(CANDIDATES[kind])
    hint = f'  加参数指定：{flag} <路径>' if flag else '  用对应参数手动指定路径'
    lines = [
        f'找不到【{ZH[kind]}】。',
        f'  在 {os.path.abspath(root)} 及其下 3 层里既没有 {names}，',
        f'  也没有可以顶替它的同类目录。',
        hint,
        '  当前实际目录：',
    ]
    for d in _walk_dirs(os.path.abspath(root), 2)[:40]:
        rel = os.path.relpath(d, os.path.abspath(root))
        if rel != '.':
            lines.append('    ' + rel)
    raise SystemExit('\n'.join(lines))


def out_dir(root, explicit=None, name='out'):
    """报告输出目录。KB_OUT 环境变量优先。"""
    p = explicit or os.environ.get('KB_OUT') or os.path.join(os.path.abspath(root), name)
    os.makedirs(p, exist_ok=True)
    return p
