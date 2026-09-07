# -*- coding: utf-8 -*-
"""Điểm vào IDEMPOTENT cho KB Graph 3D — MỌI launcher muốn MỞ UI (Start-Graph3D.bat,
agent mở graph) gọi cái NÀY thay cho serve.py. Diệt tận gốc lỗi "nhiều server / zombie
phục vụ snapshot cũ":

  - Đã có server CÙNG version + vault đang khỏe -> dùng lại, chỉ mở trình duyệt.
  - Khác version/vault hoặc zombie giữ port      -> supervisor thay bằng bản đúng.
  - Chưa có gì                             -> spawn supervisor NGẦM (nền), chờ tới khi khỏe.

Agent chỉ GHI hoạt động thì KHÔNG gọi cái này — dùng log_activity.py (offline) hoặc
GET /ping (khi server đang chạy). Tuyệt đối không agent nào tự chạy serve.py.

Hai cờ onboarding cho người CHƯA có vault (W13 — logic ở onboarding.py):
  --demo              mở cockpit trên vault demo bundled (port riêng 8322, không đụng
                      server đang chạy trên vault thật)
  --init-starter DIR  dựng vault đầu tiên tại DIR từ starter-vault/ rồi thoát;
                      thêm --force để nhập note hướng dẫn vào vault đang có

Vault Switcher (v1.59.0): UI có thể chọn một vault root bất kỳ. Lựa chọn được
lưu ngoài vault và supervisor restart cùng port để đổi toàn bộ context atomically.
CLI ``--vault DIR`` chọn root cố định cho phiên đó và khóa nút đổi vault.

Cờ --app (W58/W60): nếu Edge đã cài site-app KB Graph 3D thì ưu tiên AUMID packaged
trong Windows Start Apps (Edge hiện hành), kế đến ``--app-id`` trong shortcut kiểu cũ,
để mở bằng identity/icon taskbar riêng; chưa cài thì lùi về cửa sổ ``--app=<url>``
của Edge/Chrome như trước. Shortcut do install_launcher.py tạo chạy đúng dòng này.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from activity_paths import local_data_dir, source_version   # noqa: E402
import onboarding as onb                     # noqa: E402  (W13 — demo / starter vault)
import run_graph3d as sup                    # noqa: E402  (health/port_pid/kill_pid/flags)
import install_launcher as launcher          # noqa: E402  (doc/scan shortcut PWA Windows)
import vault_switcher                         # noqa: E402  (W180 — chọn vault root)

from activity_paths import APP_NAME, APP_TITLE, APP_TITLE_ALIASES
APP_TITLE_PREFIX = APP_NAME


def app_name_matches(name):
    return any(name.casefold().startswith(alias.casefold()) for alias in APP_TITLE_ALIASES)

_PS_START_APPS = r"""
$ErrorActionPreference = 'Stop'
Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress
"""


def bind_console():
    """pythonw.exe — shortcut dùng nó để click không loé cửa sổ CMD đen — KHÔNG có
    console: `sys.stdout is None`, và print() đầu tiên nổ AttributeError giữa chừng,
    lặng thinh. Trói stdout vào file log: vừa cứu print, vừa cho người dùng CHỖ XEM
    khi app không chịu mở (port bị chiếm, python hỏng…). Trả file để caller đóng."""
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                    # noqa: BLE001
            pass
        return None
    path = os.path.join(local_data_dir(), "launcher.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        f = open(os.devnull, "w")
    f.write("\n=== %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    sys.stdout = sys.stderr = f
    return f


def browser_exe():
    """Edge/Chrome để mở chế độ app. KHÔNG dùng --user-data-dir riêng: app lưu mọi
    tuỳ chọn trong localStorage của origin 127.0.0.1:8321, profile riêng = mất sạch
    ghim/lịch sử/bộ lọc đã chọn."""
    cands = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for p in cands:
        if os.path.isfile(p):
            return p
    for name in ("msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _switch_value(arguments, name):
    """Lấy một switch Chromium từ chuỗi Arguments của .lnk Windows.

    WScript.Shell trả nguyên command line thay vì argv; parser nhỏ này chỉ đọc các
    switch mình cần và chịu được cả ``--x=value`` lẫn ``--x "value có cách"``.
    """
    pattern = (r"(?:^|\s)--%s(?:=|\s+)(?:\"([^\"]*)\"|'([^']*)'|([^\s]+))"
               % re.escape(name))
    match = re.search(pattern, arguments or "", re.I)
    if not match:
        return None
    return next((value for value in match.groups() if value is not None), None)


def installed_app_candidates():
    """Shortcut có thể là site-app KB Graph 3D do Edge/Chrome cài.

    Chỉ lọc theo tên trước khi gọi COM đọc .lnk: Start Menu có thể có hàng trăm link,
    spawn PowerShell cho từng cái vừa chậm vừa làm launcher dễ lỗi. Nếu người dùng đã
    đổi tên app, ``GRAPH3D_PWA_SHORTCUT`` là đường chỉ định tường minh.
    """
    out = []
    explicit = (os.environ.get("TON618_PWA_SHORTCUT") or
                os.environ.get("GRAPH3D_PWA_SHORTCUT", "")).strip()
    if explicit:
        out.append(os.path.normpath(explicit))
    try:
        folders = launcher.shell_folders()
    except Exception:                              # noqa: BLE001
        folders = {}
    for root in (folders.get("programs"), folders.get("desktop")):
        if not root or not os.path.isdir(root):
            continue
        try:
            for base, _dirs, files in os.walk(root):
                for name in files:
                    if (name.lower().endswith(".lnk")
                            and app_name_matches(name[:-4])):
                        out.append(os.path.normpath(os.path.join(base, name)))
        except OSError:
            continue
    # Explicit đứng đầu; còn lại deterministic để hai lần chạy chọn cùng một link.
    return list(dict.fromkeys(out))


def registered_start_apps():
    """Đọc app Windows đã đăng ký, gồm site-app Edge kiểu packaged hiện hành.

    Edge mới không nhất thiết tạo ``.lnk --app-id``. Windows vẫn công bố app qua
    ``Get-StartApps`` với AUMID dạng ``<package>!App``; đây mới là identity mà taskbar
    dùng. Lỗi probe chỉ làm mất tối ưu này, không được chặn fallback ``--app=<url>``.
    """
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_START_APPS],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12, creationflags=sup.NO_WINDOW)
        if result.returncode or not result.stdout.strip():
            return []
        rows = json.loads(result.stdout)
        return rows if isinstance(rows, list) else [rows]
    except Exception:                              # noqa: BLE001
        return []


def packaged_app_spec(rows):
    """Chọn AUMID packaged của KB Graph, loại AppID tự sinh của shortcut Python cũ."""
    explorer = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe")
    if not os.path.isfile(explorer):
        return None
    found = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or row.get("name") or "").strip()
        app_id = str(row.get("AppID") or row.get("AppId")
                     or row.get("app_id") or "").strip()
        if (not app_name_matches(name)
                or not re.fullmatch(r"[a-z0-9._{}-]+![a-z0-9._{}-]+", app_id, re.I)):
            continue
        rank = 0 if name.casefold() == APP_TITLE.casefold() else 1
        found.append((rank, name.casefold(), app_id.casefold(), {
            "kind": "apps-folder", "name": name, "app_id": app_id,
            "target": explorer, "args": ["shell:AppsFolder\\" + app_id]}))
    return min(found, key=lambda row: row[:3])[3] if found else None


def installed_app_spec(candidates=None, read_shortcut_fn=None, isfile=None,
                       start_apps=None):
    """Trả lệnh mở site-app đã cài, hoặc ``None`` để caller dùng ``--app=<url>``.

    Identity hợp lệ là AUMID packaged ``<package>!App`` từ Windows Start Apps, hoặc
    ``--app-id`` của shortcut Chromium kiểu cũ. AppID tự sinh của shortcut launcher
    Python không có ``!`` nên bị loại; nhận nhầm nó sẽ tự gọi lồng ensure mãi và vẫn
    không cho Windows một AppUserModelID riêng.
    """
    # Khi test/caller truyền candidates tường minh, không probe máy thật ngoài ý muốn.
    # Caller vẫn có thể truyền start_apps tường minh để test nhánh packaged.
    if start_apps is None:
        start_apps = registered_start_apps() if candidates is None else []
    packaged = packaged_app_spec(start_apps)
    if packaged:
        return packaged
    candidates = installed_app_candidates() if candidates is None else candidates
    read_shortcut_fn = read_shortcut_fn or launcher.read_shortcut
    isfile = isfile or os.path.isfile
    found = []
    for path in candidates:
        if not isfile(path):
            continue
        try:
            info = read_shortcut_fn(path)
        except Exception:                          # noqa: BLE001
            continue
        target = os.path.normpath((info.get("target") or "").strip())
        app_id = _switch_value(info.get("args"), "app-id")
        exe = os.path.basename(target).casefold()
        if (not target or not isfile(target) or not app_id
                or not re.match(r"^[a-z0-9_-]+$", app_id, re.I)
                or exe not in ("msedge_proxy.exe", "msedge.exe",
                               "chrome_proxy.exe", "chrome.exe")):
            continue
        args = []
        profile = _switch_value(info.get("args"), "profile-directory")
        if profile:
            args.append("--profile-directory=" + profile)
        args.append("--app-id=" + app_id)
        # Edge đôi khi ghi URL vào shortcut site-app; giữ lại nếu có để không làm
        # khác lệnh do chính trình duyệt tạo.
        app_url = _switch_value(info.get("args"), "app-url")
        if app_url:
            args.append("--app-url=" + app_url)
        rank = 0 if exe.startswith("msedge") else 1
        found.append((rank, os.path.normcase(path), {
            "kind": "chromium-shortcut", "shortcut": path,
            "target": target, "args": args, "app_id": app_id}))
    return min(found, key=lambda row: (row[0], row[1]))[2] if found else None


def open_app_window(url):
    """Cửa sổ app riêng; ưu tiên AUMID đã đăng ký để có identity/icon taskbar riêng."""
    installed = installed_app_spec()
    if installed:
        try:
            subprocess.Popen([installed["target"]] + installed["args"], close_fds=True,
                             creationflags=sup.DETACHED | sup.NO_WINDOW)
            print("KB Graph 3D: mo app da cai (AppUserModelID=%s)" % installed["app_id"])
            return True
        except Exception as exc:                 # noqa: BLE001
            print("KB Graph 3D: mo app da cai that bai (%s) -> thu --app URL" % exc)
    exe = browser_exe()
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "--app=" + url], close_fds=True,
                         creationflags=sup.DETACHED | sup.NO_WINDOW)
        return True
    except Exception as exc:                 # noqa: BLE001
        print("KB Graph 3D: mo cua so app that bai (%s)" % exc)
        return False


def open_ui(url, app_mode):
    if app_mode:
        if open_app_window(url):
            return
        print("KB Graph 3D: khong thay Edge/Chrome -> mo trinh duyet mac dinh")
    webbrowser.open(url)


def init_starter(target, force=False):
    """--init-starter: chép starter-vault/ vào DIR. In từng file cho người dùng thấy
    mình vừa nhận được cái gì, rồi chỉ luôn bước kế (mở cockpit trên vault mới)."""
    try:
        res = onb.install_starter(target, force=force)
    except onb.OnboardingError as exc:
        print("KB Graph 3D: %s" % exc)
        if getattr(exc, "code", "") == "target_not_empty":
            print("  -> Muon them note huong dan vao vault dang co, chay lai voi --force:")
            print('     python "%s" --init-starter "%s" --force'
                  % (os.path.join(HERE, "ensure_graph3d.py"), os.path.abspath(target)))
            print("     --force van KHONG de file trung ten; file cua ban luon duoc giu nguyen.")
        return 2
    if force:
        print("KB Graph 3D: da them bo note huong dan vao %s" % res["target"])
    else:
        print("KB Graph 3D: da tao vault dau tien tai %s" % res["target"])
    for rel in res["created"]:
        print("  + " + rel)
    for rel in res["skipped"]:
        print("  . %s (da co san, giu nguyen)" % rel)
    print("Buoc ke: mo KB Graph 3D va chon folder nay, hoac chay")
    print('  python "%s" --vault "%s"' %
          (os.path.join(HERE, "ensure_graph3d.py"), res["target"]))
    return 0


def run_demo(port, open_browser, app_mode=False):
    """--demo: mirror app sang demo/vault/.graph3d rồi gọi LẠI chính ensure ở bản sao đó.

    Bản sao giữ demo tự chứa như repo public trước đây; ``--vault`` nay truyền root
    demo xuyên supervisor/serve và đồng thời khóa nút đổi vault cho phiên demo.
    """
    demo = onb.demo_vault_dir()
    if not os.path.isdir(demo):
        print("KB Graph 3D: ban cai nay khong kem vault demo (%s)" % demo)
        print("  -> demo di kem repo public; hoac tro toi vault khac bang GRAPH3D_DEMO_DIR")
        return 2
    app = os.path.join(demo, ".graph3d")
    try:
        res = onb.mirror_app(app, HERE)
    except onb.OnboardingError as exc:
        print("KB Graph 3D: %s" % exc)
        return 2
    # flush: tiến trình con in thẳng ra console, không flush thì dòng này rơi SAU nó
    print("KB Graph 3D: vault demo %s (%d note) — app dong bo %d file"
          % (demo, onb.count_notes(demo), res["copied"]), flush=True)
    cmd = [sys.executable, os.path.join(app, "ensure_graph3d.py"), "--port", str(port),
           "--vault", demo]
    if not open_browser:
        cmd.append("--no-open")
    if app_mode:
        cmd.append("--app")
    # env cách ly: log/journal/heat của demo KHÔNG rơi vào thư mục demo (tên file mang
    # tên máy — đã 2 lần suýt lọt lên repo public), và feed demo không trộn vault thật.
    return subprocess.call(cmd, cwd=app, env=onb.demo_env())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None,
                    help="mac dinh 8321, rieng --demo mac dinh %d" % onb.DEMO_PORT)
    ap.add_argument("--no-open", action="store_true",
                    help="khoi dong server nhung khong mo trinh duyet")
    ap.add_argument("--demo", action="store_true",
                    help="mo cockpit tren vault demo bundled (khong can vault cua ban)")
    ap.add_argument("--init-starter", metavar="DIR",
                    help="tao starter tai DIR; mac dinh doi vault trong, KHONG de file trung ten")
    ap.add_argument("--force", action="store_true",
                    help="kem --init-starter: cho vault dang co; van KHONG de file trung ten")
    ap.add_argument("--app", action="store_true",
                    help="mo bang cua so app cua Edge/Chrome thay vi tab trinh duyet")
    ap.add_argument("--vault", metavar="DIR",
                    help="mo vault root cu the; bo trong = vault da chon tren UI")
    args = ap.parse_args()
    log = bind_console()

    if args.force and not args.init_starter:
        ap.error("--force chi dung kem --init-starter DIR")
    if args.init_starter:
        sys.exit(init_starter(args.init_starter, force=args.force))
    if args.demo:
        sys.exit(run_demo(args.port or onb.DEMO_PORT, not args.no_open, args.app))
    args.port = args.port or 8321

    want = source_version(HERE)
    try:
        vault_ctx = vault_switcher.resolve_active_vault(HERE, explicit=args.vault)
    except vault_switcher.VaultSwitchError as exc:
        print("KB Graph 3D: vault khong hop le (%s): %s" % (exc.code, exc))
        return 2
    url = "http://127.0.0.1:%d" % args.port
    h = sup.health(args.port)

    # want=None = KHÔNG ĐỌC ĐƯỢC version (file bị khóa tạm — OneDrive), không phải version
    # lệch: server đang khỏe thì dùng lại, không được lấy đó làm cớ khởi động lại.
    if sup.health_matches(h, want, vault_ctx["id"]):
        print("KB Graph 3D: dung lai server co san (pid=%s version=%s vault=%s) %s"
              % (h.get("pid"), h.get("version"), vault_ctx["name"], url))
    else:
        if h:
            print("KB Graph 3D: server khac version/vault -> khoi dong lai "
                  "(version %s -> %s, vault %s -> %s)"
                  % (h.get("version"), want, h.get("vault_name"), vault_ctx["name"]))
        # Spawn supervisor NGẦM (sống độc lập với tiến trình ensure này).
        flags = sup.DETACHED | sup.NO_WINDOW
        cmd = [sys.executable, os.path.join(HERE, "run_graph3d.py"), "--port", str(args.port)]
        if args.vault:
            cmd += ["--vault", vault_ctx["path"]]
        subprocess.Popen(
            cmd,
            cwd=HERE, creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok = None
        for _ in range(40):                 # chờ tối đa ~10s
            ok = sup.health(args.port, 0.5)
            if sup.health_matches(ok, want, vault_ctx["id"]):
                break
            time.sleep(0.25)
        if ok:
            print("KB Graph 3D: da khoi dong (pid=%s version=%s) %s"
                  % (ok.get("pid"), ok.get("version"), url))
        else:
            pid = sup.port_pid(args.port)
            if pid:
                # P2.2: supervisor không kill process lạ — báo rõ để người dùng tự xử
                # (supervisor chạy ngầm, output bị nuốt — ensure phải nói thay)
                print("KB Graph 3D: CANH BAO - port %d dang bi process KHAC giu (pid=%s)"
                      % (args.port, pid))
                print("  -> tat process do, hoac chay: python ensure_graph3d.py --port <port khac>")
            else:
                print("KB Graph 3D: CANH BAO - server chua bao khoe sau ~10s, kiem tra thu cong")

    if not args.no_open:
        open_ui(url, args.app)
    if log is not None:
        log.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
