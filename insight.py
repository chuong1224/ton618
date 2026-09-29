# -*- coding: utf-8 -*-
"""KB Graph 3D — tầng insight + worklist đề xuất (W10/W18).

`/dashboard` trả lời *"agent đã làm gì hôm nay"*; module này trả lời
*"vault đang khoẻ không"*: note nóng / đang nguội theo tuần, note nguội theo lần
đụng cuối, note **chưa bao giờ** agent đụng, cụm ít kết nối, coverage theo khu vực.

Hai bề mặt tiêu thụ CÙNG một hàm `build_insight()` — không có bộ đếm thứ hai:
  - `serve.py`  → `GET /insight?days=&cold=`   (section 🩺 + overlay trong app)
  - CLI         → `python .graph3d/insight.py --report`  (note báo cáo trong vault)

Chạy tay:
  python .graph3d/insight.py                 # in tóm tắt ra console
  python .graph3d/insight.py --json          # đổ nguyên JSON (debug)
  python .graph3d/insight.py --days 7 --cold 14

Ba nguồn dữ liệu, mỗi chỉ số đọc nguồn nào ghi rõ trong docstring của nó:
  J = event log gộp mọi máy (serve.read_all_events) — CUỘN, hiện ~16–18 ngày/máy
  H = heat tích luỹ (heat_cumulative-<HOST>.json, gộp 2 máy) — có first/last per-note,
      không mất khi log xoay vòng, nhưng chỉ có từ ngày bật tính năng
  G = /graph-data (nodes/links) — cấu trúc vault HIỆN TẠI

Mọi con số đi kèm cửa sổ dữ liệu của chính nó (`data.oldest_event`, `data.heat_since`):
"nguội 14 ngày" trên store mới 3 tuần tuổi KHÔNG cùng nghĩa với "nguội 14 ngày" sau
nửa năm — caller PHẢI hiện kèm, đừng bày số trần.

W18/H3 đóng vòng bằng `build_worklist()`: nó CHỈ tiêu thụ snapshot `build_insight()`
đã tính, không đi đo lại nguồn. Kết quả là đề xuất read-only có đích + bằng chứng +
ưu tiên ổn định; module này KHÔNG bao giờ tự sửa link/note hay tự ghi vào Work Map.

Hồ sơ đợt + định nghĩa chỉ số: note vault "Tầng Insight Sức Khoẻ Vault — KB Graph 3D".
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import log_activity  # noqa: E402  (aggregate_by_file = bộ đếm dùng chung với heat)

DAY = 86400.0
DEFAULT_DAYS = 7          # cửa sổ "tuần" = 7 ngày CUỘN từ lúc chạy (không phải tuần lịch)
# Ngày không ai đụng thì coi là "nguội". 7 chứ không phải 14: routine daily (audit
# 08:00, catalog regen) quét gần như cả vault mỗi ngày, nên tuổi last-touch dồn hết
# về phía trẻ — đo thật 25/07/2026: note già nhất mới 10.5 ngày, ngưỡng 14 trả về 0
# note. Ngưỡng chỉ là cái ĐUÔI actionable; bức tranh chính là histogram `cold.hist`
# (không phụ thuộc ngưỡng, đọc được kể cả khi cửa sổ dữ liệu còn ngắn).
DEFAULT_COLD = 7
AGE_BUCKETS = ((1, "0-1"), (3, "1-3"), (7, "3-7"), (14, "7-14"), (30, "14-30"))
COOLING_MIN = 3           # tuần trước ≥ ngần này lượt mà tuần này 0 => "đang nguội đi"
SMALL_CLUSTER = 3         # thành phần liên thông ≤ ngần này note = "cụm nhỏ"
HUB_GROUP = "Index / MOC"  # nhóm màu của note index/MOC (build_graph_data.TAG_COLORS)
TYPES = ("read", "search", "edit")
TAXONOMY_MIN_CHARS = 40   # paper D.4: content unit ngan hon 40 ky tu bi loai
TAXONOMY_PAIR_CAP = 20000 # B4 sample co dinh de chi phi khong tang O(n^2)
TAXONOMY_EPS = 1e-12
REREAD_MIN = 2            # >=2 lượt đọc lặp trong cửa sổ mới thành đề xuất
LONG_CHAIN_MIN = 6        # chuỗi đi qua >=6 note khác nhau = đường truy xuất dài
SCOPE_MARGIN_MIN = 0.08   # B3 yếu hơn mức này chỉ là descriptor, chưa vào worklist
WORKLIST_LIMIT = 30       # report/UI không được ngập; total vẫn giữ số đầy đủ
REREAD_WORKLIST_CAP = 8   # giữ top tín hiệu mỗi lớp — worklist là hàng đợi, không dump
LONG_WORKLIST_CAP = 5
SCOPE_WORKLIST_CAP = 10

# Note "sống" do chính module này sinh ra (vế b) — ghi đè mỗi lần chạy, cùng họ với
# Báo Cáo Audit Vault. Vault khác đặt chỗ khác: env GRAPH3D_INSIGHT_REPORT.
REPORT_REL = ("Vault Operation/Audit Vault/Báo Cáo Sức Khoẻ Truy Xuất/"
              "Báo Cáo Sức Khoẻ Truy Xuất.md")
REPORT_TITLE = "Báo Cáo Sức Khoẻ Truy Xuất"


def _ts(ev):
    """ts của event dạng số, 0.0 nếu thiếu/hỏng — event thiếu ts KHÔNG được rơi vào
    cửa sổ tuần (bài học day_key: localtime(None) = BÂY GIỜ)."""
    ts = ev.get("ts")
    return float(ts) if isinstance(ts, (int, float)) else 0.0


def _under_attachments(rel):
    """True khi đường dẫn nằm dưới một thư mục `attachments/`.

    Graph scanner vẫn cần đi qua `attachments/` để dựng node file, và hiện coi mọi
    `.md` nó gặp là node note. Với tầng insight, `.md` ở đó chỉ là file phụ trợ/
    bản nháp, cùng phạm vi chọn note của catalog, nên phải loại theo THÀNH PHẦN
    đường dẫn — không match substring kiểu `my-attachments`.
    """
    if not isinstance(rel, str):
        return False
    parts = rel.replace("\\", "/").split("/")
    return any(part.casefold() == "attachments" for part in parts[:-1])


def note_graph(graph, exclude=None):
    """(notes, adj, hubs) của đồ thị **NOTE–NOTE**: bỏ hết cạnh tới node tag/file.

    Nguồn G. Cạnh tag làm mọi note cùng tag trông như liền cụm, nên chỉ số kết nối
    phải tính trên note–note thuần. `hubs` = note index/MOC (dùng cho "không nằm
    index nào"). Link ở server luôn là id chuỗi; vẫn nhận dict cho chắc (thư viện
    force-graph thay id bằng object node sau khi ingest).
    `exclude` = note bị loại khỏi phép đo (xem self_excludes). `.md` nằm dưới
    `attachments/` cũng bị loại theo cùng phạm vi chọn note của catalog.
    """
    skip = set(exclude or ())
    notes = {n["id"]: n for n in graph.get("nodes", [])
             if n.get("kind") == "note" and n.get("id") not in skip
             and not _under_attachments(n.get("id"))}
    adj = {rel: set() for rel in notes}
    for lk in graph.get("links", []):
        s, t = lk.get("source"), lk.get("target")
        if isinstance(s, dict):
            s = s.get("id")
        if isinstance(t, dict):
            t = t.get("id")
        if s != t and s in adj and t in adj:
            adj[s].add(t)
            adj[t].add(s)
    hubs = {rel for rel, n in notes.items()
            if n.get("hub") or n.get("group") == HUB_GROUP}
    return notes, adj, hubs


def components(adj):
    """Thành phần liên thông của đồ thị note–note, lớn nhất trước.

    BFS/DFS LẶP (không đệ quy) — vault phình sâu vẫn không tràn stack. Cụm size 1
    = note mồ côi; cụm nhỏ = tri thức nằm rời khỏi phần còn lại của vault.
    """
    seen, out = set(), []
    for start in sorted(adj):
        if start in seen:
            continue
        seen.add(start)
        stack, comp = [start], []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        out.append(sorted(comp))
    out.sort(key=lambda c: (-len(c), c[0]))
    return out


def area_of(rel):
    """Khu vực = folder cấp 1 (Work / Vault Operation / Personal / Skills…)."""
    return rel.split("/")[0] if "/" in rel else "(gốc vault)"


def nearest_index(rel, notes, hubs):
    """Index gần nhất theo folder ancestry — chỉ là ỨNG VIÊN, không tự tạo link.

    Chọn hub có folder sâu nhất vẫn là tổ tiên của folder note. Đây là phép chọn cơ
    học, xác định; nếu không có hub tổ tiên thì trả None thay vì đoán chéo khu vực.
    """
    node = notes.get(rel) or {}
    folder = (node.get("folder") or os.path.dirname(rel)).replace("\\", "/").strip("/")
    candidates = []
    for hub in hubs:
        hnode = notes.get(hub) or {}
        hfolder = (hnode.get("folder") or os.path.dirname(hub)).replace("\\", "/").strip("/")
        if not hfolder or folder == hfolder or folder.startswith(hfolder + "/"):
            candidates.append((len([p for p in hfolder.split("/") if p]), hub))
    return sorted(candidates, key=lambda x: (-x[0], x[1]))[0][1] if candidates else None


def build_friction(chains, notes, cur_from, list_n=40):
    """Tín hiệu đọc-lặp/chuỗi-dài từ chain canonical do `serve.build_chains` sinh.

    Hàm không tự gom chain lần hai. Caller truyền đúng output canonical; ở đây chỉ
    cắt về cửa sổ insight và giao với tập note hiện hành.
    """
    if chains is None:
        return {"available": False, "chains": 0,
                "reread": {"total": 0, "list": []},
                "long": {"total": 0, "list": []}}
    reread = defaultdict(lambda: {"rereads": 0, "chains": 0})
    long = []
    chain_count = 0
    for chain in chains:
        events = [e for e in chain.get("events", [])
                  if _ts(e) >= cur_from and e.get("file") in notes
                  and not _under_attachments(e.get("file"))]
        if not events:
            continue
        chain_count += 1
        reads = Counter(e.get("file") for e in events if e.get("type", "read") == "read")
        for rel, count in reads.items():
            excess = max(0, count - 1)
            if excess:
                reread[rel]["rereads"] += excess
                reread[rel]["chains"] += 1
        ordered = []
        for e in sorted(events, key=_ts):
            rel = e.get("file")
            if rel not in ordered:
                ordered.append(rel)
        if len(ordered) >= LONG_CHAIN_MIN:
            start, end = min(_ts(e) for e in events), max(_ts(e) for e in events)
            long.append({"agent": chain.get("agent") or "Claude", "start": start,
                         "end": end, "span": max(0.0, end - start),
                         "count": len(events), "distinct": len(ordered),
                         "first": ordered[0], "last": ordered[-1],
                         "files": ordered[:list_n]})
    rr = [{"file": rel, **row} for rel, row in reread.items()]
    rr.sort(key=lambda x: (-x["rereads"], -x["chains"], x["file"]))
    long.sort(key=lambda x: (-x["distinct"], -x["count"], x["start"], x["first"]))
    return {"available": True, "chains": chain_count,
            "reread": {"total": len(rr), "list": rr[:list_n]},
            "long": {"total": len(long), "list": long[:list_n]}}


def _work_id(kind, rel, target="", extra=""):
    raw = "|".join((kind, rel or "", target or "", extra or ""))
    return "H3-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def build_worklist(ins, limit=WORKLIST_LIMIT):
    """Biến snapshot insight thành đề xuất read-only — KHÔNG đo lại và KHÔNG sửa.

    Mỗi item có hành động cụ thể, đích, bằng chứng và mức ưu tiên. Semantic choice
    (thêm link, gộp/move section, sửa aliases/summary) luôn để người duyệt.
    """
    items, seen = [], set()

    def add(priority, kind, rel, target=None, evidence=None, extra=""):
        ident = _work_id(kind, rel, target or "", extra)
        if ident in seen:
            return
        seen.add(ident)
        items.append({"id": ident, "priority": priority, "kind": kind,
                      "file": rel, "target": target,
                      "evidence": evidence or {}, "review_required": True})

    wk = ins.get("weak") or {}
    never = {x["file"] for x in (ins.get("never") or {}).get("list", [])}
    unread = set((ins.get("unread") or {}).get("list", []))
    orphans = set((wk.get("orphans") or {}).get("list", []))
    no_index = (wk.get("no_index") or {}).get("list", [])
    candidates = wk.get("index_candidates") or {}
    covered = set()
    for rel in no_index:
        target = candidates.get(rel)
        blind = rel in never or rel in unread
        add("P1" if blind or rel in orphans else "P2",
            "connect_index" if target else "review_index", rel, target,
            {"orphan": rel in orphans, "never": rel in never,
             "unread": rel in unread})
        covered.add(rel)
    for rel in sorted((never | unread) - covered):
        add("P1", "open_unseen", rel, evidence={"never": rel in never,
                                                  "unread": rel in unread})

    friction = ins.get("friction") or {}
    for row in (friction.get("reread") or {}).get("list", [])[:REREAD_WORKLIST_CAP]:
        if row.get("rereads", 0) >= REREAD_MIN:
            add("P2", "reduce_reread", row["file"], evidence={
                "rereads": row["rereads"], "chains": row["chains"]})
    routes = {}
    for row in (friction.get("long") or {}).get("list", []):
        key = (row["first"], row["last"])
        cur = routes.get(key)
        if cur is None:
            cur = dict(row)
            cur["occurrences"] = 1
            routes[key] = cur
        else:
            cur["occurrences"] += 1
            if (row["distinct"], row["count"], row["span"]) > (
                    cur["distinct"], cur["count"], cur["span"]):
                keep = cur["occurrences"]
                cur.update(row)
                cur["occurrences"] = keep
    route_rows = sorted(routes.values(), key=lambda x: (-x["occurrences"],
                         -x["distinct"], -x["count"], x["first"], x["last"]))
    for row in route_rows[:LONG_WORKLIST_CAP]:
        add("P2", "shorten_chain", row["first"], row["last"], {
            "distinct": row["distinct"], "count": row["count"],
            "span": row["span"], "agent": row["agent"],
            "occurrences": row["occurrences"]})

    b3 = ((ins.get("taxonomy") or {}).get("b3_scope_leakage") or {})
    scope_added = 0
    for row in b3.get("list", []):
        if row.get("margin", 0.0) >= SCOPE_MARGIN_MIN:
            add("P2", "review_scope", row["file"], row.get("target"), {
                "section": row.get("section", ""), "margin": row.get("margin", 0.0),
                "own_similarity": row.get("own_similarity", 0.0),
                "other_similarity": row.get("other_similarity", 0.0)},
                extra=row.get("section", ""))
            scope_added += 1
            if scope_added >= SCOPE_WORKLIST_CAP:
                break

    rank = {"P1": 0, "P2": 1, "P3": 2}
    items.sort(key=lambda x: (rank.get(x["priority"], 9), x["kind"], x["file"],
                              x.get("target") or "", x["id"]))
    counts = Counter(x["priority"] for x in items)
    shown = items[:max(1, int(limit))]
    return {"mode": "proposal_only", "auto_apply": False, "review_required": True,
            "total": len(items), "shown": len(shown), "truncated": len(items) > len(shown),
            "counts": {p: counts.get(p, 0) for p in ("P1", "P2", "P3")},
            "thresholds": {"reread_min": REREAD_MIN,
                           "long_chain_min_distinct": LONG_CHAIN_MIN,
                           "scope_margin_min": SCOPE_MARGIN_MIN,
                           "caps": {"reread": REREAD_WORKLIST_CAP,
                                    "long_chain": LONG_WORKLIST_CAP,
                                    "scope": SCOPE_WORKLIST_CAP}},
            "items": shown}


def age_hist(ages):
    """Phân bố tuổi last-touch (ngày) theo AGE_BUCKETS — bức tranh chính của mục
    "nguội", đọc được không cần ngưỡng. Trả dict giữ THỨ TỰ bucket."""
    out = {label: 0 for _, label in AGE_BUCKETS}
    out["30+"] = 0
    for a in ages:
        for lim, label in AGE_BUCKETS:
            if a < lim:
                out[label] += 1
                break
        else:
            out["30+"] += 1
    return out


def self_excludes():
    """Note do CHÍNH module này sinh ra — phải loại khỏi mọi chỉ số.

    Không loại thì report tự đếm mình vào tổng note VÀ tự nằm trong danh sách "chưa
    bao giờ agent đụng" của chính nó (đã gặp thật lúc dựng: 144 → 145 note, "chưa
    đụng" 1 → 2). Công cụ đo không được nằm trong phép đo.
    """
    out = {REPORT_REL}
    p = os.environ.get("GRAPH3D_INSIGHT_REPORT")
    if p:
        try:
            rel = os.path.relpath(os.path.abspath(p), VAULT).replace("\\", "/")
            if not rel.startswith(".."):
                out.add(rel)
        except ValueError:                          # ổ đĩa khác → không thuộc vault
            pass
    return out


# ------------------------------------------------------- taxonomy B3 / B4

def logical_note_path(rel):
    """Cay logic cua mot note, bo cap lap cua quy uoc folder-per-note.

    ``A/B/B.md`` la node note ``A/B`` (khong phai ``A/B/B``); ``A/Index.md``
    van la ``A/Index``. Cach chuan hoa nay giu khoang cach cay phan anh taxonomy
    ma nguoi dung nhin thay, thay vi phat moi note mot cap gia do dong goi file.
    """
    parts = tuple(p for p in str(rel).replace("\\", "/").split("/") if p)
    if not parts:
        return ()
    stem = os.path.splitext(parts[-1])[0]
    if len(parts) >= 2 and parts[-2].casefold() == stem.casefold():
        return parts[:-1]
    return parts[:-1] + (stem,)


def _without_frontmatter(text):
    text = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return text


def taxonomy_units(docs, min_chars=TAXONOMY_MIN_CHARS):
    """Tach markdown thanh content unit la theo dung paper D.4.

    Cay gom folder -> file -> heading. Neu file co heading, chi section KHONG co
    subsection moi la la; file khong heading tu no la mot unit. Unit ngan hon
    ``min_chars`` sau khi gom whitespace bi loai. Ham thuần, khong doc dia.
    """
    out, ignored = [], 0
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    fence_re = re.compile(r"^\s*(```+|~~~+)")
    for rel, raw in sorted((docs or {}).items()):
        text = _without_frontmatter(raw)
        sections, stack, preface = [], [], []
        fence = None
        for line in text.split("\n"):
            fm = fence_re.match(line)
            if fm:
                mark = fm.group(1)[0]
                if fence == mark:
                    fence = None
                elif fence is None:
                    fence = mark
            hm = None if fence else heading_re.match(line)
            if hm:
                level = len(hm.group(1))
                title = re.sub(r"\s+#+\s*$", "", hm.group(2)).strip()
                while stack and stack[-1]["level"] >= level:
                    stack.pop()
                for ancestor in stack:
                    ancestor["leaf"] = False
                sec = {"level": level, "titles": tuple(x["title"] for x in stack) + (title,),
                       "title": title, "body": [], "leaf": True}
                sections.append(sec)
                stack.append(sec)
            elif stack:
                stack[-1]["body"].append(line)
            else:
                preface.append(line)

        candidates = [(s["titles"], "\n".join(s["body"]))
                      for s in sections if s["leaf"]]
        if not sections:
            candidates = [((), "\n".join(preface))]
        note_tree = logical_note_path(rel)
        for titles, body in candidates:
            compact = " ".join(body.split())
            if len(compact) < int(min_chars):
                ignored += 1
                continue
            section = " > ".join(titles) if titles else os.path.splitext(
                str(rel).replace("\\", "/").split("/")[-1])[0]
            out.append({"file": rel, "section": section, "text": compact,
                        "chars": len(compact), "tree": note_tree + titles,
                        "note_tree": note_tree})
    return out, ignored


def _tokens(text):
    """Tokenizer Unicode nhe, xac dinh, khong learned component."""
    return [t.casefold() for t in re.findall(r"[^\W_]+", text or "", flags=re.UNICODE)
            if len(t) > 1]


def _tfidf(units):
    counts = [Counter(_tokens(u["text"])) for u in units]
    df = Counter()
    for row in counts:
        df.update(row.keys())
    n = len(counts)
    vectors = []
    for row in counts:
        vec = {term: (1.0 + math.log(freq)) * (math.log((1.0 + n) / (1.0 + df[term])) + 1.0)
               for term, freq in row.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        vectors.append({k: v / norm for k, v in vec.items()} if norm else {})
    return vectors


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _centroid(vectors):
    total = defaultdict(float)
    rows = [v for v in vectors if v]
    if not rows:
        return {}
    for vec in rows:
        for k, v in vec.items():
            total[k] += v
    norm = math.sqrt(sum(v * v for v in total.values()))
    return {k: v / norm for k, v in total.items()} if norm else {}


def _average_ranks(values):
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0       # average cua rank 1-based i+1 .. j
        for pos in order[i:j]:
            ranks[pos] = rank
        i = j
    return ranks


def spearman(xs, ys):
    """Spearman rho voi average-rank cho ties; ``None`` neu khong xac dinh."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _average_ranks(xs), _average_ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    dx, dy = [x - mx for x in rx], [y - my for y in ry]
    den = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if den <= TAXONOMY_EPS:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / den


def _tree_distance(a, b):
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return len(a) + len(b) - 2 * common


def _sample_pairs(n, cap):
    total = n * (n - 1) // 2
    cap = max(0, int(cap))
    if total <= cap:
        return [(i, j) for i in range(n) for j in range(i + 1, n)], total
    rng, picked = random.Random(115), set()
    while len(picked) < cap:
        i, j = rng.randrange(n), rng.randrange(n)
        if i != j:
            picked.add((i, j) if i < j else (j, i))
    return sorted(picked), total


def build_taxonomy(docs, list_n=40, pair_cap=TAXONOMY_PAIR_CAP):
    """Tinh B3 scope leakage va B4 distance-relatedness cua paper arXiv:2607.26637.

    B3 duoc ap vao packaging cua vault: moi note la mot sibling group, content unit
    la section la cua note; chi so la ty le unit gan centroid mot note ANH EM (cung
    folder logic) hon centroid note cha. Danh sach kem target de con nguoi duyet,
    tuyet doi khong tu move/sua note.

    B4 la Spearman giua path length qua LCA va ``1 - TF-IDF cosine`` tren cap unit.
    Neu qua ``pair_cap``, lay mau cap uniform bang seed co dinh de ket qua lap lai.
    Ca hai la descriptor adherence, KHONG phai diem chat luong — dung canh bao D.4.
    """
    units, ignored = taxonomy_units(docs)
    vectors = _tfidf(units)
    usable = [(u, v) for u, v in zip(units, vectors) if v]
    units = [u for u, _ in usable]
    vectors = [v for _, v in usable]

    # B3: note centroids, chi so sanh note anh em sau khi collapse folder-per-note.
    by_note = defaultdict(list)
    for i, unit in enumerate(units):
        by_note[unit["file"]].append(i)
    centroids = {rel: _centroid([vectors[i] for i in ids]) for rel, ids in by_note.items()}
    by_parent = defaultdict(list)
    for rel in by_note:
        by_parent[logical_note_path(rel)[:-1]].append(rel)
    siblings = {}
    for rels in by_parent.values():
        if len(rels) >= 2:
            for rel in rels:
                siblings[rel] = sorted(x for x in rels if x != rel)

    evaluated, leaks = 0, []
    for unit, vec in zip(units, vectors):
        others = siblings.get(unit["file"], [])
        if not others:
            continue
        evaluated += 1
        own = _cos(vec, centroids[unit["file"]])
        target, other = max(((rel, _cos(vec, centroids[rel])) for rel in others),
                            key=lambda row: (row[1], row[0]))
        if other > own + TAXONOMY_EPS:
            leaks.append({"file": unit["file"], "section": unit["section"],
                          "target": target, "own_similarity": round(own, 4),
                          "other_similarity": round(other, 4),
                          "margin": round(other - own, 4)})
    leaks.sort(key=lambda x: (-x["margin"], x["file"], x["section"], x["target"]))

    # B4: pair sample lap lai; pair count luon la so cap THAT da tinh rho.
    pairs, total_pairs = _sample_pairs(len(units), pair_cap)
    tree_d = [_tree_distance(units[i]["tree"], units[j]["tree"]) for i, j in pairs]
    content_d = [1.0 - _cos(vectors[i], vectors[j]) for i, j in pairs]
    rho = spearman(tree_d, content_d)
    return {
        "available": bool(docs), "notes": len(docs or {}), "units": len(units),
        "ignored_short": ignored, "min_chars": TAXONOMY_MIN_CHARS,
        "b3_scope_leakage": {
            "evaluated": evaluated, "total": len(leaks),
            "pct": round(100.0 * len(leaks) / evaluated, 1) if evaluated else 0.0,
            "list": leaks[:max(0, int(list_n))],
        },
        "b4_distance_relatedness": {
            "spearman": round(rho, 4) if rho is not None else None,
            "pairs": len(pairs), "pair_population": total_pairs,
            "sampled": len(pairs) < total_pairs,
        },
    }


_TAXONOMY_DOC_CACHE = {"signature": None, "docs": None, "taxonomy": None}


def read_taxonomy_docs(graph, vault=VAULT):
    """Doc dung tap note cua graph va cache theo (path, mtime_ns, size)."""
    notes, _adj, _hubs = note_graph(graph, exclude=self_excludes())
    vault = os.path.abspath(vault)
    rows = []
    for rel in sorted(notes):
        path = os.path.abspath(os.path.join(vault, *rel.split("/")))
        try:
            if os.path.commonpath((vault, path)) != vault:
                continue
            st = os.stat(path)
        except (OSError, ValueError):
            continue
        rows.append((rel, path, st.st_mtime_ns, st.st_size))
    signature = (vault, tuple((rel, mtime, size) for rel, _p, mtime, size in rows))
    if _TAXONOMY_DOC_CACHE["signature"] == signature:
        return dict(_TAXONOMY_DOC_CACHE["docs"] or {})
    docs = {}
    for rel, path, _mtime, _size in rows:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                docs[rel] = f.read()
        except OSError:
            continue
    _TAXONOMY_DOC_CACHE.update(signature=signature, docs=docs, taxonomy=None)
    return dict(docs)


def measure_taxonomy(graph, vault=VAULT):
    """I/O + cache cho server/CLI; cung signature voi cache doc markdown."""
    docs = read_taxonomy_docs(graph, vault=vault)
    if _TAXONOMY_DOC_CACHE["taxonomy"] is None:
        _TAXONOMY_DOC_CACHE["taxonomy"] = build_taxonomy(docs)
    return _TAXONOMY_DOC_CACHE["taxonomy"]


def build_insight(events, graph, heat_notes=None, heat_meta=None, now=None,
                  days=DEFAULT_DAYS, cold_days=DEFAULT_COLD, top_n=12, list_n=40,
                  taxonomy_result=None, chains=None):
    """Ảnh chụp sức khoẻ truy xuất của vault.

    HÀM THUẦN: không đọc đĩa, không lấy giờ ẩn (`now` truyền vào) → test được bằng
    dữ liệu dựng tay. Caller lo phần I/O:
      events     — list event đã gộp mọi máy (serve.read_all_events)
      graph      — dict /graph-data (nodes/links/meta)
      heat_notes — {rel: {total, read, search, edit, first, last, agents}} đã gộp 2 máy
      heat_meta  — {since, updated, machines} của store heat (để in cửa sổ dữ liệu)
      taxonomy_result — kết quả build_taxonomy (measure_taxonomy đã cache); None =
                   caller chưa cấp nội dung markdown, B3/B4 unavailable
    Note báo cáo do chính module sinh (self_excludes) luôn bị loại khỏi phép đo.
      chains      — output canonical của serve.build_chains; chỉ dùng để rút tín hiệu
                    đọc-lặp/chuỗi-dài, không tự gom chain lần hai

    8 chỉ số (định nghĩa đầy đủ: note "Tầng Insight Sức Khoẻ Vault — KB Graph 3D"):
      1 nóng tuần này (J)         4 chưa bao giờ agent đụng (G − (H ∪ J))
      2 đang nguội đi (J)         5 cụm ít kết nối (G)
      3 nguội ≥ cold_days (H ∩ G) 6 coverage theo khu vực (G + H + J)
      7 B3 scope leakage (M)      8 B4 distance-relatedness (M)
      M = markdown hiện tại; TF-IDF cosine thuần, không embedding/LLM.
    """
    now = float(now if now is not None else time.time())
    days = max(1, int(days))
    cold_days = max(1, int(cold_days))
    heat_meta = heat_meta or {}
    skip = self_excludes()
    # Áp cùng phạm vi cho G, J và H. Chỉ lọc node graph là chưa đủ: event/heat của
    # file nháp vẫn có thể lọt vào bảng "nóng nhất" và cửa sổ dữ liệu.
    heat_notes = {rel: row for rel, row in (heat_notes or {}).items()
                  if rel not in skip and not _under_attachments(rel)}
    notes, adj, hubs = note_graph(graph, exclude=skip)

    cur_from = now - days * DAY
    prev_from = now - 2 * days * DAY
    # MỘT bộ đếm duy nhất (log_activity.aggregate_by_file) cho cả 3 lượt — cùng
    # luật gom loại/agent với heat, sửa một nơi khỏi lệch nhau. Event của note bị
    # loại (report tự sinh) rơi ra ngay từ đây, kẻo nó lọt vào bảng "nóng nhất".
    evs = [e for e in events if e.get("file") not in skip
           and not _under_attachments(e.get("file"))]
    cur = log_activity.aggregate_by_file([e for e in evs if _ts(e) >= cur_from])
    prev = log_activity.aggregate_by_file(
        [e for e in evs if prev_from <= _ts(e) < cur_from])
    seen_all = log_activity.aggregate_by_file(evs)

    # ---- 1. nóng tuần này (kèm số tuần trước để thấy chiều) ----
    hot = []
    for rel, r in sorted(cur.items(), key=lambda kv: (-kv[1]["total"], kv[0]))[:top_n]:
        p = prev.get(rel, {}).get("total", 0)
        hot.append({"file": rel, "n": r["total"], "prev": p, "delta": r["total"] - p,
                    "types": {t: r.get(t, 0) for t in TYPES},
                    "exists": rel in notes})

    # ---- 2. đang nguội đi: tuần trước sôi, tuần này im ----
    cooling = []
    for rel, r in sorted(prev.items(), key=lambda kv: (-kv[1]["total"], kv[0])):
        if r["total"] >= COOLING_MIN and rel not in cur:
            cooling.append({"file": rel, "prev": r["total"], "n": 0,
                            "exists": rel in notes})
    cooling_total = len(cooling)
    cooling = cooling[:top_n]

    # ---- lần đụng CUỐI của mỗi note: H (dài hạn) hợp J (cuộn) ----
    last_touch = {}
    for src in (seen_all, heat_notes):
        for rel, r in src.items():
            lt = (r or {}).get("last") or 0
            if isinstance(lt, (int, float)) and lt:
                last_touch[rel] = max(last_touch.get(rel, 0.0), float(lt))

    # ---- 3. nguội: đã từng đụng, nhưng lâu rồi. Chỉ note CÒN TỒN TẠI trong G ----
    # (heat store giữ cả đường dẫn note đã rename/xoá — báo "nguội" cho note không
    #  còn tồn tại là tín hiệu rác, nên phải giao với vault hiện hành.)
    cold_all, ages = [], []
    for rel in notes:
        lt = last_touch.get(rel, 0.0)
        if not lt:
            continue
        age = (now - lt) / DAY
        ages.append(age)
        if age >= cold_days:
            total = max(heat_notes.get(rel, {}).get("total", 0),
                        seen_all.get(rel, {}).get("total", 0))
            cold_all.append({"file": rel, "last": lt, "days": age, "total": total})
    cold_all.sort(key=lambda d: d["last"])       # nguội nhất (đụng xa nhất) lên đầu

    # ---- 4. chưa vào đường truy xuất: KHÔNG dấu vết nào, hoặc chỉ khớp tìm kiếm ----
    # "unread" = có dấu vết nhưng chưa lần nào read/edit (chỉ tình cờ khớp Grep/Glob):
    # agent chưa THẬT SỰ mở note đó — cùng họ tín hiệu "sót data" với never.
    touched = [rel for rel in notes if rel in seen_all or rel in heat_notes]
    never_all = sorted(rel for rel in notes if rel not in seen_all and rel not in heat_notes)
    unread_all = []
    for rel in sorted(touched):
        opened = max(seen_all.get(rel, {}).get("read", 0), heat_notes.get(rel, {}).get("read", 0)) \
            + max(seen_all.get(rel, {}).get("edit", 0), heat_notes.get(rel, {}).get("edit", 0))
        if not opened:
            unread_all.append(rel)

    # ---- 5. cụm ít kết nối (đồ thị note–note) ----
    comps = components(adj)
    orphans = sorted(rel for rel in notes if not adj[rel])
    thin = sorted(rel for rel in notes if len(adj[rel]) == 1)
    no_index = sorted(rel for rel in notes
                      if rel not in hubs and not (adj[rel] & hubs))
    index_candidates = {rel: nearest_index(rel, notes, hubs) for rel in no_index}
    small = [c for c in comps if len(c) <= SMALL_CLUSTER and len(c) > 1]

    # ---- 6. coverage theo khu vực ----
    never_set, orphan_set = set(never_all), set(orphans)
    cold_set = {d["file"] for d in cold_all}
    areas = {}
    for rel in notes:
        a = areas.setdefault(area_of(rel), {"area": area_of(rel), "notes": 0,
                                            "touched": 0, "never": 0,
                                            "cold": 0, "orphans": 0})
        a["notes"] += 1
        a["never" if rel in never_set else "touched"] += 1
        if rel in cold_set:
            a["cold"] += 1
        if rel in orphan_set:
            a["orphans"] += 1
    areas = sorted(areas.values(), key=lambda a: (-a["notes"], a["area"]))

    ts_all = [t for t in (_ts(e) for e in evs) if t]
    meta = graph.get("meta", {})
    n_notes = len(notes)
    taxonomy = taxonomy_result or build_taxonomy({}, list_n=list_n)
    friction = build_friction(chains, notes, cur_from, list_n=list_n)
    out = {
        "generated": now,
        "params": {"days": days, "cold_days": cold_days,
                   "cooling_min": COOLING_MIN, "small_cluster": SMALL_CLUSTER},
        "vault": {"notes": n_notes, "links": meta.get("links", len(graph.get("links", []))),
                  "files": meta.get("files", 0), "tags": meta.get("tags", 0),
                  "note_links": sum(len(v) for v in adj.values()) // 2,
                  "hubs": len(hubs)},
        "coverage": {"touched": len(touched), "never": len(never_all),
                     "notes": n_notes,
                     "pct": round(100.0 * len(touched) / n_notes, 1) if n_notes else 0.0},
        "window": {"cur_from": cur_from, "prev_from": prev_from,
                   "cur_events": sum(r["total"] for r in cur.values()),
                   "cur_notes": len(cur),
                   "prev_events": sum(r["total"] for r in prev.values()),
                   "prev_notes": len(prev),
                   "cur_by_type": {t: sum(r.get(t, 0) for r in cur.values())
                                   for t in TYPES}},
        "hot": hot,
        "cooling": {"total": cooling_total, "list": cooling},
        "cold": {"total": len(cold_all), "list": cold_all[:list_n],
                 "hist": age_hist(ages), "oldest_age": max(ages) if ages else 0.0},
        "never": {"total": len(never_all),
                  "list": [{"file": rel, "folder": notes[rel].get("folder", ""),
                            "degree": len(adj[rel])} for rel in never_all[:list_n]]},
        "unread": {"total": len(unread_all), "list": unread_all[:list_n]},
        "weak": {"components": len(comps),
                 "largest": len(comps[0]) if comps else 0,
                 "small": [{"size": len(c), "files": c} for c in small[:list_n]],
                 "orphans": {"total": len(orphans), "list": orphans[:list_n]},
                 "thin": {"total": len(thin), "list": thin[:list_n]},
                 "no_index": {"total": len(no_index), "list": no_index[:list_n]},
                 "index_candidates": {rel: index_candidates.get(rel)
                                      for rel in no_index[:list_n]}},
        "friction": friction,
        "taxonomy": taxonomy,
        "areas": areas,
        "data": {"events": len(evs),
                 "oldest_event": min(ts_all) if ts_all else None,
                 "newest_event": max(ts_all) if ts_all else None,
                 "heat_notes": len(heat_notes),
                 # Đường dẫn còn trong heat store mà vault không còn: note đã
                 # rename/xoá → lịch sử truy xuất của nó thành mồ côi. Nhiều bất
                 # thường = vault vừa qua đợt tái cấu trúc lớn.
                 "heat_stale_paths": sum(1 for rel in heat_notes if rel not in notes),
                 "heat_since": heat_meta.get("since"),
                 "heat_updated": heat_meta.get("updated"),
                 "heat_machines": heat_meta.get("machines") or []},
    }
    out["worklist"] = build_worklist(out, limit=WORKLIST_LIMIT)
    return out


# ---------------------------------------------------------------- I/O cho CLI

def collect(days=DEFAULT_DAYS, cold_days=DEFAULT_COLD, now=None):
    """Đọc 3 nguồn rồi gọi build_insight — dùng cho CLI (không cần server chạy).

    Import `serve` MUỘN (trong hàm): module-level `serve` đã `import insight`, nên
    import ở đầu file sẽ vòng tròn. Ở chế độ CLI, `insight` là `__main__` nên bản
    `serve` nạp thêm một COPY module `insight` — vô hại, hai bản đều thuần (không
    có state module-level dùng chung). Đổi lại: chỉ MỘT đường đọc/gộp event (không
    viết lại read_all_events lần thứ hai trong module này).
    """
    import serve  # noqa: PLC0415  (xem docstring — cố ý muộn để tránh vòng tròn)
    heat_notes, heat_meta = serve.merge_cumulative_stores()
    graph = serve.get_graph_data()
    events = serve.read_all_events()
    return build_insight(events, graph,
                         heat_notes=heat_notes, heat_meta=heat_meta,
                         now=now, days=days, cold_days=cold_days,
                         taxonomy_result=measure_taxonomy(graph),
                         chains=serve.build_chains(events, limit=len(events) + 1))


def _fmt_day(ts):
    if not isinstance(ts, (int, float)) or not ts:
        return "—"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _fmt_min(ts):
    if not isinstance(ts, (int, float)) or not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def print_summary(ins, out=print):
    """Tóm tắt cho console — đủ để chạy tay xem nhanh, không cần mở app."""
    p, c, w, d = ins["params"], ins["coverage"], ins["window"], ins["data"]
    out("== SỨC KHOẺ TRUY XUẤT VAULT — %s ==" % _fmt_min(ins["generated"]))
    out("Cửa sổ: %d ngày cuộn · nguội ≥ %d ngày · dữ liệu: event từ %s, heat từ %s (%s)"
        % (p["days"], p["cold_days"], _fmt_day(d["oldest_event"]),
           _fmt_day(d["heat_since"]), ", ".join(d["heat_machines"]) or "—"))
    out("Note: %d · coverage %.1f%% (%d đã từng đụng / %d CHƯA BAO GIỜ / %d chỉ khớp tìm kiếm)"
        % (ins["vault"]["notes"], c["pct"], c["touched"], c["never"],
           ins["unread"]["total"]))
    out("Tuần này: %d lượt / %d note   (tuần trước: %d / %d)"
        % (w["cur_events"], w["cur_notes"], w["prev_events"], w["prev_notes"]))
    out("Tuổi lần đụng cuối: %s  (già nhất %.1f ngày)"
        % (" · ".join("%s: %d" % (k, v) for k, v in ins["cold"]["hist"].items()),
           ins["cold"]["oldest_age"]))
    out("Nguội ≥%d ngày: %d note · đang nguội đi: %d"
        % (p["cold_days"], ins["cold"]["total"], ins["cooling"]["total"]))
    wk = ins["weak"]
    out("Kết nối: %d thành phần (lớn nhất %d note) · %d mồ côi · %d chỉ-1-dây · %d không nằm index nào"
        % (wk["components"], wk["largest"], wk["orphans"]["total"],
           wk["thin"]["total"], wk["no_index"]["total"]))
    wl = ins.get("worklist") or {"total": 0, "counts": {}}
    out("Worklist đề xuất: %d việc (%d P1 · %d P2 · %d P3) — chỉ đọc, cần người duyệt"
        % (wl["total"], wl["counts"].get("P1", 0), wl["counts"].get("P2", 0),
           wl["counts"].get("P3", 0)))
    tax = ins["taxonomy"]
    b3, b4 = tax["b3_scope_leakage"], tax["b4_distance_relatedness"]
    rho = "—" if b4["spearman"] is None else "%.3f" % b4["spearman"]
    out("Taxonomy: B3 scope leakage %.1f%% (%d/%d section) · B4 rho %s (%d/%d cặp)"
        % (b3["pct"], b3["total"], b3["evaluated"], rho,
           b4["pairs"], b4["pair_population"]))
    out("")
    out("Nóng nhất tuần này:")
    for h in ins["hot"][:8]:
        out("  %4d (tuần trước %3d)  %s" % (h["n"], h["prev"], h["file"]))
    if ins["never"]["list"]:
        out("Chưa bao giờ agent đụng (%d, hiện %d đầu):"
            % (ins["never"]["total"], min(8, len(ins["never"]["list"]))))
        for n in ins["never"]["list"][:8]:
            out("  %s" % n["file"])


# ------------------------------------------------- vế (b): note báo cáo trong vault

def report_path():
    return os.environ.get("GRAPH3D_INSIGHT_REPORT") or os.path.join(
        VAULT, *REPORT_REL.split("/"))


def _existing_date(path):
    """Giữ nguyên `date:` của bản đã có (ngày TẠO note) — chỉ `updated:` mới nhảy."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f.read().split("\n")[:15]:
                if line.startswith("date:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _tbl(header, rows, empty="_— không có._"):
    if not rows:
        return empty + "\n"
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _work_action(item):
    """Câu hành động hoàn chỉnh cho report; đường dẫn luôn là code, không wikilink."""
    rel, target, ev = item["file"], item.get("target"), item.get("evidence") or {}
    kind = item["kind"]
    if kind == "connect_index":
        return "Đề xuất thêm liên kết giữa `%s` và index gần nhất `%s`." % (rel, target)
    if kind == "review_index":
        return "Xác định index đúng cho `%s`, rồi mới đề xuất liên kết; máy không đoán chéo khu vực." % rel
    if kind == "open_unseen":
        return "Mở `%s`, xác nhận giá trị rồi quyết định giữ, gộp hoặc bổ sung đường truy xuất." % rel
    if kind == "reduce_reread":
        return "Rà `aliases` · `summary` · liên kết vào `%s` để giảm đọc lặp." % rel
    if kind == "shorten_chain":
        return "Rà lối tắt/MOC từ đầu chuỗi `%s` tới cuối chuỗi `%s`." % (rel, target)
    if kind == "review_scope":
        return "Duyệt section **%s** trong `%s` so với `%s`; không tự di chuyển." % (
            ev.get("section") or "—", rel, target)
    return "Duyệt `%s`." % rel


def _work_evidence(item):
    ev, kind = item.get("evidence") or {}, item["kind"]
    if kind in ("connect_index", "review_index"):
        flags = []
        if ev.get("orphan"):
            flags.append("mồ côi")
        if ev.get("never"):
            flags.append("chưa có dấu vết")
        if ev.get("unread"):
            flags.append("chỉ khớp tìm kiếm")
        return "ngoài index" + ((" · " + " · ".join(flags)) if flags else "")
    if kind == "open_unseen":
        return "chưa có dấu vết" if ev.get("never") else "chỉ khớp tìm kiếm"
    if kind == "reduce_reread":
        return "%d lượt đọc lặp trong %d chuỗi" % (ev.get("rereads", 0), ev.get("chains", 0))
    if kind == "shorten_chain":
        return "%d note khác nhau · %d thao tác · %.1f phút · %s · lặp %d lần" % (
            ev.get("distinct", 0), ev.get("count", 0), ev.get("span", 0.0) / 60.0,
            ev.get("agent") or "—", ev.get("occurrences", 1))
    if kind == "review_scope":
        return "B3 margin %.3f · cosine %.3f → %.3f" % (
            ev.get("margin", 0.0), ev.get("own_similarity", 0.0),
            ev.get("other_similarity", 0.0))
    return "—"


def render_report(ins, path=None):
    """Markdown của note báo cáo — thuần hàm (test được), không ghi đĩa.

    Đường dẫn note in dạng `code` chứ KHÔNG phải wikilink: report này không được tự
    sinh cạnh mới trong chính đồ thị mà nó đang đo (mồ côi/cụm/kết nối sẽ méo ngay
    lần chạy sau). Nội dung ổn định giữa 2 lần chạy cùng dữ liệu (idempotent) —
    chỉ dòng "Lần chạy" và `updated:` đổi.
    """
    p, c, w, wk, da = (ins["params"], ins["coverage"], ins["window"],
                       ins["weak"], ins["data"])
    today = time.strftime("%Y-%m-%d", time.localtime(ins["generated"]))
    created = _existing_date(path or report_path()) or today

    fm = ["---", "gate_ignore: true", "title: " + REPORT_TITLE,
          'aliases: ["Sức khoẻ vault", "Sức khoẻ truy xuất", "Báo cáo insight vault", '
          '"Note nóng nguội vault", "Vault health report"]',
          'summary: "Báo cáo SINH TỰ ĐỘNG (python .graph3d/insight.py --report) — sức khoẻ '
          'TRUY XUẤT của vault, song sinh với Báo Cáo Audit Vault (bản kia bắt vi phạm quy '
          'tắc): tổng quan coverage, note nóng nhất tuần, phân bố tuổi lần đụng cuối, note '
          'đang nguội đi, note nguội quá ngưỡng, note chưa vào đường truy xuất (không dấu '
          'vết / chỉ khớp tìm kiếm), cụm ít kết nối trên đồ thị note–note (mồ côi, chỉ-1-dây, '
          'ngoài index), hai chỉ số taxonomy B3 scope leakage + B4 khoảng cách cây so với '
          'độ liên quan, worklist đề xuất read-only có ưu tiên/đích/bằng chứng, và bảng '
          'coverage theo khu vực. Kèm cửa sổ dữ liệu của từng nguồn."',
          "source: Sinh từ `.graph3d/insight.py` (log hoạt động + heat tích luỹ + graph + markdown vault)",
          "date: " + created, "updated: " + today,
          "type: reference", "tags: [vault-operation]", "---", "", ""]

    L = ["# " + REPORT_TITLE, "",
         "> [!info] Note SINH TỰ ĐỘNG — `python .graph3d/insight.py --report`",
         "> Ảnh chụp sức khoẻ **truy xuất + taxonomy** của vault: độ tươi · độ phủ · "
         "độ kết nối · nội dung có còn nằm đúng chỗ. "
         "Song sinh với [[Báo Cáo Audit Vault]] — bản kia bắt **vi phạm quy tắc**, bản này "
         "đo **vault có đang được dùng đủ khắp không**. Ghi đè mỗi lần chạy: **đừng sửa tay**.",
         "> - Đường dẫn note để dạng `code` chứ KHÔNG phải wikilink — report không được tự "
         "tạo cạnh mới trong chính đồ thị nó đang đo.",
         "> - Xem tương tác (click mở note): section **🩺 Sức khoẻ vault** trong app "
         "[[KB Graph 3D]] (endpoint `/insight`, cùng một hàm tính).",
         "> - B3/B4 là **descriptor mức bám taxonomy, không phải điểm chất lượng**; danh "
         "sách lệch scope chỉ để người duyệt, công cụ không tự di chuyển note.",
         "> - Worklist H3 là **đề xuất read-only**: không tự thêm link, gộp/move section, "
         "sửa metadata hay ghi vào Work Map.", "",
         "**Lần chạy:** %s · **Cửa sổ:** %d ngày cuộn · nguội ≥ %d ngày · "
         "**Dữ liệu:** %d event (từ %s) + heat tích luỹ từ %s (máy: %s)"
         % (_fmt_min(ins["generated"]), p["days"], p["cold_days"], da["events"],
            _fmt_day(da["oldest_event"]), _fmt_day(da["heat_since"]),
            ", ".join(da["heat_machines"]) or "—"), "", "---", "",
         "## Tổng quan", ""]

    tax = ins["taxonomy"]
    wl = ins.get("worklist") or {"total": 0, "shown": 0, "counts": {}, "items": []}
    b3, b4 = tax["b3_scope_leakage"], tax["b4_distance_relatedness"]
    rho = "—" if b4["spearman"] is None else "%.3f" % b4["spearman"]
    L.append(_tbl(["Chỉ số", "Số", "Nghĩa"], [
        ["Note trong vault", c["notes"],
         "note `.md` được ĐO — không tính chính note báo cáo này"],
        ["Coverage", "%.1f%%" % c["pct"],
         "%d note đã từng có agent đụng" % c["touched"]],
        ["Chưa bao giờ đụng", c["never"], "không một dấu vết truy xuất nào"],
        ["Chỉ khớp tìm kiếm", ins["unread"]["total"],
         "có dấu vết nhưng chưa lần nào được đọc/sửa"],
        ["Ghé trong %d ngày" % p["days"], "%d note" % w["cur_notes"],
         "%d lượt (kỳ trước: %d lượt / %d note)"
         % (w["cur_events"], w["prev_events"], w["prev_notes"])],
        ["Nguội ≥%d ngày" % p["cold_days"], ins["cold"]["total"],
         "note già nhất: %.1f ngày" % ins["cold"]["oldest_age"]],
        ["Đang nguội đi", ins["cooling"]["total"],
         "kỳ trước ≥%d lượt, kỳ này 0" % p["cooling_min"]],
        ["Liên kết note–note", ins["vault"]["note_links"],
         "%d thành phần liên thông, lớn nhất %d note"
         % (wk["components"], wk["largest"])],
        ["Mồ côi / chỉ-1-dây", "%d / %d" % (wk["orphans"]["total"], wk["thin"]["total"]),
         "0 liên kết note / đúng 1 liên kết note"],
        ["Ngoài index", wk["no_index"]["total"],
         "không liên kết tới note index/MOC nào"],
        ["Worklist đề xuất", wl["total"], "%d P1 · %d P2 · %d P3 — cần người duyệt" %
         (wl["counts"].get("P1", 0), wl["counts"].get("P2", 0),
          wl["counts"].get("P3", 0))],
        ["B3 scope leakage", "%.1f%%" % b3["pct"],
         "%d/%d section gần note anh em hơn note cha" %
         (b3["total"], b3["evaluated"])],
        ["B4 cây ↔ nội dung", "ρ=" + rho,
         "%d/%d cặp section%s" % (b4["pairs"], b4["pair_population"],
          " — mẫu cố định" if b4["sampled"] else "")],
    ]))

    L += ["", "## 📋 Worklist đề xuất — hành động cụ thể, cần người duyệt", "",
          "> [!warning] Máy chỉ **đề xuất**, không tự sửa vault. Mỗi dòng có đích và "
          "bằng chứng để phiên có giám sát quyết định; bác bỏ đề xuất không làm thay đổi dữ liệu.", ""]
    L.append(_tbl(["ID", "Ưu tiên", "Đề xuất", "Bằng chứng"],
                  [["`%s`" % x["id"], x["priority"], _work_action(x), _work_evidence(x)]
                   for x in wl["items"]],
                  "_— snapshot này không sinh đề xuất nào._"))
    if wl.get("truncated"):
        L += ["", "_Đang hiện %d/%d đề xuất; JSON `/insight` giữ cùng giới hạn của snapshot._"
              % (wl["shown"], wl["total"])]

    L += ["", "## 🔥 Nóng nhất %d ngày qua" % p["days"], ""]
    L.append(_tbl(["Note", "Lượt", "Kỳ trước", "Chênh"],
                  [["`%s`" % h["file"], h["n"], h["prev"],
                    "%+d" % h["delta"]] for h in ins["hot"]],
                  "_— chưa có lượt truy xuất nào trong cửa sổ này._"))

    L += ["", "## 🌡 Tuổi lần đụng cuối (toàn vault)", "",
          "Bức tranh KHÔNG phụ thuộc ngưỡng — routine daily quét gần cả vault mỗi ngày nên "
          "phân bố dồn về phía trẻ; đọc cột phải để thấy phần vault đang bị bỏ xa.", ""]
    L.append(_tbl(["Khoảng (ngày)", "Số note"],
                  [[k, v] for k, v in ins["cold"]["hist"].items()]))

    L += ["", "## 🥶 Đang nguội đi (%d note)" % ins["cooling"]["total"], ""]
    L.append(_tbl(["Note", "Kỳ trước", "Kỳ này"],
                  [["`%s`" % x["file"], x["prev"], 0] for x in ins["cooling"]["list"]],
                  "_— không note nào vừa rời tay._"))

    L += ["", "## 🕸 Nguội ≥%d ngày (%d note — nguội nhất trước)"
          % (p["cold_days"], ins["cold"]["total"]), ""]
    L.append(_tbl(["Note", "Lần cuối", "Ngày", "Tổng lượt"],
                  [["`%s`" % x["file"], _fmt_day(x["last"]), "%.1f" % x["days"],
                    x["total"]] for x in ins["cold"]["list"]],
                  "_— không note nào nguội quá ngưỡng._"))

    L += ["", "## 🚫 Chưa vào đường truy xuất", "",
          "Đây là chỗ dễ **sót data** nhất: tri thức có trong vault nhưng chưa lần nào "
          "vào đường truy xuất của agent.", "",
          "**Không một dấu vết nào (%d):**" % ins["never"]["total"], ""]
    L.append(_tbl(["Note", "Liên kết note"],
                  [["`%s`" % x["file"], x["degree"]] for x in ins["never"]["list"]],
                  "_— mọi note đều đã từng được đụng._"))
    L += ["", "**Chỉ tình cờ khớp tìm kiếm, chưa lần nào được đọc/sửa (%d):**"
          % ins["unread"]["total"], ""]
    L.append(_tbl(["Note"], [["`%s`" % f] for f in ins["unread"]["list"]],
                  "_— không có._"))

    L += ["", "## 🔗 Cụm ít kết nối (đồ thị note–note, bỏ cạnh tag/file)", "",
          "%d thành phần liên thông · lớn nhất %d note"
          % (wk["components"], wk["largest"]), ""]
    if wk["small"]:
        L += ["**Cụm nhỏ (≤%d note) nằm rời khỏi phần còn lại:**" % p["small_cluster"], ""]
        L += ["- cụm %d note: %s" % (cl["size"], " · ".join("`%s`" % f for f in cl["files"]))
              for cl in wk["small"]] + [""]
    for label, key in (("Mồ côi (0 liên kết note)", "orphans"),
                       ("Chỉ 1 liên kết note", "thin"),
                       ("Không nằm index nào", "no_index")):
        L += ["**%s (%d):**" % (label, wk[key]["total"]), ""]
        L.append(_tbl(["Note"], [["`%s`" % f] for f in wk[key]["list"]], "_— không có._"))
        L.append("")

    L += ["", "## 🌳 Taxonomy — nội dung có còn nằm đúng chỗ?", "",
          "Nguồn: content unit = section lá ≥%d ký tự; TF-IDF cosine thuần, không "
          "embedding/LLM. Theo Appendix D.4 của arXiv:2607.26637. Hai số này mô tả "
          "mức bám taxonomy, **không phải điểm chất lượng**." % tax["min_chars"], "",
          "- **B3 scope leakage:** %.1f%% (%d/%d section được đánh giá) gần centroid "
          "note anh em hơn note cha." % (b3["pct"], b3["total"], b3["evaluated"]),
          "- **B4 distance-relatedness:** ρ=%s trên %d/%d cặp section%s. Số dương = "
          "nội dung liên quan có xu hướng nằm gần nhau trên cây."
          % (rho, b4["pairs"], b4["pair_population"],
             " lấy mẫu cố định" if b4["sampled"] else ""), "",
          "**Section lệch scope (margin cao trước; chỉ là gợi ý để người duyệt):**", ""]
    L.append(_tbl(["Note cha", "Section", "Note anh em gần hơn", "Cosine cha → đích", "Margin"],
                  [["`%s`" % x["file"], x["section"], "`%s`" % x["target"],
                    "%.3f → %.3f" % (x["own_similarity"], x["other_similarity"]),
                    "%.3f" % x["margin"]] for x in b3["list"]],
                  "_— không section nào lệch scope theo phép đo này._"))

    L += ["", "## 🗺 Theo khu vực", ""]
    L.append(_tbl(["Khu vực", "Note", "Đã đụng", "Chưa bao giờ", "Nguội", "Mồ côi"],
                  [[a["area"], a["notes"], a["touched"], a["never"], a["cold"],
                    a["orphans"]] for a in ins["areas"]]))

    if da["heat_stale_paths"]:
        L += ["", "> [!note] %d đường dẫn trong heat store không còn trong vault"
              % da["heat_stale_paths"],
              "> Note đã rename/xoá — lịch sử truy xuất của chúng thành mồ côi (mọi chỉ số "
              "ở trên đã giao với vault hiện hành nên không bị nhiễu). Nhiều bất thường = "
              "vault vừa qua một đợt tái cấu trúc lớn."]

    L += ["", "---", "", "[[Index - Audit Vault]]", ""]
    return "\n".join(fm) + "\n".join(L)


def write_report(ins, path=None, dry_run=False):
    """Ghi note báo cáo (LF, UTF-8). Trả (path, text, changed).

    CỐ Ý không gọi log_activity: report là công cụ ĐO truy xuất, tự log lần ghi của
    mình sẽ tự bơm chính nó thành "note nóng" ở lần chạy sau (vòng tự quan sát).
    """
    path = path or report_path()
    text = render_report(ins, path=path)
    old = None
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        pass
    changed = old != text
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return path, text, changed


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        pass                       # console cp1252 không in được tiếng Việt
    ap = argparse.ArgumentParser(description="Insight sức khoẻ truy xuất vault (KB Graph 3D)")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help="cửa sổ 'tuần' tính bằng ngày cuộn (mặc định 7)")
    ap.add_argument("--cold", type=int, default=DEFAULT_COLD,
                    help="bao nhiêu ngày không ai đụng thì coi là nguội (mặc định 14)")
    ap.add_argument("--json", action="store_true", help="đổ nguyên JSON thay vì tóm tắt")
    ap.add_argument("--report", action="store_true",
                    help="ghi/cập nhật note báo cáo trong vault (%s)" % REPORT_REL)
    ap.add_argument("--dry-run", action="store_true",
                    help="với --report: in markdown ra stdout, KHÔNG ghi đĩa")
    args = ap.parse_args(argv)
    ins = collect(days=args.days, cold_days=args.cold)
    if args.report:
        path, text, changed = write_report(ins, dry_run=args.dry_run)
        if args.dry_run:
            print(text)
            print("-- dry-run: KHÔNG ghi %s (%d ký tự, %s) --"
                  % (path, len(text), "khác bản trên đĩa" if changed else "y hệt bản trên đĩa"))
        else:
            print("Đã ghi %s (%d ký tự)" % (path, len(text)))
        return 0
    if args.json:
        print(json.dumps(ins, ensure_ascii=False, indent=2))
    else:
        print_summary(ins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
