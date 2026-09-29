# -*- coding: utf-8 -*-
"""Supervisor cho KB Graph 3D — giữ đúng MỘT server sống trên port và tự khởi động
lại khi mã nguồn đổi (serve.py exit 3) hoặc process chết. PORT chính là "khóa" duy
nhất: nếu đã có server CÙNG version + vault id đang khỏe thì supervisor này tự thoát (idempotent),
nên chạy bao nhiêu lần cũng không đẻ ra nhiều server.

Dùng bởi:
  - .claude/launch.json  (chạy FOREGROUND — Claude Code preview giữ tiến trình sống)
  - ensure_graph3d.py    (spawn NGẦM khi cần khởi động mới)

Exit code của serve.py mà supervisor diễn giải:
  3  = mã nguồn đổi   -> relaunch (reload)
  4  = active vault đổi -> đọc lại lựa chọn đã lưu rồi relaunch cùng port
  0  = /shutdown/Ctrl+C -> dừng hẳn, KHÔNG relaunch
  75 = port bị chiếm  -> nhường nếu server kia cùng version, ngược lại giết zombie & thử lại
  khác = crash        -> backoff rồi relaunch (chặn vòng lặp điên)
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from activity_paths import source_version  # noqa: E402
import vault_switcher  # noqa: E402

DETACHED = 0x00000008     # DETACHED_PROCESS  (cho ensure spawn ngầm)
# 0 ngoài Windows: `creationflags` khác 0 là ValueError trên POSIX, mà netstat/taskkill/
# powershell dưới đây tuy chỉ có trên Windows vẫn được gọi không rào theo hệ điều hành.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0    # CREATE_NO_WINDOW


def health(port, timeout=1.2):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def health_retry(port, tries=3, delay=0.7):
    """Server vừa thắng cuộc đua bind có thể CHƯA kịp trả /health trong nhịp đầu —
    thử lại vài lần TRƯỚC khi kết luận zombie, kẻo giết nhầm server mới (review
    P5.10). Port trống thì thoát ngay, không chờ vô ích."""
    h = health(port)
    for _ in range(tries - 1):
        if h or port_pid(port) is None:
            break
        time.sleep(delay)
        h = health(port)
    return h


def request_shutdown(port, timeout=3.0):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/shutdown" % port, timeout=timeout).read()
    except Exception:
        pass


def port_pid(port):
    """PID đang LISTEN trên port (Windows). Nhận diện dòng listening qua địa chỉ
    foreign là wildcard -> không phụ thuộc chữ 'LISTENING' (tránh lỗi locale)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], creationflags=NO_WINDOW,
                             capture_output=True, text=True, timeout=6).stdout
    except Exception:
        return None
    needle = ":%d" % port
    wild = ("0.0.0.0:0", "[::]:0", "*:*")
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[0].upper() == "TCP" and p[1].endswith(needle) \
                and p[2] in wild and p[-1].isdigit():
            return int(p[-1])
    return None


def _pid_cmdline(pid):
    """Command line của PID (PowerShell CIM — wmic đã bị gỡ khỏi Win11 bản mới).
    Trả None nếu không đọc được (process vừa chết / không đủ quyền)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % int(pid)],
            creationflags=NO_WINDOW, capture_output=True, text=True, timeout=10).stdout.strip()
        return out or None
    except Exception:
        return None


def kill_pid(pid):
    """Giết process giữ port — CHỈ khi xác minh được nó là graph3d (cmdline chứa
    serve.py / .graph3d). P2.2 chốt 2026-07-10: app LẠ tình cờ bind
    port không bị taskkill oan cả cây process; không đọc được cmdline cũng KHÔNG
    giết (default-deny). Trả True = đã giết xong, False = từ chối giết — caller
    phải bỏ cuộc có thông điệp, đừng lặp vô hạn. Caller tự chặn pid rỗng."""
    cmd = _pid_cmdline(pid)
    low = (cmd or "").lower()
    if "serve.py" not in low and ".graph3d" not in low:
        print("supervisor: port dang bi process KHAC giu (pid=%s, cmdline=%s)"
              % (pid, (cmd or "<khong doc duoc>")[:120]))
        print("supervisor: KHONG kill process la — tat process do hoac chay lai voi --port khac")
        return False
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       creationflags=NO_WINDOW, capture_output=True, timeout=8)
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
    return True


def health_matches(h, want_version, want_vault_id=None):
    return bool(h) and (want_version is None or h.get("version") == want_version) \
        and (want_vault_id is None or h.get("vault_id") == want_vault_id)


def free_port(port, want_version, want_vault_id=None):
    """Dọn port để mình chiếm. Trả True nếu nên NHƯỜNG (đã có server tốt sẵn)."""
    h = health_retry(port)
    # want_version=None = không đọc được version (OneDrive khóa file tạm) -> coi như khớp,
    # KHÔNG shutdown server đang khỏe chỉ vì một lần đọc lỗi thoáng qua.
    if health_matches(h, want_version, want_vault_id):
        return True                       # đã có server CÙNG version + vault -> nhường
    if h:                                 # server khác version/vault -> xin dừng sạch
        request_shutdown(port)
        for _ in range(24):
            if health(port, 0.5) is None and port_pid(port) is None:
                break
            time.sleep(0.25)
    pid = port_pid(port)
    if pid:                               # zombie không trả /health mà vẫn giữ port
        if not kill_pid(pid) and port_pid(port) is not None:
            # App lạ vẫn giữ port (kill_pid đã in chẩn đoán) — không có gì tự xử được
            raise SystemExit(2)
        time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--vault", help="vault root cố định; bỏ trống = đọc lựa chọn UI đã lưu")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    want = source_version(HERE)
    try:
        ctx = vault_switcher.resolve_active_vault(HERE, explicit=args.vault)
    except vault_switcher.VaultSwitchError as exc:
        print("supervisor: vault khong hop le (%s): %s" % (exc.code, exc))
        return 2
    if free_port(args.port, want, ctx["id"]):
        print("supervisor: da co server khoe (version=%s vault=%s) tren %d -> thoat"
              % (want, ctx["name"], args.port))
        return 0

    quick = 0
    while True:
        try:
            # Không có --vault: đọc LẠI config sau mỗi exit code 4. Nhờ đó active
            # vault vẫn bất biến trong từng process nhưng switch UI có hiệu lực ngay.
            ctx = vault_switcher.resolve_active_vault(HERE, explicit=args.vault)
        except vault_switcher.VaultSwitchError as exc:
            print("supervisor: vault khong hop le (%s): %s" % (exc.code, exc))
            return 2
        child_env = os.environ.copy()
        child_env[vault_switcher.VAULT_ENV] = ctx["path"]
        child_env[vault_switcher.LOCKED_ENV] = "1" if args.vault else "0"
        try:
            proc = subprocess.Popen(
                [sys.executable, os.path.join(HERE, "serve.py"),
                 "--port", str(args.port), "--no-open"],
                cwd=HERE, env=child_env)
        except Exception as e:
            print("supervisor: khong spawn duoc serve.py: %s" % e)
            return 1
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            print("supervisor: dung theo yeu cau")
            return 0

        if code == 3:
            print("supervisor: code doi -> reload")
            quick = 0
            continue
        if code == 4:
            print("supervisor: active vault doi -> reload")
            quick = 0
            continue
        if code == 0:
            print("supervisor: server dung sach -> thoat")
            return 0
        if code == 75:
            h = health_retry(args.port)
            want = source_version(HERE)
            try:
                ctx = vault_switcher.resolve_active_vault(HERE, explicit=args.vault)
            except vault_switcher.VaultSwitchError:
                return 2
            if health_matches(h, want, ctx["id"]):
                print("supervisor: port da co server khac cung version -> nhuong")
                return 0
            pid = port_pid(args.port)
            if pid and not kill_pid(pid) and port_pid(args.port) is not None:
                return 2                  # app lạ giữ port — bỏ cuộc, không lặp spawn vô hạn
            time.sleep(0.5)
            continue
        quick += 1
        if quick > 5:
            print("supervisor: serve.py crash lien tuc (code=%s) -> bo cuoc" % code)
            return 1
        print("supervisor: serve.py exit %s -> khoi dong lai (#%d)" % (code, quick))
        time.sleep(0.6 * quick)


if __name__ == "__main__":
    sys.exit(main() or 0)
