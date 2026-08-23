# -*- coding: utf-8 -*-
"""Test bao co ban moi tren repo (W69) — kiem TINH + kiem HANH VI, khong goi mang that.

Ba dieu tuyet doi khong duoc vo, moi dieu mot may gac:

  1. KHONG goi ra internet khi nguoi dung chua dong y. App hua "chay hoan toan local";
     day la cho dau tien no mo ket noi ra ngoai, nen consent la cua chan cung. Kiem 2
     thay _api bang mot ham NEM ra loi: chua consent ma refresh() van chay tron nghia
     la khong ai goi mang.
  2. KHONG tu cap nhat de len viec cua nguoi dung. pull chi duoc chay khi la clone that,
     co origin, khong detached, tree sach — va chi bang --ff-only.
  3. Semver KHONG duoc chep ra hang so thu hai; no phai derive tu badge index.html
     (contract 2i cua selfcheck gac badge chi xuat hien 1 lan).
"""
import io, os, re, shutil, sys, tempfile
sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _scratch import G3D, SCRATCH

sys.path.insert(0, G3D)
import activity_paths                      # noqa: E402
import update_check as U                   # noqa: E402

SRC = os.path.join(G3D, "src")
fails = []


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


serve = read(os.path.join(G3D, "serve.py"))
main_js = read(os.path.join(SRC, "main.js"))
upd_js = read(os.path.join(SRC, "update.js"))
html = read(os.path.join(G3D, "index.html"))
i18n = read(os.path.join(SRC, "i18n.js"))
mod = read(os.path.join(G3D, "update_check.py"))

# --- 1: khai bao vao danh sach file app (2j) va danh sach can-restart (2k) ---
check("1 update_check.py nam trong APP_PY", "update_check.py" in activity_paths.APP_PY)
check("1 update_check.py nam trong _VERSION_FILES (serve.py import luc nap)",
      "update_check.py" in activity_paths._VERSION_FILES)

# --- 2: CHUA dong y => TUYET DOI khong goi mang ---
_tmp = os.path.join(SCRATCH, "update-state")
if os.path.isdir(_tmp):
    shutil.rmtree(_tmp)
os.makedirs(_tmp)
os.environ["LOCALAPPDATA"] = _tmp                 # state file ra thu muc tam


def _boom(*a, **k):
    raise AssertionError("da goi ra internet khi CHUA duoc dong y")


_real_api = U._api
U._api = _boom
try:
    U.save_state({})                              # khong co consent
    U.refresh(force=True)
    ok_no_net = True
except AssertionError:
    ok_no_net = False
check("2 chua dong y thi KHONG goi ra internet", ok_no_net)

# ...va da dong y thi moi goi (cung ham gia, lan nay ky vong CO goi)
U.save_state({"consent": True})
called = {"n": 0}


def _count(path):
    called["n"] += 1
    return None, "offline", 0                     # gia lam mat mang


U._api = _count
U.refresh(force=True)
check("2 da dong y thi co di hoi", called["n"] >= 1, called["n"])

# --- 3: loi mang KHONG duoc lam hong state cu ---
U.save_state({"consent": True, "behind": 3, "latest": "v9.9.9",
              "versions": [{"tag": "v9.9.9", "summary": "x"}]})
U._api = lambda p: (None, "offline", 0)
st = U.refresh(force=True)
check("3 mat mang van giu ket qua cu", st.get("behind") == 3 and st.get("latest") == "v9.9.9", st)
check("3 mat mang co ghi lai ly do", st.get("error") == "offline", st.get("error"))

# --- 4: rate limit => ton trong X-RateLimit-Reset, khong thu lai mu ---
U.save_state({"consent": True})
U._api = lambda p: (None, "rate_limit", 4102444800)      # reset o tuong lai xa
U.refresh(force=True)
st = U.load_state()
check("4 bi rate limit thi hen gio thu lai", float(st.get("retry_after") or 0) > 0, st.get("retry_after"))
hit = {"n": 0}


def _should_not_run(path):
    hit["n"] += 1
    return None, "offline", 0


U._api = _should_not_run
U.refresh()                                        # KHONG force: phai bi chan boi retry_after
check("4 chua toi gio hen thi khong goi lai", hit["n"] == 0, hit["n"])
U._api = _real_api

# --- 5: dem so ban thieu, bo qua tag khong phai semver ---
tags = [{"name": n, "commit": {"sha": n}} for n in
        ("v1.50.0", "v1.49.0", "v1.48.2", "nightly", "v1.9.0", "khong-phai-tag")]
check("5 dem dung so ban moi hon", len(U._newer_tags(tags, "v1.48.2")) == 2,
      [t for t, _ in U._newer_tags(tags, "v1.48.2")])
check("5 sap xep moi nhat truoc", U._newer_tags(tags, "v1.48.2")[0][0] == "v1.50.0")
check("5 bo qua tag khong phai semver", all(U.parse_semver(t) for t, _ in U._newer_tags(tags, "v1.0.0")))
check("5 so sanh theo SO chu khong theo chu cai",
      len(U._newer_tags([{"name": "v1.9.0", "commit": {"sha": "x"}}], "v1.10.0")) == 0)

# --- 6: semver derive tu badge, KHONG co hang so thu hai ---
check("6 app_version doc duoc tu index.html", bool(activity_paths.app_version(G3D)))
check("6 update_check.py KHONG chua hang so version",
      not re.search(r"=\s*[\"']v\d+\.\d+\.\d+[\"']", mod))

# --- 7: pull chi khi AN TOAN, va chi --ff-only ---
check("7 pull dung --ff-only (khong merge/rebase)", '"--ff-only"' in mod)
# Kiem DUNG cac lenh git duoc dung, khong san chuoi: ban dau kiem "reset" not in mod
# thi do ngay, vi chu do nam trong X-RateLimit-Reset — duong tinh gia cua chinh may gac.
_git_calls = re.findall(r'\[\s*"git"\s*,(.*?)\]', mod, re.S) + re.findall(r'_git\(\s*\[(.*?)\]', mod, re.S)
_danger = [g.strip() for g in _git_calls
           if re.search(r'"(reset|clean|checkout|push|fetch\s*--force)"|--hard|--force', g)]
check("7 khong lenh git nao pha huy (reset/clean/checkout/--hard)", not _danger, _danger)
check("7 co doc duoc lenh git de kiem (may gac khong rong)", len(_git_calls) >= 3, len(_git_calls))

# --- 7b: MOI lan spawn phai giau cua so console ---
# Server chay bang pythonw (khong console) nen spawn mot chuong trinh console ma thieu
# CREATE_NO_WINDOW la Windows cap cho no mot cua so moi -> nguoi dung thay khung den
# nhap nhay roi tat, cam giac "app nay co gi do khong on". Anh Chuong bao dung trieu
# chung do ngay 29/07: status() goi 5 lenh git moi request nen no loe may lan lien.
# Phai soi TUNG CHO GOI, khong duoc dem chuoi toan file: ban dau kiem
# mod.count("no_window_kwargs()") >= so_spawn thi go that mot cho van ALL PASS, vi
# chinh docstring cua _git co nhac ten ham do nen dem bu vao. Day la lan thu BA trong
# ngay mot may gac cua minh do sai — dung lan nao cung la "dem chuoi thay vi soi cau
# truc". Nay cat dung than lenh goi roi moi kiem.
_spans = []
for _m in re.finditer(r"subprocess\.(?:run|Popen)\(", mod):
    _tail = mod[_m.end():]
    _stop = _tail.find("\n    except")
    _spans.append(_tail[:_stop if _stop > 0 else 400])
check("7b co spawn tien trinh trong module (may gac khong rong)", len(_spans) >= 2, len(_spans))
_naked = [s.strip()[:60] for s in _spans if "no_window_kwargs()" not in s]
check("7b moi cho spawn deu truyen no_window_kwargs()", not _naked, _naked)
_tmp_prefix = "kb-test-update-"
with tempfile.TemporaryDirectory(prefix=_tmp_prefix, dir=SCRATCH) as _precheck_tmp:
    check("7 thu muc tam precheck co prefix", os.path.basename(_precheck_tmp).startswith(_tmp_prefix), _precheck_tmp)
    ok, why = U.pull_precheck(_precheck_tmp)       # thu muc trong: khong phai repo
    check("7 thu muc khong phai repo thi tu choi", ok is False and why == "not_a_repo", (ok, why))
check("7 thu muc tam precheck duoc don", not os.path.exists(_precheck_tmp), _precheck_tmp)

with tempfile.TemporaryDirectory(prefix=_tmp_prefix, dir=SCRATCH) as _pull_tmp:
    check("7 thu muc tam pull co prefix", os.path.basename(_pull_tmp).startswith(_tmp_prefix), _pull_tmp)
    res = U.pull(_pull_tmp)
    check("7 pull() tu choi truoc khi chay git", res.get("ok") is False, res)
check("7 thu muc tam pull duoc don", not os.path.exists(_pull_tmp), _pull_tmp)

# --- 8: khong tu reload sau khi cap nhat (khong cuop tab dang doc) ---
check("8 update.js khong tu goi location.reload()", "location.reload()" not in upd_js)

# --- 8b: 2 cua ghi PHAI goi bang POST ---
# Ban dau consent goi bang GET: dai hoi an di, nguoi dung tuong da tra loi xong, ma
# server khong ghi nhan gi ca — lan sau mo lai van hoi. Khong may gac tinh nao bat
# duoc, chi bam that moi lo ra. Nay chot lai bang kiem.
def _call_stmt(js, route):
    """Cat tu cho goi `route` toi dau cham phay ket cau. KHONG dung [^)]* — doi so co
    the chua dau ngoac (toan tu ba ngoi), cat theo ) dau tien la cat cut mat method:
    POST roi bao do oan. Chinh may gac nay da tung do vi ly do do."""
    i = js.find("fetch('" + route)
    return js[i:js.find(";", i)] if i >= 0 else ""


for _route in ("/update-consent", "/update-pull"):
    _stmt = _call_stmt(upd_js, _route)
    check("8b goi %s bang POST" % _route, "method: 'POST'" in _stmt, _stmt[:120])

# --- 9: server co du 3 cua, va GET khong tu hoi mang ---
for p in ('path == "/update"', 'path == "/update-consent"', 'path == "/update-pull"'):
    check("9 serve.py co route %s" % p.split('"')[1], p in serve)
check("9 GET /update chi hoi mang khi co ?refresh=1", 'qs.get("refresh"' in serve)

# --- 10: TTL khong duoc ha xuong duoi 1 ngay (quota 60 req/gio theo IP) ---
check("10 TTL >= 1 ngay", U.TTL >= 24 * 3600, U.TTL)

# --- 10b: PHAI co duong DOI Y luon co mat ---
# Ban v1.50.x hoi dong y dung mot lan roi khoa cung lua chon: bat roi khong tat duoc, lo
# bam Khong thi vinh vien khong bat lai. Badge KHONG thay duoc vai nay vi no chi hien khi
# dang thieu ban. Nen so version phai bam duoc, va panel phai co nut doi y.
check("10b so version bam duoc (id=app-ver)", 'id="app-ver"' in html)
check("10b app-ver mo panel update", "'app-ver'" in upd_js)
check("10b panel co nut doi y consent", 'id="upd-consent"' in html and "toggleConsent" in upd_js)
check("10b nhan nut la HANH DONG (2 chieu bat/tat)",
      "'upd.consent.on'" in i18n and "'upd.consent.off'" in i18n)
check("10b tat kiem tra thi panel noi ro khong goi internet", "'upd.disabled'" in i18n)

# --- 11: badge nam CUNG DONG voi so version (bai hoc W43/W65) ---
m = re.search(r'<div class="sub">(.*?)</div>', html, re.S)
check("11 badge update nam trong div.sub", bool(m) and 'id="update-badge"' in m.group(1))

# --- 12: 3 khoi khoa i18n co ca vi lan en ---
parts = i18n.split("\n  en: {")
vi_b, en_b = parts[0], (parts[1] if len(parts) > 1 else "")
for k in ("upd.ask", "upd.behind", "upd.sum", "upd.pull", "upd.cant.no_remote", "upd.cant.dirty"):
    check("12 khoa %s co ca vi lan en" % k, ("'%s'" % k) in vi_b and ("'%s'" % k) in en_b)

# --- 13: main.js that su noi module vao ---
check("13 main.js goi initUpdate()", "initUpdate();" in main_js)
check("13 main.js goi pollUpdate luc boot", "pollUpdate(true)" in main_js)
fx = re.search(r"window\.__fx\s*=\s*\{(.*?)\};", main_js, re.S)
check("13 openUpdate/pollUpdate co trong __fx (nghiem thu tab an)",
      bool(fx) and "openUpdate" in fx.group(1) and "pollUpdate" in fx.group(1))

print("\nTONG KET test_update: %s" % (("FAIL %d: %s" % (len(fails), ", ".join(fails))) if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
