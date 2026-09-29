# -*- coding: utf-8 -*-
"""Test onboarding vault TRONG (W13) — onboarding.state / install_starter / mirror_app:

  - state(): vault 0 note -> empty True; co note -> empty False; nguon bundled
    (starter-vault/ + demo/vault/) khong co tren may nay -> available False, KHONG doan
  - install_starter: chep du file, dem dung so note, BO QUA dot-file trong nguon
  - install_starter: TUYET DOI khong de file trung ten (file cu giu nguyen byte)
  - install_starter: tu choi khi dich da co note .md (force=True moi cho qua)
  - mirror_app: copy du APP_TOP + APP_DIRS; thieu file khai trong danh sach = loi CUNG
    (bug that: try_demo.py cua repo public sot insight.py/integrity.py -> demo chet
     luc serve import); lan 2 khong chep lai gi; xoa file thua o dich; tu choi src==dst
  - demo_env: log/journal/heat cua demo tro ra NGOAI thu muc demo (ten file mang ten
    may, khong duoc roi vao working tree repo public — su co doi 4 va doi 6)
  - danh sach dan xuat: restart_py_files() = phan .py cua _VERSION_FILES va nam trong APP_PY
"""
import contextlib, io, os, re, shutil, subprocess, sys
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252
except Exception:
    pass

from _scratch import SCRATCH, G3D
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_onboarding.jsonl"))
sys.path.insert(0, G3D)

import activity_paths as AP
import onboarding as ONB
import ensure_graph3d as ENS

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)


ROOT = os.path.join(SCRATCH, "onb")
STARTER = os.path.join(ROOT, "starter-vault")
VAULT_EMPTY = os.path.join(ROOT, "vault-empty")
VAULT_FULL = os.path.join(ROOT, "vault-full")
SRC_APP = os.path.join(ROOT, "src-app")
DST_APP = os.path.join(ROOT, "dst-app")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build_fixture():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    # Nguon starter: 2 note + 1 file phu trong thu muc con + 1 dot-file phai bi bo qua
    write(os.path.join(STARTER, "Start Here.md"), "# Start Here\n[[What Is a Note]]\n")
    write(os.path.join(STARTER, "What Is a Note.md"), "# What Is a Note\n")
    write(os.path.join(STARTER, "attachments", "note.txt"), "kem theo\n")
    write(os.path.join(STARTER, ".gitkeep"), "")
    # dot-FOLDER co .md: scanner graph (count_notes) va install_starter deu phai bo qua
    write(os.path.join(STARTER, ".obsidian", "workspace.md"), "# khong phai note\n")
    os.makedirs(VAULT_EMPTY, exist_ok=True)
    write(os.path.join(VAULT_FULL, "Note cua toi.md"), "# Note cua toi\n")
    # Bo app gia: du moi file khai trong APP_TOP/APP_DIRS
    for name in AP.APP_TOP:
        write(os.path.join(SRC_APP, name), "print('%s')\n" % name)
    write(os.path.join(SRC_APP, "src", "main.js"), "export const v = 1;\n")
    write(os.path.join(SRC_APP, "vendor", "lib.js"), "// lib\n")


build_fixture()

# ---- state() ----
st = ONB.state(VAULT_EMPTY)
check("state vault trong -> empty", st["empty"] is True and st["notes"] == 0, st)
check("state co ten + duong dan vault",
      st["vault"] == os.path.basename(VAULT_EMPTY) and os.path.isabs(st["vault_path"]), st)
check("state kem lenh chay tay cho ca 2 loi di",
      "--demo" in st["cmd"]["demo"] and "--init-starter" in st["cmd"]["starter"], st["cmd"])
check("state demo co port RIENG (khong cuop 8321)",
      st["demo"]["port"] == ONB.DEMO_PORT and ONB.DEMO_PORT != 8321, st["demo"])

st_full = ONB.state(VAULT_FULL)
check("state vault co note -> khong empty", st_full["empty"] is False and st_full["notes"] == 1, st_full)
check("state truyen notes vao thi dung so do (khong quet lai)",
      ONB.state(VAULT_EMPTY, notes=42)["notes"] == 42 and not ONB.state(VAULT_EMPTY, notes=42)["empty"])

os.environ["GRAPH3D_STARTER_DIR"] = os.path.join(ROOT, "khong-ton-tai")
os.environ["GRAPH3D_DEMO_DIR"] = os.path.join(ROOT, "cung-khong-ton-tai")
st_none = ONB.state(VAULT_EMPTY)
check("nguon bundled thieu -> available False (khong doan)",
      st_none["starter"]["available"] is False and st_none["demo"]["available"] is False, st_none)

os.environ["GRAPH3D_STARTER_DIR"] = STARTER
st_ok = ONB.state(VAULT_EMPTY)
check("co starter-vault -> available True + dem dung so note",
      st_ok["starter"]["available"] is True and st_ok["starter"]["notes"] == 2, st_ok["starter"])
check("count_notes bo qua dot-folder nhu scanner graph",
      ONB.count_notes(STARTER) == 2, ONB.count_notes(STARTER))

# ---- W42: app co nam trong vault duoi ten .graph3d hay khong ----
check("installed_in_vault: ten thu muc .graph3d -> True",
      ONB.installed_in_vault(os.path.join(ROOT, "vault-x", ".graph3d")) is True)
check("installed_in_vault: clone bare (ten repo) -> False",
      ONB.installed_in_vault(os.path.join(ROOT, "agents-knowledge-base")) is False)
# W180: vault chon tuong minh (khac thu muc cha cua app) khong duoc bao "cai sai cho";
# con vault = thu muc cha thi quay ve phan xet W42 theo ten thu muc app.
APP_DIR = os.path.dirname(os.path.abspath(ONB.__file__))
check("state installed: vault chon noi khac -> True (W180); vault = cha app -> theo ten .graph3d (W42)",
      st["installed"] is True
      and ONB.state(os.path.dirname(APP_DIR), notes=1)["installed"] == ONB.installed_in_vault(APP_DIR)
      and st["app_dir"] == os.path.basename(APP_DIR), st)
check("state co lenh cai dat dung cho ca canh bao",
      ".graph3d" in st["cmd"]["install"] and "clone" in st["cmd"]["install"], st["cmd"])

# count_bundled: cache theo mtime thu muc goc (state() chay ca khi vault KHONG trong).
# Them note vao thu muc CON khong doi mtime thu muc goc -> ban cache van tra so cu,
# trong khi count_notes (khong cache) thay ngay. Bo cache thi hai so bang nhau.
n1 = ONB.count_bundled(STARTER)
extra = os.path.join(STARTER, "attachments", "Them Sau.md")
write(extra, "# Them Sau\n")
try:
    check("count_bundled cache theo mtime thu muc goc (khong quet lai)",
          (n1, ONB.count_bundled(STARTER), ONB.count_notes(STARTER)) == (2, 2, 3),
          (n1, ONB.count_bundled(STARTER), ONB.count_notes(STARTER)))
finally:
    os.remove(extra)

# ---- W42: note "cua vao" mo ngay sau khi dung starter vault ----
check("entry_note uu tien 'Start Here'",
      ONB.entry_note(["attachments/a.txt", "What Is a Note.md", "Start Here.md"]) == "Start Here.md")
check("entry_note nhan tieng Viet 'Bat Dau'",
      ONB.entry_note(["Linking Notes.md", "Bắt Đầu — Tiếng Việt.md"]) == "Bắt Đầu — Tiếng Việt.md")
check("entry_note khong co ten uu tien -> note nong nhat/ngan nhat",
      ONB.entry_note(["sub/deep/z.md", "b.md"]) == "b.md")
check("entry_note khong co .md -> None", ONB.entry_note(["attachments/a.png"]) is None)

# ---- install_starter ----
res = ONB.install_starter(VAULT_EMPTY)
check("install_starter tao du file (2 note + 1 file kem)",
      len(res["created"]) == 3 and res["notes"] == 2, res)
check("install_starter tra ve note 'cua vao' de UI mo ngay (W42)",
      res["entry"] == "Start Here.md", res.get("entry"))
check("install_starter giu cau truc thu muc con",
      os.path.isfile(os.path.join(VAULT_EMPTY, "attachments", "note.txt")), res["created"])
check("install_starter bo qua dot-file trong nguon",
      not os.path.exists(os.path.join(VAULT_EMPTY, ".gitkeep")), os.listdir(VAULT_EMPTY))
check("install_starter -> vault khong con trong",
      ONB.state(VAULT_EMPTY)["empty"] is False, ONB.state(VAULT_EMPTY)["notes"])

# Lan 2: vault da co note -> tu choi (hang rao 1)
try:
    ONB.install_starter(VAULT_EMPTY)
    check("install_starter tu choi vault da co note", False, "khong raise")
except ONB.OnboardingError as e:
    check("install_starter tu choi vault da co note", "TRỐNG" in str(e) or "trong" in str(e).lower(), str(e))

# force=True: van chay nhung KHONG DE file trung ten (hang rao 2 khong co co nao tat)
mine = os.path.join(VAULT_EMPTY, "Start Here.md")
write(mine, "NOI DUNG CUA TOI\n")
res2 = ONB.install_starter(VAULT_EMPTY, force=True)
with open(mine, encoding="utf-8") as f:
    kept = f.read()
check("force=True van KHONG de file trung ten",
      kept == "NOI DUNG CUA TOI\n" and "Start Here.md" in res2["skipped"], res2)
check("file trung ten vao 'skipped', khong vao 'created'",
      "Start Here.md" not in res2["created"], res2["created"])

# ---- W44: CLI co loi ra AN TOAN cho vault dang co ----
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = ENS.init_starter(VAULT_FULL)
refusal = out.getvalue()
check("CLI tu choi vault co note nhung goi ro --force",
      rc == 2 and "--force" in refusal and "KHONG de file trung ten" in refusal, refusal)

out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = ENS.init_starter(VAULT_FULL, force=True)
check("CLI --force them starter vao vault dang co ma giu note cua user",
      rc == 0 and os.path.isfile(os.path.join(VAULT_FULL, "Note cua toi.md"))
      and os.path.isfile(os.path.join(VAULT_FULL, "Start Here.md")), out.getvalue())

hp = subprocess.run([sys.executable, os.path.join(G3D, "ensure_graph3d.py"), "--help"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", check=False)
help_text = " ".join(hp.stdout.split())       # argparse xuong dong theo be rong console
check("--help mo ta --no-open + --force + hang rao khong de file",
      hp.returncode == 0 and "--no-open" in help_text
      and "khong mo trinh duyet" in help_text and "--force" in help_text
      and "KHONG de file trung ten" in help_text, hp.stdout)

# W44 UI: vault 0 note khong de 0/0 + control graph chen vao man onboarding; moi
# control click duoc trong onboarding phai la button that de Enter/Space dung duoc.
with open(os.path.join(G3D, "src", "onboarding.js"), encoding="utf-8") as f:
    onb_js = f.read()
with open(os.path.join(G3D, "src", "style.css"), encoding="utf-8") as f:
    css = f.read()
with open(os.path.join(G3D, "index.html"), encoding="utf-8") as f:
    html = f.read()
check("UI vault trong gan class vault-empty tu so note hien hanh",
      re.search(r"classList\.toggle\('vault-empty',\s*!\s*[\w.]*\bmeta\.notes\)", onb_js))
check("CSS vault-empty an panel/cay/hint/layout khoi man dau",
      ":root.vault-empty #panel" in css and ":root.vault-empty #sidebar" in css
      and ":root.vault-empty #hint" in css and ":root.vault-empty #layout-fab" in css)
check("lenh copy onboarding la button ban phim, khong con code onclick",
      '<button type="button" class="onb-cmd"' in onb_js
      and '<code>${esc(cmd)}</code></button>' in onb_js)
check("nut dong onboarding la button co aria-label",
      '<button type="button" id="onb-x"' in html and 'data-i18n-aria="onb.close"' in html)

try:
    os.environ["GRAPH3D_STARTER_DIR"] = os.path.join(ROOT, "khong-co-that")
    ONB.install_starter(VAULT_EMPTY)
    check("install_starter bao loi khi thieu nguon", False, "khong raise")
except ONB.OnboardingError as e:
    check("install_starter bao loi khi thieu nguon", "starter" in str(e), str(e))
finally:
    os.environ["GRAPH3D_STARTER_DIR"] = STARTER

# ---- mirror_app ----
m1 = ONB.mirror_app(DST_APP, SRC_APP)
missing = [n for n in AP.APP_TOP if not os.path.isfile(os.path.join(DST_APP, n))]
check("mirror_app copy du APP_TOP", not missing, missing)
check("mirror_app copy du APP_DIRS",
      os.path.isfile(os.path.join(DST_APP, "src", "main.js"))
      and os.path.isfile(os.path.join(DST_APP, "vendor", "lib.js")))
check("mirror_app dem so file da chep", m1["copied"] == len(AP.APP_TOP) + 2, m1)

m2 = ONB.mirror_app(DST_APP, SRC_APP)
check("mirror_app lan 2 khong chep lai gi (khoi ton 3.3MB vendor)", m2["copied"] == 0, m2)

write(os.path.join(DST_APP, "src", "module-da-go.js"), "// rac\n")
ONB.mirror_app(DST_APP, SRC_APP)
check("mirror_app xoa file thua o dich (module bi go khong song sot)",
      not os.path.exists(os.path.join(DST_APP, "src", "module-da-go.js")))

os.remove(os.path.join(SRC_APP, AP.APP_PY[-1]))
try:
    ONB.mirror_app(DST_APP, SRC_APP)
    check("mirror_app: thieu file khai trong APP_TOP = loi CUNG", False, "khong raise")
except ONB.OnboardingError as e:
    check("mirror_app: thieu file khai trong APP_TOP = loi CUNG", AP.APP_PY[-1] in str(e), str(e))

try:
    ONB.mirror_app(SRC_APP, SRC_APP)
    check("mirror_app tu choi src == dst", False, "khong raise")
except ONB.OnboardingError as e:
    check("mirror_app tu choi src == dst", "trùng" in str(e) or "trung" in str(e), str(e))

# ---- demo_env ----
env = ONB.demo_env({"PATH": "x"})
demo_dir = os.path.normcase(os.path.join(G3D, "demo"))
outside = all(not os.path.normcase(env[k]).startswith(demo_dir)
              for k in ("GRAPH3D_ACTIVITY_FILE", "GRAPH3D_JOURNAL_DIR", "GRAPH3D_HEAT_DIR"))
check("demo_env: 3 duong runtime deu NGOAI thu muc demo", outside,
      {k: env[k] for k in ("GRAPH3D_ACTIVITY_FILE", "GRAPH3D_JOURNAL_DIR", "GRAPH3D_HEAT_DIR")})
check("demo_env giu env goc", env.get("PATH") == "x")
check("demo_env tat ghi bytecode (khoi sinh __pycache__ trong cay repo)",
      env.get("PYTHONDONTWRITEBYTECODE") == "1", env.get("PYTHONDONTWRITEBYTECODE"))
# Chieu "co env -> doi duong" do test_journal J9p0 + test_selfcheck H-explicit gac.
os.environ.pop("GRAPH3D_HEAT_DIR", None)
check("bo env -> store heat ve lai .graph3d",
      os.path.dirname(AP.cumulative_heat_path()) == G3D, AP.cumulative_heat_path())

# ---- danh sach dan xuat, khong chep tay ----
check("restart_py_files() = phan .py cua _VERSION_FILES",
      set(AP.restart_py_files()) == {n for n in AP._VERSION_FILES if n.endswith(".py")},
      AP.restart_py_files())
check("restart_py_files() nam tron trong APP_PY",
      set(AP.restart_py_files()) <= set(AP.APP_PY),
      sorted(set(AP.restart_py_files()) - set(AP.APP_PY)))

print("\nTONG KET test_onboarding: %s" % (("FAIL %d: %s" % (len(fails), ", ".join(fails))) if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
