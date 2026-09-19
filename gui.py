# -*- coding: utf-8 -*-
"""
古籍/图书整理工具 —— 图形界面（tkinter，纯本地 / 无 OCR / 无 AI）
选项卡一「著录建夹」：扫描 -> 复核 -> 建文件夹并把文件移入
选项卡二「后缀替换」：把 _layered / _result 换成 _<版本>AI<OCR|FOCR>
选项卡三「繁简转换 / 编码」：繁体 TXT 生成简体副本（或反向），或统一转 UTF-8 无 BOM
三页共用同一份「待处理」来源，可只用其中任意一个。都支持把「文件 / 文件夹」直接拖进窗口。
"""
import os, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core

from ui_common import HAS_DND, TkinterDnD, tk_splitlist, bind_drop, Shared  # noqa
import tab_simplify
from tab_simplify import SimplifyTab

# ---------- 出错时把堆栈写进 app_dir\_error.log（打包后没有控制台，靠它排查）----------
def _log(kind, text):
    try:
        import time
        p = os.path.join(core.app_dir(), '_error.log')
        with open(p, 'a', encoding='utf-8') as f:
            f.write('\n==== %s  %s ====\n%s\n'
                    % (kind, time.strftime('%Y-%m-%d %H:%M:%S'), text))
    except Exception:
        pass

COLS = [('no', '序号', 45), ('base', '原文件名', 200), ('book', '书名', 160),
        ('author', '著者', 80), ('country', '国别', 46), ('translator', '译者', 90),
        ('city', '出版地', 70), ('publisher', '出版社', 130), ('year', '年', 52),
        ('vol', '册数', 60), ('nfiles', '文件', 46), ('trad', '繁简', 46),
        ('tags', '标签', 100), ('folder', '新夹名', 400), ('state', '状态', 70)]
FIELDS = [('book', '书名'), ('author', '著者'), ('country', '国别'),
          ('translator', '译者'), ('city', '出版地'), ('publisher', '出版社'),
          ('year', '出版年(数字)'), ('vol', '册数')]

SCOLS = [('no', '序号', 45), ('name', '所在文件夹', 230), ('script', '判定', 50),
         ('ratio', '繁体占比', 68), ('hit', '命中', 50), ('old', '原文件名', 320),
         ('new', '新文件名', 320), ('state', '状态', 80)]


# ============================ 选项卡一：著录建夹 ============================
class CatalogTab(ttk.Frame):
    def __init__(self, master, root, sh):
        super().__init__(master)
        self.root = root
        self.sh = sh
        self.records = []
        self.settings = core.load_settings()
        self.excluded = set()     # 被移出列表的（按 base）
        self.edited = {}          # 用户改过的字段（按 base）
        self.scanning = False
        self.scanned_sig = None

        self.dz = tk.Label(
            self, height=2,
            text='⬇  把「PDF / 文本 / 文件夹」直接拖进这个窗口（文件夹会自动递归处理）',
            bg='#eef3fb', fg='#2b4a7d', relief='ridge', bd=1)
        self.dz.pack(fill='x', padx=6, pady=(6, 2))

        bar = ttk.Frame(self, padding=(6, 2))
        bar.pack(fill='x')
        ttk.Button(bar, text='选择文件…', command=self.pick_files).pack(side='left')
        ttk.Button(bar, text='选择文件夹…', command=self.pick_dir).pack(side='left', padx=4)
        ttk.Button(bar, text='清空列表', command=self.clear).pack(side='left', padx=4)
        ttk.Button(bar, text='移出列表', command=self.remove_sel).pack(side='left', padx=4)
        ttk.Button(bar, text='扫 描', command=self.do_scan).pack(side='left', padx=10)
        self.pbar = ttk.Progressbar(bar, length=170)
        self.pbar.pack(side='left')
        ttk.Button(bar, text='导出复核表', command=self.do_export).pack(side='right')
        self.v_exp = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='应用后导出对照表',
                        variable=self.v_exp).pack(side='right', padx=8)
        self.btn_apply = ttk.Button(bar, text='应用：建夹+移动', command=self.do_apply)
        self.btn_apply.pack(side='right', padx=6)

        self.src = ttk.Label(self, text='待处理：0 项', foreground='#555', padding=(8, 0))
        self.src.pack(fill='x')

        opts = ttk.Frame(self, padding=(6, 2))
        opts.pack(fill='x')
        self.v_prefix = tk.BooleanVar(value=self.settings.get('author_prefix', False))
        self.v_keepnum = tk.BooleanVar(value=self.settings.get('keep_number', True))
        self.v_manual = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='夹名保留「著者：」前缀',
                        variable=self.v_prefix, command=self.rebuild).pack(side='left')
        ttk.Checkbutton(opts, text='保留原文件名编号前缀',
                        variable=self.v_keepnum, command=self.rebuild).pack(side='left', padx=14)
        ttk.Checkbutton(opts, text='红底行也按文件名应用',
                        variable=self.v_manual).pack(side='left', padx=14)
        ttk.Label(opts, text='（双击一行可编辑 / 黄底=没把握 / 红底=无文字层 ｜ '
                             '选中若干行=只处理这几本，不选=全部）',
                  foreground='#888').pack(side='left', padx=10)

        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS], show='headings')
        for k, t, w in COLS:
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor='w')
        vs = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        hs = ttk.Scrollbar(wrap, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=vs.set, xscroll=hs.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure('warn', background='#fff4cc')
        self.tree.tag_configure('manual', background='#ffd9d9')
        self.tree.bind('<Double-1>', self.edit_row)

        self.status = ttk.Label(self, text='就绪', anchor='w', padding=4)
        self.status.pack(fill='x')

        bind_drop(root, (self, self.dz, self.tree, self.src), self.on_drop)
        if not HAS_DND:
            self.dz.config(text='（未安装 tkinterdnd2，拖放不可用；请用「选择文件/文件夹」按钮）',
                           bg='#ffe9e9', fg='#8a2b2b')

    @property
    def paths(self):
        return self.sh.paths

    @paths.setter
    def paths(self, v):
        self.sh.paths = list(v)

    # ---------- 拖放 ----------
    def on_drop(self, ev):
        items = tk_splitlist(self.root, ev.data)
        add = [p for p in items if p and p not in self.paths and os.path.exists(p)]
        self.paths.extend(add)
        self.refresh_src()
        if add:
            self.status.config(text='拖入 %d 项，开始自动扫描…' % len(add))
            self.do_scan()
        return getattr(ev, 'action', None)

    def refresh_src(self):
        head = '；'.join(os.path.basename(p.rstrip('\\/')) for p in self.paths[:3])
        more = '' if len(self.paths) <= 3 else ' …'
        self.src.config(text='待处理：%d 项   %s%s' % (len(self.paths), head, more))

    def clear(self):
        self.paths = []
        self.records = []
        self.tree.delete(*self.tree.get_children())
        self.refresh_src()
        self.status.config(text='已清空')

    def pick_files(self):
        fs = filedialog.askopenfilenames(
            title='选择要整理的 PDF/文本',
            filetypes=[('图书文件', '*.pdf *.txt *.docx *.epub *.pptx *.djvu'),
                       ('全部文件', '*.*')])
        if fs:
            self.paths.extend([p for p in fs if p not in self.paths])
            self.refresh_src()
            self.do_scan()

    def pick_dir(self):
        d = filedialog.askdirectory(title='选择要整理的文件夹（自动递归）')
        if d:
            if d not in self.paths:
                self.paths.append(d)
            self.refresh_src()
            self.do_scan()

    # ---------- 扫描 ----------
    def do_scan(self):
        if not self.paths:
            messagebox.showwarning('提示', '请先拖入或选择文件/文件夹')
            return
        if self.scanning:
            return
        self.scanning = True
        self.status.config(text='扫描中…')
        self.pbar.config(maximum=100, value=0)
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        try:
            def prog(i, n, b):
                self.root.after(0, lambda: (self.pbar.config(value=(i + 1) * 100 / max(n, 1)),
                                            self.status.config(text='%d/%d %s' % (i + 1, n, b[:40]))))
            recs, st = core.scan_paths(list(self.paths), progress=prog)
            self.records = recs
            self.settings = st
            self.root.after(0, self.fill)
        except Exception:
            self.scanning = False
            err = traceback.format_exc()
            _log('tab-scan', err)
            self.root.after(0, lambda: messagebox.showerror('扫描出错', err))

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        recs = []
        for r in self.records:
            if r.get('base') in self.excluded:
                continue
            if r.get('base') in self.edited:
                r.update(self.edited[r['base']])
            recs.append(r)
        self.records = recs
        self.scanning = False
        self.scanned_sig = tuple(sorted(self.paths))
        for i, r in enumerate(self.records, 1):
            tag = 'manual' if r.get('need_manual') else (
                'warn' if min(list(r.get('conf', {}).values() or [1])) < 0.6 else '')
            self.tree.insert('', 'end', iid=str(i - 1), values=self.rowvals(i, r), tags=(tag,))
        self.status.config(text='扫描完成：%d 项' % len(self.records))

    def rowvals(self, i, r):
        return (i, r.get('base', ''), r.get('book', ''), r.get('author', ''),
                r.get('country', ''), r.get('translator', ''), r.get('city', ''),
                r.get('publisher', ''), r.get('year', ''), r.get('vol', ''),
                len(r.get('files') or []),
                '繁体' if r.get('trad') else '', ';'.join(r.get('tags') or []),
                r.get('folder', '') or ('需人工' if r.get('need_manual') else ''),
                '无文字层' if r.get('need_manual') else '')

    def refresh_row(self, idx):
        self.tree.item(str(idx), values=self.rowvals(idx + 1, self.records[idx]))

    def edit_row(self, ev):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0]); r = self.records[idx]
        win = tk.Toplevel(self.root)
        win.title('编辑 #%d  %s' % (idx + 1, r.get('base', '')))
        win.geometry('940x640')
        ttk.Label(win, text='版权页原文（自动定位）：', padding=4).pack(anchor='w')
        txt = tk.Text(win, height=15, wrap='word')
        txt.insert('1.0', r.get('colophon', '') or '（无文本层，需人工录入）')
        txt.pack(fill='both', expand=True, padx=6)
        frm = ttk.Frame(win, padding=6)
        frm.pack(fill='x')
        ents = {}
        for i, (k, label) in enumerate(FIELDS):
            ttk.Label(frm, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky='e', padx=4, pady=3)
            e = ttk.Entry(frm, width=34)
            e.insert(0, str(r.get(k, '')))
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky='w')
            ents[k] = e
        ttk.Label(frm, text='标签(分号隔开)').grid(row=4, column=0, sticky='e', padx=4)
        e_tag = ttk.Entry(frm, width=34)
        e_tag.insert(0, ';'.join(r.get('tags') or []))
        e_tag.grid(row=4, column=1, sticky='w')
        v_trad = tk.BooleanVar(value=bool(r.get('trad')))
        ttk.Checkbutton(frm, text='繁体', variable=v_trad).grid(row=4, column=2, sticky='w')

        def ok():
            for k, _ in FIELDS:
                r[k] = ents[k].get().strip()
            r['tags'] = [t for t in e_tag.get().split(';') if t.strip()]
            r['trad'] = v_trad.get()
            r['need_manual'] = False
            r['folder'] = core.build_folder_name(r, self.settings)
            self.edited[r['base']] = {k: r.get(k) for k in
                                      ('book', 'author', 'country', 'translator', 'city',
                                       'publisher', 'year', 'vol', 'tags', 'trad',
                                       'need_manual', 'folder')}
            self.refresh_row(idx)
            win.destroy()
        btns = ttk.Frame(win, padding=6)
        btns.pack(fill='x')
        ttk.Button(btns, text='确定（重算夹名）', command=ok).pack(side='right')
        ttk.Button(btns, text='取消', command=win.destroy).pack(side='right', padx=6)

    def rebuild(self):
        self.settings['author_prefix'] = self.v_prefix.get()
        self.settings['keep_number'] = self.v_keepnum.get()
        for i, r in enumerate(self.records):
            if not r.get('need_manual'):
                r['folder'] = core.build_folder_name(r, self.settings)
                self.refresh_row(i)

    def do_export(self):
        if not self.records:
            return
        base = self.paths[0] if self.paths else '.'
        base = base if os.path.isdir(base) else os.path.dirname(base)
        p = filedialog.asksaveasfilename(
            defaultextension='.csv', initialdir=base, initialfile='复核表.csv',
            filetypes=[('CSV', '*.csv')])
        if p:
            core.export_files(self.records, p)
            self.status.config(text='已导出复核表：' + p)
            messagebox.showinfo('完成', '复核表已导出：\n' + p)

    def remove_sel(self):
        sel = [int(x) for x in self.tree.selection()]
        if not sel:
            messagebox.showinfo('提示', '先在列表里选中要移出的行（Ctrl / Shift 可多选）')
            return
        for i in sel:
            self.excluded.add(self.records[i]['base'])
        self.fill()
        self.status.config(text='已移出 %d 项（重新扫描也不会再出现）' % len(sel))

    def do_apply(self):
        if not self.records:
            return
        sel = sorted(int(x) for x in self.tree.selection())
        pool = [self.records[i] for i in sel] if sel else self.records
        todo = [r for r in pool if r.get('folder') and
                (self.v_manual.get() or not r.get('need_manual'))]
        what = ('选中的 %d 项' % len(sel)) if sel else ('全部 %d 项' % len(self.records))
        if not messagebox.askyesno('确认', '%s中可用的 %d 本将建文件夹并把文件移入。\n继续？'
                                           % (what, len(todo))):
            return
        try:
            log, err, moved = core.apply(todo)
        except Exception:
            err = [traceback.format_exc()]
            log, moved = [], []
            _log('catalog-apply-crash', err[0])
        if err:
            _log('catalog-apply', '\n'.join(str(x) for x in err))
        if moved:
            gone = {os.path.normcase(a) for a, b in moved}
            keep = [p for p in self.paths
                    if os.path.exists(p) and os.path.normcase(p) not in gone]
            for a, b in moved:
                d2 = os.path.dirname(b)
                if d2 not in keep:
                    keep.append(d2)
            self.paths = keep
            self.refresh_src()
        base = self.paths[0] if self.paths else '.'
        base = base if os.path.isdir(base) else os.path.dirname(base)
        mp = ''
        if self.v_exp.get():
            mp = os.path.join(base, '_新夹名对照表.csv')
            try:
                core.export_files(self.records, mp)
            except Exception:
                mp = '（对照表写入失败）'
        msg = '完成 %d 项。' % len(log)
        if err:
            msg += '\n失败 %d 项：\n' % len(err) + '\n'.join(err[:8])
        if mp:
            msg += '\n\n对照表：' + mp
        messagebox.showinfo('结果', msg)
        self.status.config(text=msg.replace('\n', ' ')[:120])
        self.do_scan()


# ============================ 选项卡二：后缀替换 ============================
class SuffixTab(ttk.Frame):
    def __init__(self, master, root, sh):
        super().__init__(master)
        self.root = root
        self.sh = sh
        self.scanned_sig = None
        self.records = []
        self.rows = []
        self.rowmap = {}
        self.excluded = set()     # 被移出列表的（按原文件全路径）
        self.scanning = False
        self.settings = core.load_settings()
        self.paths = []

        self.dz = tk.Label(
            self, height=2,
            text='⬇  把带 _layered / _result 的文件或文件夹拖进来（文件夹自动递归）',
            bg='#eef7ee', fg='#2b6b3d', relief='ridge', bd=1)
        self.dz.pack(fill='x', padx=6, pady=(6, 2))

        bar = ttk.Frame(self, padding=(6, 2))
        bar.pack(fill='x')
        ttk.Button(bar, text='选择文件夹…', command=self.pick_dir).pack(side='left')
        ttk.Button(bar, text='清空列表', command=self.clear).pack(side='left', padx=4)
        ttk.Button(bar, text='移出列表', command=self.remove_sel).pack(side='left', padx=4)
        ttk.Button(bar, text='扫 描', command=self.do_scan).pack(side='left', padx=10)
        self.pbar = ttk.Progressbar(bar, length=170)
        self.pbar.pack(side='left')
        ttk.Button(bar, text='导出对照表', command=self.do_export).pack(side='right')
        self.v_exp = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='应用后导出对照表',
                        variable=self.v_exp).pack(side='right', padx=8)
        self.btn_apply = ttk.Button(bar, text='应用：重命名', command=self.do_apply)
        self.btn_apply.pack(side='right', padx=6)

        opts = ttk.Frame(self, padding=(6, 2))
        opts.pack(fill='x')
        ttk.Label(opts, text='OCR 软件版本：').pack(side='left')
        self.e_ver = ttk.Entry(opts, width=10)
        self.e_ver.insert(0, str(self.settings.get('ocr_ver', 'PD6')))
        self.e_ver.pack(side='left')
        ttk.Label(opts, text='  →  _版本AI[F]OCR   （简体=OCR，繁体=FOCR，其他语言=OCR）',
                  foreground='#666').pack(side='left', padx=6)
        ttk.Label(opts, text='黄底=繁简把握不大，红底=没读到文字，灰字=无需处理',
                  foreground='#888').pack(side='left', padx=10)

        self.src = ttk.Label(self, text='待处理：0 项', foreground='#555', padding=(8, 0))
        self.src.pack(fill='x')

        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in SCOLS], show='headings')
        for k, t, w in SCOLS:
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor='w')
        vs = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        hs = ttk.Scrollbar(wrap, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=vs.set, xscroll=hs.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure('warn', background='#fff4cc')
        self.tree.tag_configure('manual', background='#ffd9d9')
        self.tree.tag_configure('dim', foreground='#a3a3a3')

        self.status = ttk.Label(self, text='就绪', anchor='w', padding=4)
        self.status.pack(fill='x')

        bind_drop(root, (self, self.dz, self.tree, self.src), self.on_drop)
        if not HAS_DND:
            self.dz.config(text='（未安装 tkinterdnd2，拖放不可用；请用「选择文件夹」按钮）',
                           bg='#ffe9e9', fg='#8a2b2b')

    @property
    def paths(self):
        return self.sh.paths

    @paths.setter
    def paths(self, v):
        self.sh.paths = list(v)

    # ---------- 输入 ----------
    def on_drop(self, ev):
        items = tk_splitlist(self.root, ev.data)
        add = [p for p in items if p and p not in self.paths and os.path.exists(p)]
        self.paths.extend(add)
        self.refresh_src()
        if add:
            self.do_scan()
        return getattr(ev, 'action', None)

    def refresh_src(self):
        head = '；'.join(os.path.basename(p.rstrip('\\/')) for p in self.paths[:3])
        more = '' if len(self.paths) <= 3 else ' …'
        self.src.config(text='待处理：%d 项   %s%s' % (len(self.paths), head, more))

    def pick_dir(self):
        d = filedialog.askdirectory(title='选择文件夹（自动递归找 _layered / _result）')
        if d:
            if d not in self.paths:
                self.paths.append(d)
            self.refresh_src()
            self.do_scan()

    def clear(self):
        self.paths = []
        self.records = []
        self.rows = []
        self.tree.delete(*self.tree.get_children())
        self.refresh_src()
        self.status.config(text='已清空')

    # ---------- 扫描 ----------
    def do_scan(self):
        if not self.paths:
            messagebox.showwarning('提示', '请先拖入或选择文件夹')
            return
        if self.scanning:
            return
        ver = self.e_ver.get().strip() or 'PD6'      # 主线程里读控件
        self.scanning = True
        self.status.config(text='扫描中…')
        self.pbar.config(maximum=100, value=0)
        threading.Thread(target=self._scan, args=(ver,), daemon=True).start()

    def _scan(self, ver):
        try:
            recs = core.suffix_scan(list(self.paths), ver=ver)
            self.records = recs
            self.settings['ocr_ver'] = ver
            try:
                core.save_settings({'ocr_ver': ver})
            except Exception:
                pass
            self.root.after(0, self.fill)
        except Exception:
            self.scanning = False
            err = traceback.format_exc()
            _log('tab-scan', err)
            self.root.after(0, lambda: messagebox.showerror('扫描出错', err))

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        recs = []
        for r in self.records:
            its = [it for it in r['items'] if it['old'] not in self.excluded]
            if its:
                r = dict(r)
                r['items'] = its
                recs.append(r)
        self.records = recs
        self.rows = []
        self.rowmap = {}
        self.scanning = False
        self.scanned_sig = tuple(sorted(self.paths))
        n = 0
        nskip = 0
        for r in self.records:
            for it in r['items']:
                n += 1
                if it.get('no_need'):
                    tag = 'dim'
                    nskip += 1
                    vals = (n, os.path.basename(it['old']), '-', '0.00', 0,
                            os.path.basename(it['old']), '—', '无需处理')
                else:
                    tag = 'manual' if r.get('no_text') else (
                        'warn' if 0.25 <= r['ratio'] <= 0.75 else '')
                    vals = (n, r['name'], r['script'], '%.2f' % r['ratio'], r['hit'],
                            os.path.basename(it['old']), os.path.basename(it['new']),
                            '无文字·跳过' if r.get('no_text') else '')
                self.rows.append(it)
                self.rowmap[str(n - 1)] = (r, it)
                self.tree.insert('', 'end', iid=str(n - 1), tags=(tag,), values=vals)
        nf = sum(1 for r in self.records if r.get('script') == '繁')
        ng = sum(1 for r in self.records if not r.get('no_need'))
        if not self.records:
            self.status.config(text='扫描完成：这个来源里一个文件都没有')
        elif not ng:
            self.status.config(
                text='扫描完成：没找到 _layered / _result 产物；其余 %d 个文件无需处理'
                     % nskip)
        else:
            self.status.config(
                text='扫描完成：待换后缀 %d 组 / %d 个文件（繁体 %d 组）'
                     '，另有 %d 个无需处理' % (ng, n - nskip, nf, nskip))

    # ---------- 导出 / 应用 ----------
    def do_export(self):
        if not self.records:
            return
        base = self.paths[0] if self.paths else '.'
        base = base if os.path.isdir(base) else os.path.dirname(base)
        p = filedialog.asksaveasfilename(
            defaultextension='.csv', initialdir=base, initialfile='后缀对照表.csv',
            filetypes=[('CSV', '*.csv')])
        if p:
            core.export_suffix(self.records, p)
            self.status.config(text='已导出：' + p)
            messagebox.showinfo('完成', '对照表已导出：\n' + p)

    def remove_sel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('提示', '先选中要移出的行（Ctrl / Shift 可多选）')
            return
        for iid in sel:
            r, it = self.rowmap.get(iid, (None, None))
            if it:
                self.excluded.add(it['old'])
        self.fill()
        self.status.config(text='已移出 %d 个文件（重新扫描也不会再出现）' % len(sel))

    def do_apply(self):
        if not self.records:
            return
        sel = sorted(self.tree.selection(), key=lambda x: int(x))
        if sel:
            plan, seen = [], {}
            for iid in sel:
                r, it = self.rowmap[iid]
                if it.get('no_need'):
                    continue
                k = (r['dir'], r['base'])
                if k not in seen:
                    p = dict(r)
                    p['items'] = []
                    seen[k] = p
                    plan.append(p)
                seen[k]['items'].append(it)
        else:
            plan = []
            for r in self.records:
                if r.get('no_need'):
                    continue
                p = dict(r)
                p['items'] = [it for it in r['items'] if not it.get('no_need')]
                if p['items']:
                    plan.append(p)
        n = sum(len(p['items']) for p in plan)
        if not plan:
            messagebox.showinfo('提示', '选中的都是「无需处理」的文件，没有要改名的')
            return
        if not messagebox.askyesno(
                '确认', '%s重命名 %d 个文件（_layered / _result → _%sAI[F]OCR）。\n继续？'
                        % ('选中的 ' if sel else '将', n, self.e_ver.get().strip() or 'PD6')):
            return
        log, err, skip = core.suffix_apply(plan)
        msg = '完成 %d 个文件。' % len(log)
        if skip:
            msg += '\n\n跳过 %d 组（读不到文字）：\n' % len(skip) + '\n'.join(skip[:8])
        if err:
            msg += '\n\n失败 %d 个：\n' % len(err) + '\n'.join(err[:8])
        if self.v_exp.get():
            base = self.paths[0] if self.paths else '.'
            base = base if os.path.isdir(base) else os.path.dirname(base)
            mp = os.path.join(base, '_后缀对照表.csv')
            try:
                core.export_suffix(self.records, mp)
                msg += '\n\n对照表：' + mp
            except Exception:
                pass
        messagebox.showinfo('结果', msg)
        self.status.config(text=msg.replace('\n', ' ')[:120])
        self.do_scan()


def on_tab_changed(nb):
    """切选项卡：列表不丢，只把现场重新扫一遍。"""
    try:
        w = nb.nametowidget(nb.select())
    except Exception:
        return
    ps = getattr(w, 'paths', None)
    if not ps:
        try:
            w.status.config(text='本页还没有「待处理」来源：在任意一页拖入文件/文件夹即可（三页共用）')
        except Exception:
            pass
        return
    sh = getattr(w, 'sh', None)
    dirty = bool(getattr(sh, 'dirty', False))
    if getattr(w, 'scanning', False) or getattr(w, 'working', False):
        if sh is not None and dirty:
            sh.dirty = True       # 本页正忙，留着下次再扫
        return
    if sh is not None and dirty:
        sh.dirty = False          # 有页生成了新文件，本页必须重扫
    sig = tuple(sorted(ps))
    if dirty or sig != getattr(w, 'scanned_sig', None) or not w.records:
        w.do_scan()          # 只在来源变了 / 还没扫过时才扫


# ============================ 主窗口 ============================
def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    try:
        root.call('tk', 'scaling', 1.2)
    except Exception:
        pass

    # 界面里任何未捕获异常都落到 _error.log，方便反馈问题
    def _tk_hook(exc, val, tb):
        _log('tk-callback', ''.join(traceback.format_exception(exc, val, tb)))
    root.report_callback_exception = _tk_hook
    sys.excepthook = lambda t, v, tb: _log('uncaught', ''.join(traceback.format_exception(t, v, tb)))
    root.title('图书自动著录软件  v0.4.3')
    try:
        ico = os.path.join(core.res_dir(), 'app.ico')
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    root.geometry('1560x840')
    nb = ttk.Notebook(root)
    nb.pack(fill='both', expand=True)
    sh = Shared()
    nb.add(SuffixTab(nb, root, sh), text='  ① 后缀替换  ')
    nb.add(SimplifyTab(nb, root, sh), text='  ② 繁简转换+编码规范化  ')
    nb.add(CatalogTab(nb, root, sh), text='  ③ 著录建夹  ')

    nb.bind('<<NotebookTabChanged>>', lambda e: on_tab_changed(nb))

    root.mainloop()


def selftest():
    """--selftest：把自检结果写到 app_dir/_selftest.txt（用来验证打包/便携环境是否完好）"""
    out = []

    def w(k, v):
        out.append('%s = %s' % (k, v))
    w('frozen', getattr(sys, 'frozen', False))
    w('app_dir', core.app_dir())
    w('res_dir', core.res_dir())
    for m in ('fitz', 'zhconv', 'opencc', 'chardet', 'tkinterdnd2'):
        try:
            mod = __import__(m)
            w(m, getattr(mod, '__version__', 'ok'))
        except Exception as e:
            w(m, 'FAIL %s' % e)
    try:
        w('publishers', len(core.load_publishers()))
    except Exception as e:
        w('publishers', 'FAIL %s' % e)
    try:
        w('settings', core.load_settings())
    except Exception as e:
        w('settings', 'FAIL %s' % e)
    w('dnd', HAS_DND)
    # --- 真跑一遍依赖（import 成功不代表能用：zhconv 的字典是运行时才加载的数据文件，
    #     曾经只 import 没调用，导致打包版缺 zhcdict.json 却没被发现）---
    try:
        import zhconv
        w('zhconv.convert', zhconv.convert('臺灣圖書館', 'zh-cn'))
    except Exception as e:
        w('zhconv.convert', 'FAIL %s' % e)
    try:
        import opencc
        w('opencc.convert', opencc.OpenCC('t2s').convert('臺灣圖書館'))
    except Exception as e:
        w('opencc.convert', 'FAIL %s' % e)
    # --- 造一本"书"真跑著录：PDF(带文字层) + 繁体版权页 txt ---
    import shutil as _sh
    import tempfile as _tf
    _d = _tf.mkdtemp(prefix='csh_')
    try:
        import fitz as _fz
        _doc = _fz.open()
        _pg = _doc.new_page(width=595, height=842)
        _pg.insert_text((60, 80), 'TEXT LAYER', fontsize=12)
        _doc.save(os.path.join(_d, '測試書_PD6AIFOCR.pdf'))
        _doc.close()
        with open(os.path.join(_d, '測試書_PD6AIFOCR.txt'), 'w', encoding='utf-8') as _f:
            _f.write('图书在版编目(CIP)数据\n測試書/某某著.—北京:中華書局,1999.9\n'
                     'ISBN 7-101-00000-0\n1999年9月第1版\n定价:20.00元\n')
        _recs, _st = core.scan_paths([_d])
        w('catalog.scan', '%d 项 %s' % (len(_recs), [r.get('folder') for r in _recs]))
        _log2, _err2, _moved = core.apply([r for r in _recs
                                           if r.get('folder') and not r.get('need_manual')])
        w('catalog.apply', 'ok=%d err=%d moved=%d %s' % (len(_log2), len(_err2), len(_moved),
                                                         sorted(os.listdir(_d))))
    except Exception as e:
        w('catalog', 'FAIL %s' % e)
    finally:
        _sh.rmtree(_d, ignore_errors=True)
    try:
        root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        root.withdraw()
        nb = ttk.Notebook(root)
        sh = Shared()
        for cls in (SuffixTab, SimplifyTab, CatalogTab):
            nb.add(cls(nb, root, sh))
        w('tabs', len(nb.tabs()))
        w('icon_exists', os.path.exists(os.path.join(core.res_dir(), 'app.ico')))
        root.destroy()
    except Exception as e:
        w('tabs', 'FAIL %s' % e)
    w('result', 'FAIL' if any('FAIL' in x for x in out) else 'OK')
    p = os.path.join(core.app_dir(), '_selftest.txt')
    try:
        open(p, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    except Exception:
        p = os.path.join(os.environ.get('TEMP', '.'), '_selftest.txt')
        open(p, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    return p


def cli():
    """--cli <目录...> [--apply]：不开界面跑一遍「著录建夹」扫描（加 --apply 真的建夹移文件），
    结果写 app_dir\\_cli.log。用于在没有控制台的打包版里复现/排查问题。"""
    args = sys.argv[1:]
    mode = 'apply' if '--apply' in args else 'scan'
    paths = [a for a in args if a != '--cli' and not a.startswith('--')]
    ln = ['mode=%s' % mode, 'paths=%r' % paths,
          'frozen=%s  app_dir=%s  res_dir=%s' % (getattr(sys, 'frozen', False),
                                                 core.app_dir(), core.res_dir())]
    try:
        recs, st = core.scan_paths(paths)
        ln.append('扫描: %d 项   settings=%s' % (len(recs), st))
        for i, r in enumerate(recs, 1):
            ln.append('%3d| 夹名=%s | 文件=%d | 需人工=%s | 书名=%s | 出版社=%s | 年=%s'
                      % (i, r.get('folder'), len(r.get('files') or []),
                         bool(r.get('need_manual')), r.get('book'),
                         r.get('publisher'), r.get('year')))
            for f in (r.get('files') or []):
                ln.append('      file: %s  存在=%s' % (f, os.path.isfile(f)))
        if mode == 'apply':
            todo = [r for r in recs if r.get('folder') and not r.get('need_manual')]
            log, err, moved = core.apply(todo)
            ln.append('应用: 成功=%d 失败=%d 移动=%d' % (len(log), len(err), len(moved)))
            for x in err:
                ln.append('   ERR ' + str(x))
            for a, b in moved:
                ln.append('   %s  ->  %s' % (a, b))
    except Exception:
        ln.append('EXCEPTION:\n' + traceback.format_exc())
    out = os.path.join(core.app_dir(), '_cli.log')
    open(out, 'w', encoding='utf-8').write('\n'.join(ln) + '\n')
    return out


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    elif '--cli' in sys.argv:
        cli()
    else:
        main()
