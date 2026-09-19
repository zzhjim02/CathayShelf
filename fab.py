# -*- coding: utf-8 -*-
"""一键发版：打包单文件 exe → 算 SHA256 → 生成发行说明骨架。

用法：
    py -3 fab.py                 # 打包 + 校验值 + 发行说明
    py -3 fab.py --skip-build    # 跳过打包，只重算校验值/发行说明
"""
import hashlib, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
NAME = 'CathayShelf'
ENTRY = 'gui.py'
EXTRA = ['--add-data', 'config;config', '--collect-all', 'tkinterdnd2', '--collect-all', 'opencc', '--collect-all', 'zhconv', '--hidden-import', 'chardet', '--hidden-import', 'zhconv']
REPO = 'https://github.com/zzhjim02/CathayShelf'


def version():
    t = open(ENTRY, encoding='utf-8').read()
    for line in t.splitlines():
        if 'APP_TITLE' in line or 'root.title' in line:
            m = re.search(r'v[0-9]+[.][0-9]+(?:[.][0-9]+)?', line)
            if m:
                return m.group(0)[1:]
    return '0.0'


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def build():
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
           '--windowed', '--name', NAME, '--icon', 'app.ico',
           '--add-data', 'app.ico;.'] + EXTRA + [ENTRY]
    print('>>', ' '.join(cmd))
    if subprocess.run(cmd).returncode != 0:
        sys.exit('打包失败')


def find_exe():
    """找成品 exe：优先标准名，否则取 dist 或 Release 目录下最新的 exe（兼容手动改名）。"""
    cands = [os.path.join('dist', 'Release', NAME + '.exe'), os.path.join('dist', NAME + '.exe')]
    for c in cands:
        if os.path.isfile(c):
            return c
    import glob
    g = sorted(glob.glob(os.path.join('dist', 'Release', '*.exe')),
               key=os.path.getmtime, reverse=True)
    return g[0] if g else ''


def main():
    v = version()
    out = os.path.join('dist', 'Release')
    if '--skip-build' not in sys.argv:
        build()
    os.makedirs(out, exist_ok=True)
    src = os.path.join('dist', NAME + '.exe')
    if os.path.isfile(src):
        shutil.move(src, os.path.join(out, NAME + '.exe'))
    exe = find_exe()
    if not exe:
        sys.exit('没找到成品 exe（dist 或 Release 目录下），请先打包')

    size = os.path.getsize(exe) / 1048576.0
    lines = ['%s  %d 字节  %.2f MB' % (os.path.basename(exe), os.path.getsize(exe), size),
             'SHA256  %s' % sha256(exe)]
    open(os.path.join(out, '校验值.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))

    notes = """# CathayShelf v%s

> 发布日期：%s

## 本版要点
<!-- 一句话说清这一版最重要的变化 -->

-

## 下载

| 下载方式 | 链接 |
|:-------|:-----|
| 📥 中国移动云盘（推荐） | <待填：中国移动云盘分享链接> |
| 📥 百度网盘（备用，密码 2026） | <待填：百度网盘分享链接> |
| 🐙 GitHub Releases | %s/releases/tag/v%s |

## 包内包含

- `CathayShelf.exe` —— 单文件版，约 %.0f MB，双击即用
- `runtime\\`（约 92 MB，自带 Python）+ `著录.bat`

## 校验值（SHA256）

```
%s
```

## 从上一版以来
<!-- 逐条列出修复与新增 -->

-
""" % (v, time.strftime('%Y-%m-%d'), REPO, v, size, '\n'.join(lines))
    p = os.path.join(out, '发行说明_v%s.md' % v)
    if os.path.exists(p) and os.path.getsize(p) > 200:      # 已手写过的正文不覆盖
        print('发行说明 -> %s（已存在手写正文，保留）' % p)
    else:
        open(p, 'w', encoding='utf-8').write(notes)
        print('发行说明 ->', p)


if __name__ == '__main__':
    main()
