# -*- coding: utf-8 -*-
"""Ghi hoạt động agent cho KB Graph 3D — 2 chế độ:

1) HOOK Claude Code (không tham số): nhận JSON PostToolUse qua stdin
   (tool_name, tool_input, tool_response), tự lọc file .md thuộc vault.
2) CLI cho agent khác (Hermes, script, cron…):
       python log_activity.py <read|search|edit> <đường-dẫn-note> [...]
   Đường dẫn tuyệt đối hoặc tương đối gốc vault đều được.

Cả hai append vào activity log (NGOÀI OneDrive để tránh sync churn):
    %LOCALAPPDATA%/claude-graph3d/activity.jsonl
Mỗi dòng: {"ts": epoch, "type": "read|search|edit", "file": "...", "agent": "<tên>"}
KB Graph 3D (serve.py) đọc file này để phát hiệu ứng + gom chuỗi truy xuất theo agent.
Chế độ hook phải luôn exit 0 — không được làm phiền phiên làm việc.

Nhãn agent (để đo hiệu quả truy xuất từng agent): thứ tự ưu tiên
  1) --agent "<tên>" (CLI) hoặc query ?agent= (/ping)   2) env GRAPH3D_AGENT   3) "Claude".
Đặt env GRAPH3D_AGENT trong ngữ cảnh Cowork/Hermes để phân biệt.
"""
import json
import os
import re
import sys
import time

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from activity_paths import (activity_log_path, cumulative_heat_path, host_name,
                            parse_jsonl, vault_journal_path)

LOG_FILE = activity_log_path()
LOG_DIR = os.path.dirname(LOG_FILE)
LOCK_FILE = LOG_FILE + ".lock"
MAX_FILES_PER_EVENT = 8

TYPE_BY_TOOL = {
    "Read": "read",
    "Grep": "search",
    "Glob": "search",
    "Edit": "edit",
    "Write": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
}

PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\"'\n\r*?<>|]+?\.md", re.IGNORECASE)


def _collect_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)


def _demojibake(p):
    """Sửa tên bị mojibake: UTF-8 đã bị decode nhầm bằng CP1252 (vd 'â€"' ← '—',
    'Ã©' ← 'é'). CHỈ trả bản sửa khi nó thật sự tồn tại trên đĩa (an toàn tuyệt đối,
    không đụng path hợp lệ). Kế thừa bài học gotcha #2 nhưng vá luôn từ MỌI writer."""
    if not any(m in p for m in ("Ã", "Â", "â€")):
        return p
    try:
        fixed = p.encode("cp1252", "strict").decode("utf-8", "strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return p
    if fixed == p:
        return p
    ap = fixed if os.path.isabs(fixed) else os.path.join(VAULT, fixed)
    if not os.path.exists(os.path.normpath(ap)):
        return p
    _log_demojibake_hit(p, fixed)
    return fixed


def _log_demojibake_hit(orig, fixed):
    """Lưới an toàn vừa PHẢI SỬA path — nghĩa là vẫn còn writer decode sai ở đâu đó.
    Ghi vết (ngoài vault, cap 50KB) để truy gốc bệnh thay vì để mojibake bị che
    vĩnh viễn không ai biết (review P4.4). Xem hits: activity.jsonl.demojibake-hits.log"""
    try:
        hits = LOG_FILE + ".demojibake-hits.log"
        if os.path.exists(hits) and os.path.getsize(hits) > 50_000:
            return
        with open(hits, "ab") as f:
            f.write((json.dumps({"ts": time.time(), "orig": orig, "fixed": fixed},
                                ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError:
        pass


def _acquire(lf):
    """Khóa liên-process (non-blocking + retry ~1s). Windows msvcrt / POSIX fcntl."""
    if os.name == "nt":
        import msvcrt
        lf.seek(0)
        for _ in range(100):
            try:
                msvcrt.locking(lf.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                time.sleep(0.01)
        return False
    try:
        import fcntl
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass
    return True


def _release(lf):
    try:
        if os.name == "nt":
            import msvcrt
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _load_cumulative(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cumulative(path, data):
    # tmp per-process: 2 writer song song (hook + server reconcile, hoặc 2 realm MSIX)
    # không bao giờ ghi đè cùng một file tạm của nhau
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)   # thay nguyên tử — reader luôn thấy file hoàn chỉnh


def _cum_locked(work):
    """Chạy work() dưới khoá liên-process đặt CẠNH store (TRONG vault).
    Không dùng LOCK_FILE cạnh activity.jsonl cho store này: %LOCALAPPDATA% bị MSIX
    ảo hoá nên lock của hook-dưới-Cowork và lock của server là 2 file vật lý KHÁC
    nhau, không bảo vệ chéo được store chung trong vault. Best-effort: không lấy
    được khoá (~1s) vẫn chạy — như hành vi cũ, còn hơn mất đếm."""
    lf = None
    try:
        lf = open(cumulative_heat_path() + ".lock", "a+")
        _acquire(lf)
        return work()
    finally:
        if lf is not None:
            _release(lf)
            lf.close()


FLUSH_SEC = 60                                   # gộp bump vào store mỗi ≤60s
PENDING_FILE = LOG_FILE + ".heat-pending.jsonl"  # delta chờ đổ vào store — NGOÀI vault
JOURNAL_MAX_BYTES = 1_500_000                    # journal vault vượt cỡ này → rotate
JOURNAL_KEEP_LINES = 4000                        # giữ ~4000 event cuối (nhiều tuần)


def _journal_append(evs):
    """Chép event vào journal per-máy TRONG vault (activity-<HOST>.jsonl) — máy KHÁC
    đọc qua OneDrive để chuỗi/timeline/dashboard thấy CẢ 2 máy (vấn đề 16/07/2026:
    ngồi laptop không thấy log máy cty). Gọi tại điểm flush pending (≤60s/lô) DƯỚI
    khoá store vault-side — không thêm nhịp ghi vault mới, không đua 2 realm MSIX.
    Lần đầu (journal chưa có): seed bằng log cuộn local hiện có — lịch sử gần nhất
    của máy lên vault ngay; trùng lặp vô hại, reader dedup theo (ts,file,type,agent).
    Best-effort: lỗi chỉ mất bản sync, log chính + heat không ảnh hưởng."""
    jp = vault_journal_path()
    seed = b""
    if not os.path.exists(jp):
        try:
            with open(LOG_FILE, "rb") as f:
                seed = f.read()
            if seed and not seed.endswith(b"\n"):
                seed += b"\n"
        except OSError:
            seed = b""
    payload = "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in evs)
    with open(jp, "ab") as f:
        f.write(seed + payload.encode("utf-8"))
    try:
        if os.path.getsize(jp) > JOURNAL_MAX_BYTES:
            with open(jp, "rb") as f:
                tail = f.read().decode("utf-8", "replace").splitlines(True)[-JOURNAL_KEEP_LINES:]
            tmp = "%s.tmp-%d" % (jp, os.getpid())
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.writelines(tail)
            os.replace(tmp, jp)        # thay nguyên tử — máy khác luôn thấy file lành
    except OSError:
        pass


def _apply_events_to_store(evs, now):
    """Cộng list event (dạng {ts,type,file,agent}) vào store. Gọi DƯỚI khoá store."""
    path = cumulative_heat_path()
    data = _load_cumulative(path)
    data["host"] = host_name()
    data.setdefault("since", now)
    data["updated"] = now
    notes = data.setdefault("notes", {})
    for ev in evs:
        rel = ev.get("file")
        if not rel:
            continue
        t = ev.get("type")
        if t not in ("read", "search", "edit"):
            t = "read"
        ag = ev.get("agent") or "Claude"
        try:
            ts = float(ev.get("ts") or now)
        except (TypeError, ValueError):
            ts = now
        r = notes.get(rel)
        if not isinstance(r, dict):
            r = {"total": 0, "read": 0, "search": 0, "edit": 0,
                 "first": ts, "last": ts, "agents": {}}
            notes[rel] = r
        r["total"] = r.get("total", 0) + 1
        r[t] = r.get(t, 0) + 1
        r["last"] = max(r.get("last") or ts, ts)
        r.setdefault("first", ts)
        ags = r.setdefault("agents", {})
        ags[ag] = ags.get(ag, 0) + 1
    _save_cumulative(path, data)


def _flush_pending_into_store(now=None):
    """Đổ pending (ngoài vault) vào store trong vault, rồi xoá pending.
    Gọi khi ĐANG giữ khoá LOG (append_events / reconcile) — appender cùng realm
    không chen được vào giữa lúc đọc và lúc xoá pending."""
    now = now or time.time()
    try:
        with open(PENDING_FILE, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return
    evs = parse_jsonl(text)
    if evs:
        def work():
            _apply_events_to_store(evs, now)
            try:
                _journal_append(evs)   # bản sync 2 máy — best-effort, cùng khoá store
            except Exception:
                pass
        _cum_locked(work)
    try:
        os.remove(PENDING_FILE)
    except OSError:
        pass


def _bump_cumulative(rels, ev_type, agent, now):
    """Ghi nhận event cho store TÍCH LUỸ dài hạn — nhưng KHÔNG đọc/ghi file trong
    vault mỗi tool call (store nằm vùng sync OneDrive → churn theo từng hook):
    append delta vào PENDING ngoài vault (rẻ), pending già ≥FLUSH_SEC hoặc >64KB
    mới đổ gộp MỘT lần vào store. Pending per-realm (MSIX): realm nào tự flush
    của mình; server flush realm chuẩn trong reconcile. Best-effort, gọi khi đang
    giữ khoá LOG trong append_events. Event không mất khi log xoay vòng — nó nằm
    trong pending cho tới khi được đổ vào store."""
    payload = "".join(
        json.dumps({"ts": now, "type": ev_type, "file": rel, "agent": agent},
                   ensure_ascii=False) + "\n"
        for rel in rels)
    with open(PENDING_FILE, "ab") as f:
        f.write(payload.encode("utf-8"))
    due = False
    try:
        if os.path.getsize(PENDING_FILE) > 64_000:
            due = True
        else:
            with open(PENDING_FILE, "rb") as f:
                first = json.loads(f.readline().decode("utf-8", "replace"))
            due = now - float(first.get("ts") or now) >= FLUSH_SEC
    except (OSError, ValueError, TypeError):
        due = True                        # pending khó đọc → đổ luôn cho chắc
    if due:
        _flush_pending_into_store(now)


def _rotate_if_big():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 400_000:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-200:]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def read_all_activity_events():
    """Log cuộn local + journal vault của chính máy, khử trùng lặp theo event.

    Journal giữ cửa sổ dài hơn log cuộn và vì vậy là mức sàn dương tốt hơn cho
    store tích luỹ. Local vẫn cần để phủ phần pending vừa flush nhưng OneDrive chưa
    kịp phản ánh. Không đọc journal máy khác: mỗi store là per-host.
    """
    out, seen = [], set()
    for act in (activity_log_path(), vault_journal_path()):
        if not os.path.exists(act):
            continue
        try:
            with open(act, "rb") as f:
                data = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for ev in parse_jsonl(data):
            if "ts" not in ev or "file" not in ev:
                continue
            key = (ev.get("ts"), ev.get("file"), ev.get("type"), ev.get("agent"))
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
    return out


def aggregate_by_file(events):
    """Gom metric heat theo đường dẫn note (relative vault path)."""
    out = {}
    for e in events:
        f = e.get("file")
        if not f:
            continue
        ts = float(e.get("ts") or 0)
        t = e.get("type", "read")
        if t not in ("read", "search", "edit"):
            t = "read"
        ag = e.get("agent") or "Claude"
        r = out.setdefault(f, {"total": 0, "read": 0, "search": 0, "edit": 0,
                               "first": ts, "last": ts, "agents": {}})
        r["total"] += 1
        r[t] = r.get(t, 0) + 1
        if ts:
            r["first"] = min(r["first"], ts) if r["first"] else ts
            r["last"] = max(r["last"], ts)
        r["agents"][ag] = r["agents"].get(ag, 0) + 1
    return out


COUNT_TYPES = ("read", "search", "edit")


def _count(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0


def _pad_key(keys, source, old, fallback):
    """Chọn ô nhận phần bù khi hai phân hoạch type/agent có tổng khác nhau."""
    keys = list(keys)
    if not keys:
        return fallback
    order = {k: -i for i, k in enumerate(keys)}
    return max(keys, key=lambda k: (_count(source.get(k)), _count(old.get(k)), order[k]))


def merge_cumulative_floor(old, floor):
    """Least coherent upper bound của record cũ và mức sàn từ event thật.

    Mỗi count cũ và count ở floor đều là bằng chứng dương nên không ô nào được hạ.
    Type và agent là hai phân hoạch của cùng tập event; sau khi lấy max từng ô, hai
    tổng có thể khác nhau vì store chỉ giữ aggregate, không giữ ma trận type×agent.
    Ta bù phía thấp hơn vào ô có bằng chứng mạnh nhất để đạt tổng nhỏ nhất có thể,
    thay vì chép đè nguyên record và làm rụng lịch sử đã xoay khỏi log.
    """
    old = old if isinstance(old, dict) else {}
    floor = floor if isinstance(floor, dict) else {}
    types = {k: max(_count(old.get(k)), _count(floor.get(k))) for k in COUNT_TYPES}
    old_agents = old.get("agents") if isinstance(old.get("agents"), dict) else {}
    floor_agents = floor.get("agents") if isinstance(floor.get("agents"), dict) else {}
    agent_keys = sorted(set(old_agents) | set(floor_agents))
    agents = {k: max(_count(old_agents.get(k)), _count(floor_agents.get(k)))
              for k in agent_keys}
    agents = {k: v for k, v in agents.items() if v > 0}

    type_total, agent_total = sum(types.values()), sum(agents.values())
    total = max(type_total, agent_total)
    if type_total < total:
        key = _pad_key(COUNT_TYPES, floor, old, "read")
        types[key] += total - type_total
    if agent_total < total:
        key = _pad_key(sorted(set(old_agents) | set(floor_agents)),
                       floor_agents, old_agents, "Claude")
        agents[key] = agents.get(key, 0) + total - agent_total

    firsts = [v for v in (old.get("first"), floor.get("first"))
              if isinstance(v, (int, float)) and v > 0]
    lasts = [v for v in (old.get("last"), floor.get("last"))
             if isinstance(v, (int, float)) and v > 0]
    return {"total": total, "read": types["read"], "search": types["search"],
            "edit": types["edit"], "first": min(firsts) if firsts else 0,
            "last": max(lasts) if lasts else 0, "agents": agents}


def reconcile_cumulative_with_log():
    """Nâng heat tích lũy máy này theo log local + journal vault dài hơn.

    Mọi dòng trong log cuộn phải đã được _bump_cumulative khi ghi; nếu thiếu (seed,
    bump lỗi, log trước khi có feature) thì đồng bộ theo nguồn event. KHÔNG giảm
    bất kỳ count cũ nào: store có thể giữ lịch sử đã xoay khỏi cả hai log.
    """
    # Giữ khoá LOG suốt (flush pending realm mình → rồi mới đọc log): mọi event có
    # mặt trong log-aggregate chắc chắn đã được flush vào store trước đó, nên nhánh
    # "raise theo log" không bao giờ đếm trùng với pending sẽ flush sau này.
    lf = None
    try:
        lf = open(LOCK_FILE, "a+")
        _acquire(lf)
        _flush_pending_into_store()
        events = read_all_activity_events()
    finally:
        if lf is not None:
            _release(lf)
            lf.close()
    agg = aggregate_by_file(events)
    path = cumulative_heat_path()

    def work():
        data = _load_cumulative(path)
        data["host"] = host_name()
        notes = data.setdefault("notes", {})
        now = time.time()
        changed = False
        for rel, st in agg.items():
            old = notes.get(rel)
            merged = merge_cumulative_floor(old, st)
            if merged != old:
                notes[rel] = merged
                changed = True
        if changed:
            data.setdefault("since", now)
            data["updated"] = now
            _save_cumulative(path, data)
        return changed

    # Dưới khoá store: reconcile (server) và _bump_cumulative (hook) không còn
    # đọc-ghi đè lên nhau (lost-update — review P1.2).
    return _cum_locked(work)


def resolve_agent(explicit=None):
    """Nhãn agent: explicit > env GRAPH3D_AGENT > 'Claude'. Cắt 40 ký tự.
    MỌI phiên Claude — Claude Code CLI hay Cowork/Desktop — DÙNG CHUNG nhãn 'Claude',
    KHÔNG tách theo vỏ chạy (chốt thiết kế 06/07/2026: phân biệt Code/Cowork
    không cần thiết). Agent KHÁC (Hermes…) tự truyền --agent/?agent= nên không bị gộp."""
    name = (explicit or os.environ.get("GRAPH3D_AGENT") or "Claude").strip()
    return (name or "Claude")[:40]


def append_events(ev_type, paths, agent=None):
    """Ghi event cho danh sách đường dẫn (tuyệt đối hoặc tương đối vault).
    Chỉ nhận file .md thuộc vault, bỏ folder ẩn. Trả về số dòng đã ghi.
    An toàn khi NHIỀU agent (Claude hook + Hermes + script) cùng ghi: khóa
    liên-process + rotate & append trong 1 lần ghi duy nhất (chống xé dòng)."""
    if ev_type not in ("read", "search", "edit"):
        ev_type = "read"
    agent = resolve_agent(agent)
    vault_norm = os.path.normcase(os.path.normpath(VAULT))
    rels, seen = [], set()
    for p in paths:
        p = str(p).strip().strip('"').strip("'")
        if not p:
            continue
        p = _demojibake(p)
        ap = p if os.path.isabs(p) else os.path.join(VAULT, p)
        ap = os.path.normpath(ap)
        if not os.path.normcase(ap).startswith(vault_norm + os.sep):
            continue
        try:
            # Lấy đúng case thật trên đĩa: Windows mở file case-insensitive nhưng id
            # node graph (từ os.walk) và byId.get() phía UI thì case-sensitive — path
            # lệch case sẽ im lặng không match node. Chỉ nhận kết quả còn nằm trong
            # vault (realpath xuyên symlink có thể trỏ ra ngoài).
            rp = os.path.realpath(ap)
            if os.path.normcase(rp).startswith(vault_norm + os.sep):
                ap = rp
        except OSError:
            pass
        rel = os.path.relpath(ap, VAULT).replace("\\", "/")
        top = rel.split("/", 1)[0]
        if not rel.lower().endswith(".md") or top.startswith(".") or rel in seen:
            continue
        seen.add(rel)
        rels.append(rel)
    if not rels:
        return 0
    os.makedirs(LOG_DIR, exist_ok=True)
    now = time.time()
    logged = rels[:MAX_FILES_PER_EVENT]
    payload = "".join(
        json.dumps({"ts": now, "type": ev_type, "file": rel, "agent": agent},
                   ensure_ascii=False) + "\n"
        for rel in logged)

    lf = None
    try:
        lf = open(LOCK_FILE, "a+")
        _acquire(lf)
        _rotate_if_big()                       # rotate trong khóa để không đua với append
        with open(LOG_FILE, "ab") as f:        # O_APPEND + ghi 1 phát = không xé dòng
            f.write(payload.encode("utf-8"))
            f.flush()
        try:
            _bump_cumulative(logged, ev_type, agent, now)   # store tích luỹ (vault)
        except Exception:
            pass                                # best-effort, không làm hỏng log chính
    except Exception:
        # Cùng lắm ghi không khóa còn hơn mất event.
        try:
            with open(LOG_FILE, "ab") as f:
                f.write(payload.encode("utf-8"))
            try:
                _bump_cumulative(logged, ev_type, agent, now)
            except Exception:
                pass
        except Exception:
            pass
    finally:
        if lf is not None:
            _release(lf)
            lf.close()
    return min(len(rels), MAX_FILES_PER_EVENT)


def _paths_from_payload(ev_type, payload):
    """Lấy path từ FIELD CẤU TRÚC của payload hook thay vì regex-quét mọi string.
    PATH_RE cũ chỉ khớp path TUYỆT ĐỐI có ổ đĩa nên Grep/Glob (trả path tương đối)
    gần như không bao giờ được log (đo thật: 5/39 event là search); quét cả
    tool_response của Read còn bắt nhầm path chỉ được NHẮC ĐẾN trong nội dung note."""
    ti = payload.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    if ev_type in ("read", "edit"):
        # Tool đọc/sửa luôn khai báo đích tường minh trong tool_input —
        # KHÔNG đụng tool_response (nội dung file = nguồn event giả).
        p = ti.get("file_path") or ti.get("notebook_path")
        if isinstance(p, str) and p.strip():
            return [p]
        strings = []
        _collect_strings(ti, strings)
        return [m for s in strings for m in PATH_RE.findall(s)]
    # search (Grep/Glob): danh sách kết quả nằm trong tool_response, mỗi path một
    # dòng, TƯƠNG ĐỐI gốc vault hoặc tuyệt đối. Chỉ nhận dòng .md TỒN TẠI trên đĩa
    # (tự loại header "Found N files", pattern "*.md", path bịa trong nội dung).
    cands = []
    p = ti.get("path")
    if isinstance(p, str) and p.lower().endswith(".md"):
        cands.append(p)
    strings = []
    _collect_strings(payload.get("tool_response"), strings)
    for s in strings:
        for line in s.splitlines():
            line = line.strip().strip('"\'')
            if line.lower().endswith(".md") and len(line) < 500:
                cands.append(line)
    out, seen = [], set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        ap = c if os.path.isabs(c) else os.path.join(VAULT, c)
        if os.path.isfile(os.path.normpath(ap)):
            out.append(c)
        if len(out) >= MAX_FILES_PER_EVENT:
            break
    return out


def main():
    try:
        # Windows: stdin pipe mặc định decode theo code page -> hỏng ký tự
        # tiếng Việt/em-dash. Đọc binary rồi decode UTF-8 tường minh.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        return
    ev_type = TYPE_BY_TOOL.get(payload.get("tool_name", ""))
    if not ev_type:
        return
    append_events(ev_type, _paths_from_payload(ev_type, payload))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Chế độ CLI: log_activity.py <read|search|edit> [--agent "Tên"] <path...>
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        args = sys.argv[1:]
        agent = None
        if "--agent" in args:
            i = args.index("--agent")
            if i + 1 < len(args):
                agent = args[i + 1]
                del args[i:i + 2]
        n = append_events(args[0] if args else "read", args[1:], agent=agent)
        print("logged: %d" % n)
    else:
        try:
            main()
        except Exception:
            pass
    sys.exit(0)
