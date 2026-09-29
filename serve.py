# -*- coding: utf-8 -*-
"""KB Graph 3D — local server.

Chạy:  python .graph3d/serve.py           (tự mở trình duyệt, port 8321)
       python .graph3d/serve.py --no-open --port 8321

Endpoint:
  /              -> index.html
  /src/*         -> ES modules + CSS của UI (giai đoạn 0 Vault Cockpit — tách monolith)
  /vendor/*      -> thư viện three.js / 3d-force-graph / markdown-it (vendored, offline OK)
  /graph-data    -> quét vault, trả JSON nodes/links (build in-memory, không ghi file)
  /vault-state   -> active vault + id ổn định + trạng thái khóa/cảnh báo
  POST /vault-pick -> native folder picker; lưu lựa chọn ngoài vault rồi exit 4 để
                    supervisor relaunch atomically trên cùng port
  /note?path=    -> markdown thô + mtime/size của 1 note (giai đoạn 1 Vault Cockpit — Reader)
  /asset?path=   -> file đính kèm trong vault (ảnh/video/pdf… cho Reader hiển thị)
                    cả hai chặn path traversal + dot-folder (xem vault_file)
  /search?q=     -> full-text search .md trong vault (giai đoạn 2 Vault Cockpit — Finder):
                    AND mọi từ, không dấu (mirror deAccent của UI), index in-memory
                    cache theo mtime — KHÔNG sinh file DB
  /timeline?day= -> TOÀN BỘ event của MỘT ngày (giai đoạn 3 Vault Cockpit — Cockpit):
                    mọi nguồn log, kèm danh sách ngày còn trong log — UI phát lại
  /dashboard?day= -> tổng hợp hiệu quả truy xuất một ngày: per-agent + histogram
                     giờ + top note (metric chuỗi tính bằng build_chains)
  /insight?days=&cold= -> "vault đang khoẻ không" (W10): note nóng/đang nguội theo
                     tuần cuộn, note nguội theo lần đụng cuối, note CHƯA BAO GIỜ
                     agent đụng, cụm ít kết nối, coverage theo khu vực — tính trong
                     insight.py (CLI --report của module đó dùng CÙNG hàm)
  /integrity     -> "vault có đang GÃY chỗ nào không" (W11/W149): wikilink/nhúng gãy,
                     anchor lệch heading, ảnh mồ côi, YAML frontmatter vỡ/thiếu trường,
                     file nhị phân chưa "mở nilon" — tính trong
                     integrity.py (tiêu chí bỏ qua note lấy của gate verify_vault_
                     integrity.py; luật đếm được đọc từ vault-rules.json trong vault)
  /onboarding    -> vault có TRỐNG không + lối đi nào sẵn có (W13): starter-vault/
                    và demo/vault/ bundled hay không — UI dựng empty-state từ đây
  POST /file-action?path=&action= -> mở file bằng ứng dụng mặc định hoặc chọn file
                    trong trình quản lý tệp; cùng guard vault_file + Origin như các
                    hành động cục bộ khác, không trả đường dẫn tuyệt đối về client
  POST /starter-init -> chép starter-vault/ vào vault đang trống (không đè file)
  POST /demo-start   -> mở cockpit trên vault demo bundled ở PORT RIÊNG (gọi
                    ensure_graph3d.py --demo, không tự chạy serve.py)
                    Các POST có tác dụng phụ đều có hàng rào Origin; xem onboarding.py.
  /activity?cursor=N -> event mới trong activity.jsonl từ byte-offset N
                        (hook log_activity.py của Claude Code ghi file này)
  /work          -> bản đồ việc đang mở của vault, đã phân loại (làm ngay được / chờ việc / chờ điều kiện)
                    — logic thuộc `Vault Operation/Work Map/attachments/work.py`,
                    server chỉ import + cache theo mtime, KHÔNG chép lại luật phân loại.
                    Vault khác đặt bản đồ chỗ khác: biến môi trường GRAPH3D_WORKMAP_DIR;
                    không có bản đồ thì endpoint trả 404 và UI hiện đúng như vậy.
"""
import argparse
import glob
from collections import Counter
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
APP_VAULT = os.path.dirname(HERE)
from activity_paths import (active_activity_log_path,  # noqa: E402
                            activity_log_candidates, codex_session_candidates,
                            is_codex_rollout, parse_codex_rollout, source_version,
                            cumulative_heat_files, parse_jsonl, restart_py_files,
                            vault_journal_files, journal_host, host_name,
                            no_window_kwargs)

# Danh tính process (browser dùng để phát hiện server vừa restart → tự resync,
# ensure/run dùng version để biết server có "cũ" so với code trên đĩa không).
BOOT_ID = uuid.uuid4().hex[:12]
VERSION = source_version(HERE) or "unknown"
_httpd = None            # gán trong main() để /shutdown gọi được
PORT = [8321]            # gán trong main() — POST guard so Origin theo port đang chạy
EXIT_CODE = [0]          # 4 = đổi vault, supervisor relaunch cùng port

sys.path.insert(0, HERE)
import build_graph_data  # noqa: E402
import log_activity  # noqa: E402  (dùng append_events cho endpoint /ping)
import insight  # noqa: E402  (tầng insight sức khoẻ vault — /insight)
import integrity  # noqa: E402  (đèn báo toàn vẹn vault — /integrity)
import onboarding  # noqa: E402  (vault trống: empty-state + starter vault — /onboarding)
import update_check  # noqa: E402  (báo có bản mới trên repo — /update, W69)
import vault_switcher  # noqa: E402  (W180 — chọn active vault từ UI)

# Direct import/test/serve.py keeps the historical app-parent vault.  The supported
# launcher path passes GRAPH3D_VAULT for every server process.  Normal processes may
# switch; --vault/demo marks the process locked.
_process_vault = os.environ.get(vault_switcher.VAULT_ENV, "").strip()
_process_locked = os.environ.get(vault_switcher.LOCKED_ENV, "") == "1"
if _process_vault:
    if _process_locked:
        _VAULT_CTX = vault_switcher.resolve_active_vault(HERE, explicit=_process_vault)
    else:
        _VAULT_CTX = vault_switcher.resolve_active_vault(HERE)
        if not vault_switcher.same_vault(_VAULT_CTX["path"], _process_vault):
            _VAULT_CTX = vault_switcher.resolve_active_vault(HERE, explicit=_process_vault)
    _VAULT_CTX["locked"] = _process_locked
else:
    _VAULT_CTX = vault_switcher.resolve_active_vault(HERE, explicit=APP_VAULT)
    _VAULT_CTX["locked"] = False
    _VAULT_CTX["source"] = "app"
VAULT = _VAULT_CTX["path"]
ACTIVE_STORE_DIR = os.path.join(VAULT, ".graph3d")
ACTIVE_STORE_DIR = ACTIVE_STORE_DIR if os.path.isdir(ACTIVE_STORE_DIR) else None
ACTIVE_JOURNAL_DIR = os.environ.get("GRAPH3D_JOURNAL_DIR", "").strip() or ACTIVE_STORE_DIR
ACTIVE_HEAT_DIR = os.environ.get("GRAPH3D_HEAT_DIR", "").strip() or ACTIVE_STORE_DIR
APP_TELEMETRY = vault_switcher.same_vault(VAULT, APP_VAULT)

_cache = {"ts": 0.0, "data": None}
_cache_lock = threading.Lock()
CACHE_SECONDS = 3.0

# Work Map: active vault chỉ cung cấp registry JSON. Tuyệt đối không import ``work.py``
# từ một vault user vừa chọn: Vault Switcher cho phép folder bất kỳ, nên làm vậy sẽ
# biến thao tác xem graph thành thực thi mã không tin cậy. Engine chỉ lấy từ app vault.
WORKMAP_DIR = os.environ.get("GRAPH3D_WORKMAP_DIR") or os.path.join(
    VAULT, "Vault Operation", "Work Map", "attachments")
WORKMAP_ENGINE = os.environ.get("GRAPH3D_WORKMAP_ENGINE") or os.path.join(
    APP_VAULT, "Vault Operation", "Work Map", "attachments", "work.py")
_workmap_cache = {"key": None, "data": None}


def workmap_export():
    """Bản đồ việc đã phân loại, hoặc None nếu vault này không có Work Map.

    Cache theo mtime của engine tin cậy + registry active — sửa work.json là F5 thấy
    ngay, không phải restart server (cùng tinh thần /src/* đọc thẳng đĩa).
    """
    registry = os.path.join(WORKMAP_DIR, "work.json")
    if not (os.path.isfile(WORKMAP_ENGINE) and os.path.isfile(registry)):
        return None
    key = (os.path.getmtime(WORKMAP_ENGINE), os.path.getmtime(registry))
    if _workmap_cache["key"] == key:
        return _workmap_cache["data"]
    spec = importlib.util.spec_from_file_location("kb_workmap", WORKMAP_ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(registry, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    data = mod.export_data(cfg)
    _workmap_cache.update(key=key, data=data)
    return data

MIME = {".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png", ".svg": "image/svg+xml",
        # /asset (Reader): các định dạng đính kèm hay gặp trong vault
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".webp": "image/webp", ".avif": "image/avif", ".bmp": "image/bmp",
        ".ico": "image/x-icon", ".mp4": "video/mp4", ".webm": "video/webm",
        ".mov": "video/quicktime", ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


APP_STATIC_DIRS = ("src", "vendor")


def app_static_file(url_path):
    """Đường file tĩnh của APP cho `/src/*` và `/vendor/*`, hoặc None.

    Prefix phải kèm os.sep (P0.4) — thiếu thì thư mục anh em `vendor_old`/`src2` cũng
    lọt whitelist qua `/vendor/../vendor_old/x`. Chỉ file có thật mới được phục vụ."""
    for d in APP_STATIC_DIRS:
        if not url_path.startswith("/%s/" % d):
            continue
        full = os.path.join(HERE, os.path.normpath(url_path.lstrip("/")))
        root = os.path.normcase(os.path.join(HERE, d)) + os.sep
        if os.path.normcase(full).startswith(root) and os.path.isfile(full):
            return full
        return None
    return None


def vault_file(rel, exts=None):
    """Resolve đường dẫn tương đối ('/'-sep, từ query ?path=) → file THẬT trong vault.
    Trả None khi: rỗng / thoát vault (.., tuyệt đối, ổ đĩa) / đi vào dot-folder
    (.obsidian, .graph3d, .claude, .git… — server bắt đầu phục vụ nội dung note thì
    các folder cấu hình càng phải đóng) / sai đuôi / không tồn tại. Guard này là
    hàng rào duy nhất của /note + /asset — có unit test riêng (tests/test_reader.py)."""
    if not rel or "\x00" in rel:
        return None
    norm = os.path.normpath(rel.replace("\\", "/").lstrip("/"))
    if norm.startswith("..") or os.path.isabs(norm) or ":" in norm:
        return None
    if any(p.startswith(".") for p in norm.replace("\\", "/").split("/")):
        return None
    if exts and os.path.splitext(norm)[1].lower() not in exts:
        return None
    root = os.path.realpath(VAULT)
    full = os.path.realpath(os.path.join(root, norm))
    try:
        if os.path.normcase(os.path.commonpath((root, full))) != os.path.normcase(root):
            return None                    # symlink/junction trong vault trỏ ra ngoài
    except ValueError:                     # khác drive trên Windows
        return None
    return full if os.path.isfile(full) else None


def run_file_action(rel, action, platform=None, startfile=None, popen=None):
    """Mở attachment bằng app mặc định hoặc reveal đúng file trong file manager.

    Đây là lõi thuần để endpoint POST và unit test dùng chung. ``rel`` luôn đi qua
    ``vault_file`` nên không thể chạm dot-folder/path ngoài vault; response chỉ có
    path tương đối để không làm lộ đường dẫn máy chủ cho client.
    """
    if action not in ("open", "reveal"):
        raise ValueError("action khong hop le")
    full = vault_file(rel)
    if not full:
        raise FileNotFoundError(rel)

    platform = platform or sys.platform
    popen = popen or subprocess.Popen
    if platform == "win32":
        if action == "open":
            startfile = startfile or getattr(os, "startfile", None)
            if not startfile:
                raise OSError("Windows file association khong kha dung")
            startfile(full)
        else:
            # Explorer parse /select khac CommandLineToArgvW: dau phay phai nam
            # NGOAI cap quote cua path. subprocess.list2cmdline() quote ca doi so
            # khi path co space, tao `"/select,E:\..."` va Explorer roi ve
            # Documents. Truyen command line dung contract cua Explorer:
            #     explorer.exe /select,"E:\folder co space\file, x.xlsx"
            command = 'explorer.exe /select,"%s"' % os.path.normpath(full)
            popen(command,
                  close_fds=True, **no_window_kwargs())
    elif platform == "darwin":
        argv = ["open", full] if action == "open" else ["open", "-R", full]
        popen(argv, close_fds=True)
    else:
        target = full if action == "open" else os.path.dirname(full)
        popen(["xdg-open", target], close_fds=True)

    return {"ok": True, "action": action,
            "path": rel.replace("\\", "/").lstrip("/")}


_build_src_mtime = [0.0]


def get_graph_data():
    with _cache_lock:
        # Tự nạp lại scanner khi build_graph_data.py thay đổi (sync OneDrive /
        # agent sửa code) — không cần restart server nữa.
        src = os.path.join(HERE, "build_graph_data.py")
        try:
            mt = os.path.getmtime(src)
        except OSError:
            mt = 0.0
        if mt != _build_src_mtime[0]:
            importlib.reload(build_graph_data)
            _build_src_mtime[0] = mt
            _cache["data"] = None
        if _cache["data"] is None or time.time() - _cache["ts"] > CACHE_SECONDS:
            _cache["data"] = build_graph_data.build(VAULT)
            _cache["ts"] = time.time()
        return _cache["data"]


def _fold(s):
    """Chuẩn hoá chuỗi để so khớp KHÔNG DẤU — MIRROR deAccent của UI (src/state.js):
    lower → NFD bỏ dấu combining → đ→d. Fold TỪNG KÝ TỰ để chuỗi ra CÙNG ĐỘ DÀI
    chuỗi vào (1:1) — vị trí khớp trên bản fold map thẳng về text gốc khi cắt snippet."""
    out = []
    for ch in s.lower():
        b = "".join(c for c in unicodedata.normalize("NFD", ch)
                    if not unicodedata.combining(c))
        b = b[0] if b else " "
        out.append("d" if b == "đ" else b)
    return "".join(out)


_search_cache = {"vault": None, "sig": None, "docs": None}
_search_lock = threading.Lock()


def _search_docs(vault):
    """Index full-text in-memory: đọc mọi .md trong vault (CÙNG luật loại trừ với
    scanner — dot-folder + build_graph_data.EXCLUDED_DIRS, không bao giờ tìm thấy
    note mà graph không có). Cache theo (rel, mtime, size) toàn bộ — vault đổi mới
    đọc lại. KHÔNG ghi file nào ra đĩa (vault format bất khả xâm phạm)."""
    entries, sig = [], []
    for root, dirs, fnames in os.walk(vault):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in build_graph_data.EXCLUDED_DIRS]
        for fn in fnames:
            if not fn.lower().endswith(".md"):
                continue
            full = os.path.join(root, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, vault).replace("\\", "/")
            entries.append((rel, full))
            sig.append((rel, st.st_mtime_ns, st.st_size))
    sig = tuple(sig)
    with _search_lock:
        if _search_cache["vault"] == vault and _search_cache["sig"] == sig:
            return _search_cache["docs"]
    docs = []
    for rel, full in entries:
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        docs.append({"rel": rel, "stem": stem, "text": text,
                     "stem_f": _fold(stem), "text_f": _fold(text)})
    with _search_lock:
        _search_cache.update(vault=vault, sig=sig, docs=docs)
    return docs


def search_notes(q, limit=20):
    """Full-text search cho Finder: AND mọi từ (mỗi từ phải xuất hiện trong TÊN
    hoặc THÂN note). Điểm = khớp tên file nặng hơn khớp thân (người tìm thường
    nhớ tên); snippet cắt quanh vị trí khớp đầu tiên, trả TEXT GỐC còn dấu."""
    terms = [t for t in _fold(q or "").split() if t]
    if not terms:
        return []
    out = []
    for d in _search_docs(VAULT):
        score, hits, first = 0, 0, -1
        for t in terms:
            cnt = d["text_f"].count(t)
            in_stem = t in d["stem_f"]
            if not cnt and not in_stem:
                score = -1
                break
            score += cnt + (12 if in_stem else 0)
            hits += cnt
            if cnt:
                pos = d["text_f"].find(t)
                first = pos if first < 0 else min(first, pos)
        if score < 0:
            continue
        snippet = ""
        if first >= 0:
            lo = max(0, first - 60)
            snippet = " ".join(d["text"][lo:first + 90].split())
            if lo:
                snippet = "…" + snippet
        out.append({"path": d["rel"], "score": score, "hits": hits,
                    "snippet": snippet})
    out.sort(key=lambda r: (-r["score"], r["path"]))
    return out[:max(1, limit)]


def _parse_activity_source(act_path, text):
    if is_codex_rollout(act_path):
        return parse_codex_rollout(text, vault=VAULT)
    return parse_jsonl(text)


def _read_source(act_path, start):
    """Đọc JSONL một nguồn từ byte offset. Trả (events, cursor_mới).
    Cursor = vị trí SAU DÒNG HOÀN CHỈNH cuối cùng (f.tell() lùi về sau ký tự \\n
    cuối) — KHÔNG stat lại file sau khi đọc: writer chen giữa read() và getsize()
    từng làm cursor nhảy qua event chưa đọc (mất vĩnh viễn); dòng writer đang ghi
    dở cũng được đọc trọn ở poll sau thay vì bị cắt cụt."""
    with open(act_path, "rb") as f:
        f.seek(start)
        chunk = f.read()
        end = f.tell()
    nl = chunk.rfind(b"\n")
    if nl < 0:
        return [], start                  # chưa có dòng hoàn chỉnh mới nào
    end -= len(chunk) - (nl + 1)
    text = chunk[:nl].decode("utf-8", errors="replace")
    return _parse_activity_source(act_path, text), end


def _realtime_sources():
    """Nguồn live của active vault, không suy diễn provenance bị thiếu.

    Log hook Claude/Hermes chỉ lưu path TƯƠNG ĐỐI của app vault nên không thể phân
    biệt hai vault cùng có ``Index.md``. Khi xem vault ngoài, bỏ nguồn đó hoàn toàn;
    rollout Codex có workdir/path tuyệt đối nên vẫn parse an toàn theo active vault.
    """
    out, seen = [], set()
    paths = codex_session_candidates()
    if APP_TELEMETRY:
        paths = activity_log_candidates() + paths
    for path in paths:
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def read_activity_all(cursors, replay=False):
    """Event mới từ MỌI nguồn activity (đường chuẩn CLI + LocalCache MSIX của
    Cowork), cursor RIÊNG từng file — thay mô hình 'một file đang sống theo mtime'
    từng flap qua lại khi 2 nguồn cùng ghi (reset cursor liên tục → hiệu ứng phát
    lại + event lọt khe). cursors: dict {path: offset} client gửi lại nguyên văn
    (opaque với client). Trả (cursors_mới, events sort theo ts, forced_replay)."""
    out, events, forced = {}, [], False
    now = time.time()
    seen_src = set()
    for act in _realtime_sources():
        try:
            st = os.stat(act)
        except OSError:
            continue                       # nguồn chưa tồn tại — xuất hiện sau sẽ được mồi
        # Process chạy TRONG sandbox MSIX (Cowork) bị redirect cả đường chuẩn về
        # LocalCache → 2 đường dẫn trỏ CÙNG một file vật lý: chỉ đọc một lần,
        # kẻo mỗi event trả về gấp đôi.
        sig = (st.st_dev, st.st_ino)
        if st.st_ino:
            if sig in seen_src:
                continue
            seen_src.add(sig)
        size = st.st_size
        cur = cursors.get(act)
        fresh = cur is None
        if replay or fresh or cur > size:
            # boot / nguồn mới giữa phiên / file co lại (rotate): đọc tail để mồi cursor
            if not replay and not fresh:
                forced = True              # rotate → client không được bắn lại hiệu ứng
            tail_bytes = 1048576 if is_codex_rollout(act) else 65536
            evs, end = _read_source(act, max(0, size - tail_bytes))
            if fresh and not replay:
                # Nguồn mới xuất hiện giữa phiên (Cowork vừa chạy hook lần đầu): chỉ
                # nhận event thật sự mới — nội dung cũ trong file không phải hoạt động mới.
                evs = [e for e in evs if isinstance(e.get("ts"), (int, float))
                       and now - e["ts"] <= 90]
            evs = evs[-15:]
        else:
            evs, end = _read_source(act, cur)
        events.extend(evs)
        out[act] = end
    events.sort(key=lambda e: e.get("ts", 0))
    # Khử trùng lặp chéo nguồn (dòng từng bị copy giữa 2 realm) — cùng key với read_all_events
    uniq, seen = [], set()
    for e in events:
        k = (e.get("ts"), e.get("file"), e.get("type"), e.get("agent"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    events = uniq
    if replay:
        events = events[-15:]              # mở trang: tránh bắn 30 pulse cùng lúc
    return out, events, forced


CHAIN_GAP = 60.0   # giây: gap <= => cùng chuỗi truy xuất; > => tách chuỗi mới


_events_cache = {"sig": None, "events": []}
_events_cache_lock = threading.Lock()


def _event_sources():
    """(path, host|None) mọi nguồn cho view TỔNG HỢP: log local realtime (host=None)
    + journal per-máy TRONG vault (activity-<HOST>.jsonl — v1.25.0, sync OneDrive để
    laptop thấy event máy cty và ngược lại). Local đứng TRƯỚC: bản trùng log↔journal
    của chính máy này dedup giữ bản local (không host)."""
    out = [(p, None) for p in _realtime_sources()]
    if ACTIVE_JOURNAL_DIR:
        out += [(p, journal_host(p)) for p in vault_journal_files(ACTIVE_JOURNAL_DIR)]
    return out


def read_all_events():
    """Toàn bộ activity (MỌI nguồn) -> list event dict: đường chuẩn (CLI) + LocalCache
    MSIX (Cowork) + journal vault của MỌI máy; khử trùng lặp theo (ts,file,type,agent)
    — key KHÔNG chứa host nên event của chính máy này nằm cả trong log local lẫn
    journal chỉ tính một lần; event máy KHÁC mang field host (từ tên file journal).
    Dùng cho heat/chains/timeline/dashboard — UI poll 4s nên CACHE theo (mtime, size)
    từng file. Realtime /activity KHÔNG đi đường này (journal sync trễ hàng phút —
    bắn hiệu ứng live từ đó là tín hiệu giả). Caller KHÔNG được sửa list trả về."""
    sig = []
    for act, _h in _event_sources():
        try:
            st = os.stat(act)
        except OSError:
            continue
        sig.append((act, st.st_mtime_ns, st.st_size))
    sig = tuple(sig)
    with _events_cache_lock:
        if sig == _events_cache["sig"]:
            return _events_cache["events"]
    out, seen = [], set()
    for act, host in _event_sources():
        if not os.path.exists(act):
            continue
        try:
            with open(act, "rb") as f:
                data = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        for ev in _parse_activity_source(act, data):
            if "ts" in ev and "file" in ev:
                key = (ev.get("ts"), ev.get("file"), ev.get("type"), ev.get("agent"))
                if key in seen:
                    continue
                seen.add(key)
                if host:
                    ev.setdefault("host", host)
                out.append(ev)
    out.sort(key=lambda e: e.get("ts", 0))
    with _events_cache_lock:
        _events_cache["sig"] = sig
        _events_cache["events"] = out
    return out


def build_chains(events, gap=CHAIN_GAP, limit=40):
    """Gom event LIÊN TIẾP theo TỪNG agent thành 'chuỗi truy xuất' khi khoảng cách
    thời gian ≤ gap. Mỗi event: dwell = khoảng tới event kế trong chuỗi (cuối = 0)
    → 'thời gian đọc' note đó. Tổng thời gian chuỗi = span = ts[cuối]-ts[đầu] =
    sum(dwell). Metric để đo hiệu quả truy xuất + phát hiện cấu trúc bất hợp lý:
    count (số thao tác), distinct (số note khác nhau), rereads (đọc lặp = nghi ngờ)."""
    by_agent = {}
    for e in sorted(events, key=lambda e: e.get("ts", 0)):
        ag = e.get("agent") or "Claude"
        by_agent.setdefault(ag, []).append(e)

    chains = []
    for ag, aevs in by_agent.items():
        cur = None
        for e in aevs:
            ts = e.get("ts", 0)
            if cur is None or ts - cur["end"] > gap:
                cur = {"agent": ag, "start": ts, "end": ts, "events": []}
                chains.append(cur)
            cur["end"] = ts
            cur["events"].append(e)

    out = []
    for c in chains:
        evl = c["events"]
        for i, e in enumerate(evl):
            nxt = evl[i + 1].get("ts", e.get("ts", 0)) if i + 1 < len(evl) else e.get("ts", 0)
            e = dict(e)
            evl[i] = e
            e["dwell"] = max(0.0, nxt - e.get("ts", 0))
        files = [e.get("file") for e in evl]
        distinct = len(set(files))
        types = {}
        for e in evl:
            t = e.get("type", "read")
            types[t] = types.get(t, 0) + 1
        # rereads = repeated READS only (sequential edits on same file = normal workflow)
        read_files = [e.get("file") for e in evl if e.get("type", "read") == "read"]
        read_counts = Counter(read_files)
        rereads = sum(cnt - 1 for cnt in read_counts.values() if cnt > 1)
        edit_files = [e.get("file") for e in evl if e.get("type") == "edit"]
        edit_counts = Counter(edit_files)
        reedits = sum(cnt - 1 for cnt in edit_counts.values() if cnt > 1)
        out.append({
            "agent": c["agent"], "start": c["start"], "end": c["end"],
            "span": max(0.0, c["end"] - c["start"]),
            "count": len(evl), "distinct": distinct, "rereads": rereads, "reedits": reedits,
            "types": types,
            "events": [{"file": e.get("file"), "type": e.get("type", "read"),
                        "ts": e.get("ts"), "dwell": e.get("dwell", 0.0)} for e in evl],
        })
    out.sort(key=lambda c: c["end"], reverse=True)
    return out[:limit]


def build_heat(events, top_n=14):
    """Heatmap tần suất từ log cửa sổ cuộn. Đếm bằng log_activity.aggregate_by_file —
    MỘT bộ đếm duy nhất cho cả heat window lẫn reconcile, sửa một nơi khỏi lệch nhau."""
    agg = log_activity.aggregate_by_file(events)
    counts = {f: r["total"] for f, r in agg.items()}
    mx = max(counts.values()) if counts else 0
    top = sorted(agg.items(), key=lambda kv: kv[1]["total"], reverse=True)[:top_n]
    return {"scope": "window", "counts": counts, "max": mx, "total": sum(counts.values()),
            "distinct": len(counts),
            "top": [{"file": f, "n": r["total"],
                     "types": {t: r.get(t, 0) for t in ("read", "search", "edit")}}
                    for f, r in top]}


def merge_cumulative_stores():
    """Gộp mọi heat_cumulative-<HOST>.json (đa máy) trong vault → (notes, meta).

    notes = {rel: {total, read, search, edit, first, last, agents}} — `first`/`last`
    là mốc dài hạn KHÔNG mất khi log cuộn xoay vòng, nên đây là nguồn duy nhất trả
    lời được "note này bao lâu rồi không ai đụng" (insight.py dùng).
    meta  = {machines, since, updated}.

    Tách riêng khỏi build_heat_cumulative để hai người tiêu thụ (/heat và /insight)
    dùng CHUNG một logic gộp — /heat giữ nguyên contract của nó (chỉ counts + top).
    """
    if APP_TELEMETRY:
        try:
            log_activity.reconcile_cumulative_with_log()
        except Exception:
            pass
    merged, machines, since, updated = {}, [], None, 0
    stores = cumulative_heat_files(ACTIVE_HEAT_DIR) if ACTIVE_HEAT_DIR else []
    for p in stores:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        machines.append(d.get("host") or os.path.splitext(os.path.basename(p))[0])
        s = d.get("since")
        if isinstance(s, (int, float)):
            since = s if since is None else min(since, s)
        u = d.get("updated") or 0
        if isinstance(u, (int, float)):
            updated = max(updated, u)
        for rel, r in (d.get("notes") or {}).items():
            if not isinstance(r, dict):
                continue
            m = merged.setdefault(rel, {"total": 0, "read": 0, "search": 0, "edit": 0,
                                        "first": None, "last": None, "agents": {}})
            m["total"] += r.get("total", 0)
            for t in ("read", "search", "edit"):
                m[t] += r.get(t, 0)
            for k, pick in (("first", min), ("last", max)):
                v = r.get(k)
                if isinstance(v, (int, float)) and v:
                    m[k] = v if m[k] is None else pick(m[k], v)
            for ag, n in (r.get("agents") or {}).items():
                m["agents"][ag] = m["agents"].get(ag, 0) + n
    return merged, {"machines": sorted(set(machines)), "since": since, "updated": updated}


def build_heat_cumulative(top_n=14):
    """Heat TÍCH LUỸ dài hạn cho heatmap: đếm + top note (gộp đa máy qua
    merge_cumulative_stores). Không mất khi log xoay vòng — dùng phân tích hiệu quả
    vault lâu dài."""
    merged, hmeta = merge_cumulative_stores()
    machines, since, updated = hmeta["machines"], hmeta["since"], hmeta["updated"]
    counts = {f: r["total"] for f, r in merged.items()}
    mx = max(counts.values()) if counts else 0
    top = sorted(merged.items(), key=lambda kv: kv[1]["total"], reverse=True)[:top_n]
    return {"scope": "all", "counts": counts, "max": mx, "total": sum(counts.values()),
            "distinct": len(counts), "machines": machines,
            "since": since, "updated": updated,
            "top": [{"file": f, "n": r["total"],
                     "types": {t: r.get(t, 0) for t in ("read", "search", "edit")},
                     "agents": r.get("agents", {})} for f, r in top]}


def day_key(ts):
    """Khoá ngày LOCAL của một timestamp — 'cả ngày' theo giờ máy người dùng
    (2 máy đều chạy local, không cần timezone param). ts không phải số → ""
    (localtime(None) = BÂY GIỜ — event thiếu ts sẽ bị gán nhầm vào hôm nay)."""
    if not isinstance(ts, (int, float)):
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return ""


def list_days(events):
    """Các ngày còn event trong log (mới nhất trước) — log cuộn nên thường 1–3 ngày."""
    return sorted({day_key(e.get("ts", 0)) for e in events
                   if isinstance(e.get("ts"), (int, float))}, reverse=True)


def events_for_day(events, day=None):
    """Lọc event của MỘT ngày. day rỗng/lạ → fallback ngày mới nhất còn trong log.
    Trả (day_events, days, day) — KHÔNG sửa list events (cache dùng chung)."""
    days = list_days(events)
    if not day or day not in days:
        day = days[0] if days else None
    if not day:
        return [], days, None
    return [e for e in events if day_key(e.get("ts", 0)) == day], days, day


DASH_TYPES = ("read", "search", "edit")


def build_dashboard(events, day=None, gap=CHAIN_GAP, top_n=10):
    """Dashboard hiệu quả truy xuất MỘT ngày (giai đoạn 3 Vault Cockpit):
    tổng lượt theo loại, per-agent (lượt r/s/e, note khác nhau, số chuỗi, tổng
    span, rereads/reedits), histogram 24 giờ theo loại, top note. Metric chuỗi
    tính bằng build_chains — MỘT nguồn sự thật, không viết bộ đếm thứ hai."""
    day_evs, days, day = events_for_day(events, day)
    chains = build_chains(day_evs, gap=gap, limit=len(day_evs) + 1)
    hours = [{"read": 0, "search": 0, "edit": 0} for _ in range(24)]
    by_agent, per_file = {}, {}
    for e in day_evs:
        t = e.get("type", "read")
        t = t if t in DASH_TYPES else "read"
        ag = e.get("agent") or "Claude"
        a = by_agent.setdefault(ag, {"agent": ag, "total": 0, "read": 0,
                                     "search": 0, "edit": 0, "files": set(),
                                     "chains": 0, "span": 0.0,
                                     "rereads": 0, "reedits": 0})
        a["total"] += 1
        a[t] += 1
        a["files"].add(e.get("file"))
        try:
            hours[time.localtime(e.get("ts", 0)).tm_hour][t] += 1
        except (OverflowError, OSError, ValueError):
            pass
        pf = per_file.setdefault(e.get("file"),
                                 {"total": 0, "read": 0, "search": 0, "edit": 0})
        pf["total"] += 1
        pf[t] += 1
    for c in chains:
        a = by_agent.get(c["agent"])
        if a is None:
            continue
        a["chains"] += 1
        a["span"] += c.get("span", 0.0)
        a["rereads"] += c.get("rereads", 0)
        a["reedits"] += c.get("reedits", 0)
    agents = []
    for a in sorted(by_agent.values(), key=lambda a: -a["total"]):
        a = dict(a)
        a["distinct"] = len(a.pop("files"))
        agents.append(a)
    top = sorted(per_file.items(), key=lambda kv: (-kv[1]["total"], kv[0]))[:top_n]
    ts_list = [e.get("ts", 0) for e in day_evs]
    return {"day": day, "days": days, "total": len(day_evs),
            "distinct": len(per_file),
            "by_type": {t: sum(h[t] for h in hours) for t in DASH_TYPES},
            "chains": len(chains),
            "span_total": sum(c.get("span", 0.0) for c in chains),
            "rereads": sum(c.get("rereads", 0) for c in chains),
            "first": min(ts_list) if ts_list else None,
            "last": max(ts_list) if ts_list else None,
            "agents": agents, "hours": hours,
            "top": [{"file": f, "n": r["total"],
                     "types": {t: r[t] for t in DASH_TYPES}} for f, r in top]}


_FAVICON = {"raw": None}


def favicon_bytes():
    """Icon app dạng `.ico` — CÙNG nguồn vẽ với icon shortcut (`install_launcher`),
    không có bản vẽ thứ hai để lệch nhau.

    Vì sao phải phục vụ file thật thay vì `<link rel=icon href="data:…">`: Chromium
    **bỏ qua favicon dạng data: URI**, nên cửa sổ app (`ensure --app`) không có icon
    nào và rơi về icon Edge/Chrome — đúng triệu chứng báo 28/07. Vẽ ~0.3s nên cache
    lại; server tự restart khi `install_launcher.py` đổi (nằm trong _VERSION_FILES)."""
    if _FAVICON["raw"] is None:
        try:
            import install_launcher
            _FAVICON["raw"] = install_launcher.icon_bytes((16, 32, 48, 64))
        except Exception as exc:                   # noqa: BLE001
            print("favicon: khong ve duoc (%s)" % exc)
            _FAVICON["raw"] = b""
    return _FAVICON["raw"]


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive: 3 vòng poll của UI (800ms + 4s + 4s) tái dùng kết nối
    # thay vì bắt tay TCP mới mỗi request (mọi response đều kèm Content-Length nên
    # an toàn); timeout dọn kết nối idle để thread không treo vô hạn chờ request kế.
    protocol_version = "HTTP/1.1"
    timeout = 75

    def _host_ok(self):
        """Reject DNS-rebinding Host names before any GET can expose local paths/data."""
        raw = (self.headers.get("Host") or "").strip().lower()
        if not raw:                           # HTTP/1.0 script on the local machine
            return True
        if raw.startswith("["):
            host = raw[1:].split("]", 1)[0]
        else:
            host = raw.rsplit(":", 1)[0] if ":" in raw else raw
        return host in ("127.0.0.1", "localhost", "::1")

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            self._send(403, b'{"error":"host khong hop le"}')
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/favicon.ico":
            raw = favicon_bytes()
            if raw:
                self._send(200, raw, "image/x-icon")
            else:                                  # không vẽ được icon: im lặng như cũ
                self.send_response(204)
                self.end_headers()
            return

        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", MIME[".html"])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/graph-data":
            body = json.dumps(get_graph_data(), ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/vault-state":
            # Full path chỉ trả trên loopback, dùng làm tooltip và initial directory
            # cho native picker. Browser khác origin không đọc được response (không CORS).
            state = dict(_VAULT_CTX)
            state["boot_id"] = BOOT_ID
            state["telemetry"] = "full" if APP_TELEMETRY else (
                "stored" if (ACTIVE_JOURNAL_DIR or ACTIVE_HEAT_DIR) else "codex_only")
            self._send(200, json.dumps(state, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/ping":
            # Cổng cho agent KHÁC Claude Code (Hermes, script, curl…) báo hoạt động:
            #   GET /ping?type=read&file=Projects/Demo/Note.md&agent=Hermes  (file lặp lại được)
            if not APP_TELEMETRY:
                self._send(409, json.dumps(
                    {"ok": False, "logged": 0, "code": "telemetry_unavailable",
                     "error": "logger hiện không có vault identity cho vault ngoài"},
                    ensure_ascii=False).encode("utf-8"))
                return
            qs = parse_qs(parsed.query)
            ev = qs.get("type", ["read"])[0]
            agent = qs.get("agent", [None])[0]
            n = log_activity.append_events(ev, qs.get("file", []), agent=agent)
            self._send(200, json.dumps({"ok": True, "logged": n}).encode("utf-8"))
            return

        if path == "/health":
            # ensure/run đọc để quyết định: dùng lại (version khớp) hay giết + khởi động lại.
            body = json.dumps({"ok": True, "version": VERSION, "boot_id": BOOT_ID,
                               "pid": os.getpid(), "vault_id": _VAULT_CTX["id"],
                               "vault_name": _VAULT_CTX["name"]},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/shutdown":
            # Dừng sạch (chỉ 127.0.0.1 mới gọi được vì server chỉ bind loopback).
            # serve_forever() trả về → main() exit 0 → supervisor KHÔNG relaunch.
            self._send(200, b'{"ok":true,"stopping":true}')
            if _httpd is not None:
                threading.Thread(target=_httpd.shutdown, daemon=True).start()
            return

        if path == "/activity":
            qs = parse_qs(parsed.query)
            replay = qs.get("replay", ["0"])[0].lower() in ("1", "true", "yes")
            # cursor = JSON {path: offset}, mỗi nguồn một cursor. Client CŨ (trang
            # chưa hard-refresh sau deploy) gửi SỐ → không map được vào nguồn nào:
            # trả rỗng + stale_client thay vì đoán bừa/ném lỗi.
            cursors, legacy = {}, False
            try:
                raw = json.loads(qs.get("cursor", ["{}"])[0])
                if isinstance(raw, dict):
                    cursors = {str(k): int(v) for k, v in raw.items()
                               if isinstance(v, (int, float))}
                else:
                    legacy = True
            except ValueError:
                legacy = True
            if legacy and not replay:
                body = json.dumps({"cursor": {}, "file_size": 0, "events": [],
                                   "boot_id": BOOT_ID, "replay": False,
                                   "stale_client": True,
                                   "log": active_activity_log_path() if APP_TELEMETRY else None},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, body)
                return
            new_cursors, events, forced = read_activity_all(cursors, replay=replay)
            body = json.dumps({"cursor": new_cursors,
                               "file_size": sum(new_cursors.values()),
                               "events": events, "boot_id": BOOT_ID,
                               "replay": bool(replay or forced),
                                "log": active_activity_log_path() if APP_TELEMETRY else None},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/chains":
            # Gom event thành chuỗi truy xuất theo agent (đo hiệu quả + soi cấu trúc).
            qs = parse_qs(parsed.query)
            try:
                gap = float(qs.get("gap", [str(CHAIN_GAP)])[0])
            except ValueError:
                gap = CHAIN_GAP
            try:
                limit = int(qs.get("limit", ["40"])[0])
            except ValueError:
                limit = 40
            evs = read_all_events()
            chains = build_chains(evs, gap=gap, limit=limit)
            agents = sorted({(e.get("agent") or "Claude") for e in evs})
            body = json.dumps({"gap": gap, "boot_id": BOOT_ID,
                               "agents": agents, "chains": chains},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/heat":
            # Tần suất truy xuất mỗi note → heatmap. scope=window (log cuộn, ngắn hạn)
            # hoặc scope=all (tích luỹ dài hạn từ store trong vault).
            qs = parse_qs(parsed.query)
            scope = qs.get("scope", ["window"])[0].lower()
            heat = build_heat_cumulative() if scope == "all" else build_heat(read_all_events())
            body = json.dumps(heat, ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/search":
            # Finder (giai đoạn 2 Vault Cockpit): full-text search — quick switcher
            # gọi debounce 250ms. Không dấu, AND mọi từ; xem search_notes().
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0][:200]
            try:
                limit = int(qs.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            res = search_notes(q, limit=limit)
            body = json.dumps({"q": q, "total": len(res), "results": res},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/timeline":
            # Cockpit (giai đoạn 3 Vault Cockpit): TOÀN BỘ event của MỘT ngày để UI
            # phát lại — mọi nguồn log (dedup sẵn trong read_all_events), kèm danh
            # sách ngày còn trong log cuộn. day rỗng/lạ → ngày mới nhất.
            qs = parse_qs(parsed.query)
            evs = read_all_events()
            day_evs, days, day = events_for_day(evs, qs.get("day", [""])[0])
            body = json.dumps({"day": day, "days": days, "count": len(day_evs),
                               "boot_id": BOOT_ID, "host": host_name(),
                               "events": [{"ts": e.get("ts"), "file": e.get("file"),
                                           "type": e.get("type", "read"),
                                           "agent": e.get("agent") or "Claude",
                                           "host": e.get("host")}
                                          for e in day_evs]},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/dashboard":
            # Cockpit: tổng hợp hiệu quả truy xuất một ngày — xem build_dashboard().
            qs = parse_qs(parsed.query)
            try:
                gap = float(qs.get("gap", [str(CHAIN_GAP)])[0])
            except ValueError:
                gap = CHAIN_GAP
            dash = build_dashboard(read_all_events(), day=qs.get("day", [""])[0], gap=gap)
            dash["boot_id"] = BOOT_ID
            body = json.dumps(dash, ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/insight":
            # "Vault đang khoẻ không" + worklist H3: cùng build_insight/build_worklist
            # mà CLI `insight.py --report` gọi, không có bộ đếm thứ hai. Chỉ ĐỌC:
            # event đã cache theo mtime + graph cache 3s + store heat, không ghi gì.
            qs = parse_qs(parsed.query)

            def _int(name, default, lo, hi):
                try:
                    return max(lo, min(hi, int(qs.get(name, [str(default)])[0])))
                except ValueError:
                    return default
            days = _int("days", insight.DEFAULT_DAYS, 1, 90)
            cold = _int("cold", insight.DEFAULT_COLD, 1, 365)
            heat_notes, heat_meta = merge_cumulative_stores()
            graph = get_graph_data()
            events = read_all_events()
            ins = insight.build_insight(events, graph,
                                        heat_notes=heat_notes, heat_meta=heat_meta,
                                        days=days, cold_days=cold,
                                        taxonomy_result=insight.measure_taxonomy(graph, vault=VAULT),
                                        chains=build_chains(events, limit=len(events) + 1))
            ins["boot_id"] = BOOT_ID
            ins["host"] = host_name()
            self._send(200, json.dumps(ins, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/integrity":
            # Đèn báo toàn vẹn vault (W11): tính trong integrity.collect — cùng hàm
            # mà CLI `integrity.py` gọi. Chỉ ĐỌC (cache theo chữ ký mtime toàn vault
            # + mtime nguồn luật), không ghi gì; lỗi đọc trả 500 kèm thông điệp.
            qs = parse_qs(parsed.query)
            try:
                limit = max(1, min(500, int(qs.get("limit", [str(integrity.LIST_N)])[0])))
            except ValueError:
                limit = integrity.LIST_N
            try:
                rep = dict(integrity.collect(vault=VAULT, list_n=limit))   # active vault, không app vault
            except Exception as exc:                          # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            rep["boot_id"] = BOOT_ID
            rep["host"] = host_name()
            self._send(200, json.dumps(rep, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/update":
            # Bản mới trên repo (W69). `status()` KHÔNG bao giờ tự gọi ra internet —
            # chỉ khi client hỏi kèm `?refresh=1` mới cân nhắc đi hỏi, và chính
            # `update_check.refresh()` tự chặn theo consent + TTL 1 ngày + rate limit.
            # Nhờ vậy một lần F5 không thể biến thành một lần gọi ra ngoài ngoài ý muốn.
            qs = parse_qs(parsed.query)
            if qs.get("refresh", ["0"])[0] == "1":
                try:
                    update_check.refresh(here=HERE)
                except Exception:              # noqa: BLE001 — mạng hỏng KHÔNG phải lỗi app
                    pass
            body = json.dumps(update_check.status(HERE), ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/onboarding":
            # Vault TRỐNG (W13): UI hỏi "có gì để mời user vào không" — số note lấy
            # từ cache graph (khỏi quét lần hai), phần còn lại là những lối đi có
            # SẴN trên máy này (starter-vault/ + demo/vault/ bundled hay không).
            st = onboarding.state(VAULT, notes=get_graph_data()["meta"]["notes"])
            st["boot_id"] = BOOT_ID
            self._send(200, json.dumps(st, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/work":
            # Work Map — xem workmap_export(). Lỗi registry/engine trả 500 kèm
            # thông điệp để UI hiện thẳng, đừng nuốt im.
            try:
                data = workmap_export()
            except Exception as exc:                              # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            if data is None:
                self._send(404, b'{"error":"vault nay khong co work map"}')
                return
            self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/note":
            # Reader (giai đoạn 1 Vault Cockpit): markdown thô của 1 note — client
            # tự render (markdown-it) + tự strip frontmatter. Chỉ .md trong vault.
            qs = parse_qs(parsed.query)
            full = vault_file(qs.get("path", [""])[0], exts={".md"})
            if not full:
                self._send(404, b'{"error":"note not found"}')
                return
            with open(full, "rb") as f:
                raw = f.read()
            st = os.stat(full)
            body = json.dumps({"path": qs["path"][0], "size": st.st_size,
                               "mtime": st.st_mtime,
                               "text": raw.decode("utf-8", errors="replace")},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body)
            return

        if path == "/asset":
            # Reader: file đính kèm note (ảnh/video/pdf…) — mọi file trong vault
            # NGOÀI dot-folder; đuôi lạ trả octet-stream (trình duyệt tự tải về).
            # Asset có thể đến từ folder bất kỳ user vừa chọn. CSP sandbox chặn
            # HTML/SVG/PDF chủ động chạy script cùng origin rồi gọi các POST local.
            qs = parse_qs(parsed.query)
            full = vault_file(qs.get("path", [""])[0])
            if not full:
                self._send(404, b'{"error":"asset not found"}')
                return
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as f:
                self._send(200, f.read(), MIME.get(ext, "application/octet-stream"), {
                    "Content-Security-Policy": (
                        "sandbox; default-src 'none'; img-src data:; "
                        "media-src 'self'; style-src 'unsafe-inline'"),
                    "Cross-Origin-Resource-Policy": "same-origin",
                })
            return

        # /src/* = ES modules + CSS của UI — đọc thẳng từ đĩa mỗi request (no-store qua
        # _send, sửa module chỉ cần F5); /vendor/* = thư viện tĩnh.
        full = app_static_file(path)
        if full:
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as f:
                self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))
            return

        self._send(404, b'{"error":"not found"}')

    # ---- POST: các hành động có tác dụng phụ cục bộ ----
    # Mọi thứ khác của app là GET thuần đọc. Các endpoint này CỐ Ý là POST: chúng ghi
    # file, spawn process hoặc mở app/file manager. POST cùng-origin luôn kèm header
    # Origin ⇒ so Origin là hàng rào CSRF đủ chặt cho server local.
    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True                      # curl / script trên chính máy này
        return origin in ("http://127.0.0.1:%d" % PORT[0],
                          "http://localhost:%d" % PORT[0])

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._host_ok():
            self._send(403, b'{"error":"host khong hop le"}')
            return
        if not self._origin_ok():
            self._send(403, b'{"error":"origin khong hop le"}')
            return

        if path == "/vault-pick":
            if _VAULT_CTX.get("locked"):
                self._send(409, json.dumps(
                    {"error": "vault bị khoá bởi --vault/demo", "code": "locked"},
                    ensure_ascii=False).encode("utf-8"))
                return
            try:
                chosen = vault_switcher.choose_folder(VAULT)
            except vault_switcher.VaultSwitchError as exc:
                self._send(400, json.dumps(
                    {"error": str(exc), "code": exc.code},
                    ensure_ascii=False).encode("utf-8"))
                return
            if not chosen:
                self._send(200, b'{"ok":true,"cancelled":true,"changed":false}')
                return
            if vault_switcher.same_vault(chosen, VAULT):
                # Nếu đang fallback vì saved path hỏng, chọn lại chính app vault phải
                # xóa cảnh báo bền. Restart để /vault-state của process mới sạch.
                if _VAULT_CTX.get("warning"):
                    try:
                        vault_switcher.save_selection(chosen)
                    except (vault_switcher.VaultSwitchError, OSError) as exc:
                        self._send(400, json.dumps(
                            {"error": str(exc), "code": getattr(exc, "code", "save_failed")},
                            ensure_ascii=False).encode("utf-8"))
                        return
                    self._send(200, json.dumps(
                        {"ok": True, "cancelled": False, "changed": True,
                         "vault": _VAULT_CTX["name"], "vault_id": _VAULT_CTX["id"],
                         "boot_id": BOOT_ID}, ensure_ascii=False).encode("utf-8"))
                    EXIT_CODE[0] = 4
                    if _httpd is not None:
                        threading.Timer(0.25, _httpd.shutdown).start()
                    return
                self._send(200, json.dumps(
                    {"ok": True, "cancelled": False, "changed": False,
                     "vault": _VAULT_CTX["name"], "vault_id": _VAULT_CTX["id"]},
                    ensure_ascii=False).encode("utf-8"))
                return
            try:
                vault_switcher.save_selection(chosen)
                new_id = vault_switcher.vault_id(chosen)
            except (vault_switcher.VaultSwitchError, OSError) as exc:
                self._send(400, json.dumps(
                    {"error": str(exc), "code": getattr(exc, "code", "save_failed")},
                    ensure_ascii=False).encode("utf-8"))
                return
            self._send(200, json.dumps(
                {"ok": True, "cancelled": False, "changed": True,
                 "vault": os.path.basename(chosen) or chosen, "vault_id": new_id,
                 "boot_id": BOOT_ID}, ensure_ascii=False).encode("utf-8"))
            # Response phải rời socket trước. serve_forever trả về code 4; supervisor
            # đọc config MỚI và spawn process mới cùng port.
            EXIT_CODE[0] = 4
            if _httpd is not None:
                threading.Timer(0.25, _httpd.shutdown).start()
            return

        if path == "/file-action":
            qs = parse_qs(urlparse(self.path).query)
            rel = qs.get("path", [""])[0]
            action = qs.get("action", [""])[0]
            try:
                res = run_file_action(rel, action)
            except ValueError as exc:
                self._send(400, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            except FileNotFoundError:
                self._send(404, json.dumps({"error": "file khong ton tai"},
                                           ensure_ascii=False).encode("utf-8"))
                return
            except OSError as exc:
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/starter-init":
            # Dựng vault ĐẦU TIÊN ngay trong app: chép starter-vault/ vào vault đang
            # trống. Hàng rào "vault phải trống" + "không đè file" nằm trong
            # onboarding.install_starter (một chỗ, CLI dùng chung).
            try:
                res = onboarding.install_starter(VAULT)
            except onboarding.OnboardingError as exc:
                self._send(400, json.dumps({"error": str(exc),
                                            "code": getattr(exc, "code", "")},
                                           ensure_ascii=False).encode("utf-8"))
                return
            except OSError as exc:
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            with _cache_lock:                # vault vừa đổi → /graph-data phải quét lại ngay
                _cache["data"] = None
            self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/demo-start":
            # Mở cockpit trên vault demo bundled. Server KHÔNG tự chạy serve.py —
            # nó gọi ensure_graph3d.py (điểm vào idempotent) đúng như launcher, và
            # trên PORT KHÁC nên server hiện tại không bị đụng.
            st = onboarding.state(VAULT)
            if not st["demo"]["available"]:
                self._send(400, json.dumps(
                    {"error": "bản cài này không kèm vault demo (%s)" % st["demo"]["path"],
                     "code": "demo_missing"},
                    ensure_ascii=False).encode("utf-8"))
                return
            port = st["demo"]["port"]
            try:
                subprocess.Popen(
                    [sys.executable, os.path.join(HERE, "ensure_graph3d.py"),
                     "--demo", "--no-open", "--port", str(port)],
                    cwd=HERE, env=onboarding.demo_env(), close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, **no_window_kwargs())
            except OSError as exc:
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            # Chép app + khởi động mất vài giây; chờ hộ client (mỗi request một thread)
            # để UI chỉ việc nhảy sang URL khi đã chắc chắn có server.
            h = onboarding.wait_health(port, timeout=45.0)
            if not h:
                self._send(504, json.dumps(
                    {"error": "demo chưa báo khoẻ sau 45s — chạy tay: %s" % st["cmd"]["demo"]},
                    ensure_ascii=False).encode("utf-8"))
                return
            self._send(200, json.dumps({"url": "http://127.0.0.1:%d" % port,
                                        "port": port, "notes": st["demo"]["notes"]},
                                       ensure_ascii=False).encode("utf-8"))
            return

        if path == "/update-consent":
            # Người dùng trả lời câu hỏi "cho phép kiểm tra bản mới?" — ĐÂY là chỗ duy
            # nhất bật được việc gọi ra internet. Trả lời "không" cũng được ghi nhớ để
            # không hỏi lại lần sau (`asked`).
            qs = parse_qs(urlparse(self.path).query)
            on = qs.get("value", ["off"])[0] == "on"
            try:
                update_check.set_consent(on, here=HERE)
            except Exception as exc:           # noqa: BLE001
                self._send(500, json.dumps({"error": str(exc)},
                                           ensure_ascii=False).encode("utf-8"))
                return
            self._send(200, json.dumps(update_check.status(HERE),
                                       ensure_ascii=False).encode("utf-8"))
            return

        if path == "/update-pull":
            # Cập nhật tại chỗ = `git pull --ff-only`, và CHỈ khi 4 điều kiện của
            # `pull_precheck` đạt (là repo · có origin · không detached · tree sạch).
            # Không bao giờ đè lên thay đổi của người dùng; hoà giải được thì để họ tự.
            res = update_check.pull(HERE)
            self._send(200 if res.get("ok") else 400,
                       json.dumps(res, ensure_ascii=False).encode("utf-8"))
            return

        self._send(404, b'{"error":"not found"}')

    def log_message(self, fmt, *args):  # im lặng, tránh lỗi encoding console
        pass


def _restart_sources_sane():
    """Chống restart vào nguồn OneDrive đang ghi DỞ: file .py phải compile được,
    index.html phải kết thúc bằng </html>. Hỏng → coi như CHƯA ổn định, chờ bản
    hoàn chỉnh ở tick sau thay vì relaunch vào code cụt (review P5.9)."""
    for name in restart_py_files():          # derive từ _VERSION_FILES — đừng chép tay
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                compile(f.read(), name, "exec")
        except (OSError, SyntaxError, ValueError):
            return False
    try:
        p = os.path.join(HERE, "index.html")
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            f.seek(max(0, size - 64))
            if b"</html>" not in f.read():
                return False
    except OSError:
        return False
    # src/* (ES modules + CSS): file rỗng hoặc cụt đuôi (không kết thúc \n) = đang ghi dở
    try:
        for sp in glob.glob(os.path.join(HERE, "src", "*")):
            if not os.path.isfile(sp):
                continue
            ssize = os.path.getsize(sp)
            if ssize == 0:
                return False
            with open(sp, "rb") as f:
                f.seek(ssize - 1)
                if f.read(1) != b"\n":
                    return False
    except OSError:
        return False
    return True


def _watch_source():
    """Tự thoát (exit 3) khi mã nguồn cần-restart đổi → supervisor relaunch.
    Diệt gotcha 'sửa serve.py/index.html xong quên restart'. Chống thrash:
    hash mới phải ỔN ĐỊNH 2 tick liên tiếp (~4s) VÀ nguồn lành lặn mới thoát."""
    pending, count = None, 0
    while True:
        time.sleep(2.0)
        cur = source_version(HERE)
        if cur is None or cur == VERSION:
            pending, count = None, 0
            continue
        count = count + 1 if cur == pending else 1
        pending = cur
        if count >= 2:
            if _restart_sources_sane():
                os._exit(3)
            pending, count = None, 0   # nguồn đang ghi dở → chờ bản hoàn chỉnh


def main():
    global _httpd
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    PORT[0] = args.port                      # hàng rào Origin của do_POST so theo port này

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        # Port đã bị process khác giữ — exit 75 để supervisor xử lý (nhường / giết zombie).
        print("KB Graph 3D: port %d dang bi giu (%s) -> exit 75" % (args.port, e))
        sys.exit(75)

    _httpd = server
    url = "http://127.0.0.1:%d" % args.port
    print("KB Graph 3D: %s  (vault: %s id=%s)  version=%s boot=%s"
          % (url, VAULT, _VAULT_CTX["id"], VERSION, BOOT_ID))
    print("Ctrl+C de dung server.")
    threading.Thread(target=_watch_source, daemon=True).start()
    if not args.no_open:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    # serve_forever chỉ trả về khi có /shutdown hoặc Ctrl+C → dừng hẳn, exit 0
    # (supervisor thấy code 0 sẽ KHÔNG relaunch). Reload code do _watch_source lo (exit 3).
    sys.exit(EXIT_CODE[0])


if __name__ == "__main__":
    main()
