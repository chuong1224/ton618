# -*- coding: utf-8 -*-
"""Test P2.2 — xac minh danh tinh PID truoc khi taskkill. CHAM (~15s, spawn process that) — selfcheck chi chay khi --slow. Scratch trong %TEMP%."""
import os, subprocess, sys, time
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault

from _scratch import SCRATCH, G3D
sys.path.insert(0, G3D)
import run_graph3d as RG

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)

def alive(p):
    return p.poll() is None

# t1: doc duoc cmdline cua chinh minh
cmd = RG._pid_cmdline(os.getpid())
check("t1 _pid_cmdline doc duoc (chua 'python')", cmd is not None and "python" in cmd.lower(), cmd)

# t2: process LA (khong phai graph3d) -> TU CHOI kill, van song
foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
try:
    time.sleep(0.5)
    r = RG.kill_pid(foreign.pid)
    time.sleep(0.5)
    check("t2a kill_pid tu choi process la (return False)", r is False, r)
    check("t2b process la VAN SONG", alive(foreign))
finally:
    foreign.kill()

# t3: process cmdline chua serve.py -> BI giet nhu truoc
fake = os.path.join(SCRATCH, "serve.py")
open(fake, "w").write("import time; time.sleep(120)\n")
zombie = subprocess.Popen([sys.executable, fake])
try:
    time.sleep(0.5)
    r = RG.kill_pid(zombie.pid)
    time.sleep(1.2)
    check("t3a kill_pid chap nhan zombie serve.py (return True)", r is True, r)
    check("t3b zombie DA CHET", not alive(zombie))
finally:
    if alive(zombie):
        zombie.kill()
    os.remove(fake)

# t5: TICH HOP — app la giu port, supervisor phai bo cuoc exit 2, app song.
# Holder bind port 0 va IN port ve cho parent NHUNG van giu listener mo xuyen suot
# phep thu. Nhu vay moi selfcheck co port rieng ma khong co khoang dua
# "tim port rong -> dong socket -> process khac cuop port".
holder_code = ("import socket, time; s = socket.socket(); "
               "s.bind(('127.0.0.1', 0)); s.listen(1); "
               "print(s.getsockname()[1], flush=True); time.sleep(120)")
holder = subprocess.Popen([sys.executable, "-c", holder_code], stdout=subprocess.PIPE,
                          text=True, encoding="ascii", errors="strict")
try:
    port_line = holder.stdout.readline().strip()
    port = int(port_line)
    check("t5 port dong duoc OS cap va holder dang giu", 0 < port < 65536 and alive(holder), port)
    # encoding PHAI khai tuong minh: supervisor tu reconfigure stdout sang UTF-8, con
    # text=True tran thi giai ma bang locale cua may. Tren may co locale gbk chang han,
    # dau '—' trong thong diep cua supervisor la E2 80 94 -> UnicodeDecodeError, run.stdout
    # thanh None va test no TypeError o dong duoi. Loi CO SAN, chi lo ra khi chay --slow
    # tren may co locale KHONG phai UTF-8.
    run = subprocess.run([sys.executable, os.path.join(G3D, "run_graph3d.py"), "--port", str(port)],
                         capture_output=True, text=True, timeout=60,
                         encoding="utf-8", errors="replace")
    check("t5a supervisor bo cuoc voi exit code 2", run.returncode == 2, run.returncode)
    check("t5b co thong diep 'process KHAC'", "process KHAC" in run.stdout, run.stdout[-300:])
    check("t5c app la VAN SONG sau khi supervisor bo cuoc", alive(holder))
finally:
    holder.kill()
    holder.wait(timeout=5)
    holder.stdout.close()

print("\nTONG KET:", ("FAIL %d muc" % len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
