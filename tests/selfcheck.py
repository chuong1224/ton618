# -*- coding: utf-8 -*-
"""Selfcheck .graph3d (G1.2) — luat G1.3: sua .graph3d/* xong PHAI chay selfcheck, PASS moi duoc ghi nghiem thu.

3 lop, ca bo < 30s:
  1. Compile — syntax moi file .py goc (danh sach doc tu activity_paths.APP_PY, khong
     chep tay) + tests/*.py; src/* (ES modules giai doan 0) khong rong + LF + ket
     thuc \n + index tro /src/main.js. index.html cut duoi do test_p5 P5.9 gac bang
     chinh _restart_sources_sane (W426).
  2. Contract grep — ma hoa cac bug DA SUA (muc 2a..2o, < 1s): moi contract la mot bug
     tung xay ra, FAIL nghia la co nguoi vua dua bug do quay lai. 2a..2i tu review
     2026-07-10 (W426 bo 2d/2e/2h + nua solar cua 2c: dead state khong co hanh vi, 2e
     thay bang test hanh vi app_static_file o test_reader, 2h do test_p2 --slow gac);
     2j/2k tu 2 su co publish doi 7+8 (danh sach file .py chep tay bi sot);
     2m/2n tu W222 (quy uoc [SKIP] + danh sach bo unit chep tay); 2o tu W239 (bo test
     cham diem im lang thi khong dem duoc vung phu).
  3. Unit — test_p1/p3/p4/p5 + test_reader (guard /note + /asset, giai doan 1 Vault
     Cockpit) + test_finder (/search fold + AND + loai dot-folder, giai doan 2)
     + test_cockpit (/timeline + /dashboard theo ngay local, giai doan 3)
     + test_journal (journal dong bo log 2 may qua vault, v1.25.0)
     + test_insight (tang insight suc khoe vault /insight + note bao cao, W10)
     + test_integrity (den bao toan ven vault /integrity — link/nhung/anchor gay,
       anh mo coi, YAML frontmatter vo/thieu truong, "mo nilon"; W11/W149)
     + test_onboarding (vault trong: state/install_starter/mirror_app, W13)
     + test_vault_switcher (active root/config/restart routing, W180)
     + test_i18n (song ngu VI/EN: 2 ngon ngu cung tap khoa, khoa dung deu co that,
       bien {x} khop, src/*.js het chuoi giao dien tieng Viet; W43)
     + test_launcher (loi vao he dieu hanh: shortcut .lnk goi ensure --app, icon .ico,
       uninstall khong dung .lnk nguoi khac, bind_console cho pythonw; W58)
     + test_selfcheck (chinh runner nay: phan loai PASS/PASS*/THIEU-LIB/FAIL, W222);
     test_p2 (~15s, spawn process that + chiem port rieng) chi chay khi --slow.
     Bo nao KHONG do het thi phai TU KHAI bang dong `[SKIP] <ly do>` — xem khoi
     "Quy uoc chua do duoc" ben duoi.

Chay:  python .graph3d/tests/selfcheck.py [--slow] [--chap-nhan "ly do"]
Exit:  0 = ALL PASS; 1 = co FAIL, THIEU-LIB (phep do hong cung la chua do duoc), hoac
       VUNG PHU TUT (W239). Muc tu khai [SKIP] KHONG doi exit code (may nay khong co
       `node` thi khong the va bang cach sua code) nhung LUON hien ra + duoc dem o TONG KET.

W239 (16/08/2026) — ba lop tren van mu truoc bo test bo qua IM LANG:

  W220/W222 day runner doc dong `[SKIP]` TU KHAI. Nhung mot bo viet `if not dieu_kien:
  pass`, hay bi xoa bot khang dinh, thi khong phat tin hieu nao: khong dong SKIP, exit 0,
  runner ghi PASS. Nay runner DO thay vi hoi — dem so khang dinh moi muc vua chay that
  (moi bo test in mot dong PASS/FAIL cho moi khang dinh), ghi vao moc per-MAY ngoai repo,
  luot sau dem so. Tut thi CHAN nhu FAIL; ha moc hop le di bang `--chap-nhan "ly do"`.
  Lop 1+2 cua chinh runner cung duoc dem (khoa `__runner__`).
"""
import glob
import json, os, re, socket, subprocess, sys, time

sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
from _scratch import SCRATCH, G3D, VAULT

TESTS = os.path.dirname(os.path.abspath(__file__))
# File CHI co trong ban private (backup git nam ngoai OneDrive — khong publish).
# Thieu cac file NAY thi bo qua; thieu bat ky file nao KHAC van la FAIL (bug that).
PRIVATE_ONLY = {"backup_graph3d.py", "test_backup.py"}
# Nguoc lai: script CHI co o ban public (repo clone) — khong thuoc app, khong mirror,
# khong publish tu vault. Co mat cung khong sao, khong can khai trong APP_PY.
REPO_ONLY = {"try_demo.py"}


def _declared_py():
    """Danh sach .py goc KHONG chep tay nua (W13): doc tu activity_paths.APP_PY —
    nguon DUY NHAT dung chung voi mirror demo va whitelist publish. activity_paths
    hong syntax -> fallback glob de lop 1 con bao duoc dung loi compile."""
    try:
        sys.path.insert(0, G3D)
        import activity_paths as ap
        return sorted(set(ap.APP_PY) | PRIVATE_ONLY), ap
    except Exception:                                    # noqa: BLE001
        return sorted(os.path.basename(p) for p in glob.glob(os.path.join(G3D, "*.py"))), None


PY_MAIN, AP = _declared_py()
# Module serve.py import luc nap NHUNG co y khong nam _VERSION_FILES: no co duong
# reload rieng (importlib.reload theo mtime — gotcha #8), khai vao day se restart thua.
RELOADABLE = {"build_graph_data.py"}
INDEX = os.path.join(G3D, "index.html")
SRC = os.path.join(G3D, "src")

# Bo unit cua lop 3. Danh sach nam O DAY chu khong trong lop3_unit() de contract 2n
# doi chieu duoc voi tests/ tren dia — danh sach chep tay khong ai doi chieu chinh la
# thu da can he nay 2 lan (doi publish 7+8).
UNIT_FILES = ("test_p1.py", "test_p3.py", "test_p4.py", "test_p5.py", "test_reader.py",
              "test_finder.py", "test_cockpit.py", "test_journal.py", "test_insight.py",
              "test_integrity.py", "test_onboarding.py", "test_i18n.py",
              "test_launcher.py", "test_reload.py", "test_update.py",
              "test_vault_switcher.py", "test_selfcheck.py")
SLOW_FILES = ("test_p2.py",)                         # chi chay khi --slow


def src_files():
    return sorted(p for p in glob.glob(os.path.join(SRC, "*")) if os.path.isfile(p))


def ui_sources():
    """(ten, noi dung) cua MOI file UI: index.html + src/* — contract quet ca bo."""
    out = [("index.html", read(INDEX))]
    out += [("src/" + os.path.basename(p), read(p)) for p in src_files()]
    return out

fails = []
skips = []                                           # muc TU KHAI la chua do duoc (W222)
thieu_lib = {}                                       # ten bo -> module con thieu
so_check = [0]                                       # W239: dem khang dinh cua CHINH runner
khang_dinh = {}                                      # W239: ten bo -> so khang dinh da chay

def check(name, cond, info=""):
    # Dem MOI lan goi, ke ca lan FAIL: con so nay do VUNG PHU (bao nhieu khang dinh da
    # chay), khong do ket qua. Lop 1/2 cua runner cung bi xoa bot khang dinh nhu bat ky
    # bo test nao — khong dem thi chinh cho phat hien lo hong lai la cho khong ai soi.
    so_check[0] += 1
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

def an_toan(s):
    """Ha ky tu ma stdout cua CHINH selfcheck khong ma hoa noi ve '?'.

    Tren Windows, stdout bi pipe lay encoding theo locale (cp1252) chu khong phai UTF-8.
    Mot ly do bo qua co dau — hay ky tu U+FFFD sinh ra khi giai ma output process con —
    se nem UnicodeEncodeError va giet CA lan selfcheck, dung tai cho no dang bao "toi
    chua do gi". Ban ra chu mat dau van doc duoc; mat ca lan chay thi khong."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        s.encode(enc)
        return s
    except (UnicodeEncodeError, LookupError):
        return s.encode(enc, "replace").decode(enc, "replace")


def skip(ly_do):
    """Khai mot muc CHINH selfcheck khong do duoc — cung quy uoc voi bo test con,
    de mat nguoi va may deu dem duoc mot kieu."""
    print(an_toan("[SKIP] " + ly_do))
    skips.append(ly_do)

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- Quy uoc "chua do duoc" (W222) — CHUNG voi may gac tooling cua vault ----
# Bug goc, do 14/08/2026 o pass audit nguoc cua W220: lop 3 chi doc returncode. Bo test
# nao bat ImportError, khong tim thay `node`, hoac khong chay tren Windows thi in mot
# dong SKIP roi exit 0 — runner dem PASS trong khi no KHONG do gi. Xanh gia nguy hon do
# gia: do gia con thay ma cai, xanh gia thi im lang. Trong tests/ co dung 5 cho nhu vay.
#
# QUY UOC CHOT cho ca hai may gac: bo test tu khai bang dong `[SKIP] <ly do>` o DAU DONG,
# MOT dong cho MOI muc bi bo qua. Ngoac vuong la co y — bat chu SKIP tran thi bo test nao
# lo in chu do trong du lieu do choi cua no cung bi dem oan.
#
# Ban goc cua bo ba ham nay + 6 case nghiem thu quy uoc (33..38) song o may gac tooling:
#   Vault Operation/Quy Tac & Van Hanh/May Gac Test Tooling/attachments/tooling_selfcheck.py
# Hai ban CO Y tach roi: ban public clone ra ngoai vault khong voi toi file kia duoc.
# Cai phai trung khop la MARKER va NGHIA cua 4 nhan, khong phai chinh ta (file nay ASCII,
# ben kia tieng Viet co dau) — test_selfcheck.py giu hai ban khong troi nhau.
#
# W239 (16/08/2026): ban W222 neo cung `^\[SKIP\]`, nen dong khai bi THUT LE khong ai dem.
# Bo test in marker tu trong mot khoi da canh le, hay chuyen tiep output cua runner con
# (runner con thut output vao 6 dau cach), deu khai dung quy uoc ma van tang hinh. Nay cho
# phep khoang trang dau dong; NGOAC VUONG van la thu chan dem oan, khong phai cot 0.
SKIP_RE = re.compile(r"^[ \t]*\[SKIP\][ \t]*(.*)$", re.M)
THIEU_RE = re.compile(r"No module named '([\w.]+)'")
# Kieu khai CU (truoc W222) ma contract 2m cam: PHAT ra chuoi bat dau bang chu SKIP tran.
#
# W239: ban W222 chi bam `print(`, nen mot loi ra qua `sys.stdout.write` lot thang. Nay bat
# ca hai loi ra stdout/stderr, va cho phep thut le ben trong chuoi. (Cho nay co y KHONG
# viet ra mau vi pham: chinh file nay nam trong pham vi 2m quet, va ban dau tien cua dong
# chu thich nay da lam 2m tu bat chinh no — bug that, do luc 16/08/2026.)
# Van neo vao LENH PHAT chu
# khong bat moi chuoi bat dau bang SKIP: `"SKIP dung parser THAT"` la DU LIEU hop le cua
# test_selfcheck.py (case A4 phai co mau kieu cu de chung minh no khong bi dem oan), bat
# ca literal la bat oan chinh cai test dang gac. Nua con lai cua lo — chuoi dung dong roi
# in bien — khong vao duoc 2m, va khong can: bo test do van bi W239 bat qua SO KHANG DINH.
SKIP_TRAN_RE = re.compile(
    r"""(?:print|sys\.std(?:out|err)\.write)\(\s*f?["']\s{0,4}SKIP[ :\t-]""")
# W239 — LO MA W222 KHONG BIT DUOC: bo test bo qua IM LANG.
#
# `bo_qua()` va contract 2m chi thay duoc muc test TU KHAI. Mot bo viet `if not dieu_kien:
# pass`, hay bi xoa bot khang dinh, thi khong phat tin hieu nao: khong dong SKIP, exit 0,
# runner ghi PASS. Dung lop bug W220/W222 sinh ra de chan, chi khac o cho no CAM.
#
# Cach bit: dung hoi bo test "may co bo qua gi khong" (no phai nho moi tra loi duoc) ma DO
# xem no vua chay bao nhieu khang dinh, roi so voi lan xanh truoc. Vung phu tut la du kien
# quan sat duoc, khong can doan y dinh — xoa 5 case hay bo qua im lang 5 case lo y het.
#
# Dem duoc vi moi bo test trong he nay in MOT DONG cho MOI khang dinh. Chinh ta co 4 kieu
# (do 16/08/2026 tren toan vault): `[PASS] x` · `PASS x` (kieu .graph3d) · `  PASS  x` ·
# `PASS · x`. Regex nhan ca 4 va CO Y doi ky tu phan cach ngay sau nhan — `PASSED`, `PASS*`
# (nhan cua chinh runner) hay `TONG KET: ALL PASS` khong duoc tinh.
KHANG_DINH_RE = re.compile(r"(?m)^[ \t]*(?:\[(?:PASS|FAIL)\]|PASS|FAIL)(?=[ \t·:])")
# Kieu thu 5: bo dung `assert` tran roi in MOT dong gop `PASS 10/10 · <ten>`. Dem dong thi
# chung mai bang 1 — xoa 9 kich ban van ra 1. Lay VE TRAI (so da chay qua), khong lay mau
# so: mau so la hang chep tay, xoa kich ban no khong nhuc nhich. That chat de khong cuop
# nham ten case bat dau bang `3/4`: chi nhan nhan TRAN va phai het dong hoac sang dau `·`.
GOP_RE = re.compile(r"(?m)^[ \t]*(?:PASS|FAIL)[ \t]+(\d+)[ \t]*/[ \t]*\d+(?=[ \t]*(?:·|$))")


def moc_path():
    """Moc vung phu per-MAY, NGOAI repo. `.graph3d` duoc publish ra repo public — de moc
    trong do la day mot file rac vao moi clone, va OneDrive lai them mot cho de conflict.
    Mat cache chi ton dung mot lan chay khong so sanh duoc, khong bao gio sai ket qua."""
    p = os.environ.get("GRAPH3D_SELFCHECK_STATE")
    if p:
        return p
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
            or os.path.join(os.path.expanduser("~"), ".cache"))
    host = socket.gethostname().split(".")[0] or "unknown"
    # Ten thu muc CO Y khong mang ten repo private: cua gac denylist cua buoc publish
    # quet ca file nay, va ban dau dat theo ten repo da bi chan dung 16/08/2026.
    return os.path.join(base, "graph3d-vung-phu", "moc-%s.json" % host)


def moc_key(slow):
    """Moc phai tach theo (thu muc .graph3d, che do chay). Ban private va ban public clone
    tren CUNG mot may co so bo/so file khac nhau, con --slow them han mot bo — gop chung
    mot moc la tu che ra bao dong gia moi lan doi che do."""
    return "%s|%s" % (os.path.normcase(os.path.abspath(G3D)), "slow" if slow else "nhanh")


def doc_moc():
    try:
        with open(moc_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ghi_moc(data):
    try:
        p = moc_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp-%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        pass                                         # cache hong khong duoc lam chet gate


def dem_khang_dinh(res):
    """So khang dinh bo test VUA CHAY THAT — dem tu output, khong hoi no (W239)."""
    out = res.get("output") or ""
    gop = [int(n) for n in GOP_RE.findall(out)]
    # Dong gop da duoc dem la 1 o luot tren; tra lai cai 1 do roi cong so no tu khai.
    return len(KHANG_DINH_RE.findall(out)) - len(gop) + sum(gop)


def so_vung_phu(cu, moi, con_tren_dia):
    """So so khang dinh voi moc xanh truoc. Tra (tut, bien_mat).

    · tut      — muc con do nhung chay it khang dinh hon: bo qua im lang, hoac xoa case.
    · bien mat — ca BO khong con tren dia. Xoa mot file test cung la vung phu tut, ma loi
      W222 con mu hon: khong co bo thi khong co output, khong output thi khong co gi de soi.
      Chi tinh muc tung do duoc (>0), de bo von im lang dung keu luc bi don.

    Co y KHONG co nguong dung sai: dung sai chinh la cho de lot vai case mot luot, va vai
    case mot luot la cach vung phu that su tut trong doi thuc."""
    tut = [(t, cu[t], moi[t]) for t in sorted(moi)
           if isinstance(cu.get(t), int) and moi[t] < cu[t]]
    bien_mat = sorted(t for t, n in cu.items()
                      if isinstance(n, int) and n > 0 and t not in con_tren_dia)
    return tut, bien_mat
# Ten import KHAC ten goi pip — cho duy nhat khong suy ra duoc, nen phai chep.
TEN_GOI_PIP = {"yaml": "PyYAML", "PIL": "pillow", "docx": "python-docx"}


def bo_qua(res):
    """Nhung muc bo test TU KHAI la chua do duoc. Rong = do tron."""
    return [s.strip() for s in SKIP_RE.findall(res.get("output") or "")]


def thieu_module(res):
    """Interpreter dang chay THIEU THU VIEN = PHEP DO hong, KHONG phai code hong (W218).
    Tra ten module thieu; "" = khong dinh loi nay.

    Bat CA hai chieu, vi thieu thu vien hien ra theo hai kieu nguoc nhau:
      · do  — bo test no ModuleNotFoundError ngay luc import;
      · XANH GIA — bo test bat ImportError roi [SKIP] va exit 0 (W220)."""
    if not res.get("ok"):
        m = THIEU_RE.search(res.get("output") or "")
        if m:
            return m.group(1).split(".")[0]
    for ly_do in bo_qua(res):
        m = THIEU_RE.search(ly_do)
        if m:
            return m.group(1).split(".")[0]
    return ""


def phan_loai(res):
    """Nhan mot bo test. Bon loai, KHONG duoc nhap nhem vao nhau:
    PASS (do tron, xanh) · PASS* (xanh nhung co muc chua do) · THIEU-LIB (phep do hong,
    CHAN) · FAIL (code hong that, CHAN)."""
    if thieu_module(res):
        return "THIEU-LIB"
    if not res.get("ok"):
        return "FAIL"
    return "PASS*" if bo_qua(res) else "PASS"


def lenh_cai(mods):
    """Lenh va dung interpreter DANG chay test — khong phai `python` nao khac tren may."""
    goi = sorted({TEN_GOI_PIP.get(m, m) for m in mods if m})
    return '"%s" -m pip install %s' % (sys.executable, " ".join(goi))


def py_main():
    """[(ten, path)] cac file .py goc CO MAT. File trong PRIVATE_ONLY vang mat thi
    bo qua (ban public khong co); file khac vang mat -> FAIL ngay."""
    out = []
    for name in PY_MAIN:
        p = os.path.join(G3D, name)
        if os.path.isfile(p):
            out.append((name, p))
        elif name not in PRIVATE_ONLY:
            check("0 thieu file goc " + name, False, p)
    return out


# ---- Lop 1: compile ----
def lop1_compile():
    py_files = py_main()
    py_files += [("tests/" + os.path.basename(p), p)
                 for p in sorted(glob.glob(os.path.join(TESTS, "*.py")))]
    for name, p in py_files:
        try:
            compile(read(p), p, "exec")
            ok, info = True, ""
        except SyntaxError as e:
            ok, info = False, e
        check("1 compile " + name, ok, info)
    # Giai doan 0 Vault Cockpit: UI tach ES modules — kiem cung logic _restart_sources_sane
    srcs = src_files()
    check("1 src/ co main.js + style.css",
          any(p.endswith("main.js") for p in srcs) and any(p.endswith("style.css") for p in srcs),
          [os.path.basename(p) for p in srcs])
    bad = []
    for p in srcs:
        with open(p, "rb") as f:
            raw = f.read()
        if not raw or not raw.endswith(b"\n") or b"\r\n" in raw:
            bad.append(os.path.basename(p))
    check("1 src/* khong rong + LF + ket thuc \\n", not bad, bad)
    check("1 index.html tro /src/main.js", 'src="/src/main.js"' in read(INDEX))


# ---- Lop 2: contract grep ----
def lop2_contract():
    # 2a — bug P0.1: bat set GRAPH3D_ACTIVITY_FILE -> vo hieu va MSIX (server khong thay log Cowork)
    bat = read(os.path.join(G3D, "Start-Graph3D.bat"))
    bad = [l.strip() for l in bat.splitlines()
           if re.match(r'\s*set\s+"?GRAPH3D_ACTIVITY_FILE', l, re.I)]
    check("2a bat KHONG set GRAPH3D_ACTIVITY_FILE", not bad, bad)

    # 2b — bug P0.6: matcher hook thieu tool -> event khong duoc ghi
    os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_selfcheck.jsonl"))
    sys.path.insert(0, G3D)
    tools = None
    try:
        import log_activity as LA
        tools = set(LA.TYPE_BY_TOOL)
    except Exception as e:
        check("2b import log_activity de doc TYPE_BY_TOOL", False, e)
    hook_cfg = os.path.join(VAULT, ".claude", "settings.json")
    if tools is not None and not os.path.isfile(hook_cfg):
        # Ban public (clone ra ngoai vault) khong co hook settings — kiem nay vo nghia
        # o do; bo qua co bao, KHONG FAIL (bug that trong vault van bi bat nhu cu).
        skip("2b matcher hook — khong tim thay " + hook_cfg + " (khong chay trong vault)")
        tools = None
    if tools is not None:
        cfg = json.loads(read(hook_cfg))
        matched = set()
        for ent in cfg.get("hooks", {}).get("PostToolUse", []):
            cmds = " ".join(h.get("command", "") for h in ent.get("hooks", []))
            if "log_activity" in cmds:
                matched |= set((ent.get("matcher") or "").split("|"))
        thieu = sorted(tools - matched)
        check("2b matcher hook bao trum TYPE_BY_TOOL", not thieu, thieu)

    # 2c — P0.5 nhan chung 'Claude' (literal 'Claude Code' tach mot agent thanh 2 danh tinh).
    # Tu giai doan 0: UI = index.html + src/* — quet ca bo, keo bug lach qua module.
    ui = ui_sources()
    cc = [n for n, txt in ui if "Claude Code" in txt]
    check("2c UI (index+src) khong con literal 'Claude Code'", not cc, cc)

    sv = read(os.path.join(G3D, "serve.py"))

    # 2f — P4.1: parse_jsonl MOT ban duy nhat (3 ban tung phan ky)
    defs = {n: read(p).count("def parse_jsonl") for n, p in py_main()}
    check("2f def parse_jsonl duy nhat, nam trong activity_paths.py",
          defs["activity_paths.py"] == 1 and sum(defs.values()) == 1, defs)

    # 2g — P4.5: khong file app nao hardcode hash package MSIX (glob Claude_* bat package
    # bat ky do test_p4 t4b gac bang hanh vi).
    hard = [n for n, p in py_main() if "Claude_pzs8sxrjxfjjc" in read(p)]
    check("2g khong file app nao hardcode Claude_pzs8sxrjxfjjc", not hard, hard)

    # 2i — bai hoc da-stream 10/07: badge version duy nhat, version moi = badge hien hanh + 1.
    # Quet ca src/* de khong ai nhet version string thu 2 vao module.
    badges = [b for _, txt in ui for b in re.findall(r"\bv\d+\.\d+\.\d+\b", txt)]
    check("2i badge version xuat hien dung 1 lan (index+src)", len(badges) == 1, badges)

    # 2j — bug doi 7 repo public: whitelist publish (TOP_FILES) liet ke CUNG tung file .py
    # nen them insight.py la SOT, va sot thi im lang (publish bao OK, file moi khong len).
    # Cung lop voi try_demo.py sot insight/integrity -> demo chet luc serve import.
    # Tu W13 chi con MOT danh sach: activity_paths.APP_PY. Contract nay bat quen khai.
    # Huong kiem: moi file CO MAT phai duoc khai (do la bug can bat). Chieu nguoc lai —
    # file da khai ma vang mat — do py_main() lo san ("0 thieu file goc"), va PRIVATE_ONLY
    # duoc mien o day de ban public khong FAIL oan.
    if AP is None:
        check("2j nap duoc activity_paths de doc APP_PY", False, "import that bai")
    else:
        found = {os.path.basename(p) for p in glob.glob(os.path.join(G3D, "*.py"))} - REPO_ONLY
        undeclared = sorted(found - (set(AP.APP_PY) | PRIVATE_ONLY))
        check("2j moi .py goc duoc khai trong APP_PY", not undeclared, undeclared)

    # 2k — bug doi 8: integrity.py khong nam _VERSION_FILES -> sua module xong server
    # VAN phuc vu ban cu, lang thinh (source_version khong hash file do). Luat: moi
    # module local serve.py import luc nap phai co trong _VERSION_FILES (tru RELOADABLE).
    if AP is not None:
        mods = set(re.findall(r"(?m)^(?:import|from)\s+(\w+)", sv))
        local = {m + ".py" for m in mods if os.path.isfile(os.path.join(G3D, m + ".py"))}
        thieu = sorted(local - set(AP._VERSION_FILES) - RELOADABLE)
        check("2k module serve.py import deu nam trong _VERSION_FILES", not thieu, thieu)

    # 2l — W186: private/public selfcheck --slow tung tranh port 8397 khi chay
    # dong thoi. Test P2 phai giu mot listener bind port 0 xuyen suot phep thu; cach
    # "tim port rong roi dong socket" van co khoang dua truoc khi process con bind.
    p2 = read(os.path.join(TESTS, "test_p2.py"))
    fixed = re.findall(r"(?m)^\s*PORT\s*=\s*(\d+)\s*$", p2)
    ephemeral = re.search(r"\.bind\(\(\s*[\"']127\.0\.0\.1[\"']\s*,\s*0\s*\)\)", p2)
    check("2l test_p2 giu listener port 0, khong hardcode port", not fixed and bool(ephemeral), fixed)

    # 2m — W222: quy uoc khai bao "chua do duoc". Marker phai la `[SKIP] ` co ngoac vuong
    # o dau dong; chu SKIP tran (kieu cu cua .graph3d) khong ai dem duoc, va do la dung
    # cach 5 muc trong tests/ da tang hinh suot tu 2026-07 toi 14/08/2026.
    tran = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(TESTS, "*.py")))
            if SKIP_TRAN_RE.search(read(p))]
    check("2m tests/ khai bo qua bang '[SKIP] ', khong dung SKIP tran", not tran, tran)

    # 2n — cung lop bug voi 2j/2k: lop3_unit chay theo danh sach CHEP TAY, nen mot bo
    # test moi them vao tests/ ma quen khai o day thi KHONG BAO GIO chay — va im lang.
    tren_dia = {os.path.basename(p) for p in glob.glob(os.path.join(TESTS, "test_*.py"))}
    thieu_khai = sorted(tren_dia - set(UNIT_FILES) - set(SLOW_FILES))
    thua_khai = sorted((set(UNIT_FILES) | set(SLOW_FILES)) - tren_dia)
    check("2n moi tests/test_*.py deu duoc lop 3 chay", not thieu_khai and not thua_khai,
          {"chua khai": thieu_khai, "khai ma khong co file": thua_khai})

    # 2o — W239: phep do vung phu chi voi toi bo test co IN nhan PASS/FAIL cho tung khang
    # dinh. Mot bo cham diem im lang (chi `assert` roi exit 0, khong in gi) thi so khang
    # dinh cua no mai bang 0: no khong tut duoc vi chua tung co gi de tut, va the la lot
    # ra ngoai dung cai luoi vua cang. Chan tu luc them file, dung doi den luc no cam.
    cam = []
    for p in sorted(glob.glob(os.path.join(TESTS, "test_*.py"))):
        if not re.search(r"""["']\[?(?:PASS|FAIL)""", read(p)):
            cam.append(os.path.basename(p))
    check("2o moi bo test in nhan PASS/FAIL de dem duoc vung phu", not cam, cam)


# ---- Lop 3: unit ----
def chay_bo(name, path):
    """Chay MOT bo test trong process con dung nhu lop 3 lam that; tra dict ma
    phan_loai/bo_qua/dem_khang_dinh doc. test_selfcheck goi CHINH ham nay (khong chep
    lai loi goi) — doi mot chu o day la phep do encoding cua no doi theo (W426).

    Process con tren Windows ghi stdout theo locale (cp1252), con o day lai giai ma
    UTF-8 — moi em-dash trong output test bien thanh U+FFFD. Nen ep con noi dung mot
    thu tieng voi cha thay vi doan chu o dau kia. (env dung luc chay, KHONG chup tu
    luc nap module: 2b co setdefault GRAPH3D_ACTIVITY_FILE ma con phai thua ke.)"""
    r = subprocess.run([sys.executable, path],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, cwd=TESTS,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return {"test": name, "ok": r.returncode == 0, "output": r.stdout + r.stderr}


def lop3_unit(slow):
    files = list(UNIT_FILES) + (list(SLOW_FILES) if slow else [])
    jobs = [(name, os.path.join(TESTS, name)) for name in files]
    private_backup_test = os.path.join(G3D, "test_backup.py")
    if os.path.isfile(private_backup_test):
        jobs.append(("test_backup.py (private)", private_backup_test))
    for name, path in jobs:
        t0 = time.perf_counter()
        res = chay_bo(name, path)
        dt = time.perf_counter() - t0
        # W222: returncode 0 KHONG con dong nghia voi "da do". Phan loai 4 nhan roi moi
        # ket luan — THIEU-LIB chan nhu FAIL (chua do duoc), PASS* thi hien ra nhung
        # khong chan (thieu `node` / khong phai Windows thi sua code cung khong het).
        nhan, muc = phan_loai(res), "3 %s (%.1fs)" % (name, dt)
        # W239: dem khang dinh bo nay VUA CHAY THAT. In ra ngay de nguoi doc thay vung phu
        # truoc khi may keu, va ghi lai de luot sau con cai ma so.
        khang_dinh[name] = dem_khang_dinh(res)
        print("%s %s  %d khang dinh" % (nhan, muc, khang_dinh[name]))
        for ly_do in bo_qua(res):
            print(an_toan("      ~ bo qua: " + ly_do))
            skips.append(name + ": " + ly_do)
        # Ca hai deu CHAN, nhung KHONG duoc gop ten: "FAIL" bao nguoi sau di sua code,
        # con THIEU-LIB thi code dang lanh, phai va interpreter (W218).
        if nhan == "THIEU-LIB":
            thieu_lib[name] = thieu_module(res)
        elif nhan == "FAIL":
            fails.append(muc)
        if nhan in ("FAIL", "THIEU-LIB"):
            for l in res["output"].strip().splitlines()[-12:]:
                print(an_toan("      | " + l))
    if not slow:
        # Bo cham khong chay = mot muc KHONG DO DUOC that su, nen no phai di vao dung
        # cai so dem do — chu khong nam mot minh o dong ghi chu cuoi nhu truoc W222.
        skip("test_p2 (kill/port policy, ~15s) — them --slow de do that")


def tong_ket(fails, thieu_lib, skips, n_khang_dinh, n_tut, chan_vung_phu):
    """(dong TONG KET, ma thoat) — HAM THUAN de test bang bang case thay vi grep
    nguyen van __main__ (W426; W239 tung do oan E3 khi doi dieu kien thoat).

    FAIL va THIEU-LIB deu CHAN nhung KHONG gop ten (W218: FAIL = di sua code, THIEU-LIB
    = va interpreter). Muc tu khai [SKIP] hien o TONG KET nhung KHONG chan (may khong
    co `node` thi sua code cung khong het). Tut vung phu chua chap nhan thi CHAN."""
    phan = []
    if fails:
        phan.append("FAIL %d muc: %s" % (len(fails), ", ".join(fails)))
    if thieu_lib:
        phan.append("CHUA DO DUOC %d bo vi thieu thu vien: %s"
                    % (len(thieu_lib), ", ".join(sorted(thieu_lib))))
    ket = " · ".join(phan) if phan else "ALL PASS"
    if skips:
        ket += " · BO QUA %d muc" % len(skips)
    ket += " · %d khang dinh" % n_khang_dinh
    if n_tut:
        ket += " · TUT VUNG PHU %d muc" % n_tut
    return ket, (1 if (fails or thieu_lib or chan_vung_phu) else 0)


if __name__ == "__main__":
    argv = sys.argv[1:]
    slow = "--slow" in argv
    # Ha moc vung phu phai TON mot cau giai thich, neu khong day dung la cai nut "tat
    # tieng" ma W239 dang di bit.
    vi_sao_nhan = ""
    if "--chap-nhan" in argv:
        i = argv.index("--chap-nhan")
        vi_sao_nhan = (argv[i + 1].strip() if i + 1 < len(argv) else "")
        if not vi_sao_nhan or vi_sao_nhan.startswith("--"):
            print("LOI: --chap-nhan phai kem ly do, vi du:\n"
                  '   python selfcheck.py --chap-nhan "gop 3 case trung nhau thanh 1"')
            sys.exit(2)
    t0 = time.perf_counter()
    print("== Lop 1: compile ==")
    lop1_compile()
    print("== Lop 2: contract ==")
    lop2_contract()
    print("== Lop 3: unit ==")
    lop3_unit(slow)
    dt = time.perf_counter() - t0
    # Lop 1+2 la khang dinh cua CHINH runner (lop 3 dem rieng theo tung bo con).
    khang_dinh["__runner__"] = so_check[0]

    # ---- W239: vung phu tut ----
    # CHI so khi luot nay xanh tron: bo do thuong chet giua chung nen in thieu khang dinh,
    # dem so la bao "tut" trong khi thu pham la cai do da bi chan o cua khac roi.
    xanh_tron = not fails and not thieu_lib
    moc, khoa = doc_moc(), moc_key(slow)
    cu = moc.get(khoa) if isinstance(moc.get(khoa), dict) else {}
    cu_counts = cu.get("counts") if isinstance(cu.get("counts"), dict) else {}
    tren_dia = set(khang_dinh)
    tut, bien_mat = (so_vung_phu(cu_counts, khang_dinh, tren_dia) if xanh_tron else ([], []))
    if xanh_tron and (not (tut or bien_mat) or vi_sao_nhan):
        ghi = dict(moc)
        muc_moi = {"counts": khang_dinh, "khi": time.strftime("%Y-%m-%d %H:%M")}
        if vi_sao_nhan and (tut or bien_mat):
            lich_su = [x for x in (cu.get("chap_nhan") or []) if isinstance(x, dict)]
            lich_su.append({"khi": muc_moi["khi"], "vi_sao": vi_sao_nhan,
                            "tut": [{"test": t, "cu": a, "moi": b} for t, a, b in tut],
                            "bien_mat": list(bien_mat)})
            muc_moi["chap_nhan"] = lich_su[-5:]
        elif cu.get("chap_nhan"):
            muc_moi["chap_nhan"] = cu["chap_nhan"]
        ghi[khoa] = muc_moi
        ghi_moc(ghi)
    chan_vung_phu = bool(tut or bien_mat) and not vi_sao_nhan

    ket, ma_thoat = tong_ket(fails, thieu_lib, skips, sum(khang_dinh.values()),
                             len(tut) + len(bien_mat), chan_vung_phu)
    print("\nTONG KET selfcheck (%.1fs): %s" % (dt, ket))
    if tut or bien_mat:
        print("\n" + "=" * 72)
        if vi_sao_nhan:
            print("VUNG PHU TUT — DA CHAP NHAN: %s" % vi_sao_nhan)
        else:
            print("VUNG PHU TUT (W239) — moi muc deu XANH, nhung do IT HON lan xanh truoc"
                  " (%s):" % (cu.get("khi") or "khong ro luc nao"))
        for ten, a, b in tut:
            print("   - %s: %d -> %d khang dinh (mat %d)" % (ten, a, b, a - b))
        for ten in bien_mat:
            print("   - %s: ca BO khong con chay nua (moc cu %d khang dinh)"
                  % (ten, cu_counts.get(ten, 0)))
        if not vi_sao_nhan:
            print("   Xanh ma do it di = bo qua im lang hoac khang dinh bi xoa. Khong co")
            print("   dong [SKIP] nao de soi, nen con so nay la tin hieu DUY NHAT.")
            print("   Tra vung phu ve, HOAC neu ha la co y thi ha moc CO ghi ly do:")
            print('   python .graph3d/tests/selfcheck.py%s --chap-nhan "…"'
                  % (" --slow" if slow else ""))
        print("=" * 72)
    cam = sorted(t for t, n in khang_dinh.items() if not n)
    if cam:
        print("\n~ %d bo khong phat ra khang dinh nao (vung phu KHONG do duoc): %s"
              % (len(cam), ", ".join(cam)))
    if thieu_lib:
        # W218: goi dung ten thu pham. Gop vao "FAIL" la moi phien sau di sua code dang lanh.
        print("\n" + "=" * 72)
        print("PHEP DO HONG, KHONG PHAI CODE HONG (W218) — %d bo chua do duoc vi thieu"
              " thu vien:" % len(thieu_lib))
        for name, mod in sorted(thieu_lib.items()):
            print("   - %s  <-  thieu `%s`" % (name, mod))
        print("   Interpreter dang chay test: %s" % sys.executable)
        print("   DUNG sua code. Va dung interpreter do:")
        print("   %s" % lenh_cai(thieu_lib.values()))
        print("=" * 72)
    if skips:
        print("\n~ DO THIEU (khong chan): %d muc tu khai bo qua —" % len(skips))
        for s in skips:
            print(an_toan("   - " + s))
        print("  'ALL PASS' o day nghia la phan CON LAI xanh, khong phai da do het.")
    # Tut vung phu CHAN nhu FAIL. Bao ma khong chan thi phien sau chi doc exit code (dung
    # cai bay W222 pass 2 da phai va: tai lieu bao "exit 0 la du") va di tiep — thanh ra
    # lai dung mot kenh im lang nua. Loi ra la `--chap-nhan "…"`, khong phai lam ngo.
    sys.exit(ma_thoat)
