# -*- coding: utf-8 -*-
"""Test Finder (giai doan 2 Vault Cockpit) — endpoint /search: fold khong dau
mirror deAccent cua UI, AND moi tu, diem ten nang hon than, snippet map nguoc
ve text goc, loai dot-folder nhu scanner. Scratch trong %TEMP%."""
import io, os, sys
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 khong in duoc tieng Viet
except Exception:
    pass

from _scratch import SCRATCH, G3D, VAULT
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_finder.jsonl"))
sys.path.insert(0, G3D)

import serve as SV

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

# ---- _fold: mirror deAccent (lower + bo dau + d) va giu 1:1 do dai ----
check("F fold bo dau + lower", SV._fold("Hoài Niệm") == "hoai niem", SV._fold("Hoài Niệm"))
check("F fold d/D thanh d", SV._fold("Đường Đèo đá") == "duong deo da", SV._fold("Đường Đèo đá"))
for s in ["Ngoại Trang Tết 2026", "server Nhàn Rỗi — đẹp", "abc xyz"]:
    check("F fold giu do dai %r" % s, len(SV._fold(s)) == len(s), (len(s), len(SV._fold(s))))

# ---- vault gia trong scratch ----
TV = os.path.join(SCRATCH, "finder_vault")
if os.path.isdir(TV):
    import shutil
    shutil.rmtree(TV)
write(os.path.join(TV, "Ghi Chú Mèo.md"),
      "# Ghi Chú Mèo\nNội dung về ngoại trang mèo rất đẹp, ngoại trang hiếm.\n")
write(os.path.join(TV, "Sub", "Server Log.md"),
      "# Server Log\nCụm server Nhàn Rỗi mở ngày mai.\n")
write(os.path.join(TV, "Ngoại Trang Tết.md"),
      "# Ngoại Trang Tết\nDanh sách trang phục.\n")
write(os.path.join(TV, ".secret", "hidden.md"), "bimatkhongdocduoc ngoại trang\n")
write(os.path.join(TV, "node_modules", "junk.md"), "ngoại trang rác vendor\n")

SV.VAULT = TV   # search_notes quet vault dang active cua server, dung nhu /search

def hit_paths(q, **kw):
    return [r["path"] for r in SV.search_notes(q, **kw)]

# Khong dau + hoa thuong deu khop
check("F khop khong dau", "Ghi Chú Mèo.md" in hit_paths("ngoai trang meo"))
check("F khop HOA + co dau", "Sub/Server Log.md" in hit_paths("NHÀN RỖI"))
# AND moi tu: tu nam o 2 note khac nhau -> khong note nao khop
check("F AND moi tu (cheo note = truot)", hit_paths("meo nhan roi") == [])
# Dot-folder + EXCLUDED_DIRS loai nhu scanner
check("F loai dot-folder", all(".secret" not in p for p in hit_paths("bimatkhongdocduoc")))
check("F loai node_modules", all("node_modules" not in p for p in hit_paths("ngoai trang")))
# Diem ten file nang hon than: "Ngoại Trang Tết" phai dung TREN "Ghi Chú Mèo"
rank = hit_paths("ngoai trang")
check("F ten note xep tren than note", rank and rank[0] == "Ngoại Trang Tết.md", rank)
# Snippet: text GOC con dau quanh vi tri khop
res = SV.search_notes("nhan roi")
check("F snippet giu text goc co dau", res and "Nhàn Rỗi" in res[0]["snippet"],
      res[0]["snippet"] if res else None)
# hits = TONG lan khop cua MOI tu trong than ("ngoai"x2 + "trang"x2 = 4)
res = SV.search_notes("ngoai trang")
row = next((r for r in res if r["path"] == "Ghi Chú Mèo.md"), None)
check("F hits dem du lan khop moi tu", row is not None and row["hits"] == 4, row)
# Query rong / toan khoang trang -> rong, khong loi
check("F query rong tra rong", SV.search_notes("") == [])
check("F query khoang trang tra rong", SV.search_notes("   ") == [])
# limit cat dung
check("F limit=1 tra 1 ket qua", len(SV.search_notes("ngoai trang", limit=1)) == 1)

# W173: attachment co mat trong ca hai o tim va moi loi vao deu dung mot dialog.
def read_app(rel):
    with io.open(os.path.join(G3D, rel), encoding="utf-8") as f:
        return f.read()

finder = read_app("src/finder.js")
reader = read_app("src/reader.js")
graph = read_app("src/graph.js")
ui = read_app("src/ui.js")
main = read_app("src/main.js")
index = read_app("index.html")
try:
    actions = read_app("src/file-actions.js")
except OSError:
    actions = ""

check("F W173 module file-actions ton tai + POST open/reveal",
      all(tok in actions for tok in ("export function openFileActions", "method: 'POST'",
                                     "action=open", "action=reveal", "assetUrl")))
check("F W173 Ctrl+P tim va chon attachment",
      all(tok in finder for tok in ("function qsFileRow", "data-file", "openFileActions(",
                                    "n.kind === 'file'")))
check("F W173 Reader link file mo dialog chung",
      "data-file" in reader and "openFileActions(" in reader)
check("F W173 click node file tren graph mo dialog",
      "n.kind === 'file'" in graph and "openFileActions(n)" in graph)
check("F W173 o Tim note/file tim tren S.all va mo attachment",
      "openFileActions(" in ui and "n.kind === 'file'" in ui and "S.all.nodes" in ui)
check("F W173 main khoi tao + debug hook file action",
      "initFileActions()" in main and "openFileActions" in main)
ids = ("file-act", "file-act-box", "file-act-title", "file-act-path", "file-act-open",
       "file-act-reveal", "file-act-preview", "file-act-status", "file-act-close")
check("F W173 dialog DOM du %d id" % len(ids),
      all(('id=\"%s\"' % x) in index for x in ids),
      [x for x in ids if ('id=\"%s\"' % x) not in index])

# W174: Office/archive phai download cung tab, khong de lai cua so app den; chi cac
# dinh dang browser render duoc moi mo tab preview.
check("F W174 tach previewable va download-only",
      all(tok in actions for tok in ("PREVIEW_EXTS", "tr('file.preview')",
                                     "tr('file.download')", ".download =",
                                     "removeAttribute('target')", "target = '_blank'")))
preview_markup = '<a id="file-act-preview" data-i18n="file.preview">'
check("F W174 markup khong hardcode target blank",
      preview_markup in index and
      '<a id="file-act-preview" target="_blank"' not in index)

print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
