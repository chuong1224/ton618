# -*- coding: utf-8 -*-
"""Tiện ích dùng chung cho KB Graph 3D — đường dẫn log + version code.

serve.py / log_activity.py / ensure_graph3d.py / run_graph3d.py đều import.
"""
import glob
import hashlib
import json
import os
import re
import socket
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# TON618 v2: đổi thương hiệu, giữ identity dữ liệu để nâng/hạ phiên bản không mất state.
APP_NAME = "TON618"
APP_TITLE = "TON618 — Knowledge Base"
APP_TITLE_ALIASES = ("TON618", "KB Graph 3D")


def parse_jsonl(text):
    """Các dòng JSONL → list dict (dòng hỏng/dở bỏ qua). Bộ parse DUY NHẤT dùng chung
    serve.py + log_activity.py — trước đây 3 bản chép tay lệch nhau dần (review P4.1)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def local_data_dir():
    """Thư mục dữ liệu local của app — NGOÀI OneDrive (%LOCALAPPDATA%): log realtime,
    icon + log của launcher. Thứ gì ghi liên tục hoặc mang tính máy-này thì để đây,
    thứ gì cần máy KHÁC đọc được thì vào vault (journal/heat per-máy)."""
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(base, "claude-graph3d")


def activity_log_path():
    env = os.environ.get("GRAPH3D_ACTIVITY_FILE", "").strip()
    if env:
        return os.path.normpath(env)
    return os.path.join(local_data_dir(), "activity.jsonl")


# Claude Desktop (Cowork) là app đóng gói MSIX: Windows ẢO HÓA mọi ghi vào %LOCALAPPDATA%
# sang LocalCache riêng của package. Hook chạy DƯỚI Cowork ghi activity.jsonl vào đó, còn
# serve.py chạy bằng python thường (NGOÀI sandbox) lại đọc đường "thật" (trống) → graph
# không thấy hoạt động Cowork. READER phải soi thêm đường LocalCache này — QUÉT GLOB
# Packages/Claude_*/ thay vì hardcode publisher hash: Anthropic đổi tên gói, lớp vá
# vẫn sống (review P4.2). Glob quét folder Packages hơi tốn nên cache 30s.
_cand_cache = {"ts": 0.0, "paths": None}
_codex_cand_cache = {"ts": 0.0, "root": None, "paths": None}


def activity_log_candidates():
    """Mọi file activity.jsonl có thể tồn tại — để READER (serve.py) không bỏ sót nguồn:
      1) đường chuẩn %LOCALAPPDATA%/claude-graph3d (Claude Code CLI ghi thẳng)
      2) LocalCache của MỌI package Claude_* (Cowork/Claude Desktop ghi qua ảo hóa MSIX)
    Nếu đã đặt GRAPH3D_ACTIVITY_FILE (override tường minh) thì CHỈ dùng đúng đường đó."""
    env = os.environ.get("GRAPH3D_ACTIVITY_FILE", "").strip()
    if env:
        return [os.path.normpath(env)]
    now = time.time()
    if _cand_cache["paths"] is not None and now - _cand_cache["ts"] < 30:
        return list(_cand_cache["paths"])
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    cands = [os.path.join(local_data_dir(), "activity.jsonl")]
    cands.extend(sorted(glob.glob(os.path.join(
        base, "Packages", "Claude_*", "LocalCache", "Local",
        "claude-graph3d", "activity.jsonl"))))
    seen, out = set(), []
    for p in cands:
        n = os.path.normcase(os.path.normpath(p))
        if n not in seen:
            seen.add(n)
            out.append(p)
    _cand_cache["ts"], _cand_cache["paths"] = now, out
    return list(out)


def codex_session_candidates():
    """Rollout JSONL cua Codex Desktop co the chua thao tac vault.

    Codex khong chay hook Claude ``PostToolUse`` nen day la nguon read-only de
    serve.py doi thao tac tool thanh event ``agent=Codex``. Chi quet file rollout;
    parser ben duoi khong dua prompt hay output tool vao Graph.

    ``GRAPH3D_CODEX_SESSIONS`` co the tro thang vao thu muc ``sessions``; gia tri
    ``off``/``0`` tat adapter. Khi test dat ``GRAPH3D_ACTIVITY_FILE`` ma khong dat
    root Codex tuong minh, adapter cung tat de override giu tinh quyet dinh.
    """
    override = os.environ.get("GRAPH3D_CODEX_SESSIONS")
    if override is not None and override.strip().casefold() in ("", "0", "off", "false", "none"):
        return []
    if override is None and os.environ.get("GRAPH3D_ACTIVITY_FILE", "").strip():
        return []
    if override is not None:
        root = os.path.normpath(os.path.expandvars(os.path.expanduser(override.strip())))
    else:
        home = os.environ.get("CODEX_HOME", "").strip()
        if not home:
            home = os.path.join(os.path.expanduser("~"), ".codex")
        root = os.path.join(home, "sessions")
    now = time.time()
    if (_codex_cand_cache["paths"] is not None
            and _codex_cand_cache["root"] == root
            and now - _codex_cand_cache["ts"] < 5):
        return list(_codex_cand_cache["paths"])
    cands = sorted(glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl")))
    # Bao ve app khoi vault Codex rat lau nam: Agent Activity la cua so van hanh,
    # 200 session gan nhat du de giu lich su ma khong doc hang GB moi lan poll.
    cands = cands[-200:]
    _codex_cand_cache.update({"ts": now, "root": root, "paths": cands})
    return list(cands)


def is_codex_rollout(path):
    name = os.path.basename(str(path)).casefold()
    return name.startswith("rollout-") and name.endswith(".jsonl")


_JS_DQ = r'"(?:\\.|[^"\\])*"'
_JS_SQ = r"'(?:\\.|[^'\\])*'"
_JS_BT = r"`(?:\\.|[^`\\])*`"
_JS_STRING_RE = re.compile("(?:%s|%s|%s)" % (_JS_DQ, _JS_SQ, _JS_BT), re.DOTALL)
_MD_QUOTED_RE = re.compile(r"(['\"])([^'\"\r\n]*?\.md(?::\d+)?)\1", re.IGNORECASE)
_MD_BARE_RE = re.compile(
    r"(?<![\w*?])((?:[A-Za-z]:[\\/]|\.{0,2}[\\/])?"
    r"[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*\.md(?::\d+)?)"
    r"(?=$|[\s,;)])", re.IGNORECASE)


def _decode_js_string(token):
    if not token:
        return ""
    if token[0] == '"':
        try:
            return json.loads(token)
        except (ValueError, TypeError):
            return ""
    body = token[1:-1]
    # Du cho command/template Codex: giai cac escape path/newline pho bien, khong
    # danh gia JavaScript va khong noi suy ${...}.
    return (body.replace(r"\\", "\\")
                .replace(r"\'", "'")
                .replace(r'\"', '"')
                .replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t"))


def _js_strings(source):
    return [_decode_js_string(m.group(0)) for m in _JS_STRING_RE.finditer(source or "")]


def _field_js_string(source, field):
    m = re.search(r"\b%s\s*:\s*(%s|%s|%s)" %
                  (re.escape(field), _JS_DQ, _JS_SQ, _JS_BT),
                  source or "", re.DOTALL)
    return _decode_js_string(m.group(1)) if m else ""


def _codex_ts(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return 0.0


def _note_rel(path, vault, workdir=None):
    path = str(path or "").strip().strip('"').strip("'")
    path = re.sub(r":\d+$", "", path)
    if not path or "*" in path or "?" in path or not path.casefold().endswith(".md"):
        return None
    # realpath ca hai dau de alias Windows 8.3 va ten user day du khong lam
    # os.path.relpath sinh duong `../..` gia roi loai oan note hop le.
    vault = os.path.realpath(os.path.abspath(vault))
    base = os.path.realpath(os.path.abspath(workdir or vault))
    ap = os.path.realpath(os.path.normpath(
        path if os.path.isabs(path) else os.path.join(base, path)))
    try:
        if os.path.normcase(os.path.commonpath([ap, vault])) != os.path.normcase(vault):
            return None
    except ValueError:
        return None
    # Chi log note co that: day la lop chong false-positive khi command/prompt co
    # chuoi ket thuc .md nhung khong he truy cap file nao.
    if not os.path.isfile(ap):
        return None
    rel = os.path.relpath(ap, vault).replace("\\", "/")
    if rel.split("/", 1)[0].startswith("."):
        return None
    return rel


def _md_paths(text):
    out = [m.group(2) for m in _MD_QUOTED_RE.finditer(text or "")]
    out.extend(m.group(1) for m in _MD_BARE_RE.finditer(text or ""))
    seen, uniq = set(), []
    for path in out:
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            uniq.append(path)
    return uniq


def _command_type(command):
    low = (command or "").casefold()
    if any(x in low for x in ("apply_patch", "set-content", "remove-item", "move-item")):
        return "edit"
    if re.search(r"(^|[\s;&|])(rg|grep|findstr)(?:\.exe)?([\s;&|]|$)", low) or "select-string" in low:
        return "search"
    return "read"


def _codex_exec_events(source, ts, vault):
    events, seen = [], set()

    def add(ev_type, paths, workdir=None):
        for path in paths:
            rel = _note_rel(path, vault, workdir=workdir)
            key = (ev_type, rel)
            if rel and key not in seen:
                seen.add(key)
                events.append({"ts": ts, "type": ev_type, "file": rel, "agent": "Codex"})
            if len(events) >= 40:
                return

    # apply_patch: chi marker dich, khong quet noi dung patch (noi dung co the nhac
    # nhieu wikilink/.md khong duoc mo). Marker nam trong JS string da decode.
    for text in _js_strings(source):
        if "*** Begin Patch" not in text:
            continue
        paths = re.findall(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+?)\s*$",
                           text, re.MULTILINE)
        add("edit", paths)

    workdir = _field_js_string(source, "workdir") or vault
    # command truc tiep hoac template/variable literal co chua lenh. Khong dung
    # custom_tool_call_output: output co the la toan bo noi dung note, quet no se
    # bien moi wikilink trong bai thanh activity gia.
    commands = []
    direct = _field_js_string(source, "command")
    if direct:
        commands.append(direct)
    for text in _js_strings(source):
        low = text.casefold()
        if ".md" in low and any(x in low for x in
                                ("get-content", "select-string", "rg ", "rg.exe", "grep ",
                                 "findstr", "test-path", "git diff")):
            commands.append(text)
    for command in commands:
        if "*** Begin Patch" in command:
            continue
        add(_command_type(command), _md_paths(command), workdir=workdir)
    return events


def parse_codex_rollout(text, vault=None):
    """Chuyen rollout JSONL Codex thanh event activity toi gian.

    Dau ra CHI gom ``ts/type/file/agent``. Khong doc/giu prompt, reasoning, output
    tool hay noi dung note. Moi path phai resolve thanh file ``.md`` co that nam
    ben trong vault.
    """
    vault = os.path.abspath(vault or os.path.dirname(HERE))
    out = []
    for row in parse_jsonl(text):
        payload = row.get("payload") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            continue
        if payload.get("type") not in ("custom_tool_call", "function_call"):
            continue
        if payload.get("name") != "exec":
            continue
        source = payload.get("input") or payload.get("arguments")
        if not isinstance(source, str):
            continue
        ts = _codex_ts(row.get("timestamp"))
        if not ts:
            continue
        out.extend(_codex_exec_events(source, ts, vault))
    out.sort(key=lambda ev: ev["ts"])
    return out


def active_activity_log_path():
    """File activity 'đang sống' = tồn tại + mtime MỚI NHẤT trong các ứng viên (tự bám
    nguồn đang ghi: Cowork qua LocalCache hoặc CLI qua đường chuẩn). Dùng cho realtime
    /activity để GIỮ nguyên mô hình byte-cursor trên MỘT file. Fallback: đường chuẩn."""
    best, best_m = None, -1.0
    for p in activity_log_candidates():
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m > best_m:
            best, best_m = p, m
    return best or activity_log_path()


def host_name():
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "unknown").strip() or "unknown"


def no_window_kwargs():
    """kwargs cho `subprocess` để tiến trình con KHÔNG loé cửa sổ console đen.

    Bắt buộc cho MỌI lần gọi công cụ dòng lệnh lúc app đang chạy: server chạy bằng
    `pythonw.exe` (không console), nên mỗi lần spawn một tiến trình console —
    `git`, `netstat`, `taskkill` — Windows sẽ **cấp cho nó một cửa sổ mới**. Người dùng
    thấy khung đen nhấp nháy rồi tắt, và cảm giác đầu tiên là "app này có gì đó không
    ổn" — đúng phản hồi nhận được ngay sau khi phát hành tính năng kiểm bản mới.

    Trả dict rỗng ngoài Windows để chỗ gọi không phải rẽ nhánh theo hệ điều hành."""
    return {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW


SEMVER_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def app_version(here=None):
    """Semver của app (`v1.49.0`) — ĐỌC TỪ BADGE trong `index.html`, tuyệt đối không
    khai thành hằng số thứ hai ở đây.

    Lý do: badge là nguồn duy nhất từ trước tới nay và contract 2i của selfcheck gác
    cho nó chỉ xuất hiện ĐÚNG MỘT LẦN trong index+src. Thêm một hằng số Python nữa là
    đẻ ra bản chép thứ hai — đúng lớp drift mà cả H1 (`vault-rules.json`) lẫn `APP_PY`
    sinh ra để diệt. Trả None nếu không đọc được: caller phải chịu được chuyện đó chứ
    không được đoán bừa một số."""
    here = here or HERE
    try:
        with open(os.path.join(here, "index.html"), encoding="utf-8") as f:
            m = SEMVER_RE.search(f.read())
    except OSError:
        return None
    return m.group(0) if m else None


def parse_semver(text):
    """'v1.49.0' / '1.49.0' → (1, 49, 0); không phải semver → None (tag lạ trên repo
    bị bỏ qua thay vì làm hỏng phép so sánh)."""
    if not text:
        return None
    m = SEMVER_RE.search(text if text.startswith("v") else "v" + text.lstrip("v"))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def cumulative_heat_dir():
    """Thư mục chứa store heat tích luỹ. Env GRAPH3D_HEAT_DIR là override cho TEST và
    cho server DEMO (W13) — file runtime mang TÊN MÁY không được rơi vào working tree
    repo public; mirror pattern GRAPH3D_JOURNAL_DIR."""
    env = os.environ.get("GRAPH3D_HEAT_DIR", "").strip()
    return os.path.normpath(env) if env else HERE


def cumulative_heat_path():
    """Store heat TÍCH LUỸ dài hạn — TRONG vault (sync OneDrive), PER-MÁY để tránh
    conflict đa máy (giống graph-<HOST>.json của graph 2D). Dùng phân tích lâu dài."""
    return os.path.join(cumulative_heat_dir(), "heat_cumulative-%s.json" % host_name())


def cumulative_heat_files(directory=None):
    """Mọi file cumulative của mọi máy (để server gộp khi xem scope=all).

    ``directory`` cho Vault Switcher đọc store của CHÍNH active vault thay vì thư
    mục app runtime. ``None`` giữ contract cũ cho logger/CLI.
    """
    base = os.path.normpath(directory) if directory else cumulative_heat_dir()
    return sorted(glob.glob(os.path.join(base, "heat_cumulative-*.json")))


def vault_journal_dir():
    """Thư mục chứa journal event per-máy. Env GRAPH3D_JOURNAL_DIR là override
    cho TEST (không ghi vào vault thật) — mirror pattern GRAPH3D_ACTIVITY_FILE."""
    env = os.environ.get("GRAPH3D_JOURNAL_DIR", "").strip()
    return os.path.normpath(env) if env else HERE


def vault_journal_path():
    """Journal event TRONG vault (sync OneDrive), PER-MÁY — mỗi máy CHỈ ghi file
    của mình nên không bao giờ conflict (pattern heat_cumulative-<HOST>.json).
    Khác activity.jsonl (%LOCALAPPDATA%, realtime, ngoài OneDrive): journal ghi
    theo LÔ ≤60s cùng nhịp flush heat — để máy KHÁC đọc được lịch sử event
    (chuỗi/timeline/dashboard nhìn thấy cả 2 máy — vấn đề 16/07/2026)."""
    return os.path.join(vault_journal_dir(), "activity-%s.jsonl" % host_name())


def vault_journal_files(directory=None):
    """Journal của MỌI máy (reader serve.py gộp), có thể chỉ định active vault."""
    base = os.path.normpath(directory) if directory else vault_journal_dir()
    return sorted(glob.glob(os.path.join(base, "activity-*.jsonl")))


def journal_host(path):
    """Tên máy từ tên file journal 'activity-<HOST>.jsonl'."""
    name = os.path.splitext(os.path.basename(path))[0]
    return name[len("activity-"):] or "unknown"


# DANH SÁCH DUY NHẤT mã nguồn của app — mọi nơi cần "app gồm những file nào" phải
# đọc từ đây, không chép tay: mirror bản demo (onboarding.mirror_app), whitelist
# publish sang repo public (tools/publish_from_vault.py), bộ test (selfcheck PY_MAIN).
# Bài học đợt 7+8 repo public: ba danh sách chép tay ⇒ thêm module .py mới là sót một
# chỗ, và sót thì im lặng (publish báo OK, demo chết lúc import). Selfcheck có contract
# đối chiếu danh sách này với *.py thật trong thư mục — quên khai là FAIL ngay.
# backup_graph3d.py KHÔNG nằm đây: file vận hành riêng bản private, không publish.
APP_PY = ("activity_paths.py", "build_graph_data.py", "ensure_graph3d.py",
          "insight.py", "install_launcher.py", "integrity.py", "log_activity.py",
          "onboarding.py", "run_graph3d.py", "serve.py", "update_check.py",
          "vault_switcher.py")
APP_TOP = APP_PY + ("index.html", "Start-Graph3D.bat", "Start-TON618.bat")
APP_DIRS = ("src", "vendor")

# Các file mà khi đổi thì SERVER phải khởi động lại (build_graph_data.py auto-reload
# nên KHÔNG nằm đây — tránh restart thừa). ensure/run so version này để biết server
# đang chạy có "cũ" so với code trên đĩa hay không → tự chữa.
# Từ giai đoạn 0 Vault Cockpit: UI tách thành ES modules trong src/ — hash phủ cả
# src/* để sửa module cũng kích tự-reload y như sửa index.html.
# ⚠ MỌI module serve.py import lúc nạp PHẢI có mặt ở đây (selfcheck contract 2k soi
# thẳng lệnh import trong serve.py) — thiếu thì sửa module xong server vẫn phục vụ
# bản cũ, lặng thinh (bug integrity.py, đợt 8 repo public).
_VERSION_FILES = ("serve.py", "index.html", "activity_paths.py", "log_activity.py",
                   "insight.py", "integrity.py", "onboarding.py", "install_launcher.py",
                   "update_check.py", "vault_switcher.py")


def restart_py_files():
    """Chỉ phần .py của _VERSION_FILES — serve.py dùng để kiểm 'nguồn có đang ghi dở'
    trước khi tự restart. Derive chứ không chép: thêm module mới chỉ khai MỘT chỗ."""
    return tuple(n for n in _VERSION_FILES if n.endswith(".py"))


def _version_paths(here):
    out = [os.path.join(here, name) for name in _VERSION_FILES]
    out.extend(sorted(p for p in glob.glob(os.path.join(here, "src", "*"))
                      if os.path.isfile(p)))
    return out


def source_version(here=None):
    """Hash ngắn của mã nguồn cần-restart. Trả None nếu đọc lỗi (file bị khóa
    tạm thời do OneDrive…) — caller nên bỏ qua tick đó, không coi là 'đổi'."""
    here = here or os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for path in _version_paths(here):
        try:
            with open(path, "rb") as f:
                h.update(os.path.basename(path).encode("utf-8"))
                h.update(f.read())
        except OSError:
            return None
        h.update(b"\0")
    return h.hexdigest()[:12]
