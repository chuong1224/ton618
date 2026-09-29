# -*- coding: utf-8 -*-
"""Test Cockpit (giai doan 3 Vault Cockpit) — /timeline + /dashboard:
day_key/list_days/events_for_day loc dung MOT ngay local (fallback ngay moi nhat),
build_dashboard tong hop per-agent + histogram 24 gio + top note, metric chuoi
tinh bang build_chains (mot nguon su that) va KHONG mutate list event cache."""
import os, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 khong in duoc tieng Viet
except Exception:
    pass

from _scratch import SCRATCH, G3D, VAULT
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_cockpit.jsonl"))
sys.path.insert(0, G3D)

import serve as SV

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

def mk(y, mo, d, h, mi, s):
    """Timestamp LOCAL — cung dong ho voi day_key/build_dashboard (time.localtime)."""
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))

def ev(ts, f, t, ag):
    return {"ts": ts, "file": f, "type": t, "agent": ag}

# ---- du lieu tong hop: 2 ngay, 2 agent ----
T0 = mk(2026, 7, 14, 9, 0, 0)          # Claude: 1 chuoi 6 event, gap 10s
TH = mk(2026, 7, 14, 10, 30, 0)        # Hermes: 1 chuoi 2 event
T2 = mk(2026, 7, 15, 8, 0, 0)          # ngay hom sau: 1 event
EVENTS = [
    ev(T0,      "A.md", "read",   "Claude"),
    ev(T0 + 10, "B.md", "read",   "Claude"),
    ev(T0 + 20, "A.md", "read",   "Claude"),   # doc lap A -> rereads 1
    ev(T0 + 30, "B.md", "search", "Claude"),
    ev(T0 + 40, "C.md", "edit",   "Claude"),
    ev(T0 + 50, "C.md", "edit",   "Claude"),   # sua lap C -> reedits 1
    ev(TH,      "A.md", "read",   "Hermes"),
    ev(TH + 10, "D.md", "read",   "Hermes"),
    ev(T2,      "E.md", "read",   "Claude"),
]

# ---- day_key / list_days / events_for_day ----
check("C day_key theo gio local", SV.day_key(T0) == "2026-07-14", SV.day_key(T0))
check("C day_key ts hong tra chuoi rong", SV.day_key(None) == "")
days = SV.list_days(EVENTS)
check("C list_days moi nhat truoc", days == ["2026-07-15", "2026-07-14"], days)

d_evs, d_days, d_day = SV.events_for_day(EVENTS, "2026-07-14")
check("C events_for_day loc dung ngay", len(d_evs) == 8 and d_day == "2026-07-14",
      (len(d_evs), d_day))
_, _, d_def = SV.events_for_day(EVENTS)
check("C day rong -> ngay moi nhat", d_def == "2026-07-15", d_def)
_, _, d_bad = SV.events_for_day(EVENTS, "2020-01-01")
check("C day la -> fallback ngay moi nhat", d_bad == "2026-07-15", d_bad)
e_evs, e_days, e_day = SV.events_for_day([])
check("C log rong -> rong + day None", e_evs == [] and e_days == [] and e_day is None)

# ---- build_dashboard: ngay 14/07 ----
D = SV.build_dashboard(EVENTS, day="2026-07-14")
check("C dash day + days", D["day"] == "2026-07-14" and D["days"] == days,
      (D["day"], D["days"]))
check("C dash total 8", D["total"] == 8, D["total"])
check("C dash by_type", D["by_type"] == {"read": 5, "search": 1, "edit": 2}, D["by_type"])
check("C dash distinct note", D["distinct"] == 4, D["distinct"])
check("C dash 2 chuoi + span tong 60s", D["chains"] == 2 and abs(D["span_total"] - 60) < 1e-6,
      (D["chains"], D["span_total"]))
check("C dash rereads tong 1", D["rereads"] == 1, D["rereads"])
check("C dash first/last", D["first"] == T0 and D["last"] == TH + 10, (D["first"], D["last"]))

ags = {a["agent"]: a for a in D["agents"]}
check("C agent sap theo tong giam dan", [a["agent"] for a in D["agents"]] == ["Claude", "Hermes"])
cl = ags.get("Claude", {})
check("C Claude dem theo loai", (cl.get("total"), cl.get("read"), cl.get("search"), cl.get("edit"))
      == (6, 3, 1, 2), cl)
check("C Claude distinct/chains/span", (cl.get("distinct"), cl.get("chains")) == (3, 1)
      and abs(cl.get("span", 0) - 50) < 1e-6, cl)
check("C Claude rereads + reedits", (cl.get("rereads"), cl.get("reedits")) == (1, 1), cl)
hm = ags.get("Hermes", {})
check("C Hermes metric", (hm.get("total"), hm.get("distinct"), hm.get("chains"),
      hm.get("rereads")) == (2, 2, 1, 0), hm)

check("C histogram gio 9 va 10", D["hours"][9] == {"read": 3, "search": 1, "edit": 2}
      and D["hours"][10] == {"read": 2, "search": 0, "edit": 0},
      (D["hours"][9], D["hours"][10]))
check("C histogram gio khac = 0", sum(sum(h.values()) for h in D["hours"]) == 8)

check("C top note dung thu tu + dem", [(t["file"], t["n"]) for t in D["top"]]
      == [("A.md", 3), ("B.md", 2), ("C.md", 2), ("D.md", 1)], D["top"])
check("C top co types", D["top"][0]["types"] == {"read": 3, "search": 0, "edit": 0},
      D["top"][0])

# ---- ngay mac dinh + log rong + khong mutate ----
D2 = SV.build_dashboard(EVENTS)
check("C dash mac dinh = ngay moi nhat", D2["day"] == "2026-07-15" and D2["total"] == 1,
      (D2["day"], D2["total"]))
DE = SV.build_dashboard([])
check("C dash log rong khong loi", DE["day"] is None and DE["total"] == 0
      and DE["agents"] == [] and DE["top"] == [] and len(DE["hours"]) == 24, DE["day"])
check("C khong mutate event cache (dwell khong lot vao)",
      all("dwell" not in e for e in EVENTS))

# ---- UI: dropdown ngay phai duoc nap NGAY KHI BOOT (bug 17/07: initCockpit
# khong goi populateDays -> select "Ngay trong log" trong toi lan mo dau tien) ----
with open(os.path.join(G3D, "src", "cockpit.js"), encoding="utf-8") as f:
    ck_src = f.read()
init_body = ck_src.split("export function initCockpit")[-1]
check("C initCockpit nap danh sach ngay luc boot (populateDays)",
      "populateDays" in init_body and "/timeline" in init_body)

print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
