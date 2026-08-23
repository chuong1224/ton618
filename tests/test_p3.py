# -*- coding: utf-8 -*-
"""Test P3 fixes — pending batch cho store heat + cache read_all_events. Scratch trong %TEMP%."""
import json, os, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault

from _scratch import SCRATCH, G3D
LOG = os.path.join(SCRATCH, "act_p3.jsonl")
STORE = os.path.join(SCRATCH, "heat_p3.json")
JOURNAL = os.path.join(SCRATCH, "activity-p3-host.jsonl")
for f in (LOG, STORE, JOURNAL, LOG + ".heat-pending.jsonl", LOG + ".lock", STORE + ".lock"):
    try: os.remove(f)
    except OSError: pass
os.environ["GRAPH3D_ACTIVITY_FILE"] = LOG
sys.path.insert(0, G3D)

import log_activity as LA
import serve as SV
LA.cumulative_heat_path = lambda: STORE          # khong dung store that
LA.vault_journal_path = lambda: JOURNAL          # khong dung journal that
PENDING = LA.PENDING_FILE

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

REL = "Index.md"   # note that ton tai trong vault

# t1: bump dau tien -> chi ghi PENDING, store chua dung toi
LA.append_events("read", [REL])
check("t1a pending duoc tao (ngoai vault)", os.path.exists(PENDING))
check("t1b store CHUA bi ghi (khong churn per-call)", not os.path.exists(STORE))

# t2: gia hoa pending (>60s) -> bump ke tiep flush gop vao store
lines = open(PENDING, encoding="utf-8").read().strip().splitlines()
ev0 = json.loads(lines[0]); ev0["ts"] = time.time() - 120
open(PENDING, "w", encoding="utf-8").write(json.dumps(ev0) + "\n" + "\n".join(lines[1:]))
LA.append_events("edit", [REL])
store = json.load(open(STORE, encoding="utf-8"))
note = store["notes"][REL]
check("t2a flush khi pending gia: store co du 2 event", note["total"] == 2 and note["read"] == 1 and note["edit"] == 1, note)
check("t2b pending da xoa sau flush", not os.path.exists(PENDING))

# t3: reconcile KHONG dem trung voi pending chua flush
for f in (LOG, STORE, JOURNAL):
    try: os.remove(f)
    except OSError: pass
LA.append_events("read", [REL])
LA.append_events("read", [REL])          # 2 event: nam trong LOG + PENDING, store trong
check("t3a truoc reconcile: store trong, pending 2 dong", not os.path.exists(STORE)
      and len(open(PENDING, encoding="utf-8").read().strip().splitlines()) == 2)
LA.reconcile_cumulative_with_log()
total1 = json.load(open(STORE, encoding="utf-8"))["notes"][REL]["total"]
check("t3b sau reconcile: dung 2 (flush truoc, raise khong dem lai)", total1 == 2, total1)
LA.reconcile_cumulative_with_log()       # chay lai -> van 2 (idempotent)
total2 = json.load(open(STORE, encoding="utf-8"))["notes"][REL]["total"]
check("t3c reconcile lan 2 van 2", total2 == 2, total2)

# t3d: journal vault dai hon log cuon la san duong; reconcile khong duoc ha bat ky
# field cu nao khi hai nguon co phan bo type/agent khac nhau.
for f in (LOG, STORE, JOURNAL, PENDING):
    try: os.remove(f)
    except OSError: pass
events = [
    {"ts": 10 + i, "type": t, "file": REL, "agent": ag}
    for i, (t, ag) in enumerate([
        ("read", "Claude"), ("read", "Hermes"), ("read", "Hermes"),
        ("edit", "Hermes"), ("edit", "Hermes"), ("edit", "Claude")])]
open(LOG, "w", encoding="utf-8").write(json.dumps(events[-1]) + "\n")
open(JOURNAL, "w", encoding="utf-8").write(
    "".join(json.dumps(ev) + "\n" for ev in events))
json.dump({"notes": {REL: {
    "total": 5, "read": 1, "search": 2, "edit": 2,
    "first": 5, "last": 12, "agents": {"Claude": 4, "Hermes": 1}
}}}, open(STORE, "w", encoding="utf-8"))
LA.vault_journal_path = lambda: JOURNAL
LA.reconcile_cumulative_with_log()
merged = json.load(open(STORE, encoding="utf-8"))["notes"][REL]
check("t3d journal vault la san va khong field cu nao bi ha",
      merged == {"total": 8, "read": 3, "search": 2, "edit": 3,
                 "first": 5, "last": 15, "agents": {"Claude": 4, "Hermes": 4}}, merged)
LA.reconcile_cumulative_with_log()
check("t3e merge san journal idempotent",
      json.load(open(STORE, encoding="utf-8"))["notes"][REL] == merged)

# t4: cache read_all_events theo (mtime,size)
e1 = SV.read_all_events()
e2 = SV.read_all_events()
check("t4a khong doi -> tra CUNG object cache", e1 is e2)
time.sleep(0.02)
LA.append_events("search", [REL])
e3 = SV.read_all_events()
check("t4b log doi -> cache invalidate, +1 event", (e3 is not e2) and len(e3) == len(e2) + 1,
      (len(e2), len(e3)))

# t5: server keep-alive attr
check("t5 Handler HTTP/1.1 + timeout", SV.Handler.protocol_version == "HTTP/1.1" and SV.Handler.timeout == 75)

for f in (LOG, STORE, JOURNAL, PENDING, LOG + ".lock", STORE + ".lock"):
    try: os.remove(f)
    except OSError: pass
print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
