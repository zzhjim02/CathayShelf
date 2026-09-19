# -*- coding: utf-8 -*-
"""
CathayShelf 功能二引擎 —— TXT 繁简转换 / 编码规范化
（整合自 CathaySimplify 1.0.3，并修掉两个毛病：
  ① 新增「自动判定繁简体」——不必再手动选方向；
  ② 递归扫描统一走 core._walk_files，不再漏子目录。）

模式：
  convert  —— 繁简转换，输出「带后缀的新文件」（原文件保留）
  encoding —— 只把编码统一成 UTF-8 无 BOM（可覆盖原文件）
方向：
  auto     自动：繁体→简体；简体不动
  t2s      强制繁体→简体（后缀 _【繁转简】）
  s2t      强制简体→繁体（后缀 _【简转繁】）
"""
import os
import csv
import core

S_T2S = '_【繁转简】'
S_S2T = '_【简转繁】'
S_UTF8 = '_UTF8'
OUT_VARIANTS = ('_【繁转简】', '【繁转简】', '_【简转繁】', '【简转繁】')

DIR_NAME = {'t2s': '繁转简', 's2t': '简转繁', 'utf8': '转UTF-8'}


# ───────────────────────── 文件名判定 ─────────────────────────

def strip_txt(name):
    return name[:-4] if name.lower().endswith('.txt') else name


def is_variant(name):
    """文件名本身是不是转换产物（_【繁转简】/【简转繁】）"""
    stem = strip_txt(name)
    return any(stem.endswith(s) for s in OUT_VARIANTS)


def has_variant(dirpath, stem):
    """同目录下是否已有该文件的任一产物（＝已转换过）"""
    return any(os.path.exists(os.path.join(dirpath, stem + s + '.txt'))
               for s in OUT_VARIANTS)


# ───────────────────────── 编码检测 / 读取 ─────────────────────────

_ENC_TRY = ('gb18030', 'big5', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1252')
_ALIAS = {'gb2312': 'gb18030', 'gbk': 'gb18030', 'gb18030': 'gb18030',
          'big5': 'big5', 'big5-hkscs': 'big5', 'utf-16': 'utf-16',
          'utf-16le': 'utf-16', 'utf-16be': 'utf-16', 'utf-8': 'utf-8',
          'utf-8-sig': 'utf-8-sig', 'ascii': 'utf-8', 'windows-1252': 'cp1252'}


def detect_encoding(path):
    """返回 (编码名, 置信度, 有BOM)。编码名可直接喂给 open()。"""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except Exception:
        return None, 0.0, False
    if not raw:
        return 'utf-8', 1.0, False
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig', 1.0, True
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff') or raw[:4] in (
            b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff'):
        return 'utf-16', 0.95, True
    try:
        raw.decode('utf-8')
        return 'utf-8', 1.0, False
    except UnicodeDecodeError:
        pass
    enc, conf = None, 0.0
    try:
        import chardet
        r = chardet.detect(raw[:300000])
        enc = (r.get('encoding') or '').lower()
        conf = float(r.get('confidence') or 0.0)
    except Exception:
        enc, conf = None, 0.0
    enc2 = _ALIAS.get(enc, enc)
    if enc2:
        try:
            raw.decode(enc2)
            return enc2, conf, False
        except Exception:
            pass
    for e in _ENC_TRY:
        try:
            raw.decode(e)
            return e, max(conf, 0.3), False
        except Exception:
            continue
    return 'gb18030', 0.1, False


def read_text_any(path):
    """尽量把文件读出来，不改动任何字节（不做换行翻译）。
    返回 (text, 编码名, 置信度, 有BOM)；读不出来时 text 为 None。"""
    enc, conf, bom = detect_encoding(path)
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except Exception:
        return None, enc, conf, bom
    try:
        text = raw.decode('utf-8-sig' if (bom and enc == 'utf-8-sig') else (enc or 'gb18030'),
                          errors='replace')
        return text, enc, conf, bom
    except Exception:
        return raw.decode('utf-8', 'replace'), 'utf-8?', 0.0, False


# ───────────────────────── 转换 ─────────────────────────

_CC = {}


def _cc(cfg):
    if cfg not in _CC:
        import opencc
        _CC[cfg] = opencc.OpenCC(cfg)
    return _CC[cfg]


def convert_text(text, act):
    """act: 't2s' / 's2t'。优先 OpenCC，没有就退回 zhconv。"""
    try:
        return _cc(act).convert(text)
    except Exception:
        import zhconv
        return zhconv.convert(text, 'zh-cn' if act == 't2s' else 'zh-tw')


def diff_stats(a, b):
    """改动统计：字符数、变化数、一对多、多对一。"""
    total, changed = len(a), 0
    one, many = {}, {}
    for x, y in zip(a, b):
        if x == y:
            continue
        changed += 1
        one.setdefault(x, set()).add(y)
        many.setdefault(y, set()).add(x)
    ex = []
    for k, v in list(one.items()):
        if len(v) > 1:
            ex.append('一对多: %s→%s' % (k, '/'.join(sorted(v))))
    for k, v in list(many.items()):
        if len(v) > 1:
            ex.append('多对一: %s→%s' % ('/'.join(sorted(v)), k))
    return {'total': total, 'changed': changed,
            'one_to_many': sum(len(v) - 1 for v in one.values() if len(v) > 1),
            'many_to_one': sum(len(v) - 1 for v in many.values() if len(v) > 1),
            'examples': ex[:8]}


# ───────────────────────── 扫描 ─────────────────────────

def _rec(f, **kw):
    d, fn = os.path.split(f)
    r = {'file': f, 'dir': d, 'base': fn, 'name': fn,
         'enc': '', 'conf': 0.0, 'bom': False, 'script': '-', 'ratio': 0.0,
         'hit': 0, 'act': '', 'suffix': '', 'out': '', 'why': '',
         'no_need': True, 'items': []}
    r.update(kw)
    if not r['items']:
        r['items'] = [{'old': f, 'new': r['out'] or f, 'tag': '',
                       'tail': '', 'no_need': r['no_need']}]
    return r


def simplify_scan(paths, opt=None, progress=None):
    """扫描 TXT 文件，给出处理方案（不落盘）。
    opt: mode(convert|encoding) direction(auto|t2s|s2t) out_mode(suffix|overwrite)
         suffix(自定义后缀) out_dir(自定义输出目录)
    返回 record 列表；不处理的文件也在列表里，标 no_need + why。"""
    opt = dict(opt or {})
    mode = opt.get('mode', 'convert')
    direction = opt.get('direction', 'auto')
    out_mode = opt.get('out_mode', 'suffix')
    suffix = opt.get('suffix') or (S_T2S if direction != 's2t' else S_S2T)
    out_dir = (opt.get('out_dir') or '').strip()

    files = core._walk_files(paths)
    recs, n = [], len(files)
    for i, f in enumerate(sorted(files, key=lambda x: x.lower())):
        if progress:
            try:
                progress(i, n, os.path.basename(f))
            except Exception:
                pass
        fn = os.path.basename(f)
        if not fn.lower().endswith('.txt'):
            recs.append(_rec(f, why='非 TXT'))
            continue
        stem = strip_txt(fn)
        if is_variant(fn):
            recs.append(_rec(f, why='已是转换产物'))
            continue
        d = os.path.dirname(f)
        if mode == 'convert' and has_variant(d, stem):
            recs.append(_rec(f, why='已转换过'))
            continue
        text, enc, conf, bom = read_text_any(f)
        if text is None:
            recs.append(_rec(f, enc=enc or '', conf=conf, why='读不出来'))
            continue
        lab, ratio, hit = core.script_of(core.nw(text))
        if mode == 'encoding':
            if enc == 'utf-8' and not bom:
                recs.append(_rec(f, enc=enc, conf=conf, script=lab, ratio=ratio,
                                 hit=hit, why='已是 UTF-8 无 BOM'))
                continue
            act, why = 'utf8', '编码规范化'
        else:
            if direction in ('t2s', 's2t'):
                act = direction
            else:                                  # 自动：繁体才转
                act = 't2s' if lab == '繁' else ''
            if not act:
                why = '简体，无需转（自动）' if lab == '简' else '无繁简差异/非中文'
                recs.append(_rec(f, enc=enc, conf=conf, script=lab, ratio=ratio,
                                 hit=hit, why=why))
                continue
            why = ''
        if mode == 'encoding' and out_mode == 'suffix' and suffix in (
                S_T2S, S_S2T, '【繁转简】', '【简转繁】'):
            sfx = S_UTF8                            # 编码模式别用繁简后缀
        else:
            sfx = suffix if out_mode == 'suffix' else ''
        out = os.path.join(out_dir or d, stem + sfx + '.txt')
        recs.append(_rec(f, enc=enc, conf=conf, bom=bom, script=lab, ratio=ratio,
                         hit=hit, act=act, suffix=sfx, out=out, why=why,
                         no_need=False,
                         items=[{'old': f, 'new': out, 'tag': '', 'tail': '',
                                 'no_need': False}]))
    if progress:
        try:
            progress(n, n, '')
        except Exception:
            pass
    return recs


# ───────────────────────── 执行 ─────────────────────────

def simplify_apply(records, opt=None):
    """执行转换。返回 (log, errors, skipped, created)。覆盖模式下先写临时再替换。

    created = 本次新写出的文件路径（另存模式），供「待处理」列表自动收录。
    """
    log, errors, skipped, created = [], [], [], []
    for r in records:
        if r.get('no_need'):
            continue
        items = r.get('items') or []
        it = items[0] if items else {'old': r['file'], 'new': r.get('out') or r['file']}
        src, dst = it['old'], it['new']
        same = os.path.normcase(os.path.abspath(src)) == \
            os.path.normcase(os.path.abspath(dst))
        try:
            text, enc, conf, bom = read_text_any(src)
            if text is None:
                errors.append('%s : 读不出来' % r['base'])
                continue
            new = text if r['act'] == 'utf8' else convert_text(text, r['act'])
            st = diff_stats(text, new)
            r['stats'] = st
            if same:
                tmp = src + '.~tmp~'
                with open(tmp, 'w', encoding='utf-8', newline='') as fh:
                    fh.write(new)
                os.replace(tmp, src)
                log.append('%s  （原地覆盖：%s → UTF-8 无 BOM，改动 %d 字）'
                           % (r['base'], enc, st['changed']))
            else:
                od = os.path.dirname(dst)
                if od and not os.path.isdir(od):
                    os.makedirs(od, exist_ok=True)
                if os.path.exists(dst):
                    errors.append('目标已存在，跳过：%s' % os.path.basename(dst))
                    continue
                with open(dst, 'w', encoding='utf-8', newline='') as fh:
                    fh.write(new)
                created.append(dst)
                log.append('%s → %s  （%s → UTF-8 无 BOM，改动 %d 字）'
                           % (r['base'], os.path.basename(dst), enc, st['changed']))
        except Exception as e:
            errors.append('%s : %s' % (r['base'], e))
    return log, errors, skipped, created


def export_simplify(records, out_csv):
    """导出对照表（UTF-8-SIG，Excel 直接打开不乱码）。"""
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['序号', '所在文件夹', '原文件名', '判定', '繁体占比', '原编码',
                    '动作', '新文件名', '状态', '改动字符', '一对多', '多对一'])
        for i, r in enumerate(records, 1):
            st = r.get('stats') or {}
            items = r.get('items') or [{}]
            new = os.path.basename(items[0].get('new') or '')
            state = r.get('why') or (DIR_NAME.get(r.get('act'), '') or '')
            w.writerow([i, r['dir'], r['base'], r['script'], '%.2f' % r['ratio'],
                        r['enc'], DIR_NAME.get(r.get('act'), ''),
                        new if not r.get('no_need') else '—', state,
                        st.get('changed', ''), st.get('one_to_many', ''),
                        st.get('many_to_one', '')])
    return out_csv
