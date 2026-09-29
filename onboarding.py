# -*- coding: utf-8 -*-
"""KB Graph 3D — onboarding cho vault TRỐNG (W13 / backlog #16).

Vấn đề (nhận xét 19/07/2026): app đòi "có sẵn vault" nên user mới tải về
mở ra thấy KHÔNG GÌ CẢ rồi bỏ đi. Tầng repo đã xong đợt 5 (`starter-vault/` +
`demo/vault/` + README/landing); đây là tầng CODE — thang 3 bậc "cảm nhận → khởi
tạo → thói quen" đưa thẳng vào app:

  1. CẢM NHẬN  `ensure_graph3d.py --demo` → mirror app sang `demo/vault/.graph3d`
               rồi mở cockpit trên vault demo bundled (PORT RIÊNG — không đụng
               server thật đang chạy trên vault của user)
  2. KHỞI TẠO  `install_starter()` → chép `starter-vault/` vào chính vault đang
               trống; user có 9 note thật để đọc/sửa/link, không phải vault mẫu
               ở đâu đó
  3. THÓI QUEN hướng dẫn hiện ngay trong UI (vault chỉ là folder `.md`; Obsidian
               là editor TUỲ CHỌN, không phải điều kiện)

Khuôn giống `insight.py` / `integrity.py`: MỌI logic nằm ở module này, `serve.py`
chỉ route, `src/onboarding.js` chỉ trình bày. **Không có bộ đếm note thứ hai** —
số note luôn do `build_graph_data.build()` trả (đúng scanner của graph, đúng luật
loại trừ dot-folder); caller nào đã có sẵn số thì truyền vào để khỏi quét lại.

`starter-vault/` và `demo/vault/` là tài sản của REPO PUBLIC, không nằm trong bản
private (vault thật không bao giờ trống nên cũng không dùng tới). Thiếu chúng thì
`state()` báo `available: false` và UI ẩn đúng lựa chọn đó — KHÔNG đoán, không tự
sinh nội dung mẫu. Test trỏ nguồn khác bằng `GRAPH3D_STARTER_DIR` /
`GRAPH3D_DEMO_DIR` (mirror pattern `GRAPH3D_JOURNAL_DIR`).

Từ v1.59.0, app runtime không bắt buộc nằm trong active vault: khi user đã chọn
vault ngoài bằng Vault Switcher, `state()` coi lựa chọn đó là cài đặt hợp lệ và
không hiện cảnh báo W42 "app cài sai chỗ".

Chạy tay:
  python .graph3d/ensure_graph3d.py --demo              # xem demo 120 note
  python .graph3d/ensure_graph3d.py --init-starter DIR  # dựng vault đầu tiên tại DIR

Hồ sơ đợt: note vault "Onboarding Vault Trống — KB Graph 3D".
"""
import json
import os
import shutil
import time
import urllib.error
import urllib.request

import activity_paths
import build_graph_data

HERE = os.path.dirname(os.path.abspath(__file__))

# Cổng riêng cho demo: server thật của user giữ 8321, demo KHÔNG được cướp port đó.
# (Bản sao app trong demo/vault/.graph3d có nội dung y hệt ⇒ source_version TRÙNG ⇒
# ensure sẽ "dùng lại server có sẵn" và user tưởng đang xem demo trong khi vẫn là
# vault thật. Port khác là thứ duy nhất tách được hai server.)
DEMO_PORT = 8322


class OnboardingError(Exception):
    """Lỗi người dùng sửa được (thiếu nguồn, vault không trống…) — caller in nguyên văn.

    `code` để UI DỊCH được sang ngôn ngữ đang chọn (W43): thông điệp tiếng Việt trong
    ngoặc vẫn là bản gốc cho CLI và cho trường hợp UI chưa có khoá tương ứng."""

    def __init__(self, msg, code=""):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- nguồn bundled
def starter_dir():
    """Thư mục `starter-vault/` (9 note dạy khái niệm BẰNG chính app)."""
    env = os.environ.get("GRAPH3D_STARTER_DIR", "").strip()
    return os.path.normpath(env) if env else os.path.join(HERE, "starter-vault")


def demo_vault_dir():
    """Vault demo 120 note bundled — `demo/vault/` cạnh app trong bản clone public."""
    env = os.environ.get("GRAPH3D_DEMO_DIR", "").strip()
    return os.path.normpath(env) if env else os.path.join(HERE, "demo", "vault")


def count_notes(path):
    """Số note .md — DÙNG CHUNG scanner của graph (build_graph_data), không tự walk:
    một bộ luật loại trừ duy nhất cho cả graph lẫn onboarding."""
    if not os.path.isdir(path):
        return 0
    try:
        return build_graph_data.build(path)["meta"]["notes"]
    except OSError:
        return 0


_bundled_cache = {}


def count_bundled(path):
    """Như count_notes nhưng CACHE theo mtime thư mục — dùng cho starter-vault/ và
    demo/vault/ (nội dung tĩnh, đóng gói sẵn). Lý do: từ W42 `/onboarding` còn được
    gọi khi vault KHÔNG trống (để bắt ca cài sai chỗ), mà quét lại 120 note demo mỗi
    lần boot thì đắt vô ích."""
    try:
        key = os.path.getmtime(path)
    except OSError:
        return 0
    hit = _bundled_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    n = count_notes(path)
    _bundled_cache[path] = (key, n)
    return n


def installed_in_vault(app_dir=None):
    """App có đang nằm TRONG vault dưới tên `.graph3d` hay không.

    Đây là tín hiệu bắt ca cài sai chỗ phổ biến nhất (audit 26/07/2026): user clone
    repo bình thường rồi chạy `ensure_graph3d.py` ngay trong đó — vì "vault = thư mục
    CHA của app", server đi quét cả thư mục chứa repo (đo thật: 141 note của các repo
    khác) và empty-state cũ KHÔNG bắn vì vault "không trống". README chỉ có một cách
    cài đúng — clone THÀNH `.graph3d` trong vault — nên tên thư mục là tín hiệu thẳng
    thắn và rẻ nhất. Cảnh báo phải cho tắt vĩnh viễn (ai cố tình đổi tên thư mục vẫn
    là chuyện của họ), xem cờ localStorage phía UI."""
    return os.path.basename(os.path.abspath(app_dir or HERE)) == ".graph3d"


# Note "cửa vào" của starter vault, theo thứ tự ưu tiên (so trên stem đã casefold).
# Cài xong mà không mở gì thì người mới không biết bước kế là đọc note nào (audit W42).
ENTRY_PREF = ("start here", "bắt đầu", "index", "readme")


def entry_note(created):
    """Note nên mở ngay sau khi dựng starter vault: khớp ENTRY_PREF trước, không có
    thì lấy note .md nằm nông nhất (đường dẫn ngắn nhất) — luôn trả về gì đó nếu có
    ít nhất một note, để UI khỏi phải tự đoán."""
    notes = [r for r in created if r.lower().endswith(".md")]
    if not notes:
        return None
    for pref in ENTRY_PREF:
        for rel in notes:
            stem = os.path.splitext(os.path.basename(rel))[0].casefold()
            if stem.startswith(pref):
                return rel
    return min(notes, key=lambda r: (r.count("/"), len(r)))


# ---------------------------------------------------------------- trạng thái
def state(vault, notes=None):
    """Dữ liệu cho UI empty-state: vault có trống không, và những lối đi nào SẴN CÓ
    trên máy này. `notes` truyền vào khi caller đã quét (serve có cache 3s)."""
    vault = os.path.abspath(vault)
    if notes is None:
        notes = count_notes(vault)
    sd, dd = starter_dir(), demo_vault_dir()
    s_notes, d_notes = count_bundled(sd), count_bundled(dd)
    app = os.path.abspath(HERE)
    app_parent = os.path.dirname(app)
    selected_elsewhere = (os.path.normcase(os.path.realpath(vault)) !=
                          os.path.normcase(os.path.realpath(app_parent)))
    return {
        "empty": not notes,
        "notes": notes,
        "vault": os.path.basename(vault) or vault,
        "vault_path": vault,
        # W42: app nằm đúng chỗ chưa (tên thư mục = .graph3d). False = rất có thể user
        # đang xem thư mục CHA của bản clone chứ không phải vault của mình.
        # W180: app runtime có thể đứng ngoài vault. Khi active vault khác app-parent,
        # folder đã được chọn tường minh nên không được bật cảnh báo "cài sai chỗ" W42.
        "installed": installed_in_vault(app) or selected_elsewhere,
        "app_dir": os.path.basename(app),
        "starter": {"available": s_notes > 0, "notes": s_notes, "path": sd},
        "demo": {"available": d_notes > 0, "notes": d_notes, "path": dd,
                 "port": DEMO_PORT},
        "cmd": {"demo": "python .graph3d/ensure_graph3d.py --demo",
                "starter": "python .graph3d/ensure_graph3d.py --init-starter <thư-mục>",
                "install": 'git clone https://github.com/chuong1224/agents-knowledge-base '
                           '"<đường-dẫn-vault>/.graph3d"'},
    }


# ---------------------------------------------------------------- tạo vault đầu tiên
def install_starter(target, force=False):
    """Chép `starter-vault/` vào `target` (vault đang trống hoặc thư mục mới).

    Hai hàng rào, cố ý KHÔNG có cờ nào tắt được hàng rào thứ hai:
      1. target phải chưa có note .md (`force=True` bỏ qua — chỉ dành cho CLI khi
         user tự chịu trách nhiệm), vì đây là bước "vault đầu tiên", không phải
         import content vào vault đang sống;
      2. TUYỆT ĐỐI không đè file trùng tên — file đã có được bỏ qua và báo lại.
    """
    src = os.path.abspath(starter_dir())
    target = os.path.abspath(target)
    if not os.path.isdir(src):
        raise OnboardingError("không tìm thấy starter-vault: %s" % src, "starter_missing")
    if count_notes(src) <= 0:
        raise OnboardingError("starter-vault không có note .md nào: %s" % src, "starter_empty")
    if not force and count_notes(target) > 0:
        raise OnboardingError(
            "thư mục đích đã có note .md — starter vault chỉ dùng cho vault TRỐNG: %s" % target,
            "target_not_empty")

    created, skipped = [], []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_dir = os.path.relpath(root, src)
        for fn in files:
            if fn.startswith("."):
                continue
            rel = fn if rel_dir == "." else os.path.join(rel_dir, fn).replace("\\", "/")
            dst = os.path.join(target, rel.replace("/", os.sep))
            if os.path.exists(dst):
                skipped.append(rel)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(root, fn), dst)
            created.append(rel)
    created.sort()
    return {"created": created, "skipped": sorted(skipped),
            "notes": sum(1 for r in created if r.lower().endswith(".md")),
            # note mở ngay sau khi dựng — đừng để người mới nhìn 9 node rồi tự đoán
            "entry": entry_note(created),
            "src": src, "target": target}


# ---------------------------------------------------------------- bản sao app cho demo
def mirror_app(dst_app, src_app=None):
    """Chép app sang `dst_app` (= `demo/vault/.graph3d`) để vault demo có server riêng.

    Danh sách file lấy từ `activity_paths.APP_TOP/APP_DIRS` — NGUỒN DUY NHẤT. Bài học
    đợt 7+8 repo public: mỗi nơi giữ một danh sách .py chép tay thì thêm module mới là
    sót (try_demo.py sót `insight.py`/`integrity.py` ⇒ demo chết khi serve import).
    Thiếu file khai trong danh sách = lỗi CỨNG, không copy nửa vời rồi để server crash.
    """
    src_app = os.path.abspath(src_app or HERE)
    dst_app = os.path.abspath(dst_app)
    if os.path.normcase(src_app) == os.path.normcase(dst_app):
        raise OnboardingError("nguồn và đích trùng nhau: %s" % src_app)
    missing = [n for n in activity_paths.APP_TOP
               if not os.path.isfile(os.path.join(src_app, n))]
    missing += [d for d in activity_paths.APP_DIRS
                if not os.path.isdir(os.path.join(src_app, d))]
    if missing:
        raise OnboardingError("bản app nguồn thiếu: %s" % ", ".join(missing))

    os.makedirs(dst_app, exist_ok=True)
    n = 0
    for name in activity_paths.APP_TOP:
        s, d = os.path.join(src_app, name), os.path.join(dst_app, name)
        # copy2 giữ mtime ⇒ lần chạy sau size+mtime khớp là bỏ qua (khỏi chép lại 3.3MB vendor)
        if not _same_file(s, d):
            shutil.copy2(s, d)
            n += 1
    for sub in activity_paths.APP_DIRS:
        n += _mirror_dir(os.path.join(src_app, sub), os.path.join(dst_app, sub))
    return {"copied": n, "src": src_app, "dst": dst_app}


def _same_file(a, b):
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) < 2


def _mirror_dir(src, dst):
    """Đồng bộ một thư mục: chép file đổi + XOÁ file thừa (module bị gỡ ở bản mới
    không được sống sót trong bản demo — đó là cách 'code cũ' lẻn vào demo)."""
    n = 0
    keep = set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for fn in files:
            keep.add(os.path.normcase(os.path.join(out, fn)))
            s, d = os.path.join(root, fn), os.path.join(out, fn)
            if not _same_file(s, d):
                shutil.copy2(s, d)
                n += 1
    for root, dirs, files in os.walk(dst):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            p = os.path.join(root, fn)
            if os.path.normcase(p) not in keep:
                try:
                    os.remove(p)
                except OSError:
                    pass
    return n


def demo_env(base_env=None):
    """Env cho server DEMO: mọi file runtime (log realtime, journal, heat tích luỹ)
    đổ vào scratch NGOÀI thư mục demo.

    Lý do cứng: `demo/vault/` nằm trong working tree repo public, mà tên file runtime
    chứa TÊN MÁY — đợt 4 và đợt 6 đều suýt/đã publish nhầm file đó (denylist chặn).
    Cách ly ở đây thì hết hẳn lớp sự cố, và demo cũng đúng nghĩa hơn: hoạt động agent
    trên vault THẬT không trộn vào feed của vault demo (note không cùng đường dẫn)."""
    env = dict(base_env if base_env is not None else os.environ)
    scratch = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "claude-graph3d", "demo")
    os.makedirs(scratch, exist_ok=True)
    env["GRAPH3D_ACTIVITY_FILE"] = os.path.join(scratch, "activity.jsonl")
    env["GRAPH3D_JOURNAL_DIR"] = scratch
    env["GRAPH3D_HEAT_DIR"] = scratch
    # Cùng lý do: `__pycache__` do server demo sinh ra nằm trong cây repo public và .pyc
    # có chứa cả docstring — nó từng làm denylist scan báo đỏ. Không ghi bytecode thì hết.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def wait_health(port, timeout=30.0):
    """Chờ server ở `port` báo khỏe → dict /health, hết giờ → None. Dùng urllib trần
    để module này không phải import run_graph3d (serve nạp onboarding lúc khởi động)."""
    url = "http://127.0.0.1:%d/health" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.4)
    return None
