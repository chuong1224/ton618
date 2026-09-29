# -*- coding: utf-8 -*-
"""Test P5 fixes — tags quoted comma, resolver trung stem, health_retry, dead state, source sanity. Scratch trong %TEMP%."""
import json, os, shutil, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault

from _scratch import SCRATCH, G3D
os.environ["GRAPH3D_ACTIVITY_FILE"] = os.path.join(SCRATCH, "act_p5.jsonl")
sys.path.insert(0, G3D)

import build_graph_data as BG
import run_graph3d as RG
import serve as SV

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

# P5.6: tags inline co dau phay trong ngoac kep
meta = BG._parse_frontmatter('---\ntags: [server-nhan-roi, "outgame, hoai-niem"]\n---\nbody')
check("P5.6a tag chua dau phay KHONG bi vo", meta["tags"] == ["server-nhan-roi", "outgame, hoai-niem"], meta["tags"])
meta2 = BG._parse_frontmatter("---\ntags: [a, b, c]\n---\n")
check("P5.6b list thuong van dung", meta2["tags"] == ["a", "b", "c"], meta2["tags"])

# P5.5: resolver trung stem — cung folder > path ngan > lexicographic; path tuong minh thang het
tmpv = os.path.join(SCRATCH, "tmpvault_p5")
shutil.rmtree(tmpv, ignore_errors=True)
for rel, content in {
    "A/Note.md": "x", "B/Note.md": "x",
    "A/Src.md": "[[Note]]", "C/Src2.md": "[[Note]]", "D/Src3.md": "[[B/Note]]",
}.items():
    p = os.path.join(tmpv, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
data = BG.build(tmpv)
links = {(l["source"], l["target"]) for l in data["links"]}
check("P5.5a uu tien CUNG folder", ("A/Src.md", "A/Note.md") in links, sorted(links))
check("P5.5b khong con first-win: mo ho -> chon deterministic (lex A truoc B)",
      ("C/Src2.md", "A/Note.md") in links, sorted(links))
check("P5.5c path tuong minh [[B/Note]] resolve dung", ("D/Src3.md", "B/Note.md") in links, sorted(links))
shutil.rmtree(tmpv, ignore_errors=True)

# P5.10: health_retry — port trong thi thoat ngay, khong cho vo ich
t0 = time.perf_counter()
h = RG.health_retry(59321)
dt = time.perf_counter() - t0
check("P5.10 port trong -> None nhanh (1 vong netstat, <5s)", h is None and dt < 5, round(dt, 2))

# P5.9: nguon that dang lanh lan -> True
check("P5.9 _restart_sources_sane() = True voi nguon that", SV._restart_sources_sane() is True)

# P5.9 chieu am: ban sao nguon trong scratch, lan luot lam cut tung loai file ma
# OneDrive co the ghi do -> phai False (chong restart vao code cut). Chi nua duong
# "True" thi bo han kiem van xanh; day la loi P5.9 sinh ra de chan.
sane_dir = os.path.join(SCRATCH, "sane_p5")
shutil.rmtree(sane_dir, ignore_errors=True)
os.makedirs(os.path.join(sane_dir, "src"))
for name in list(SV.restart_py_files()) + ["index.html"]:
    shutil.copyfile(os.path.join(G3D, name), os.path.join(sane_dir, name))
for sp in os.listdir(os.path.join(G3D, "src")):
    if os.path.isfile(os.path.join(G3D, "src", sp)):
        shutil.copyfile(os.path.join(G3D, "src", sp), os.path.join(sane_dir, "src", sp))
real_here = SV.HERE
SV.HERE = sane_dir
try:
    check("P5.9b ban sao nguyen ven -> True", SV._restart_sources_sane() is True)

    def _cut(rel, keep):
        """Ghi de file bang `keep` byte dau, chay kiem, roi tra ve ban goc."""
        p = os.path.join(sane_dir, *rel.split("/"))
        raw = open(p, "rb").read()
        open(p, "wb").write(raw[:keep])
        try:
            return SV._restart_sources_sane()
        finally:
            open(p, "wb").write(raw)

    idx_len = os.path.getsize(os.path.join(sane_dir, "index.html"))
    check("P5.9c index.html cut (mat </html>) -> False", _cut("index.html", idx_len // 2) is False)
    check("P5.9d serve.py cut giua chung -> False", _cut("serve.py", 1000) is False)
    first_src = sorted(os.listdir(os.path.join(sane_dir, "src")))[0]
    check("P5.9e src/* rong -> False", _cut("src/" + first_src, 0) is False, first_src)
finally:
    SV.HERE = real_here
    shutil.rmtree(sane_dir, ignore_errors=True)

try: os.remove(os.environ["GRAPH3D_ACTIVITY_FILE"])
except OSError: pass
print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
