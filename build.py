#!/usr/bin/env python3
"""build.py — one source per page, every product built from it (2026-11-11).

Sources (in the author's FFF_synthetic project, two directories up):
  13_artifact/page_src.html      result report; elements marked data-v="full" go only to the full (discussion)
                                 version, data-v="public" only to the public summary, unmarked to both
  14_tutorial_site/page_src.html walkthrough (no variants)

Outputs
  GitHub Pages (docs/, published from main /docs):
    docs/index.html + fig/ + media/     public summary, plain files
    docs/full/index.html                full report, AES-256-CBC encrypted (figures inlined, videos from ../media/)
    docs/walkthrough/index.html         walkthrough, encrypted the same way
  claude.ai artifacts (self-contained, figures and small videos inlined, links stay claude.ai URLs):
    13_artifact/index.html              full report        -> https://claude.ai/artifact/NK4f3obq9drVFot4LpTAck
    13_artifact/index_public.html       public summary     -> separate artifact
    14_tutorial_site/index.html         walkthrough        -> https://claude.ai/artifact/SoCbyu869iFLo1JETnvMqK

Encryption: openssl enc -aes-256-cbc -pbkdf2 -iter ITER -md sha256 -salt, passphrase read from ../FFF3D.passphrase
(outside the repository). The loader protected_loader.html derives key+iv with Web Crypto PBKDF2 and decrypts in the
browser. Plaintext of the protected pages is never written inside the repository; a protected page is re-encrypted
only when its plaintext sha256 changes (docs/<page>/.sha256), so unchanged pages do not churn the repository.

Usage: python3 build.py            (everything)
       python3 build.py --no-site  (artifact files only)
"""
import base64, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile
from html.parser import HTMLParser
import numpy as np
from PIL import Image

H = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(H, '..', '..'))
SRC_REPORT = os.path.join(PROJ, '13_artifact')
SRC_WALK = os.path.join(PROJ, '14_tutorial_site')
PASSFILE = os.path.join(H, '..', 'FFF3D.passphrase')
ITER = 200000
REPORT_URL = 'https://claude.ai/artifact/NK4f3obq9drVFot4LpTAck'
WALK_URL = 'https://claude.ai/artifact/SoCbyu869iFLo1JETnvMqK'
PUBLIC_URL = 'https://mchsieh.github.io/FFF3D/'
HEAD = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="description" content="%s">\n')
DESC = {
    'public': "FFF3D: finite-fault inversion with 3-D strain Green's tensors, demonstrated on a synthetic test in a Taiwan 3-D velocity model.",
    'full': "Result report of a pure synthetic finite-fault inversion test in the Taiwan 3-D velocity model (Lee et al., 2025): FFF with strain Green's tensors.",
    'walk': "Step-by-step walkthrough of a pure synthetic finite-fault SGT inversion test in the Taiwan 3-D velocity model (Lee et al., 2025), run with the FFF package.",
}
INLINE = {'media/velmodel.mp4': 'media/velmodel_inline.mp4',      # 1280 x 720, crf 27 (5.9 MB)
          'media/slip_evolution.mp4': 'media/slip_inline.mp4'}   # 1388 x 1556, crf 24 (0.6 MB)
VOID = {'meta', 'link', 'img', 'br', 'hr', 'input', 'source', 'track', 'wbr', 'col', 'embed', 'param', 'area', 'base'}


# ---------------------------------------------------------------- variants
class _Marks(HTMLParser):
    """Record (start, end, variant, start-tag text) of every element carrying data-v."""
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.line_off = [0]
        for line in text.split('\n'): self.line_off.append(self.line_off[-1] + len(line) + 1)
        self.stack, self.ranges = [], []
    def pos(self):
        ln, col = self.getpos(); return self.line_off[ln - 1] + col
    def handle_starttag(self, tag, attrs):
        dv = dict(attrs).get('data-v'); p = self.pos(); raw = self.get_starttag_text()
        if tag in VOID:
            if dv: self.ranges.append((p, p + len(raw), dv, raw))
            return
        self.stack.append((tag, p, dv, raw))
    def handle_startendtag(self, tag, attrs):
        dv = dict(attrs).get('data-v'); p = self.pos(); raw = self.get_starttag_text()
        if dv: self.ranges.append((p, p + len(raw), dv, raw))
    def handle_endtag(self, tag):
        p = self.pos(); end = self.text.index('>', p) + 1
        while self.stack:
            t, s, dv, raw = self.stack.pop()
            if dv: self.ranges.append((s, end, dv, raw))
            if t == tag: break


def select(text, variant):
    """Keep elements with data-v == variant (attribute removed), drop the others, leave unmarked text alone."""
    m = _Marks(text); m.feed(text); m.close()
    assert not m.stack, 'unclosed elements: %r' % [t for t, _, _, _ in m.stack]
    ranges = list(m.ranges)
    for s, e, dv, raw in m.ranges:                       # a bare <span data-v> is only a text switch: unwrap it
        if dv == variant and re.sub(r'\s+data-v="[^"]*"', '', raw, count=1) == '<span>':
            assert text[e-7:e] == '</span>', text[e-20:e]
            ranges.append((e-7, e, '__drop__', '</span>'))
    ranges.sort()
    out, i, k = [], 0, 0
    while k < len(ranges):
        s, e, dv, raw = ranges[k]
        if s < i: k += 1; continue                       # nested inside a dropped element
        out.append(text[i:s])
        if dv == variant:
            tag = re.sub(r'\s+data-v="[^"]*"', '', raw, count=1)
            if tag != '<span>': out.append(tag)
            i = s + len(raw)
        else:
            i = e
        k += 1
    out.append(text[i:])
    res = ''.join(out)
    assert 'data-v=' not in res, 'data-v left after selection'
    return res


# ---------------------------------------------------------------- figures
def fig_bytes(path):
    """PNG: trim white rows above/below (keep 1.5 % of the height), never the sides, downscale to <= 2000 px wide.
    JPG: re-save at quality 86. Returns (bytes, mime, (w, h))."""
    im = Image.open(path); buf = io.BytesIO()
    if path.endswith('.png'):
        a = np.asarray(im.convert('L')); rows = np.where((a < 250).any(axis=1))[0]
        if rows.size:
            pad = int(0.015*a.shape[0]); im = im.crop((0, max(0, rows[0]-pad), im.size[0], min(a.shape[0], rows[-1]+1+pad)))
        if im.size[0] > 2000: im = im.resize((2000, round(im.size[1]*2000/im.size[0])), Image.LANCZOS)
        im.save(buf, 'PNG', optimize=True); mime = 'image/png'
    else:
        im.convert('RGB').save(buf, 'JPEG', quality=86); mime = 'image/jpeg'
    return buf.getvalue(), mime, im.size

_CACHE = {}
def fig(srcdir, rel):
    key = os.path.join(srcdir, rel)
    if key not in _CACHE: _CACHE[key] = fig_bytes(key)
    return _CACHE[key]

def fix_dims(srcdir, html):
    def dims(m):
        _, _, (w, h) = fig(srcdir, m.group(2))
        return '%s="%s"%s width="%d" height="%d"' % (m.group(1), m.group(2), m.group(3), w, h)
    return re.sub(r'\b(src)="(fig/[^"]+\.png)"([^>]*?) width="\d+" height="\d+"', dims, html)

def inline_images(srcdir, html):
    def rep(m):
        data, mime, _ = fig(srcdir, m.group(2))
        return '%s="data:%s;base64,%s"' % (m.group(1), mime, base64.b64encode(data).decode())
    return re.sub(r'\b(src|poster)="((?:fig|media)/[^"]+\.(?:png|jpg))"', rep, html)


# ---------------------------------------------------------------- products
def artifact(srcdir, html, outname):
    """Self-contained page for claude.ai: figures, posters and the small videos inlined; links untouched."""
    assets = json.load(open(os.path.join(srcdir, 'assets.json'))) if os.path.exists(os.path.join(srcdir, 'assets.json')) else {}
    html = inline_images(srcdir, fix_dims(srcdir, html))
    def vid(m):
        path = m.group(1)
        srcs = ['data:video/mp4;base64,' + base64.b64encode(open(os.path.join(srcdir, INLINE[path]), 'rb').read()).decode()]
        if path in assets: srcs.append(assets[path])
        return ''.join('<source src="%s" type="video/mp4">' % u for u in srcs)
    html = re.sub(r'<source src="(media/[^"]+\.mp4)" type="video/mp4">', vid, html)
    left = re.findall(r'(?:src|poster)="((?:fig|media)/[^"]+)"', html)
    out = os.path.join(srcdir, outname); open(out, 'w', encoding='utf-8').write(html)
    mb = os.path.getsize(out)/1e6
    print('%-44s %6.2f MB  still relative: %s' % (os.path.relpath(out, PROJ), mb, ', '.join(left) or 'none'))
    assert mb < 15.5, 'page over the 16 MB artifact limit'


def wrap(html, desc):
    i = html.index('<header>')
    return HEAD % desc + html[:i] + '</head>\n<body>\n' + html[i:] + '\n</body>\n</html>\n'


def public_site(srcdir, html):
    """docs/index.html with fig/ and media/ as plain files."""
    docs = os.path.join(H, 'docs')
    for d in ('fig', 'media'): os.makedirs(os.path.join(docs, d), exist_ok=True)
    html = fix_dims(srcdir, html)
    for rel in sorted(set(re.findall(r'\b(?:src|poster)="((?:fig|media)/[^"]+\.(?:png|jpg))"', html))):
        data, _, _ = fig(srcdir, rel); open(os.path.join(docs, rel), 'wb').write(data)
    for rel in sorted(set(re.findall(r'<source src="(media/[^"]+\.mp4)"', html))):
        shutil.copyfile(os.path.realpath(os.path.join(srcdir, rel)), os.path.join(docs, rel))
    assert 'claude.ai' not in html, 'claude.ai link left in the public page'
    open(os.path.join(docs, 'index.html'), 'w', encoding='utf-8').write(wrap(html, DESC['public']))


def protected(srcdir, html, sub, desc, title, passphrase):
    """docs/<sub>/index.html: encrypted self-contained page (figures inlined, videos from ../media/)."""
    html = inline_images(srcdir, fix_dims(srcdir, html))
    html = re.sub(r'<source src="media/([^"]+\.mp4)"', r'<source src="../media/\1"', html)
    assert 'claude.ai' not in html, 'claude.ai link left in ' + sub
    assert not re.search(r'(?:src|poster)="(?:fig|media)/', html), 'relative figure left in ' + sub
    plain = wrap(html, desc).encode('utf-8')
    digest = hashlib.sha256(plain).hexdigest()
    outdir = os.path.join(H, 'docs', sub); os.makedirs(outdir, exist_ok=True)
    shafile, outfile = os.path.join(outdir, '.sha256'), os.path.join(outdir, 'index.html')
    if os.path.exists(shafile) and os.path.exists(outfile) and open(shafile).read().strip() == digest:
        print('%-44s unchanged (%.2f MB plaintext)' % ('docs/%s/index.html' % sub, len(plain)/1e6)); return
    fd, tmp = tempfile.mkstemp(prefix='fff3d_', suffix='.html'); os.write(fd, plain); os.close(fd)
    try:
        ct = subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', str(ITER), '-md', 'sha256', '-salt',
                             '-in', tmp, '-pass', 'file:' + passphrase], check=True, stdout=subprocess.PIPE).stdout
    finally:
        os.remove(tmp)
    assert ct[:8] == b'Salted__'
    b64 = base64.b64encode(ct).decode()
    b64 = '\n'.join(b64[i:i+120] for i in range(0, len(b64), 120))
    loader = open(os.path.join(H, 'protected_loader.html'), encoding='utf-8').read()
    for k, v in (('{{B64}}', b64), ('{{ITER}}', str(ITER)), ('{{TITLE}}', title),
                 ('{{DESC}}', 'Protected page of the FFF3D project; a passphrase from the author is required.'), ('{{PUBLIC}}', '../')):
        loader = loader.replace(k, v)
    open(outfile, 'w', encoding='utf-8').write(loader); open(shafile, 'w').write(digest + '\n')
    print('%-44s %6.2f MB encrypted (%.2f MB plaintext, sha256 %s)' % ('docs/%s/index.html' % sub, os.path.getsize(outfile)/1e6, len(plain)/1e6, digest[:12]))


def main():
    site = '--no-site' not in sys.argv
    report = open(os.path.join(SRC_REPORT, 'page_src.html'), encoding='utf-8').read()
    walk = open(os.path.join(SRC_WALK, 'page_src.html'), encoding='utf-8').read()
    full, public = select(report, 'full'), select(report, 'public')
    assert 'Lee et al' not in public and 'w_disp' not in public and 'w_shallow' not in public, 'public variant still carries full-only content'

    # claude.ai artifact files
    artifact(SRC_REPORT, full, 'index.html')
    artifact(SRC_REPORT, public, 'index_public.html')
    artifact(SRC_WALK, walk, 'index.html')
    if not site: return

    # GitHub Pages
    assert os.path.exists(PASSFILE), 'passphrase file missing: ' + os.path.abspath(PASSFILE)
    docs = os.path.join(H, 'docs')
    for name in os.listdir(docs) if os.path.exists(docs) else []:
        if name not in ('full', 'walkthrough'):                 # protected pages are rebuilt only when their content changes
            p = os.path.join(docs, name); shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    public_site(SRC_REPORT, public)
    protected(SRC_REPORT, full.replace(WALK_URL, '../walkthrough/'), 'full', DESC['full'], 'FFF3D result report (full version)', PASSFILE)
    protected(SRC_WALK, walk.replace(REPORT_URL, '../full/'), 'walkthrough', DESC['walk'], 'FFF3D walkthrough', PASSFILE)
    open(os.path.join(docs, '.nojekyll'), 'w').close()
    tot = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(docs) for f in fs)
    print('docs/: %.1f MB, %d files' % (tot/1e6, sum(len(fs) for _, _, fs in os.walk(docs))))


if __name__ == '__main__':
    main()
