@echo off
rem KB Graph 3D — double-click de mo graph 3D cua Knowledge Base
cd /d "%~dp0"
title TON618
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
rem KHONG set GRAPH3D_ACTIVITY_FILE o day! Env nay la OVERRIDE tuong minh: set no lam
rem activity_log_candidates() chi doc dung 1 duong, MAT kha nang doc log Cowork (MSIX LocalCache).
echo (Idempotent: chay lai file nay bao nhieu lan cung khong de ra nhieu server;
echo  server tu khoi dong lai khi ban sua .graph3d — khong can dong tay.)
python ensure_graph3d.py %*
pause
