# -*- coding: utf-8 -*-
"""
选项卡二「繁简转换+编码规范化」——整合自 CathaySimplify 1.0.3。

模式「繁简转换+编码规范化」：繁体 TXT 生成简体副本（或反过来），带后缀，原文件保留；
输出同样统一为 UTF-8 无 BOM。
模式「仅编码规范化」：不做繁简转换，只把编码统一成 UTF-8 无 BOM。

与另两页联动：共用同一份「待处理」来源；本页产生新文件后会把新文件**追加进共享列表**
（另存模式）并置 sh.dirty，切到别的页会自动重扫，看到新产物、著录建夹不会漏。
"""
import os
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import core
import simplify
from ui_common import HAS_DND, tk_splitlist, bind_drop

S3COLS = [('no', '序号', 45), ('name', '文件 / 所在文件夹', 330),
          ('script', '判定', 50), ('ratio', '繁体占比', 68),
          ('enc', '原编码', 100), ('act', '动作', 80),
          ('old', '原文件名', 300), ('new', '新文件名', 330),
          ('state', '状态', 170)]


class SimplifyTab(ttk.Frame):
    def __init__(self, master, root, sh):
        super().__init__(master)
        self.root = root
        self.sh = sh
        self.scanned_sig = None
        self.records = []
        self.rows = []
        self.rowmap = {}
        self.excluded = set()
        self.scanning = False
        self.working = False
        self.paths = []

        self.dz = tk.Label(
            self, height=2,
            text='⬇  把要处理的 TXT 文件或文件夹拖进来（文件夹自动递归，子目录也扫）',
            bg='#eef2fa', fg='#2b4d8a', relief='ridge', bd=1)
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
        self.btn_apply = ttk.Button(bar, text='应用：转换', command=self.do_apply)
        self.btn_apply.pack(side='right', padx=6)

        o1 = ttk.Frame(self, padding=(6, 2))
        o1.pack(fill='x')
        self.mode_var = tk.StringVar(value='convert')
        ttk.Label(o1, text='模式：').pack(side='left')
        ttk.Radiobutton(o1, text='繁简转换+编码规范化', variable=self.mode_var,
                        value='convert', command=self._on_mode).pack(side='left', padx=(4, 6))
        ttk.Radiobutton(o1, text='仅编码规范化', variable=self.mode_var,
                        value='encoding', command=self._on_mode).pack(side='left')
        ttk.Label(o1, text='     方向：').pack(side='left', padx=(16, 0))
        self.dir_var = tk.StringVar(value='auto')
        self.rbs = []
        for v, t in (('auto', '自动（繁体才转）'), ('t2s', '强制繁转简'),
                     ('s2t', '强制简转繁')):
            rb = ttk.Radiobutton(o1, text=t, variable=self.dir_var,
                                 value=v, command=self._on_dir)
            rb.pack(side='left', padx=(6, 2))
            self.rbs.append(rb)

        o2 = ttk.Frame(self, padding=(6, 2))
        o2.pack(fill='x')
        ttk.Label(o2, text='后缀：').pack(side='left')
        self.var_sfx = tk.StringVar(value=simplify.S_T2S)
        ttk.Entry(o2, textvariable=self.var_sfx, width=14).pack(side='left')
        self.outmode_var = tk.StringVar(value='suffix')
        ttk.Label(o2, text='   输出方式：').pack(side='left')
        ttk.Radiobutton(o2, text='加后缀另存（原文件保留）', variable=self.outmode_var,
                        value='suffix').pack(side='left', padx=(4, 6))
        ttk.Radiobutton(o2, text='覆盖原文件', variable=self.outmode_var,
                        value='overwrite').pack(side='left')
        ttk.Label(o2, text='   输出目录：').pack(side='left', padx=(14, 2))
        self.var_out = tk.StringVar(value='')
        ttk.Entry(o2, textvariable=self.var_out, width=34).pack(side='left')
        ttk.Button(o2, text='浏览', command=self.pick_out).pack(side='left', padx=4)
        ttk.Label(o2, text='（留空 = 原文件所在目录）', foreground='#888').pack(side='left')

        ttk.Label(self, text='输出一律为 UTF-8 无 BOM。双击一行可预览转换前后的文字。'
                             '黄底=繁简把握不大，红底=读不出来，灰字=无需处理',
                  foreground='#888', padding=(8, 0)).pack(fill='x')

        self.src = ttk.Label(self, text='待处理：0 项', foreground='#555', padding=(8, 0))
        self.src.pack(fill='x')

        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in S3COLS], show='headings')
        for k, t, w in S3COLS:
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor='w')
        self.tree.bind('<Double-1>', self.preview_row)
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

    # ---------- 联动 ----------
    @property
    def paths(self):
        return self.sh.paths

    @paths.setter
    def paths(self, v):
        self.sh.paths = list(v)

    def _opt(self):
        return {'mode': self.mode_var.get(), 'direction': self.dir_var.get(),
                'out_mode': self.outmode_var.get(),
                'suffix': self.var_sfx.get().strip(),
                'out_dir': self.var_out.get().strip()}

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
        d = filedialog.askdirectory(title='选择文件夹（自动递归找 TXT）')
        if d:
            if d not in self.paths:
                self.paths.append(d)
            self.refresh_src()
            self.do_scan()

    def pick_out(self):
        d = filedialog.askdirectory(title='选择输出目录（留空 = 原目录）')
        if d:
            self.var_out.set(d)

    def clear(self):
        self.paths = []
        self.records = []
        self.rows = []
        self.tree.delete(*self.tree.get_children())
        self.refresh_src()
        self.status.config(text='已清空')

    # ---------- 设置 ----------
    def _on_mode(self):
        enc_mode = self.mode_var.get() == 'encoding'
        for rb in self.rbs:
            rb.state(['disabled'] if enc_mode else ['!disabled'])
        if enc_mode:
            if self.var_sfx.get() in (simplify.S_T2S, simplify.S_S2T):
                self.var_sfx.set(simplify.S_UTF8)
            self.outmode_var.set('overwrite')
        else:
            if self.var_sfx.get() in (simplify.S_UTF8, ''):
                self.var_sfx.set(simplify.S_S2T
                                 if self.dir_var.get() == 's2t' else simplify.S_T2S)
            self.outmode_var.set('suffix')

    def _on_dir(self):
        d = self.dir_var.get()
        if d == 's2t' and self.var_sfx.get() in (simplify.S_T2S, simplify.S_UTF8):
            self.var_sfx.set(simplify.S_S2T)
        elif d == 't2s' and self.var_sfx.get() in (simplify.S_S2T, simplify.S_UTF8):
            self.var_sfx.set(simplify.S_T2S)

    # ---------- 扫描 ----------
    def do_scan(self):
        if not self.paths:
            messagebox.showwarning('提示', '请先拖入或选择文件/文件夹')
            return
        if self.scanning or self.working:
            return
        opt = self._opt()                      # 主线程里读控件
        self.scanning = True
        self.status.config(text='扫描中…')
        self.pbar.config(maximum=100, value=0)
        threading.Thread(target=self._scan, args=(opt,), daemon=True).start()

    def _scan(self, opt):
        try:
            def prog(i, n, b):
                self.root.after(0, lambda: (self.pbar.config(value=(i + 1) * 100 / max(n, 1)),
                                            self.status.config(text='%d/%d %s' % (i + 1, n, b[:40]))))
            recs = simplify.simplify_scan(list(self.paths), opt, progress=prog)
            self.records = recs
            self.opt_used = opt
            self.root.after(0, self.fill)
        except Exception:
            self.scanning = False
            err = traceback.format_exc()
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
        n = nskip = nact = 0
        for r in self.records:
            for it in r['items']:
                n += 1
                if it.get('no_need'):
                    tag, nskip = 'dim', nskip + 1
                    vals = (n, r['base'], '-', '%.2f' % r['ratio'], r['enc'] or '-',
                            '—', os.path.basename(it['old']), '—', r['why'] or '无需处理')
                else:
                    tag = 'manual' if (not r['enc'] or r.get('why') == '读不出来') else (
                        'warn' if 0.25 <= r['ratio'] <= 0.75 else '')
                    nact += 1
                    vals = (n, r['base'], r['script'], '%.2f' % r['ratio'], r['enc'] or '-',
                            simplify.DIR_NAME.get(r['act'], r['act']),
                            os.path.basename(it['old']), os.path.basename(it['new']), '')
                self.rows.append(it)
                self.rowmap[str(n - 1)] = (r, it)
                self.tree.insert('', 'end', iid=str(n - 1), tags=(tag,), values=vals)
        mode = getattr(self, 'opt_used', {}).get('mode', 'convert')
        d = {v: k for k, v in simplify.DIR_NAME.items()}
        head = '繁简转换' if mode == 'convert' else '编码规范化'
        if not nact:
            self.status.config(text='扫描完成：没有需要处理的 TXT，无需处理 %d 个' % nskip)
        else:
            self.status.config(text='扫描完成：%s 待处理 %d 个，无需处理 %d 个' %
                                    (head, nact, nskip))

    # ---------- 预览 ----------
    def preview_row(self, ev):
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        r, it = self.rowmap.get(iid, (None, None))
        if not r:
            return
        w = tk.Toplevel(self.root)
        w.title('预览：' + r['base'])
        w.geometry('1200x620')
        info = ('文件：%s\n编码：%s（置信度 %.0f%%）　判定：%s（繁体占比 %.2f）　动作：%s' %
                (r['file'], r['enc'] or '?', r['conf'] * 100, r['script'],
                 r['ratio'], simplify.DIR_NAME.get(r['act'], '无需处理')))
        ttk.Label(w, text=info, justify='left', padding=6).pack(fill='x')
        box = ttk.Frame(w)
        box.pack(fill='both', expand=True, padx=6, pady=6)
        left = ttk.LabelFrame(box, text='原文')
        right = ttk.LabelFrame(box, text='转换后（前 1500 字预览）')
        left.pack(side='left', fill='both', expand=True)
        right.pack(side='left', fill='both', expand=True, padx=(6, 0))
        txt, enc, conf, bom = simplify.read_text_any(r['file'])
        txt = txt or ''
        out = txt if not r['act'] else simplify.convert_text(txt, r['act'])
        for frame, s in ((left, txt[:1500]), (right, out[:1500])):
            t = tk.Text(frame, wrap='char', font=('Microsoft YaHei UI', 10))
            sc = ttk.Scrollbar(frame, command=t.yview)
            t.configure(yscrollcommand=sc.set)
            t.insert('1.0', s)
            t.config(state='disabled')
            t.pack(side='left', fill='both', expand=True)
            sc.pack(side='right', fill='y')

    # ---------- 导出 / 应用 ----------
    def do_export(self):
        if not self.records:
            return
        base = self.paths[0] if self.paths else '.'
        base = base if os.path.isdir(base) else os.path.dirname(base)
        p = filedialog.asksaveasfilename(
            defaultextension='.csv', initialdir=base, initialfile='繁简转换对照表.csv',
            filetypes=[('CSV', '*.csv')])
        if p:
            simplify.export_simplify(self.records, p)
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
        if not self.records or self.working or self.scanning:
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
            plan = [dict(r, items=[it for it in r['items'] if not it.get('no_need')])
                    for r in self.records if not r.get('no_need')]
            plan = [p for p in plan if p['items']]
        n = sum(len(p['items']) for p in plan)
        if not plan:
            messagebox.showinfo('提示', '选中的都是「无需处理」的文件')
            return
        opt = self._opt()
        head = '繁简转换' if opt['mode'] == 'convert' else '编码规范化'
        tip = ('%s %d 个 TXT 文件？\n\n模式：%s\n' % ('选中的' if sel else '将处理', n, head))
        if opt['mode'] == 'convert':
            dd = {'auto': '自动（繁体才转）', 't2s': '强制繁转简',
                  's2t': '强制简转繁'}[opt['direction']]
            tip += '方向：%s\n后缀：%s\n' % (dd, opt['suffix'] or '（按方向默认）')
        tip += '输出：%s' % ('覆盖原文件' if opt['out_mode'] == 'overwrite'
                            else '另存' + ('到 ' + opt['out_dir'] if opt['out_dir'] else ''))
        if not messagebox.askyesno('确认', tip + '\n\n继续？'):
            return
        self.working = True
        self.btn_apply.config(state='disabled')
        self.status.config(text='转换中…')
        self.pbar.config(maximum=100, value=0)
        threading.Thread(target=self._apply_thread, args=(plan, opt), daemon=True).start()

    def _add_shared(self, created):
        """把本次新写出的文件追加进共享「待处理」列表（去重，只收存在的）。"""
        if not created:
            return 0
        have = {os.path.normcase(os.path.abspath(p)) for p in self.paths}
        added = 0
        for p in created:
            if not p or not os.path.exists(p):
                continue
            k = os.path.normcase(os.path.abspath(p))
            if k in have:
                continue
            have.add(k)
            self.sh.paths.append(p)
            added += 1
        if added:
            self.refresh_src()
        return added

    def _apply_thread(self, plan, opt):
        try:
            log, err, skip, created = simplify.simplify_apply(plan, opt)
            self.root.after(0, lambda: self._apply_done(log, err, skip, plan, created))
        except Exception:
            tb = traceback.format_exc()
            self.working = False
            self.root.after(0, lambda: (self.btn_apply.config(state='normal'),
                                        messagebox.showerror('转换出错', tb)))

    def _apply_done(self, log, err, skip, plan, created=()):
        self.working = False
        self.btn_apply.config(state='normal')
        tot = sum((r.get('stats') or {}).get('changed', 0) for r in plan)
        chars = sum((r.get('stats') or {}).get('total', 0) for r in plan)
        msg = '完成 %d 个文件。\n共 %d 字，改动 %d 字。' % (len(log), chars, tot)
        ex = []
        for r in plan:
            ex.extend((r.get('stats') or {}).get('examples', []))
        if ex:
            msg += '\n\n转换示例（前 8 条）：\n' + '\n'.join(list(dict.fromkeys(ex))[:8])
        if skip:
            msg += '\n\n跳过 %d 个：\n' % len(skip) + '\n'.join(skip[:6])
        if err:
            msg += '\n\n失败 %d 个：\n' % len(err) + '\n'.join(err[:8])
        n_add = self._add_shared(created)
        if n_add:
            msg += ('\n\n已把 %d 个新生成的文件加入「待处理」列表'
                    '（切到「著录建夹」不会漏）。' % n_add)
        if self.v_exp.get():
            base = self.paths[0] if self.paths else '.'
            base = base if os.path.isdir(base) else os.path.dirname(base)
            mp = os.path.join(base, '_繁简转换对照表.csv')
            try:
                simplify.export_simplify(self.records, mp)
                msg += '\n\n对照表：' + mp
            except Exception:
                pass
        messagebox.showinfo('结果', msg)
        self.status.config(text=msg.replace('\n', ' ')[:130])
        self.sh.dirty = True        # 让另两页切过去时自动重扫，看到新产物
        self.do_scan()
