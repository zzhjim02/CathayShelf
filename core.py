# -*- coding: utf-8 -*-
"""
古籍/图书著录自动化整理工具 —— 核心引擎（无 OCR、无 AI，纯规则）
"""
import os, re, json, csv, sys


def app_dir():
    """可写目录：打包成 exe 后 = exe 所在目录；否则 = 本脚本目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def res_dir():
    """只读资源目录：PyInstaller 打包后 = 解包临时目录；否则 = 脚本目录。"""
    return getattr(sys, '_MEIPASS', None) or app_dir()


HERE = app_dir()                            # 运行目录（settings.json 写这里）
CFG = os.path.join(HERE, 'config')
CFG_RES = os.path.join(res_dir(), 'config')  # 随包资源（publishers.csv 等，只读）

STOP_PUB = ('各', '这些', '这一', '官', '私营', '如', '由', '于', '在', '的',
            '及', '与', '等', '年', '第', '所', '其', '该', '和', '被', '设',
            '兼', '前', '后', '原', '旧', '私营')

COLOPHON_KW = ['图书在版编目', 'CIP数据', '中国版本图书馆', '出版发行', '出版發行', '出版社',
               '印书馆', '書局', '书局', '書社', '书社', '印刷', '定价', '定價', '印张',
               '開本', '开本', '印数', '印數', '字数', '字數', '第1版', '第１版', '第1次印刷',
               'ISBN', '书号', '出版年', '版次', '发行所', '發行', '经销', '經銷', '装帧', '页数']

# 全角 -> 半角（版权页常用全角数字/字母，如 ２０１６、ＩＳＢＮ）
FW = {}
for _i in range(10):
    FW[0xFF10 + _i] = chr(ord('0') + _i)
for _i in range(26):
    FW[0xFF21 + _i] = chr(ord('A') + _i)
    FW[0xFF41 + _i] = chr(ord('a') + _i)
for _a, _b in zip('：，．；－（）［］／＼％＆＃＠　', ':,.;-()[]/\\%&#@ '):
    FW[ord(_a)] = _b


JUNK = re.compile('[\ue000-\uf8ff\ufffd\u200b-\u200f\ufeff\u2028\u2029'
                   '\U000F0000-\U000FFFFD\U00100000-\U0010FFFD\U000E0000-\U000E007F]')


def nw(s):
    """全角数字/字母/标点 -> 半角；并清掉 OCR 常见的私用区乱码。"""
    return JUNK.sub('', (s or '').translate(FW))


# 繁 -> 简（夹名一律简体；用 zhconv，缺库则退化为原样）
try:
    from zhconv import convert as _zhconv

    def t2s(s):
        return _zhconv(s or '', 'zh-hans')
except Exception:
    try:
        from opencc import OpenCC
        _cc = OpenCC('t2s')

        def t2s(s):
            return _cc.convert(s or '')
    except Exception:
        def t2s(s):
            return s or ''


# 简体化（仅用于匹配出版社名）
T2S_LIGHT = str.maketrans('書館學報廣東藝齋華務國義語經點叢屬歸讀寫爲與對輯廠業這圖錄發會',
                          '书馆学报广东艺斋华务国义语经点丛属归读写为与对辑厂业这图录发会')

COUNTRIES = ['美', '英', '日', '法', '德', '俄', '苏', '意', '加', '澳', '韩',
             '印度', '葡', '荷', '瑞士', '奥地利', '以色列', '新西兰', '南非',
             '巴西', '墨西哥', '波兰', '捷克', '希腊', '埃及', '伊朗', '土耳其',
             '瑞典', '挪威', '丹麦', '芬兰', '西班牙', '阿根廷', '比利时', '匈牙利']

VOL_MARK = ('上册', '下册', '上卷', '下卷', '上编', '下编', '卷一', '卷二', '卷三',
            '第一部', '第二部', '第三部')

# 流水线命名噪声：OCR / OPT / OCR优化 / PD6AIFOCR / 8位以上编号 等
NOISE_TOK = (r'ocr\s*优化|ocr优化版|ocr|opt|orpalis\s*优化|orpalis|orp\s*优化|orp|'
             r'zhelper[-\s]?search|zhelper|(?:pd(?:vl)?\d*)?(?:ai)?f?ocr|layered|result|'
             r'unlocked|清晰扫描版|扫描版|【?\s*(?:繁转简|简转繁|繁转繁)\s*】?|纯文本|可搜索版')
NOISE_RE = re.compile(r'(?i)[\s_\-—+]*(' + NOISE_TOK + r')(?=[\s_\-—+（(【\[]|$|\.)')


def strip_noise(s):
    """去掉文件名里的流水线噪声：OCR / OPT / OCR优化 / 6位以上编号。"""
    prev = None
    while prev != s:
        prev = s
        s = NOISE_RE.sub('', s)
        s = re.sub(r'[\s_\-—+]*\d{6,}[\s_\-—+]*', ' ', s)      # 6位以上编号(任意位置)
        s = re.sub(r'(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])', ' ', s)              # 孤立单字母
        s = re.sub(r'[（(]\s*[）)]|【\s*】|\[\s*\]', '', s)     # 空括号
        s = re.sub(r'[\s_\-—、]+$', '', s).strip()
        s = re.sub(r'^[\s_\-—、]+', '', s).strip()
    return re.sub(r'\s+', ' ', s).strip()


def book_key(fn):
    """把一个文件名归一成「同一本书」的 key（去掉所有产物后缀与噪声）。"""
    return strip_noise(nw(os.path.splitext(fn)[0]))

SURNAMES = set('赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜'
               '戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐'
               '费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄'
               '和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁'
               '杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍'
               '虞万支柯咎管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程'
               '嵇邢滑裴陆荣翁荀羊於惠甄家封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗'
               '山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘景詹束龙叶幸'
               '司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党'
               '翟谭贡劳逄姬申扶堵冉宰郦雍桑桂濮牛寿通边扈燕冀郏浦尚农温别庄'
               '晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘国文寇'
               '广禄阙欧殳沃利蔚越夔隆师巩库聂勾敖融冷辛阚那简饶空曾毋沙乜'
               '养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公')
COMPOUND = ('欧阳', '太史', '端木', '上官', '司马', '东方', '独孤', '南宫', '万俟',
            '闻人', '夏侯', '诸葛', '尉迟', '公羊', '赫连', '澹台', '皇甫', '宗政',
            '濮阳', '公冶', '太叔', '申屠', '公孙', '慕容', '仲孙', '钟离', '长孙',
            '宇文', '司徒', '鲜于', '司空', '闾丘', '子车', '亓官', '司寇', '巫马',
            '公西', '颛孙', '壤驷', '公良', '漆雕', '乐正', '宰父', '谷梁', '令狐',
            '段干', '百里', '呼延', '东郭', '南门', '羊舌', '微生')
# 结尾责任者/版本词
ROLE_RE = re.compile(r'(编著|主编|编选|选编|辑录|校注|校订|点校|纂|著|撰|编)$')
PUBTAIL = ('出版社', '印书馆', '书局', '书社', '书店', '出版公司', '出版集团')


# ---------- 配置 ----------
def load_settings():
    d = {'author_prefix': False, 'keep_number': True, 'default_vol': '全1册',
         'trad_ratio': 0.5, 'tag_from_filename': True}
    for base in (CFG, CFG_RES):          # 先看可写目录，再看随包默认
        p = os.path.join(base, 'settings.json')
        if os.path.exists(p):
            try:
                d.update(json.load(open(p, encoding='utf-8')))
            except Exception:
                pass
            break
    return d


def save_settings(patch):
    d = load_settings()
    d.update(patch or {})
    try:
        os.makedirs(CFG, exist_ok=True)
        p = os.path.join(CFG, 'settings.json')
        json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception:
        pass                             # 目录只读时不致命
    return d


def load_publishers():
    m = {}
    for base in (CFG, CFG_RES):          # 可写目录里若有（用户自定义）优先
        p = os.path.join(base, 'publishers.csv')
        if os.path.exists(p):
            for row in csv.reader(open(p, encoding='utf-8-sig')):
                if len(row) >= 2 and row[0] and not row[0].startswith('#'):
                    m[row[0].strip()] = row[1].strip()
            break
    return m


# ---------- 读文本 ----------
def read_text(path):
    for enc in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return open(path, encoding=enc).read()
        except Exception:
            continue
    return open(path, encoding='utf-8', errors='replace').read()


def pdf_text(path, first=16, last=16):
    """只读 PDF 自带文字层（不做 OCR）。"""
    try:
        import fitz
    except Exception:
        return ''
    try:
        doc = fitz.open(path)
    except Exception:
        return ''
    n = doc.page_count
    idx = sorted(set(list(range(min(first, n))) + list(range(max(0, n - last), n))))
    txt = '\n'.join(doc[i].get_text() for i in idx)
    if not any(k in txt for k in ('ISBN', '出版', '定价', '印刷')):
        txt = '\n'.join(doc[i].get_text() for i in range(n))
    doc.close()
    return txt


# ---------- 版权页定位 ----------
def locate_colophon(text):
    """滑窗找版权页：在关键词最密集的窗口切出。"""
    lines = [l.rstrip() for l in text.splitlines()]
    W = 12
    w = []
    for l in lines:
        s = 0
        if 2 <= len(l) <= 80:
            if re.search(r'图书在版编目|CIP数据', l):
                s += 6
            if re.search(r'ISBN|统一书号|书号', l):
                s += 5
            if re.search(r'定价|定價', l):
                s += 5
            if re.search(r'第[1１一]版|第[1１一]次印刷', l):
                s += 4
            if re.search(r'出版|出版|發行|发行|印刷|印制', l):
                s += 3
            if re.search(r'印张|印張|开本|開本|字数|字數|印数|印數|插页|插頁', l):
                s += 3
            if re.search(r'出版社|印书馆|書局|书局|書社|书社', l):
                s += 2
        w.append(s)
    best, bi, best_strong = -1, 0, -1
    STRONG = re.compile(r'定价|定價|统一书号|統一書號|ISBN|第[1１一]次印刷|印数|印數|印张|印張')
    for i in range(len(lines)):
        seg = lines[i:i + W]
        strong = sum(1 for l in seg if STRONG.search(l))
        tot = sum(w[i:i + W])
        if (strong, tot) > (best_strong, best):
            best_strong, best, bi = strong, tot, i
    if best <= 0:
        return '\n'.join(lines[:30] + ['…'] + lines[-50:])
    return '\n'.join(lines[max(0, bi - 22):bi + 24])


PUBLINE = re.compile(r'出版社|印书馆|書局|书局|書社|书社|新华书店|出版发行|出版發行')
VOLONLY = re.compile(r'^第?[一二三四五六七八九十百\d]{0,4}\s*[卷册集部编篇辑]$|^[（(]?[一二三四五六七八九十\d]{1,3}[）)]?$')
TITLESKIP = re.compile(r'出版社|印书馆|書局|书局|書社|书社|新华书店|印刷|发行|發行|经销|經銷|'
                       r'定价|定價|印数|印數|印张|印張|开本|開本|字数|字數|插页|插頁|'
                       r'编|著|译|譯|室|会|會|院|系|大学|大學|研究所|公司|合编|编委|'
                       r'主编|校订|点校|整理|北京|上海|广州|南京|武汉|成都|'
                       r'中华民国|民国|历史|近代史|社会科学院')


def extract_title(block, text=''):
    """从版权页附近反推书名（优先取出版社行上方最近的像书名的一行）。"""
    lines = [l.strip() for l in block.splitlines()]

    def ok(s):
        if not (2 <= len(s) <= 22):
            return False
        if not re.search(r'[\u4e00-\u9fa5]', s):
            return False
        if TITLESKIP.search(s) or VOLONLY.match(re.sub(r'\s+', '', s)):
            return False
        if re.search(r'[。，；：！？、\u3000]$', s) or '。' in s or '，' in s:
            return False
        if re.search(r'(出版|發行|发行|印刷|印制|印行)$', s):
            return False
        if re.search(r'[0-9]{3,}', s):
            return False
        return True

    pubidx = [i for i, l in enumerate(lines) if PUBLINE.search(l)]
    for pi in pubidx:
        for j in range(pi - 1, max(-1, pi - 16), -1):
            if ok(lines[j]):
                return lines[j]
    for l in lines:
        if ok(l):
            return l
    if text:
        from collections import Counter
        c = Counter(l.strip() for l in text.splitlines() if ok(l.strip()))
        if c and c.most_common(1)[0][1] >= 3:
            return c.most_common(1)[0][0]
    return ''


# ---------- 出版社（词典优先） ----------
def find_pub(block, pmap):
    nb = block.translate(T2S_LIGHT)
    LINE_PUB = re.compile(r'^[\u4e00-\u9fa5]{2,14}(?:出版社|印书馆|书局|书社|出版公司|书店)$')
    for l in nb.splitlines():
        s2 = l.strip()
        if LINE_PUB.match(s2) and s2 in pmap:
            return s2, pmap[s2], 0.95
    cands = [(k, nb.find(k)) for k in pmap if k in nb]
    if cands:
        cands.sort(key=lambda x: (-len(x[0]), -x[1]))
        return cands[0][0], pmap[cands[0][0]], 0.9
    cnt = {}
    for m in re.finditer(r'([\u4e00-\u9fa5]{2,12}?(?:出版社|印书馆|书局|书社|出版公司))', nb):
        s = m.group(1)
        if len(s) >= 4 and not s.startswith(STOP_PUB):
            cnt[s] = cnt.get(s, 0) + 1
    if cnt:
        pub = max(cnt, key=lambda s: (cnt[s], len(s)))
        return pub, '', 0.5
    return '', '', 0.0


# ---------- 年份 ----------
def find_year(block, cip_year=''):
    m = re.search(r'((?:19|20)\d{2})\s*年?\s*\d{0,2}\s*月?\s*第[1１一]版', block)
    if m:
        return m.group(1), 0.85
    if cip_year:
        return cip_year, 0.7
    m = re.search(r'((?:19|20)\d{2})\s*年\s*\d{0,2}\s*月', block)
    if m:
        return m.group(1), 0.75
    m = re.search(r'((?:19|20)\d{2})\s*年[^\n]{0,20}?(?:出版|印刷)', block)
    if m:
        return m.group(1), 0.6
    m = re.search(r'出版[^\n]{0,20}?((?:19|20)\d{2})', block)
    if m:
        return m.group(1), 0.5
    return '', 0.0


# ---------- CIP 行 ----------
CIP_RE = re.compile(
    r'([\u4e00-\u9fa5A-Za-z0-9·、（）()《》〔〕]{2,40})[／/]'
    r'([\u4e00-\u9fa5A-Za-z0-9·\s]{1,28}?)\s*'
    r'[.．,，]?\s*[-—－一.．]{1,3}\s*'
    r'([\u4e00-\u9fa5]{2,4}?)\s*[:：]?\s*'
    r'([\u4e00-\u9fa5]{2,20}?(?:出版社|印书馆|书局|书社|出版公司))'
    r'[，,]?\s*((?:19|20)\d{2})')


def valid_author(s):
    if not s or not (1 < len(s) <= 12):
        return False
    if any(t in s for t in PUBTAIL):
        return False
    return bool(re.fullmatch(r'[\u4e00-\u9fa5·\s]{2,12}', s))


def parse_cip(block):
    m = CIP_RE.search(block)
    if not m:
        return {}
    book, au, city, pub, yr = [x.strip() for x in m.groups()]
    if not valid_author(au):
        au = ''
    return {'book': book, 'author': au, 'city': city, 'publisher': pub, 'year': yr}


# ---------- 其他 ----------
def find_country(text_head):
    m = re.search(r'[（\[［(]\s*(%s)\s*[)）\]］]' % '|'.join(map(re.escape, COUNTRIES)), text_head)
    return m.group(1) if m else ''


def find_translator(block):
    m = re.search(r'([\u4e00-\u9fa5·]{2,4}(?:[\s、，][\u4e00-\u9fa5·]{2,4}){0,3})(?:等)?\s*译', block)
    if m:
        return re.sub(r'\s+', '', m.group(1)) + '译', 0.6
    return '', 0.0


TRAD_PAIRS = [('書', '书'), ('學', '学'), ('國', '国'), ('會', '会'), ('發', '发'),
             ('錄', '录'), ('圖', '图'), ('這', '这'), ('業', '业'), ('廠', '厂'),
             ('輯', '辑'), ('對', '对'), ('們', '们'), ('為', '为'), ('與', '与'),
             ('說', '说'), ('讀', '读'), ('寫', '写'), ('歸', '归'), ('屬', '属'),
               ('廣', '广'), ('語', '语'), ('叢', '丛'), ('經', '经'), ('點', '点')]


def detect_trad(text):
    t = sum(text.count(a) for a, b in TRAD_PAIRS)
    s = sum(text.count(b) for a, b in TRAD_PAIRS)
    return (t / (t + s)) if (t + s) else 0.0


# ---------- 文件名解析 ----------
VOLPAT = [r'[（(]\s*第?[一二三四五六七八九十百\d]{1,4}\s*[册卷集部编篇辑]?\s*[）)]\s*$',
          r'[（(]\s*[上中下]\s*[）)]\s*$',
          r'\s*第\s*[一二三四五六七八九十百\d]{1,4}\s*[册卷集部编篇辑]\s*$',
          r'\s*[（(]\s*[一二三四五六七八九十]{1,3}\s*[）)]\s*$',
          r'[-－—_]\s*[上中下]\s*$',
          r'[-－—_]\s*\d{1,2}\s*$',
          r'\s*[上下中]\s*$']


def split_volume(name):
    """剖出结尾的册次标记，返回 (主体, 标记)。"""
    s = name
    while True:
        for p in VOLPAT:
            m = re.search(p, s)
            if m and m.start() > 0:
                return s[:m.start()].strip(), m.group(0).strip()
        return s.strip(), ''


JUNK_NAMES = {'说明', '说明文件', '使用说明', '整理说明', '扫描说明', '文件说明',
              '目录', '目次', '总目', '前言', '序', '序言', '凡例', '编例', '版权', '版权页',
              '封面', '封底', '扉页', '书名页', '空白', '空白页', 'readme', '致谢', '后记',
              '附录', '索引', '简介', '注意事项', '出版说明', '内容提要', '内容简介'}


def is_junk_name(s):
    """看名字是不是「明显不是书」的东西（说明、目录、封面、readme…）。"""
    bare = re.sub(r'[\s\d０-９\.\-—－_、,，（）()\[\]【】]+', '', t2s(s or '')).lower()
    return bool(bare) and bare in JUNK_NAMES


def mark_junk(rec, base):
    """没有任何著录信息、名字又明显不是书的 -> 标需人工，避免被建夹。"""
    if rec.get('author') or rec.get('publisher') or rec.get('year'):
        return
    if is_junk_name(rec.get('book') or base):
        rec['need_manual'] = True
        rec['junk'] = True


def strip_volnum(s):
    """去掉结尾的卷册数字：'…口头民俗 3' -> '…口头民俗'（合并多卷时用）。"""
    return re.sub(r'[\s\-—－_·、,，]*[（(]?[0-9０-９]{1,3}[)）]?$', '', (s or '').strip()).strip()


def merge_key(name):
    """把同一套书的各册归并到同一个 key（去册次 + 去数字 + 去标点）。"""
    s = split_volume(name)[0]
    s = re.sub(r'[0-9０-９]+', '', s)
    return re.sub(r'[\s（）()\[\]【】·、,，.。_\-—－]+', '', s)


def clean_base(name):
    return book_key(name)


def split_number(name):
    m = re.match(r'^\s*(\d{1,3})([\s\.\-、_]+)', name)
    if m:
        return m.group(1), name[m.end():].strip(), m.group(2)
    return '', name.strip(), ''


def strip_brackets(name):
    name = re.sub(r'^[【\[（(][^】\]）)]*[】\]）)]\s*', '', name)
    return re.sub(r'^[★☆·\s]+', '', name).strip()


def is_name(tok):
    if not (2 <= len(tok) <= 4) or not re.fullmatch(r'[\u4e00-\u9fa5·]+', tok):
        return False
    if tok in VOL_MARK:
        return False
    if re.search(r'(部|编|篇|卷|册|集|辑|附录|提要|目录)$', tok):
        return False
    if any(tok.startswith(c) for c in COMPOUND):
        return True
    return tok[0] in SURNAMES


def parse_filename(name):
    """返回 dict：title / author / publisher(可选) / tags"""
    body = re.sub(r'[（(]([^）)]*)[）)]\s*$', '', name).strip()
    tags = re.findall(r'[（(]([^）)]*(?:教材|学派|作品|理论|民族志|文集|丛书|辞典)[^）)]*)[）)]', name)
    toks = [t for t in re.split(r'[\s　.·．_、]+', body) if t]
    author = pub = ''
    if len(toks) >= 2 and any(toks[-1].endswith(x) for x in PUBTAIL):
        pub = toks[-1]
        toks = toks[:-1]
    if len(toks) >= 2:
        last = toks[-1]
        stem = ROLE_RE.sub('', last)
        if is_name(last) or (2 <= len(stem) <= 3 and is_name(stem)):
            author = last
            toks = toks[:-1]
    return {'title': ' '.join(toks) if toks else body, 'author': author,
            'publisher': pub, 'tags': tags}


# ---------- 责任者（XX著 / XX编 / XX编著 …） ----------
ROLE_TAIL = r'(编著|主编|编选|选编|辑录|校注|校订|点校|纂|著|着|撰|编)'
INST_TAIL = re.compile(r'(研究室|委员会|编辑部|编委会|研究所|研究院|办公厅|办公室|'
                       r'大学|学院|出版社|图书馆|档案馆|博物馆|研究会|'
                       r'省委|市委|县委|部|局|社|馆|会|室|院|系|所|中心)$')
NAME_STOP = ('出版', '发行', '印刷', '书店', '书局', '本社', '该', '其', '以上', '以下')


def author_from(text):
    """从一段文字里找「XX著 / XX编 / XX编著」这类责任者，返回「名称+角色」。"""
    if not text:
        return ''
    for m in re.finditer(r'([\u4e00-\u9fa5·]{2,16}(?:[、，,]+[\u4e00-\u9fa5·]{2,16}){0,3})'
                         r'\s*' + ROLE_TAIL, text):
        raw, role = m.group(1), m.group(2)
        if role == '着':
            role = '著'
        names = [x for x in re.split(r'[、，,]+', raw) if x]
        keep = []
        for nm in names:
            if any(t in nm for t in NAME_STOP):
                continue
            if INST_TAIL.search(nm):
                keep.append(nm)
            elif 2 <= len(nm) <= 4 and (any(nm.startswith(c) for c in COMPOUND)
                                        or nm[0] in SURNAMES):
                keep.append(nm)
            elif 2 <= len(nm) <= 4 and m.end() >= len(text.rstrip(' 　．。；;，,、）)】]')):
                keep.append(nm)          # 末尾的「沉志华着」这类
        if keep:
            return ' '.join(keep) + role
    return ''


# ---------- 文件名内嵌著录信息 ----------
PUB_TAIL = r'(?:出版社|印书馆|书局|书社|出版公司|书店|出版集团)'
FN_PUB = re.compile(r'((?:[\u4e00-\u9fa5]{2,20}' + PUB_TAIL + r')'
                    r'(?:[、，,]\s*[\u4e00-\u9fa5]{2,20}' + PUB_TAIL + r')*)')


def fn_title(name):
    """文件名里写了《书名》就用它。"""
    m = re.search(r'《([^》]{1,60})》', name)
    return m.group(1).strip() if m else ''


def parse_fn_meta(name):
    """从文件名里抠出版社/出版年/《书名》/卷册标记。"""
    d = {}
    t = fn_title(name)
    if t:
        d['book'] = t
    m = FN_PUB.search(name)
    if m:
        d['publisher'] = re.sub(r'[、，,]\s*', ' ', m.group(1).strip())
        y = re.match(r'[^0-9]{0,6}((?:19|20)\d{2})', name[m.end():])
        if y:
            d['year'] = y.group(1)
    if 'year' not in d:
        y = re.search(r'((?:19|20)\d{2})\s*年\s*[）)]?\s*$', name)
        if y:
            d['year'] = y.group(1)
        else:
            y = re.match(r'((?:19|20)\d{2})(?!\s*[-—~～至]\s*(?:19|20)\d{2})', name)
            if y:
                d['year'] = y.group(1)
    if t:
        vm = re.search(r'第\s*[一二三四五六七八九十百\d]{1,4}\s*[册卷集部编篇辑期]', name)
        if vm:
            d['vol'] = vm.group(0).strip()
    return d


# ---------- 组装夹名 ----------
def is_weak_title(s):
    s = (s or '').strip()
    if not s:
        return True
    if re.fullmatch(r'[\d\s\.\-—－_、（）()]+', s):
        return True
    if len(s) <= 2 and re.search(r'\d', s):
        return True
    return False


def split_role(author):
    m = ROLE_RE.search(author)
    if m:
        return author[:m.start()], m.group(1)
    return author, ''


def build_folder_name(f, st):
    book = (f.get('book') or '').strip()
    if not book:
        return ''
    vol = f.get('vol') or st.get('default_vol', '全1册')
    name = book + ('（%s）' % vol if vol else '')
    if f.get('trad'):
        name += '【繁体】'
    if f.get('english'):
        name += '【英文】'
    inner = []
    if f.get('country'):
        inner.append(f['country'])
    au = (f.get('author') or '').strip()
    if au:
        nm, role = split_role(au)
        inner.append(nm + (role or f.get('role') or '著'))
    if f.get('translator'):
        inner.append(f['translator'])
    if f.get('city') or f.get('publisher'):
        if f.get('city'):
            inner.append(f['city'])
        if f.get('publisher'):
            inner.append(f['publisher'])
    if f.get('year'):
        inner.append(f['year'] + '年')
    name += '（' + ' '.join(inner) + '）'
    for t in (f.get('tags') or []):
        name += '（' + t + '）'
    if st.get('keep_number') and f.get('num'):
        name = f['num'] + (f.get('num_sep') or '、') + name
    return t2s(name)


# ---------- 扫描 ----------
EXTS = ('.pdf', '.txt', '.docx', '.epub', '.pptx', '.djvu', '.zip')


def collect(paths):
    """把若干「文件或文件夹」（文件夹递归）收集成 book_key -> files。"""
    items = {}
    seen = set()

    def add(dp, fn):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in EXTS:
            return
        p = os.path.join(dp, fn)
        k0 = os.path.normcase(os.path.abspath(p))
        if k0 in seen:          # 同一文件既在文件夹里又被单独列出来时，只算一次
            return
        seen.add(k0)
        k = book_key(fn)
        it = items.setdefault(k, {'files': [], 'txt': '', 'pdf': ''})
        it['files'].append(p)
        if ext == '.txt' and (not it['txt'] or '繁转简' not in fn):
            it['txt'] = p
        if ext == '.pdf' and not it['pdf']:
            it['pdf'] = p

    for p in paths:
        if os.path.isfile(p):
            add(os.path.dirname(p), os.path.basename(p))
        elif os.path.isdir(p):
            for dp, dns, fns in os.walk(p):
                for fn in fns:
                    add(dp, fn)
    return items


def scan(root, progress=None):
    return scan_paths([root], progress)


def scan_paths(paths, progress=None):
    pmap = load_publishers()
    st = load_settings()
    items = collect(paths)
    out = []
    for i, (base, f) in enumerate(sorted(items.items())):
        if progress:
            progress(i, len(items), base)
        txt = read_text(f['txt']) if f.get('txt') else ''
        if not txt and f.get('pdf'):
            txt = pdf_text(f['pdf'])
        if txt:
            txt = nw(txt)
        rec = dict(base=base, txt_path=f.get('txt', ''), pdf_path=f.get('pdf', ''),
                   files=f.get('files', []),
                   has_text=bool(txt.strip()), conf={})
        if not txt.strip():
            cb2 = clean_base(base)
            _num, _body, _sep = split_number(cb2)
            _body = strip_brackets(_body)
            _pf = parse_filename(_body)
            _fm = parse_fn_meta(_body)
            _ttl = _pf['title'] or _body
            if _fm.get('publisher') and not _fm.get('book'):
                _i = _body.find(_fm['publisher'])
                if _i > 0:
                    _h = re.sub(r'[\s_\-—、，,（(]+$', '', _body[:_i]).strip()
                    if len(_h) >= 2:
                        _ttl = _h
            rec.update(need_manual=True, num=_num, num_sep=_sep,
                       book=_fm.get('book') or _ttl, author=_pf['author'],
                       publisher=_fm.get('publisher', ''), city='',
                       year=_fm.get('year', ''),
                       vol=_fm.get('vol') or st.get('default_vol', '全1册'),
                       tags=_pf['tags'], country='', translator='', trad=False,
                       colophon='', conf={})
            for _k in ('book', 'author', 'publisher', 'city', 'translator'):
                if rec.get(_k):
                    rec[_k] = t2s(rec[_k])
            rec['tags'] = [t2s(t) for t in rec['tags']]
            mark_junk(rec, base)
            rec['folder'] = build_folder_name(rec, st)
            out.append(rec)
            continue
        block = locate_colophon(txt)
        cip = parse_cip(block)
        p_pub, p_city, p_conf = find_pub(block, pmap)
        year, y_conf = find_year(block, cip.get('year', ''))
        tr, t_conf = find_translator(block)
        text_title = extract_title(block, txt)
        cb = clean_base(base)
        num, body, num_sep = split_number(cb)
        body = strip_brackets(body)
        pf = parse_filename(body)
        fm = parse_fn_meta(body)
        ttl = pf['title']
        if fm.get('publisher') and not fm.get('book'):
            i = body.find(fm['publisher'])
            if i > 0:
                head = re.sub(r'[\s_\-—、，,（(]+$', '', body[:i]).strip()
                if len(head) >= 2:
                    ttl = head
        book = fm.get('book') or cip.get('book') or ttl
        if is_weak_title(book):
            book = text_title or book
        author = (cip.get('author') or author_from(block) or author_from(body)
                  or pf['author'])
        publisher = fm.get('publisher') or cip.get('publisher') or p_pub or pf['publisher']
        city = cip.get('city') or p_city
        if not city and publisher in pmap:
            city = pmap[publisher]
        rec['colophon'] = block
        rec.update(dict(
            num=num, num_sep=num_sep, book=book.strip(), author=author.strip(), role='著',
            city=city, publisher=publisher,
            year=fm.get('year') or cip.get('year') or year,
            translator=tr, country=find_country(txt[:2500]),
            tags=pf['tags'], vol=fm.get('vol') or st.get('default_vol', '全1册'),
            trad=detect_trad(txt) >= st.get('trad_ratio', 0.5), english=False))
        for _k in ('book', 'author', 'publisher', 'city', 'translator'):
            if rec.get(_k):
                rec[_k] = t2s(rec[_k])
        rec['tags'] = [t2s(t) for t in (rec.get('tags') or [])]
        rec['conf'] = dict(book=0.9 if cip.get('book') else 0.5, publisher=p_conf,
                           year=y_conf, translator=t_conf)
        mark_junk(rec, base)
        rec['folder'] = build_folder_name(rec, st)
        out.append(rec)
    # 同目录书名传播：文件名无意义（纯编号）的本子，借用同目录多数书名
    from collections import Counter as _C
    bydir = {}
    for r in out:
        if r.get('need_manual'):
            continue
        fl = r.get('files') or ['']
        bydir.setdefault(os.path.dirname(fl[0]), []).append(r)
    for d, rs in bydir.items():
        c = _C(r['book'] for r in rs if r.get('book') and not is_weak_title(r['book']))
        if not c:
            continue
        top, n = c.most_common(1)[0]
        if n < 2:
            continue
        for r in rs:
            if is_weak_title(r.get('book')):
                r['book'] = top
                r['folder'] = build_folder_name(r, st)

    # 多卷/丛书合并：同一套书的各册归到同一个文件夹
    groups, order = {}, []
    for r in out:
        k = '__manual__' + r['base'] if r.get('need_manual') else merge_key(r.get('book') or r['base'])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    merged = []
    for k in order:
        rs = groups[k]
        if len(rs) == 1 or k.startswith('__manual__'):
            merged.extend(rs)
            continue
        rep = dict(max(rs, key=lambda r: (bool(r.get('publisher')), bool(r.get('year')),
                                          bool(r.get('author')), bool(r.get('city')),
                                          len(r.get('files') or []))))
        files = []
        for r in rs:
            files.extend(r.get('files') or [])
        rep['files'] = files
        rep['book'] = strip_volnum(split_volume(rep.get('book') or rep['base'])[0])
        rep['vol'] = '全%d册' % len(rs)
        yrs = sorted({r.get('year') for r in rs if r.get('year')})
        if len(yrs) > 1:
            rep['year'] = '%s-%s' % (yrs[0], yrs[-1])
        rep['volumes'] = [r['base'] for r in rs]
        rep['folder'] = build_folder_name(rep, st)
        merged.append(rep)
    return merged, st


# ---------- 执行 / 回滚 ----------
def apply(records, dry_run=False):
    """建夹 + 移文件。返回 (log, errors, moved)；moved=[(旧路径,新路径)]。"""
    import shutil
    log, errors, moved = [], [], []
    used = {}
    for r in records:
        name = (r.get('folder') or '').strip()
        if not name or r.get('need_manual'):
            continue
        files = r.get('files') or [p for p in (r.get('txt_path'), r.get('pdf_path'))
                                   if p and os.path.isfile(p)]
        files = [p for p in files if os.path.isfile(p)]
        if not files:
            errors.append('无文件: ' + r.get('base', ''))
            continue
        root = os.path.commonpath([os.path.dirname(p) for p in files]) \
            if len({os.path.dirname(p) for p in files}) == 1 else \
            max(set(os.path.dirname(p) for p in files),
                key=lambda d: sum(1 for p in files if os.path.dirname(p) == d))
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = '%s (%d)' % (name, used[name])
        dst = os.path.join(root, name)
        if dry_run:
            log.append('WOULD: %s  <= %d files' % (name, len(files)))
            continue
        try:
            os.makedirs(dst, exist_ok=True)
            for p in files:
                if os.path.dirname(p) != dst:
                    np2 = os.path.join(dst, os.path.basename(p))
                    shutil.move(p, np2)
                    moved.append((p, np2))
            log.append('OK: %s' % name)
        except Exception as e:
            errors.append('%s : %s' % (name, e))
    return log, errors, moved


def export_files(records, out_csv):
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['序号', '原文件名', '编号', '书名', '著者', '国别', '译者',
                    '出版地', '出版社', '年', '册数', '文件数', '繁简', '标签', '新夹名', '需人工'])
        for i, r in enumerate(records, 1):
            w.writerow([i, r.get('base', ''), r.get('num', ''), r.get('book', ''),
                        r.get('author', ''), r.get('country', ''), r.get('translator', ''),
                        r.get('city', ''), r.get('publisher', ''), r.get('year', ''),
                        r.get('vol', ''), len(r.get('files') or []),
                        '繁体' if r.get('trad') else '',
                        ';'.join(r.get('tags') or []), r.get('folder', ''),
                        '是' if r.get('need_manual') else ''])
    return out_csv


if __name__ == '__main__':
    import sys, io, collections
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    d = sys.argv[1] if len(sys.argv) > 1 else '.'
    if len(sys.argv) > 2 and sys.argv[2] == 'groups':
        cnt = collections.Counter()
        ex = {}
        for dp, dns, fns in os.walk(d):
            for fn in fns:
                if os.path.splitext(fn)[1].lower() in ('.pdf', '.txt', '.docx', '.epub', '.zip'):
                    k = book_key(fn)
                    cnt[k] += 1
                    ex.setdefault(k, []).append(fn)
        multi = {k: v for k, v in cnt.items() if v > 1}
        print('共 %d 个书 key，其中多文件 key %d 个' % (len(cnt), len(multi)))
        for k, v in list(multi.items())[:30]:
            print('  [%d] %s' % (v, k))
            for f in ex[k]:
                print('        ', f)
    else:
        recs, st = scan(d)
        for i, r in enumerate(recs, 1):
            print('%2d [%d文件] %s' % (i, len(r.get('files') or []),
                                       r['folder'] or ('【需人工·无文字层】' + r['base'])))


# ==================== 功能二：产物后缀替换 ====================
# _layered / _result  ->  _<OCR版本>AI<OCR|FOCR>
#   简体 -> OCR    繁体 -> FOCR    其他语言/无文字 -> OCR
LAYER_TOKENS = ('_layered', '_result')
SCRIPT_OTHER = '其他'


def script_of(text, th=0.5):
    """判定「繁 / 简 / 其他」，返回 (标签, 繁体占比, 命中字数)。"""
    t = sum((text or '').count(a) for a, b in TRAD_PAIRS)
    n = sum((text or '').count(b) for a, b in TRAD_PAIRS)
    if t + n == 0:
        return SCRIPT_OTHER, 0.0, 0
    r = t / (t + n)
    return ('繁' if r >= th else '简'), r, t + n


def suffix_of(ver, script):
    """按版本与繁简给出后缀，如 _PD6AIFOCR / _PD6AIOCR。"""
    return '_' + (ver or 'PD6').strip() + 'AI' + ('FOCR' if script == '繁' else 'OCR')


def _walk_files(paths):
    out = []
    for p in paths:
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for dp, dns, fns in os.walk(p):
                for fn in fns:
                    out.append(os.path.join(dp, fn))
    return out


TAIL_RE = re.compile(r'_?【\s*繁转简\s*】\s*$')


def suffix_scan(paths, ver='PD6'):
    """扫描 _layered / _result 文件，按繁简给出重命名方案（不落盘）。
    带 _【繁转简】 的保留该尾巴；繁简判定只看主文本（不看繁转简本）。"""
    groups, others = {}, []
    for f in _walk_files(paths):
        d, fn = os.path.split(f)
        stem, ext = os.path.splitext(fn)
        tail = ''
        m = TAIL_RE.search(stem)
        if m:
            tail = '_【繁转简】'
            stem = stem[:m.start()]
        low = stem.lower()
        for t in LAYER_TOKENS:
            if low.endswith(t):
                base = stem[:-len(t)]
                g = groups.setdefault((d, base), {'dir': d, 'base': base, 'files': []})
                g['files'].append((t, f, ext, tail))
                break
        else:
            others.append(f)          # 不是 _layered / _result：只列出，不处理
    out = []
    for k in sorted(groups, key=lambda x: (x[0].lower(), x[1].lower())):
        g = groups[k]
        main = [x for x in g['files'] if x[3] == '']
        cands = ([x for x in main if x[2].lower() == '.txt']
                 + [x for x in main if x[2].lower() == '.pdf']
                 + [x for x in g['files'] if x[2].lower() == '.txt']
                 + [x for x in g['files'] if x[2].lower() == '.pdf'])
        text = ''
        for t, f, ext, tail in cands:
            try:
                text = read_text(f) if ext.lower() == '.txt' else pdf_text(f)
            except Exception:
                text = ''
            if text.strip():
                break
        lab, ratio, hit = script_of(nw(text))
        suf = suffix_of(ver, lab)
        items = [{'old': f, 'new': os.path.join(g['dir'], g['base'] + suf + tail + ext),
                  'tag': t, 'tail': tail} for t, f, ext, tail in sorted(g['files'])]
        out.append({'dir': g['dir'], 'base': g['base'], 'script': lab, 'ratio': ratio,
                    'hit': hit, 'suffix': suf, 'items': items,
                    'name': os.path.basename(g['dir']) or g['dir'],
                    'no_text': (not text.strip())})
    # 其余文件：照实列出，置灰、注明「无需处理」
    for f in sorted(others, key=lambda x: x.lower())[:500]:
        out.append({'dir': os.path.dirname(f), 'base': os.path.basename(f),
                    'script': '-', 'ratio': 0.0, 'hit': 0, 'suffix': '',
                    'name': os.path.basename(f), 'no_text': False, 'no_need': True,
                    'items': [{'old': f, 'new': f, 'tag': '', 'tail': '',
                               'no_need': True}]})
    return out


def suffix_apply(records, dry_run=False):
    """执行重命名。返回 (log, errors, skipped, renamed)。无文字的直接跳过。

    renamed = [(旧路径, 新路径), ...]，供「待处理」列表跟着改名。
    """
    log, errors, skipped, renamed = [], [], [], []
    for r in records:
        if r.get('no_need'):
            continue
        if r.get('no_text'):
            skipped.append('%s  （读不到文字，已跳过）' % r['name'])
            continue
        for it in r['items']:
            o2, n2 = it['old'], it['new']
            if os.path.normcase(os.path.abspath(o2)) == os.path.normcase(os.path.abspath(n2)):
                continue
            if os.path.exists(n2):
                errors.append('重复产物/目标已存在，已跳过：%s' % os.path.basename(o2))
                continue
            try:
                if not dry_run:
                    os.rename(o2, n2)
                log.append('%s  →  %s' % (os.path.basename(o2), os.path.basename(n2)))
                renamed.append((o2, n2))
            except Exception as e:
                errors.append('%s : %s' % (os.path.basename(o2), e))
    return log, errors, skipped, renamed


def export_suffix(records, out_csv):
    import csv
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(['序号', '目录', '判定', '繁体占比', '命中字数', '原文件名', '新文件名'])
        for i, r in enumerate(records, 1):
            for it in r['items']:
                w.writerow([i, r['dir'], r['script'], '%.2f' % r['ratio'], r['hit'],
                            os.path.basename(it['old']), os.path.basename(it['new'])])
    return out_csv
