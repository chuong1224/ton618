# -*- coding: utf-8 -*-
"""Duong dan dung chung cho mot lan chay bo test .graph3d (G1.1).

SCRATCH nam trong %TEMP% — test KHONG duoc ghi file rac vao vault.
G3D/VAULT suy tu vi tri file nay -> chay dung tren moi may, khong hardcode.
Moi selfcheck co run-id rieng de private/public chay dong thoi khong giam len .lnk,
log hay vault fixture cua nhau; process con ke thua run-id qua environment.
"""
import os, tempfile

RUN_ID = os.environ.get("GRAPH3D_TEST_RUN_ID") or str(os.getpid())
os.environ.setdefault("GRAPH3D_TEST_RUN_ID", RUN_ID)
SCRATCH = os.path.join(tempfile.gettempdir(), "graph3d-selfcheck", RUN_ID)
os.makedirs(SCRATCH, exist_ok=True)

G3D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.path.dirname(G3D)

# Journal event per-may (v1.25.0) mac dinh nam TRONG vault (.graph3d/activity-<HOST>.jsonl)
# — moi test kich hoat flush heat se keo theo ghi journal, nen phai tro ve SCRATCH
# truoc khi test import log_activity/serve. Test nao can dir rieng thi tu set env
# TRUOC khi import _scratch (setdefault khong de len).
os.environ.setdefault("GRAPH3D_JOURNAL_DIR", SCRATCH)

# Heat reconciliation opens a lock even with no pending events (W354).
# Isolate it before importing serve/log_activity, including standalone tests.
os.environ.setdefault("GRAPH3D_HEAT_DIR", SCRATCH)
