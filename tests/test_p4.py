# -*- coding: utf-8 -*-
"""Test P4 fixes — parse_jsonl dung chung, build_heat qua aggregate, demojibake hits, glob MSIX. Scratch trong %TEMP%."""
import json, os, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault

from _scratch import SCRATCH, G3D
LOG = os.path.join(SCRATCH, "act_p4.jsonl")
os.environ["GRAPH3D_ACTIVITY_FILE"] = LOG
sys.path.insert(0, G3D)

import activity_paths as AP
import log_activity as LA
import serve as SV

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

# t1: parse_jsonl la MOT ban duy nhat dung chung
check("t1a serve + log_activity dung CHUNG parse_jsonl cua activity_paths",
      SV.parse_jsonl is AP.parse_jsonl and LA.parse_jsonl is AP.parse_jsonl)
check("t1b parse_jsonl bo dong hong", AP.parse_jsonl('{"a":1}\nbroken\n\n{"b":2}') == [{"a": 1}, {"b": 2}])

# t2: build_heat dem qua aggregate_by_file (type la normalize -> read)
evs = [{"ts": 1, "file": "X.md", "type": "read", "agent": "A"},
       {"ts": 2, "file": "X.md", "type": "edit", "agent": "A"},
       {"ts": 3, "file": "Y.md", "type": "weird", "agent": "B"}]
h = SV.build_heat(evs)
check("t2a counts/max/total/distinct dung",
      h["counts"] == {"X.md": 2, "Y.md": 1} and h["max"] == 2 and h["total"] == 3 and h["distinct"] == 2, h)
top0 = h["top"][0]
check("t2b top[0] = X.md voi types day du 3 key",
      top0["file"] == "X.md" and top0["n"] == 2 and top0["types"] == {"read": 1, "search": 0, "edit": 1}, top0)
check("t2c type la 'weird' normalize ve read", h["top"][1]["types"]["read"] == 1, h["top"][1])

# t3: demojibake PHAI SUA -> ghi vet hits log
fixed_name = os.path.join(SCRATCH, "test—p4.md")   # co em-dash
open(fixed_name, "w").close()
orig = fixed_name.encode("utf-8").decode("cp1252")       # gia lap mojibake
hits = LA.LOG_FILE + ".demojibake-hits.log"
try: os.remove(hits)
except OSError: pass
r = LA._demojibake(orig)
check("t3a demojibake sua dung ten that", r == fixed_name, r)
hitlines = open(hits, encoding="utf-8").read().strip().splitlines() if os.path.exists(hits) else []
check("t3b hits log ghi 1 dong orig/fixed", len(hitlines) == 1 and json.loads(hitlines[0])["fixed"] == fixed_name)
check("t3c path hop le KHONG ghi hits", LA._demojibake(fixed_name) == fixed_name
      and len(open(hits, encoding="utf-8").read().strip().splitlines()) == 1)

# t4: candidates dung GLOB Claude_* thay hardcode + cache 30s
del os.environ["GRAPH3D_ACTIVITY_FILE"]
fake = os.path.join(SCRATCH, "fakelocal")
std = os.path.join(fake, "claude-graph3d")
msix = os.path.join(fake, "Packages", "Claude_ZZTESTHASH", "LocalCache", "Local", "claude-graph3d")
for d in (std, msix):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "activity.jsonl"), "w").close()
os.environ["LOCALAPPDATA"] = fake
AP._cand_cache["paths"] = None                            # xoa cache
c = AP.activity_log_candidates()
norm = [os.path.normcase(p) for p in c]
check("t4a co duong chuan", os.path.normcase(os.path.join(std, "activity.jsonl")) in norm, c)
check("t4b glob bat package hash BAT KY (Claude_ZZTESTHASH)",
      os.path.normcase(os.path.join(msix, "activity.jsonl")) in norm, c)
# Package moi xuat hien SAU lan quet dau: trong 30s cache KHONG duoc thay no — bo
# cache (glob moi lan goi) thi lan goi 2 thay them duong nay va t4c do.
msix2 = os.path.join(fake, "Packages", "Claude_ZZLATER", "LocalCache", "Local", "claude-graph3d")
os.makedirs(msix2, exist_ok=True)
open(os.path.join(msix2, "activity.jsonl"), "w").close()
c2 = AP.activity_log_candidates()
check("t4c cache 30s: package moi sau lan quet dau chua duoc thay", c2 == c, c2)

# t5: Codex Desktop khong co Claude hook; doc rollout JSONL va chi phat event note
# trong vault. Adapter TUYET DOI khong dua prompt/noi dung note vao event.
codex_vault = os.path.join(SCRATCH, "codex-vault")
note_rel = "Area/Note.md"
note_abs = os.path.join(codex_vault, *note_rel.split("/"))
outside = os.path.join(SCRATCH, "outside.md")
os.makedirs(os.path.dirname(note_abs), exist_ok=True)
open(note_abs, "w").close()
open(outside, "w").close()

def rollout(ts, source):
    return json.dumps({"timestamp": ts, "type": "response_item", "payload": {
        "type": "custom_tool_call", "name": "exec", "input": source,
    }}, ensure_ascii=False)

read_cmd = "Get-Content -Raw 'Area\\Note.md'"
read_js = "const r = await tools.shell_command({command: %s, workdir: %s});" % (
    json.dumps(read_cmd), json.dumps(codex_vault))
search_cmd = "rg -n 'needle' 'Area\\Note.md'"
search_js = "const r = await tools.shell_command({command: %s, workdir: %s});" % (
    json.dumps(search_cmd), json.dumps(codex_vault))
patch = "*** Begin Patch\n*** Update File: %s\n@@\n-old\n+new\n*** End Patch" % note_abs
edit_js = "const patch = %s; text(await tools.apply_patch(patch));" % json.dumps(patch)
outside_cmd = "Get-Content -Raw %s" % json.dumps(outside)
outside_js = "const r = await tools.shell_command({command: %s, workdir: %s});" % (
    json.dumps(outside_cmd), json.dumps(codex_vault))
rollout_text = "\n".join([
    rollout("2026-08-07T04:00:00Z", read_js),
    rollout("2026-08-07T04:00:01Z", search_js),
    rollout("2026-08-07T04:00:02Z", edit_js),
    rollout("2026-08-07T04:00:03Z", outside_js),
])
codex_events = AP.parse_codex_rollout(rollout_text, vault=codex_vault)
check("t5a Codex rollout map read/search/edit dung note trong vault",
      [(e["type"], e["file"], e["agent"]) for e in codex_events]
      == [("read", note_rel, "Codex"), ("search", note_rel, "Codex"),
          ("edit", note_rel, "Codex")], codex_events)
check("t5b event Codex chi co metadata, khong lo prompt/noi dung",
      all(set(e) == {"ts", "type", "file", "agent"} for e in codex_events),
      codex_events)

codex_root = os.path.join(SCRATCH, "codex-home", "sessions")
codex_day = os.path.join(codex_root, "2026", "08", "07")
os.makedirs(codex_day, exist_ok=True)
rollout_path = os.path.join(codex_day, "rollout-2026-08-07T04-00-00-test.jsonl")
open(rollout_path, "w").close()
os.environ["GRAPH3D_CODEX_SESSIONS"] = codex_root
AP._codex_cand_cache["paths"] = None
check("t5c discovery bat rollout Codex khi khai root tuong minh",
      AP.codex_session_candidates() == [rollout_path],
      AP.codex_session_candidates())
del os.environ["GRAPH3D_CODEX_SESSIONS"]

for f in (LOG, fixed_name, hits, LOG + ".lock", outside):
    try: os.remove(f)
    except OSError: pass
import shutil
for d in (fake, codex_vault, os.path.dirname(codex_root)):
    shutil.rmtree(d, ignore_errors=True)
print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
