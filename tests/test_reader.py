# -*- coding: utf-8 -*-
"""Test Reader (giai doan 1 Vault Cockpit) — vault_file la hang rao DUY NHAT cua
/note + /asset (server bat dau phuc vu noi dung vault): traversal, dot-folder,
duoi file, MIME. Scratch trong %TEMP%."""
import io, json, os, pathlib, shutil, subprocess, sys
from unittest import mock
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault

from _scratch import SCRATCH, G3D
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_reader.jsonl"))
sys.path.insert(0, G3D)

import serve as SV

# Chay duoc ca khi repo public duoc clone doc lap (khong co vault o thu muc cha).
VAULT = os.path.join(SCRATCH, "vault-reader-portable")
os.makedirs(VAULT, exist_ok=True)
with open(os.path.join(VAULT, "Sample.md"), "w", encoding="utf-8") as f:
    f.write("# Sample\n")
with open(os.path.join(VAULT, "Sample.xlsx"), "wb") as f:
    f.write(b"fake-xlsx-for-file-action-test")
with open(os.path.join(VAULT, "Sample, Quarter 3.xlsx"), "wb") as f:
    f.write(b"fake-xlsx-with-spaces-and-comma")
SV.VAULT = VAULT

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

# Mot note that trong vault gia lam mau.
check("R note that resolve duoc", SV.vault_file("Sample.md", exts={".md"}) is not None)

# Traversal + duong cam — moi ca PHAI None
for bad in [
    "../secrets.txt",                      # thoat vault bang ..
    "a/../../b.md",                        # .. giau giua duong
    "..\\..\\Windows\\win.ini",            # backslash + ..
    "C:/Windows/win.ini",                  # duong tuyet doi co o dia
    "/etc/passwd",                         # duong tuyet doi kieu POSIX
    ".obsidian/app.json",                  # dot-folder: config Obsidian
    ".graph3d/serve.py",                   # dot-folder: chinh code server
    ".claude/settings.json",               # dot-folder: hook agent
    "",                                    # rong
]:
    check("R chan %r" % bad, SV.vault_file(bad) is None)

# Loc duoi: /note chi nhan .md
check("R exts loc duoi khac .md", SV.vault_file("Sample.md", exts={".png"}) is None)

# W180: vault root nay do user chon; reparse point ben trong khong duoc bien /asset
# thanh cua doc file ngoai root. Mock realpath de test duoc ca khi Windows khong cho
# tao symlink (quyen Developer Mode khong phai luc nao cung co).
real_realpath = os.path.realpath
outside = os.path.join(os.path.dirname(VAULT), "outside.md")
def fake_realpath(path):
    if os.path.normpath(path) == os.path.normpath(os.path.join(VAULT, "link.md")):
        return outside
    return real_realpath(path)
with mock.patch.object(SV.os.path, "realpath", side_effect=fake_realpath):
    check("R chan symlink/junction thoat active vault", SV.vault_file("link.md") is None)

# MIME cho /asset: cac duoi anh pho bien phai co, duoi la fallback octet-stream
for ext, want in [(".jpg", "image/jpeg"), (".webp", "image/webp"), (".pdf", "application/pdf")]:
    check("R MIME %s" % ext, SV.MIME.get(ext) == want, SV.MIME.get(ext))

# /src/* + /vendor/*: hang rao file tinh cua APP (P0.4). Thay contract grep 2e bam ten
# bien (W426): app gia trong scratch co thu muc ANH EM vendor_old/src2 + file goc app —
# bo os.sep khoi prefix thi `/vendor/../vendor_old/x` lot ra va case duoi do.
app_fake = os.path.join(SCRATCH, "reader_app_static")
for rel in ("src/main.js", "src2/x.js", "vendor/lib.js", "vendor_old/x.js", "serve.py"):
    p = os.path.join(app_fake, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("// %s\n" % rel)
real_here = SV.HERE
SV.HERE = app_fake
try:
    got = {u: SV.app_static_file(u) for u in (
        "/src/main.js", "/vendor/lib.js", "/vendor/../vendor_old/x.js",
        "/src/../src2/x.js", "/vendor/../serve.py", "/src/khong-co.js")}
finally:
    SV.HERE = real_here
check("R file tinh app: /src + /vendor phuc vu dung file",
      got["/src/main.js"] and got["/src/main.js"].endswith("main.js")
      and got["/vendor/lib.js"] and got["/vendor/lib.js"].endswith("lib.js"), got)
check("R file tinh app: chan thu muc anh em (vendor_old, src2), file goc app, file khong co",
      [got[u] for u in ("/vendor/../vendor_old/x.js", "/src/../src2/x.js",
                        "/vendor/../serve.py", "/src/khong-co.js")] == [None] * 4, got)

# W173: action OS cho attachment — cung hang rao vault_file, POST se goi ham nay.
calls = []
def fake_startfile(path):
    calls.append(("startfile", path))
def fake_popen(argv, **kwargs):
    calls.append(("popen", argv, kwargs))
    return object()

try:
    opened = SV.run_file_action("Sample.xlsx", "open", platform="win32",
                                startfile=fake_startfile, popen=fake_popen)
except Exception as exc:
    opened = {"error": repr(exc)}
check("R W173 open dung file association Windows",
      opened.get("ok") is True and calls and calls[-1][0] == "startfile" and
      calls[-1][1].endswith("Sample.xlsx"), (opened, calls))
check("R W173 response chi tra path tuong doi",
      opened.get("path") == "Sample.xlsx" and "full" not in opened, opened)

calls.clear()
try:
    revealed = SV.run_file_action("Sample, Quarter 3.xlsx", "reveal", platform="win32",
                                  startfile=fake_startfile, popen=fake_popen)
except Exception as exc:
    revealed = {"error": repr(exc)}
reveal_call = calls[-1] if calls else None
reveal_full = os.path.normpath(SV.vault_file("Sample, Quarter 3.xlsx"))
reveal_cmd = 'explorer.exe /select,"%s"' % reveal_full
check("R W174 reveal dung Explorer /select voi quote dung cho space/comma",
      revealed.get("ok") is True and reveal_call and reveal_call[0] == "popen" and
      isinstance(reveal_call[1], str) and reveal_call[1] == reveal_cmd,
      (revealed, reveal_call, reveal_cmd))
check("R W174 Explorer khong qua shell va khong loe console",
      reveal_call and not reveal_call[2].get("shell") and
      reveal_call[2].get("creationflags") == 0x08000000, reveal_call)

for rel, action, err_type in [
    ("../Sample.xlsx", "open", FileNotFoundError),
    (".graph3d/serve.py", "open", FileNotFoundError),
    ("Sample.xlsx", "delete", ValueError),
]:
    try:
        SV.run_file_action(rel, action, platform="win32",
                           startfile=fake_startfile, popen=fake_popen)
        got = None
    except Exception as exc:
        got = type(exc)
    check("R W173 chan %s %r" % (action, rel), got is err_type, got)

# W139-W143: lightbox anh Reader — contract DOM/module + toan fit/zoom/pan thuần.
INDEX = os.path.join(G3D, "index.html")
READER = os.path.join(G3D, "src", "reader.js")
VIEWER = os.path.join(G3D, "src", "image-viewer.js")
MATH = os.path.join(G3D, "src", "image-viewer-math.js")
STYLE = os.path.join(G3D, "src", "style.css")

def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()

html, reader, viewer, math_src, css = map(read, (INDEX, READER, VIEWER, MATH, STYLE))
# LF cua index.html (gotcha #15) phai doc BINARY: text-mode doi \r\n thanh \n truoc khi
# kiem nen khong bao gio do duoc. src/* do selfcheck lop 1 gac (cung doc binary).
with open(INDEX, "rb") as f:
    check("R lightbox index giu LF", b"\r\n" not in f.read())

ids = ("imgv", "imgv-box", "imgv-head", "imgv-title", "imgv-scale", "imgv-stage",
       "imgv-image", "imgv-menu", "imgv-status", "imgv-minus", "imgv-plus",
       "imgv-fit", "imgv-actual", "imgv-close", "imgv-copy-image", "imgv-copy-link",
       "imgv-open-original", "imgv-download")
check("R lightbox DOM du %d id" % len(ids), all(('id="%s"' % x) in html for x in ids),
      [x for x in ids if ('id="%s"' % x) not in html])
check("R lightbox dialog aria + focus stage",
      'role="dialog"' in html and 'aria-modal="true"' in html and
      'aria-labelledby="imgv-title"' in html and 'id="imgv-stage" tabindex="0"' in html)
check("R Reader uy quyen click + keyboard vao viewer",
      "from './image-viewer.js'" in reader and "initImageViewer($('reader'))" in reader and
      "decorateViewerImages(R.content)" in reader and "isImageViewerOpen()" in reader)
check("R viewer co fit/zoom/pan/reset",
      all(tok in viewer for tok in ("fitScale(", "zoomAround(", "clampPan(",
                                    "pointerdown", "pointermove", "applyActual", "layoutBox(true)")))
check("R context menu copy co fallback va Shift-native",
      all(tok in viewer for tok in ("ClipboardItem", "copyLink(true, src)", "image/gif", "image/svg+xml",
                                    "MAX_COPY_PIXELS", "COPY_TIMEOUT_MS", "withTimeout(",
                                    "if (ev.shiftKey) return", "window.open", "a.download")))
check("R clipboard giu dung URL va reset status khi doi anh",
      "const src = state.src" in viewer and "state.src === src" in viewer and
      "E.status.hidden = true; E.status.textContent = ''" in viewer)
check("R hop viewer fixed theo viewport, gioi han 80vw x 80vh + responsive 375",
      "#imgv { position: fixed" in css and
      "max-width: 80vw" in css and "max-height: 80vh" in css and
      "@media (max-width: 500px)" in css)
check("R focus trap + tra focus anh mo",
      "ev.key === 'Tab'" in viewer and "opener.focus({ preventScroll: true })" in viewer and
      "$('reader').setAttribute('inert', '')" in viewer and "$('reader').removeAttribute('inert')" in viewer)
check("R tay keo Reader co separator + i18n + keyboard",
      'id="rd-resize"' in html and 'role="separator"' in html and
      'data-i18n-aria="rd.resize.aria"' in html and "h.onkeydown" in reader)
check("R Reader nho rieng width single/split + pointer capture",
      all(tok in reader for tok in ("kbgraph3d.readerW.v1", "single: 520", "split: 1046",
                                    "setPointerCapture", "onpointermove", "ResizeObserver",
                                    "READER_W_MIN", "READER_W_VAR", "parseFloat(readerStyle.left)")))
check("R CSS clamp Reader theo viewport va panel an",
      all(tok in css for tok in ("--reader-w: 520px", "--reader-split-w: 1046px",
                                 "#panel.hidden ~ #reader", "--reader-right-gap: 72px",
                                 "#rd-resize", ":root.rd-dragging")))
check("R tay keo nam ngoai Reader, khong de scrollbar doc",
      '</div>\n<div id="rd-resize"' in html and
      all(tok in css for tok in ("#reader.show + #rd-resize", "display: block",
                                 "top: 12px", "bottom: 12px", "--reader-handle-gap: 2px",
                                 "#panel.hidden ~ #rd-resize", "#reader.split + #rd-resize",
                                 "var(--reader-handle-gap)")) and
      "document.documentElement.style.setProperty(READER_W_VAR[mode]" in reader and
      "h.style.left" not in reader)
check("R rail resize bam con tro tuc thoi khi dang keo",
      "#rd-resize" in css and "transition: left .25s ease" in css and
      ":root.rd-dragging #rd-resize { transition: none; }" in css and
      "classList.add('rd-dragging')" in reader and
      "classList.remove('rd-dragging')" in reader)

# Chạy chính hàm JS thuần bằng Node khi có sẵn; app không phụ thuộc Node nên môi trường
# chỉ có Python được khai `[SKIP] ` chứ không FAIL oan — và từ W222 dòng khai đó bị
# selfcheck ĐẾM, nên "bỏ qua" không còn tàng hình sau exit 0.
# Phiên release W143 bắt buộc chạy nhánh này.
node = shutil.which("node")
if node:
    math_mjs = os.path.join(SCRATCH, "image-viewer-math.mjs")
    shutil.copyfile(MATH, math_mjs)
    uri = pathlib.Path(math_mjs).resolve().as_uri()
    js = """import {fitScale,clampScale,clampPan,zoomAround} from %s;
const near=(a,b)=>Math.abs(a-b)<1e-9;
const out={};
out.fitSmall=near(fitScale(400,300,800,600),1);
out.fitLarge=near(fitScale(1600,1200,800,600),0.5);
out.fitTall=near(fitScale(400,2400,800,600),0.25);
out.scaleClamp=near(clampScale(99),8)&&near(clampScale(0.001),0.1);
const p=clampPan(999,-999,1600,1200,1,800,600);
out.panClamp=near(p.x,400)&&near(p.y,-300);
const z=zoomAround({scale:1,panX:0,panY:0},2,600,300,1600,1200,800,600);
const before=(600-400)/1, after=(600-400-z.panX)/z.scale;
out.cursorAnchor=near(before,after)&&near(z.panY,0);
console.log(JSON.stringify(out));
if(Object.values(out).some(v=>!v)) process.exit(1);""" % json.dumps(uri)
    proc = subprocess.run([node, "--input-type=module", "--eval", js], capture_output=True, text=True)
    try:
        info = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:
        info = {"stdout": proc.stdout, "stderr": proc.stderr}
    check("R toan JS fit/zoom/pan chay du 6 bien", proc.returncode == 0 and len(info) == 6, info)
    for path in (MATH, VIEWER, READER):
        syntax = subprocess.run([node, "--check", path], capture_output=True, text=True)
        check("R JS syntax %s" % os.path.basename(path), syntax.returncode == 0, syntax.stderr)
else:
    print("[SKIP] R toan JS fit/zoom/pan + JS syntax — may khong co Node"
          " (app van chi can Python)")

print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
