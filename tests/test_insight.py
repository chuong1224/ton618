# -*- coding: utf-8 -*-
"""Test tang insight suc khoe vault (W10) — insight.build_insight + render_report:

  - cua so tuan CUON: nong tuan nay + so voi tuan truoc, event thieu ts khong lot vao
  - "dang nguoi di" = tuan truoc >= COOLING_MIN ma tuan nay 0
  - "nguoi" doc last-touch tu heat tich luy VA log, chi tinh note CON TON TAI trong graph
  - histogram tuoi last-touch khong phu thuoc nguong
  - "chua vao duong truy xuat": never (0 dau vet) + unread (chi khop tim kiem)
  - do thi NOTE-NOTE: bo canh tag/file, thanh phan lien thong, mo coi, 1-day, ngoai index
  - coverage theo khu vuc (folder cap 1)
  - taxonomy metrics: content unit = section la >=40 ky tu, TF-IDF cosine thuan
  - B3 scope leakage: section gan note anh em hon centroid note cha
  - B4 distance-relatedness: Spearman giua khoang cach cay va khoang cach noi dung
  - W18/H3: worklist chi tieu thu snapshot, co uu tien/dich/bang chung, khong auto-apply
  - self_excludes: note bao cao do chinh module sinh KHONG duoc nam trong phep do
  - render_report: idempotent, KHONG sinh wikilink tro tung note (khong tu tao canh moi)
  - merge_cumulative_stores cua serve tra first/last (nguon cua chi so "nguoi")
"""
import json, os, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252
except Exception:
    pass

from _scratch import SCRATCH, G3D, VAULT
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_insight.jsonl"))
sys.path.insert(0, G3D)

import insight as IN

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

NOW = time.mktime((2026, 7, 25, 12, 0, 0, 0, 0, -1))
D = IN.DAY

def ev(days_ago, f, t="read", ag="Claude"):
    return {"ts": NOW - days_ago * D, "file": f, "type": t, "agent": ag}

def note(rel, group="Research", hub=False):
    return {"id": rel, "kind": "note", "name": rel, "stem": rel.split("/")[-1][:-3],
            "folder": os.path.dirname(rel), "group": group, "hub": hub,
            "tags": [], "summary": "", "degree": 0}

# --- vault gia: 2 khu vuc, 1 index (hub), 1 cum roi 2 note, 1 mo coi, node tag/file ---
GRAPH = {
    "meta": {"notes": 7, "links": 8, "files": 1, "tags": 1},
    "nodes": [
        note("Work/Index - Work.md", group="Index / MOC", hub=True),
        note("Work/A/A.md"), note("Work/B/B.md"), note("Work/C/C.md"),
        note("Research/D/D.md"), note("Research/E/E.md"),   # cum roi 2 note
        note("Research/F/F.md"),                            # mo coi
        {"id": "#research", "kind": "tag", "name": "#research", "stem": "#research",
         "group": "Tag", "degree": 3, "folder": ""},
        {"id": "Work/A/attachments/x.png", "kind": "file", "name": "x.png",
         "stem": "x.png", "group": "File", "degree": 1, "folder": "Work/A/attachments"},
    ],
    "links": [
        {"source": "Work/Index - Work.md", "target": "Work/A/A.md"},
        {"source": "Work/Index - Work.md", "target": "Work/B/B.md"},
        {"source": "Work/A/A.md", "target": "Work/B/B.md"},
        {"source": "Work/B/B.md", "target": "Work/C/C.md"},   # C chi 1 day, khong toi index
        {"source": "Research/D/D.md", "target": "Research/E/E.md"},
        # canh tag/file KHONG duoc tinh vao do thi note-note:
        {"source": "Research/F/F.md", "target": "#research"},
        {"source": "Research/D/D.md", "target": "#research"},
        {"source": "Work/A/A.md", "target": "Work/A/attachments/x.png"},
    ],
}

EVENTS = [
    ev(0.5, "Work/A/A.md"), ev(1, "Work/A/A.md"), ev(2, "Work/A/A.md", "edit"),
    ev(3, "Work/B/B.md"),
    ev(9, "Work/C/C.md"), ev(9.5, "Work/C/C.md"), ev(10, "Work/C/C.md"),  # tuan TRUOC: 3 luot
    ev(8, "Research/D/D.md", "search"),                      # chi khop tim kiem
    ev(20, "Work/da-xoa.md"),                                # note khong con trong vault
    {"file": "Work/B/B.md", "type": "read", "agent": "Claude"},   # thieu ts
]
HEAT = {
    "Work/A/A.md": {"total": 9, "read": 8, "search": 0, "edit": 1,
                    "first": NOW - 20 * D, "last": NOW - 0.5 * D, "agents": {"Claude": 9}},
    "Work/B/B.md": {"total": 2, "read": 2, "search": 0, "edit": 0,
                    "first": NOW - 5 * D, "last": NOW - 3 * D, "agents": {"Claude": 2}},
    "Work/C/C.md": {"total": 3, "read": 3, "search": 0, "edit": 0,
                    "first": NOW - 12 * D, "last": NOW - 9 * D, "agents": {"Claude": 3}},
    "Research/D/D.md": {"total": 1, "read": 0, "search": 1, "edit": 0,
                        "first": NOW - 8 * D, "last": NOW - 8 * D, "agents": {"Claude": 1}},
    "Research/E/E.md": {"total": 4, "read": 4, "search": 0, "edit": 0,
                        "first": NOW - 40 * D, "last": NOW - 33 * D, "agents": {"Hermes": 4}},
    "Work/da-xoa.md": {"total": 7, "read": 7, "search": 0, "edit": 0,
                       "first": NOW - 30 * D, "last": NOW - 20 * D, "agents": {"Claude": 7}},
}
META = {"machines": ["HOST-A"], "since": NOW - 40 * D, "updated": NOW}
CHAIN_EVENTS = [
    ev(1.0, "Work/A/A.md"), ev(0.999, "Work/A/A.md"), ev(0.998, "Work/A/A.md"),
    ev(0.997, "Work/B/B.md"), ev(0.996, "Work/C/C.md"),
    ev(0.995, "Research/D/D.md"), ev(0.994, "Research/E/E.md"),
    ev(0.993, "Research/F/F.md"),
]
CHAINS = [{"agent": "Claude", "start": CHAIN_EVENTS[0]["ts"],
           "end": CHAIN_EVENTS[-1]["ts"], "events": CHAIN_EVENTS}]

I = IN.build_insight(EVENTS, GRAPH, heat_notes=HEAT, heat_meta=META, now=NOW,
                     days=7, cold_days=7, exclude=set(), chains=CHAINS)

# ---- Taxonomy fixture rieng, khong phu thuoc event/heat ----
TAX_DOCS = {
    "Root/Topics/Cats/Cats.md": """---
title: Cats
---
# Cats
## Cham soc meo
Meo feline ria whisker keu purr va cham soc long meo trong nha moi ngay.
## Ngan sach dat nham cho
Ngan sach doanh thu chi phi loi nhuan du bao tai chinh theo quy va ke hoach dau tu.
""",
    "Root/Topics/Dogs/Dogs.md": """# Dogs
## Cham soc cho
Cho canine sua bark va cham soc long cho trong nha cung cac bua an moi ngay.
""",
    "Root/Topics/Budget/Budget.md": """# Budget
## Ke hoach tai chinh
Ngan sach doanh thu chi phi loi nhuan du bao tai chinh theo quy va ke hoach dau tu.
""",
    "Root/Topics/Tiny/Tiny.md": "# Tiny\n## Qua ngan\nngan\n",
}
units, ignored = IN.taxonomy_units(TAX_DOCS)
check("T1 chi lay section LA >=40 ky tu va bo frontmatter",
      len(units) == 4 and ignored == 1 and all(u["chars"] >= 40 for u in units),
      (units, ignored))
check("T1 path folder-per-note duoc collapse dung mot cap",
      IN.logical_note_path("Root/Topics/Cats/Cats.md") == ("Root", "Topics", "Cats"))
check("T1 section co du ancestry de tinh khoang cach cay",
      any(u["tree"][-2:] == ("Cats", "Cham soc meo") for u in units),
      [u["tree"] for u in units])

check("T2 Spearman co tie dung average-rank",
      abs(IN.spearman([1, 1, 2, 3], [10, 10, 20, 30]) - 1.0) < 1e-9)
check("T2 Spearman undefined khi mot ve hang",
      IN.spearman([1, 1, 1], [1, 2, 3]) is None)

TAX = IN.build_taxonomy(TAX_DOCS, list_n=10, pair_cap=1000)
check("T3 taxonomy co contract B3+B4 va dem nguon",
      TAX["available"] and TAX["notes"] == 4 and TAX["units"] == 4
      and TAX["ignored_short"] == 1
      and set(TAX) >= {"b3_scope_leakage", "b4_distance_relatedness"}, TAX)
leaks = TAX["b3_scope_leakage"]
check("T3 bat section tai chinh nam nham trong note Cats",
      leaks["total"] >= 1
      and any(x["file"] == "Root/Topics/Cats/Cats.md"
              and x["target"] == "Root/Topics/Budget/Budget.md"
              and "Ngan sach dat nham cho" in x["section"] for x in leaks["list"]),
      leaks)
check("T3 moi leak co score doi chieu va margin duong",
      all(x["other_similarity"] > x["own_similarity"]
          and x["margin"] > 0 for x in leaks["list"]), leaks["list"])

ALIGN_DOCS = {
    "Root/Animals/Cats/Cats.md": "Meo feline animal pet whisker purr cham soc dong vat trong nha rat than thien.",
    "Root/Animals/Dogs/Dogs.md": "Cho canine animal pet bark cham soc dong vat trong nha rat than thien.",
    "Root/Finance/Budget/Budget.md": "Tai chinh ngan sach doanh thu chi phi loi nhuan du bao theo quy va nam.",
    "Root/Finance/Revenue/Revenue.md": "Tai chinh doanh thu loi nhuan chi phi ngan sach du bao theo quy va nam.",
}
ALIGN = IN.build_taxonomy(ALIGN_DOCS, pair_cap=1000)
check("T4 B4 duong khi cay gan-xa phan anh noi dung gan-xa",
      ALIGN["b4_distance_relatedness"]["spearman"] is not None
      and ALIGN["b4_distance_relatedness"]["spearman"] > 0.5,
      ALIGN["b4_distance_relatedness"])
check("T4 B4 bao dung so cap va khong sample khi duoi cap",
      ALIGN["b4_distance_relatedness"]["pairs"] == 6
      and not ALIGN["b4_distance_relatedness"]["sampled"],
      ALIGN["b4_distance_relatedness"])

ITAX = IN.build_insight(EVENTS, GRAPH, heat_notes=HEAT, heat_meta=META, now=NOW,
                        days=7, cold_days=7, exclude=set(), taxonomy_docs=TAX_DOCS)
check("T5 build_insight xuat taxonomy cung snapshot",
      ITAX["taxonomy"]["available"]
      and ITAX["taxonomy"]["b3_scope_leakage"]["total"] == leaks["total"],
      ITAX["taxonomy"])
check("T5 B3 margin du manh tu vao worklist review-only",
      any(x["kind"] == "review_scope" and x["review_required"]
          for x in ITAX["worklist"]["items"]), ITAX["worklist"])

# ---- do thi note-note: canh tag/file bi bo ----
notes, adj, hubs = IN.note_graph(GRAPH)
check("N chi lay node kind=note", len(notes) == 7, sorted(notes))
check("N bo canh tag/file khoi do thi note-note",
      I["vault"]["note_links"] == 5, I["vault"]["note_links"])
check("N hub = nhom Index / MOC", hubs == {"Work/Index - Work.md"}, hubs)

# ---- .md trong attachments/ la file phu tro, KHONG phai note ----
# Hai case phai di thanh CAP: case B chung minh bo loc van nhin thay cung file khi
# no lui ra ngoai attachments/, tranh xanh gia kieu "chua bao gio nhin".
ATTACH_DRAFT = "Work/A/attachments/_inbox/_draft.md"
OUTSIDE_DRAFT = "Work/A/_inbox/_draft.md"
draft_heat = {"total": 5, "read": 5, "search": 0, "edit": 0,
              "first": NOW - 2 * D, "last": NOW - 0.25 * D,
              "agents": {"Claude": 5}}

G_ATTACH = {"meta": dict(GRAPH["meta"]),
            "nodes": GRAPH["nodes"] + [note(ATTACH_DRAFT)],
            "links": list(GRAPH["links"])}
I_ATTACH = IN.build_insight(EVENTS + [ev(0.25, ATTACH_DRAFT)], G_ATTACH,
                            heat_notes={**HEAT, ATTACH_DRAFT: draft_heat},
                            heat_meta=META, now=NOW, days=7, cold_days=7,
                            exclude=set())
check("A .md trong attachments im lang tren moi chi so",
      ATTACH_DRAFT not in json.dumps(I_ATTACH, ensure_ascii=False)
      and I_ATTACH["coverage"]["notes"] == 7,
      I_ATTACH)

G_OUTSIDE = {"meta": dict(GRAPH["meta"]),
             "nodes": GRAPH["nodes"] + [note(OUTSIDE_DRAFT)],
             "links": list(GRAPH["links"])}
I_OUTSIDE = IN.build_insight(EVENTS + [ev(0.25, OUTSIDE_DRAFT)], G_OUTSIDE,
                             heat_notes={**HEAT, OUTSIDE_DRAFT: draft_heat},
                             heat_meta=META, now=NOW, days=7, cold_days=7,
                             exclude=set())
check("B cung .md lui ra ngoai attachments duoc bat lai",
      I_OUTSIDE["coverage"]["notes"] == 8
      and OUTSIDE_DRAFT in I_OUTSIDE["weak"]["no_index"]["list"]
      and OUTSIDE_DRAFT in {h["file"] for h in I_OUTSIDE["hot"]},
      I_OUTSIDE)

# ---- cua so tuan ----
check("W tuan nay dem dung", (I["window"]["cur_events"], I["window"]["cur_notes"]) == (4, 2),
      I["window"])
# tuan TRUOC = [NOW-14d, NOW-7d): C x3 (9/9.5/10 ngay) + D (8 ngay) = 4 luot / 2 note
check("W tuan truoc dem dung", (I["window"]["prev_events"], I["window"]["prev_notes"]) == (4, 2),
      I["window"])
# 10 event dau vao: 8 nam trong 2 cua so, 1 cach nay 20 ngay, 1 THIEU ts (ts=0 -> ngoai het)
check("W event thieu ts khong lot vao cua so nao",
      I["window"]["cur_events"] + I["window"]["prev_events"] == 8,
      (I["window"]["cur_events"], I["window"]["prev_events"]))
hot = {h["file"]: h for h in I["hot"]}
check("W nong nhat = A voi 3 luot", I["hot"][0]["file"] == "Work/A/A.md"
      and I["hot"][0]["n"] == 3, I["hot"][:2])
check("W hot mang so tuan truoc + delta", hot["Work/A/A.md"]["prev"] == 0
      and hot["Work/A/A.md"]["delta"] == 3, hot["Work/A/A.md"])
check("W hot co co 'exists' de UI biet note con hay khong",
      all("exists" in h for h in I["hot"]))

# ---- dang nguoi di ----
cool = {c["file"] for c in I["cooling"]["list"]}
check("C 'dang nguoi di' = C (tuan truoc 3, tuan nay 0)", cool == {"Work/C/C.md"}, cool)
check("C khong ke note tuan truoc it luot (< COOLING_MIN)",
      "Research/D/D.md" not in cool and I["cooling"]["total"] == 1, I["cooling"])

# ---- nguoi + histogram ----
cold = {c["file"]: c for c in I["cold"]["list"]}
check("K nguoi >=7 ngay: C, D, E", set(cold) == {"Work/C/C.md", "Research/D/D.md",
      "Research/E/E.md"}, set(cold))
check("K note da xoa khoi vault KHONG bao nguoi", "Work/da-xoa.md" not in cold)
check("K nguoi nhat len dau", I["cold"]["list"][0]["file"] == "Research/E/E.md",
      I["cold"]["list"][0])
check("K so ngay tinh dung", abs(cold["Work/C/C.md"]["days"] - 9) < 0.01,
      cold["Work/C/C.md"])
check("K histogram phu du bucket + tong = note co last",
      sum(I["cold"]["hist"].values()) == 5
      and I["cold"]["hist"]["30+"] == 1 and I["cold"]["hist"]["7-14"] == 2,
      I["cold"]["hist"])
check("K oldest_age = note nguoi nhat", abs(I["cold"]["oldest_age"] - 33) < 0.01,
      I["cold"]["oldest_age"])

# ---- chua vao duong truy xuat ----
# khong dau vet nao: F (chi co canh tag) va chinh note index (fixture khong ai doc)
check("U never = F + note index (0 dau vet)",
      [x["file"] for x in I["never"]["list"]] == ["Research/F/F.md", "Work/Index - Work.md"],
      I["never"])
check("U unread = D (chi khop tim kiem, chua doc/sua)",
      I["unread"]["list"] == ["Research/D/D.md"], I["unread"])
check("U coverage dung (5 note co dau vet / 7)",
      (I["coverage"]["touched"], I["coverage"]["never"], I["coverage"]["notes"],
       I["coverage"]["pct"]) == (5, 2, 7, 71.4), I["coverage"])

# ---- cum it ket noi ----
wk = I["weak"]
check("G 3 thanh phan lien thong (4 + 2 + 1)", wk["components"] == 3, wk["components"])
check("G thanh phan lon nhat 4 note", wk["largest"] == 4, wk["largest"])
check("G cum nho (2 note D-E) duoc liet ke",
      [c["size"] for c in wk["small"]] == [2]
      and set(wk["small"][0]["files"]) == {"Research/D/D.md", "Research/E/E.md"}, wk["small"])
check("G mo coi = F", wk["orphans"]["list"] == ["Research/F/F.md"], wk["orphans"])
check("G chi-1-day = C, D, E", set(wk["thin"]["list"]) == {"Work/C/C.md",
      "Research/D/D.md", "Research/E/E.md"}, wk["thin"])
check("G ngoai index = moi note tru A, B (hub khong tu tinh)",
      set(wk["no_index"]["list"]) == {"Work/C/C.md", "Research/D/D.md",
                                      "Research/E/E.md", "Research/F/F.md"},
      wk["no_index"])
check("G index gan nhat chon bang ancestry, khong doan cheo khu vuc",
      wk["index_candidates"]["Work/C/C.md"] == "Work/Index - Work.md"
      and wk["index_candidates"]["Research/F/F.md"] is None,
      wk["index_candidates"])

# ---- W18/H3: friction -> worklist actionable, read-only ----
fr = I["friction"]
check("H3 doc lap-lai tu chain canonical, khong gom lai event",
      fr["available"] and fr["reread"]["list"][0] == {
          "file": "Work/A/A.md", "rereads": 2, "chains": 1}, fr)
check("H3 bat chuoi dai >= nguong voi dau-cuoi cu the",
      fr["long"]["total"] == 1
      and fr["long"]["list"][0]["first"] == "Work/A/A.md"
      and fr["long"]["list"][0]["last"] == "Research/F/F.md", fr["long"])
wl = I["worklist"]
kinds = {x["kind"] for x in wl["items"]}
check("H3 worklist co du 4 nhom hanh dong cu the",
      {"connect_index", "review_index", "reduce_reread", "shorten_chain"} <= kinds,
      wl["items"])
check("H3 link index co dich chinh xac + blind spot len P1",
      any(x["kind"] == "connect_index" and x["file"] == "Work/C/C.md"
          and x["target"] == "Work/Index - Work.md" and x["priority"] == "P2"
          for x in wl["items"])
      and any(x["kind"] == "review_index" and x["file"] == "Research/F/F.md"
              and x["priority"] == "P1" for x in wl["items"]), wl["items"])
check("H3 tat ca item on dinh + review-required, top-level cam auto-apply",
      not wl["auto_apply"] and wl["review_required"]
      and all(x["id"].startswith("H3-") and x["review_required"] for x in wl["items"]), wl)
check("H3 build_worklist idempotent tren cung snapshot",
      wl == IN.build_worklist(I, limit=40))

# ---- khu vuc ----
ar = {a["area"]: a for a in I["areas"]}
check("A khu vuc = folder cap 1", set(ar) == {"Work", "Research"}, set(ar))
check("A Work: 4 note / 3 da dung / 1 chua / 1 nguoi / 0 mo coi",
      (ar["Work"]["notes"], ar["Work"]["touched"], ar["Work"]["never"],
       ar["Work"]["cold"], ar["Work"]["orphans"]) == (4, 3, 1, 1, 0), ar["Work"])
check("A Research: 3 note / 2 da dung / 1 chua / 1 mo coi / 2 nguoi",
      (ar["Research"]["notes"], ar["Research"]["touched"], ar["Research"]["never"],
       ar["Research"]["orphans"], ar["Research"]["cold"]) == (3, 2, 1, 1, 2), ar["Research"])

# ---- cua so du lieu phai di kem so ----
check("D data mang cua so cua tung nguon",
      I["data"]["heat_since"] == META["since"]
      and I["data"]["heat_machines"] == ["HOST-A"]
      and I["data"]["oldest_event"] == NOW - 20 * D, I["data"])
check("D dem duong dan heat khong con trong vault", I["data"]["heat_stale_paths"] == 1,
      I["data"]["heat_stale_paths"])

# ---- tham so + bien ----
I90 = IN.build_insight(EVENTS, GRAPH, heat_notes=HEAT, now=NOW, days=7, cold_days=90,
                       exclude=set())
check("P cold_days=90 -> khong note nao nguoi", I90["cold"]["total"] == 0)
check("P days/cold_days xau bi ep >= 1",
      IN.build_insight([], GRAPH, now=NOW, days=0, cold_days=-5,
                       exclude=set())["params"] == {"days": 1, "cold_days": 1,
                                                    "cooling_min": IN.COOLING_MIN,
                                                    "small_cluster": IN.SMALL_CLUSTER})
IE = IN.build_insight([], {"nodes": [], "links": [], "meta": {}}, now=NOW, exclude=set())
check("P vault rong khong loi", IE["coverage"]["pct"] == 0.0 and IE["hot"] == []
      and IE["weak"]["components"] == 0, IE["coverage"])
check("P khong mutate list event dau vao", all("dwell" not in e for e in EVENTS)
      and len(EVENTS) == 10)

# ---- self_excludes: cong cu do khong nam trong phep do ----
G2 = {"meta": {}, "nodes": GRAPH["nodes"] + [note(IN.REPORT_REL)], "links": GRAPH["links"]}
E2 = EVENTS + [ev(0.2, IN.REPORT_REL, "edit")]
ISELF = IN.build_insight(E2, G2, heat_notes=HEAT, now=NOW, days=7, cold_days=7)
check("S note bao cao bi loai khoi tong note", ISELF["coverage"]["notes"] == 7,
      ISELF["coverage"])
check("S note bao cao khong nam trong 'chua bao gio dung'",
      all(x["file"] != IN.REPORT_REL for x in ISELF["never"]["list"]), ISELF["never"])
check("S event cua note bao cao khong lot vao bang nong",
      all(h["file"] != IN.REPORT_REL for h in ISELF["hot"]), ISELF["hot"])
check("S self_excludes chua duong dan mac dinh", IN.REPORT_REL in IN.self_excludes())

# ---- render_report ----
RP = os.path.join(SCRATCH, "insight_report.md")
txt = IN.render_report(I, path=RP)
check("R render 2 lan cung data = y het", txt == IN.render_report(I, path=RP))
check("R co frontmatter gate_ignore + tag vault-operation",
      txt.startswith("---\ngate_ignore: true\n") and "tags: [vault-operation]" in txt)
check("R title/H1 khop nhau", ("title: " + IN.REPORT_TITLE) in txt
      and ("# " + IN.REPORT_TITLE) in txt)
# Bao cao KHONG duoc wikilink tung note: no dang do chinh do thi do, tu them canh
# la lan sau so mo coi/cum/ket noi bi meo.
import re
links = set(re.findall(r"\[\[([^\]]+)\]\]", txt))
check("R khong wikilink tro tung note duoc do",
      not any(l.endswith(".md") or "/" in l for l in links), sorted(links))
for f in ("Work/A/A.md", "Research/F/F.md"):
    check("R duong dan '%s' in dang code" % f, ("`%s`" % f) in txt)
check("R co du cac muc noi dung + taxonomy",
      all(h in txt for h in ("## Tổng quan", "## 📋 Worklist đề xuất", "## 🔥 Nóng nhất", "## 🌡 Tuổi lần đụng cuối",
                             "## 🥶 Đang nguội đi", "## 🕸 Nguội", "## 🚫 Chưa vào đường truy xuất",
                             "## 🔗 Cụm ít kết nối", "## 🌳 Taxonomy", "## 🗺 Theo khu vực")))
check("R noi ro B3/B4 la descriptor, khong phai diem chat luong",
      "không phải điểm chất lượng" in txt and "B3 scope leakage" in txt
      and "B4 distance-relatedness" in txt)
check("R worklist noi ro read-only + co ID/uu tien/bang chung",
      "không tự sửa vault" in txt and "H3-" in txt
      and "| ID | Ưu tiên | Đề xuất | Bằng chứng |" in txt)
check("R ket thuc bang link index", txt.rstrip().endswith("[[Index - Audit Vault]]"))

os.environ["GRAPH3D_INSIGHT_REPORT"] = RP
_p, _t, changed = IN.write_report(I, dry_run=True)
check("R dry-run KHONG ghi dia", not os.path.exists(RP) and changed)
p2, t2, _c = IN.write_report(I)
check("R ghi that ra dung duong dan env", p2 == RP and os.path.exists(RP))
with open(RP, "rb") as f:
    raw = f.read()
check("R file ghi ra LF + UTF-8", b"\r\n" not in raw and raw.decode("utf-8"))
_p3, _t3, changed2 = IN.write_report(I, dry_run=True)
check("R ghi lai cung data -> khong doi (idempotent)", not changed2)
os.environ.pop("GRAPH3D_INSIGHT_REPORT", None)
os.remove(RP)

# ---- serve: nguon first/last cho chi so "nguoi" + endpoint ----
# W354: store rieng de do first/last ca tren clone rong, khong doc heat that.
heat_fixture = os.path.join(SCRATCH, "insight-heat")
os.makedirs(heat_fixture, exist_ok=True)
os.environ["GRAPH3D_HEAT_DIR"] = heat_fixture
with open(os.path.join(heat_fixture, "heat_cumulative-FIXTURE.json"), "w", encoding="utf-8") as f:
    json.dump({"host": "FIXTURE", "since": NOW - 10, "updated": NOW,
               "notes": {"Fixture.md": {"total": 1, "read": 1, "search": 0,
                         "edit": 0, "first": NOW - 10, "last": NOW, "agents": {"Test": 1}}}}, f)
import serve as SV
check("V serve co merge_cumulative_stores", hasattr(SV, "merge_cumulative_stores"))
merged, hmeta = SV.merge_cumulative_stores()
check("V merge tra (notes, meta) dung hinh",
      isinstance(merged, dict) and set(hmeta) == {"machines", "since", "updated"}, hmeta)
row = merged.get("Fixture.md", {})
check("V moi note trong store co first/last (nguon chi so nguoi)",
      row.get("first") == NOW - 10 and row.get("last") == NOW, row)
check("V /heat scope=all giu nguyen contract cu",
      set(SV.build_heat_cumulative(top_n=1)) >= {"scope", "counts", "max", "total",
                                                 "distinct", "machines", "since",
                                                 "updated", "top"})
sv_src = open(os.path.join(G3D, "serve.py"), encoding="utf-8").read()
check("V serve co endpoint /insight goi insight.build_insight",
      '"/insight"' in sv_src and "insight.build_insight" in sv_src)
check("V endpoint va CLI dung chain canonical cho worklist",
      "chains=build_chains(events" in sv_src
      and "chains=serve.build_chains(events" in open(os.path.join(G3D, "insight.py"), encoding="utf-8").read())
check("V server nap taxonomy active vault qua cache cua insight.py",
      "insight.measure_taxonomy(graph, vault=VAULT)" in sv_src)
check("V insight.py nam trong _VERSION_FILES (sua module PHAI restart server)",
      '"insight.py"' in open(os.path.join(G3D, "activity_paths.py"), encoding="utf-8").read())
ui_src = open(os.path.join(G3D, "src", "insight.js"), encoding="utf-8").read()
check("V UI khong tu tinh lai chi so (khong co nguong hard-code)",
      "pollInsight" in ui_src and "cold_days" not in ui_src.split("function render")[0])
check("V UI trinh bay B3/B4 tu contract server, khong tu vector hoa",
      "b3_scope_leakage" in ui_src and "b4_distance_relatedness" in ui_src
      and "tfidf" not in ui_src.lower() and "spearman(" not in ui_src.lower())
check("V UI trinh bay worklist server, khong tu sinh de xuat",
      "d.worklist" in ui_src and "ins.wl." in ui_src
      and "nearest_index" not in ui_src and "REREAD_MIN" not in ui_src)

print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
