# -*- coding: utf-8 -*-
"""Cài LỐI VÀO KB Graph 3D ở tầng hệ điều hành — shortcut Start Menu / Desktop (tuỳ chọn
phím tắt) chạy `pythonw ensure_graph3d.py --app`.

Vì sao có file này: cửa vào cũ (`Start-Graph3D.bat`) NẰM TRONG vault, nên muốn mở app
phải đi Obsidian → note → click link `file:///…` — và vì mỗi máy một ổ đĩa nên note phải
treo HAI link, người dùng phải tự chọn đúng link của máy mình. Đường dẫn vault là thuộc
tính của MÁY, không phải của note: dời nó vào shortcut thì bước "chọn link theo máy" biến
mất, và app mở được mà không cần Obsidian.

  python .graph3d/install_launcher.py                      # Start Menu + Desktop
  python .graph3d/install_launcher.py --hotkey "CTRL+ALT+G"
  python .graph3d/install_launcher.py --status
  python .graph3d/install_launcher.py --uninstall

Windows-only: tạo .lnk qua COM WScript.Shell gọi bằng PowerShell — không cần thư viện
ngoài (giữ luật "chạy local, không internet, không pip install" của app).

Shortcut LUÔN trỏ điểm vào idempotent `ensure_graph3d.py`, không bao giờ trỏ thẳng
server (luật: mọi launcher đi qua ensure) — test_launcher.py gác điều này.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from activity_paths import local_data_dir, no_window_kwargs   # noqa: E402

from activity_paths import APP_NAME
ENSURE = "ensure_graph3d.py"

# Truyền tham số cho PowerShell bằng BIẾN MÔI TRƯỜNG, không nội suy vào chuỗi lệnh:
# đường dẫn vault thường có dấu cách, gạch nối, có khi cả dấu nháy (thư mục OneDrive
# đồng bộ từ tổ chức là ca kinh điển) — mọi kiểu escape thủ công đều sẽ hỏng ở đâu đó.
_PS_WRITE = """
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:G3D_LNK)
$s.TargetPath = $env:G3D_TARGET
$s.Arguments = $env:G3D_ARGS
$s.WorkingDirectory = $env:G3D_WORKDIR
$s.Description = $env:G3D_DESC
if ($env:G3D_ICON) { $s.IconLocation = $env:G3D_ICON }
if ($env:G3D_HOTKEY) { $s.Hotkey = $env:G3D_HOTKEY }
$s.Save()
"""

_PS_READ = """
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:G3D_LNK)
@{ target = $s.TargetPath; args = $s.Arguments; workdir = $s.WorkingDirectory;
   icon = $s.IconLocation; hotkey = $s.Hotkey } | ConvertTo-Json -Compress
"""

_PS_FOLDERS = """
$ErrorActionPreference = 'Stop'
@{ desktop = [Environment]::GetFolderPath('Desktop')
   programs = [Environment]::GetFolderPath('Programs') } | ConvertTo-Json -Compress
"""


class LauncherError(Exception):
    pass


def _powershell(script, extra_env=None):
    """Chạy helper PowerShell mà không để ``pythonw`` làm loé cửa sổ terminal.

    Shell folder và mỗi shortcut đều đi qua đây. Thiếu ``CREATE_NO_WINDOW`` khiến
    một lần mở app tạo liên tiếp nhiều khung PowerShell rồi tắt (máy công ty, 11/08).
    """
    env = dict(os.environ)
    env.update(extra_env or {})
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30, env=env,
                           **no_window_kwargs())
    except Exception as exc:                       # noqa: BLE001
        raise LauncherError("khong goi duoc PowerShell: %s" % exc)
    if r.returncode != 0:
        raise LauncherError((r.stderr or r.stdout or "PowerShell exit %d" % r.returncode).strip())
    return r.stdout.strip()


# ---------------------------------------------------------------- đường dẫn

def _registry_version_key(tag):
    """Khoá sort version Registry, đủ cho tag PythonCore kiểu 3.13 / 3.13-32."""
    nums = tuple(int(n) for n in re.findall(r"\d+", tag or ""))
    return nums or (-1,)


def store_pythonw_alias(path, isfile=None, localappdata=None):
    """Đổi đường Store Python có số build sang app-exec alias ổn định nếu có thật.

    Registry của Microsoft Store trỏ vào ``Program Files/WindowsApps`` với version
    package trong path; Store update sẽ thay folder đó và làm shortcut chết. Package
    đồng thời cấp alias per-user không mang số build — vẫn hỏi Registry để xác định
    bản cài, nhưng ghim alias mới đúng mục tiêu lâu dài của launcher.
    """
    isfile = isfile or os.path.isfile
    package = os.path.basename(os.path.dirname(os.path.normpath(path or "")))
    match = re.match(r"^(PythonSoftwareFoundation\.Python\.[^_]+)_.+__([A-Za-z0-9]+)$",
                     package, re.I)
    base = localappdata or os.environ.get("LOCALAPPDATA", "").strip()
    if not match or not base:
        return path
    family = match.group(1) + "_" + match.group(2)
    alias = os.path.normpath(os.path.join(
        base, "Microsoft", "WindowsApps", family, "pythonw.exe"))
    return alias if isfile(alias) else path


def registered_pythonw_exe(winreg_module=None, isfile=None):
    """Tìm Python cài chuẩn qua PEP 514 Registry, không cần thư viện ngoài.

    Ưu tiên HKCU rồi HKLM; trong mỗi hive lấy version mới nhất còn tồn tại. Quét cả
    view Registry mặc định/64/32 để một Python 32-bit vẫn thấy bản cài 64-bit. Entry
    stale bị bỏ qua — Registry còn key không có nghĩa file sau update/uninstall còn.

    ``winreg_module``/``isfile`` là seam nhỏ cho test; lúc chạy thật đều để mặc định.
    """
    if winreg_module is None:
        if os.name != "nt":
            return None
        try:
            import winreg as winreg_module       # stdlib, Windows-only
        except ImportError:
            return None
    isfile = isfile or os.path.isfile
    wr = winreg_module
    base = r"SOFTWARE\Python\PythonCore"
    views = [0]
    for attr in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        view = getattr(wr, attr, 0)
        if view and view not in views:
            views.append(view)

    # Hive người dùng đứng trước hive toàn máy: bản cài per-user là lựa chọn có chủ
    # đích của chính tài khoản đang tạo shortcut.
    for hive in (wr.HKEY_CURRENT_USER, wr.HKEY_LOCAL_MACHINE):
        found = {}
        for view in views:
            try:
                root = wr.OpenKey(hive, base, 0, wr.KEY_READ | view)
            except OSError:
                continue
            try:
                index = 0
                while True:
                    try:
                        tag = wr.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        key = wr.OpenKey(hive, base + "\\" + tag + r"\InstallPath",
                                         0, wr.KEY_READ | view)
                    except OSError:
                        continue
                    try:
                        value, _kind = wr.QueryValueEx(key, "WindowedExecutablePath")
                    except OSError:
                        continue
                    finally:
                        wr.CloseKey(key)
                    path = os.path.normpath(os.path.expandvars(str(value).strip()))
                    if path and isfile(path):
                        target = store_pythonw_alias(path, isfile=isfile)
                        found[os.path.normcase(target)] = (_registry_version_key(tag), target)
            finally:
                wr.CloseKey(root)
        if found:
            return max(found.values(), key=lambda item: item[0])[1]
    return None


def managed_python_path(path):
    """True nếu interpreter nằm trong venv/runtime do công cụ khác quản."""
    low = os.path.normcase(os.path.normpath(path or "")).replace("/", "\\")
    markers = ("\\venv\\", "\\.venv\\", "\\venvs\\", "\\uv\\",
               "\\virtualenvs\\", "\\codex-runtimes\\")
    return any(marker in low for marker in markers) or re.search(r"\\generation-[^\\]+\\", low) is not None


def pythonw_exe(override=None):
    """Python để nhét vào shortcut. Ba điều kiện:

    1. Ưu tiên `pythonw.exe` — python KHÔNG cửa sổ console, nhờ nó click shortcut không
       loé lên một khung CMD đen rồi biến mất.
    2. Sau chỉ định tay, hỏi Registry trước: đó là bản Python cài chuẩn của máy.
    3. TRÁNH python của VENV. Người cài rất hay đang đứng trong venv của một dự án khác
       (agent, tooling…); venv là thứ bị xoá/dời/tái tạo thường xuyên, shortcut trỏ vào
       đó là shortcut chết yểu — mà app chỉ dùng stdlib nên chẳng cần venv nào cả.
       Chỉ khi Registry không có bản hợp lệ mới lùi về sys.base_prefix/interpreter hiện
       hành; base_prefix cũng có thể là runtime tạm nên không còn là lựa chọn số một.

    Chỉ định tay: --python <đường dẫn> hoặc env GRAPH3D_PYTHONW."""
    for cand in (override, os.environ.get("GRAPH3D_PYTHONW", "").strip()):
        if cand and os.path.isfile(cand):
            return cand
    registered = registered_pythonw_exe()
    if registered:
        return registered
    roots = []
    in_venv = bool(getattr(sys, "base_prefix", sys.prefix) != sys.prefix)
    if in_venv:
        roots.append(sys.base_prefix)
    if sys.executable:
        roots.append(os.path.dirname(sys.executable))
    for root in roots:
        for name in ("pythonw.exe", "python.exe"):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                return p
    return sys.executable or "pythonw.exe"


def icon_dir():
    """Nơi sinh icon = THƯ MỤC APP, tuyệt đối KHÔNG phải %LOCALAPPDATA%.

    Lý do (bug 28/07, mất mấy vòng mới ra): agent có thể chạy trong sandbox MSIX của
    Claude Desktop, mà MSIX **ảo hoá %LOCALAPPDATA%** — file ghi ra đó thật sự nằm
    trong `Packages\\Claude_*\\LocalCache\\Local\\…`. Tiến trình TRONG sandbox đọc
    đường "thật" vẫn thấy file (merged view) nên mọi phép đo đều báo OK, nhưng
    **Explorer chạy NGOÀI sandbox thì không thấy gì** ⇒ shortcut mất icon và hiện
    biểu tượng tờ giấy trắng. Cùng họ với gotcha #19 (activity.jsonl của Cowork).
    Thư mục app nằm trên ổ thật, mọi tiến trình đều thấy như nhau.

    Env GRAPH3D_ICON_DIR: cho test (và cho ai muốn để icon chỗ khác)."""
    d = os.environ.get("GRAPH3D_ICON_DIR", "").strip() or HERE
    return os.path.normpath(d)


def shell_folders():
    """Desktop + Start Menu\\Programs hỏi THẲNG Windows: OneDrive hay Known Folder
    Redirection dời Desktop đi chỗ khác thì %USERPROFILE%\\Desktop là đường CHẾT."""
    try:
        got = json.loads(_powershell(_PS_FOLDERS))
        out = {k: got.get(k) for k in ("desktop", "programs")}
        if all(out.values()):
            return out
    except Exception:                              # noqa: BLE001
        pass
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    return {"desktop": os.path.join(home, "Desktop"),
            "programs": os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")}


def shortcut_spec(port=8321, app_mode=True, name=APP_NAME, python=None, icon=None):
    """Mô tả shortcut sẽ tạo — tách khỏi việc GHI để test soi được nội dung mà không
    phải đẻ file .lnk thật."""
    args = ['"%s"' % os.path.join(HERE, ENSURE)]
    if app_mode:
        args.append("--app")
    if port != 8321:
        args += ["--port", str(port)]
    return {"target": pythonw_exe(python),
            "args": " ".join(args),
            "workdir": HERE,
            "desc": "%s — cockpit vault (local, port %d)" % (name, port),
            "icon": icon or ""}


def shortcut_paths(name=APP_NAME, desktop=True, start_menu=True, dest_dir=None):
    """[(nhãn, đường dẫn .lnk)] theo lựa chọn. dest_dir = ghi đè cả hai (test / người
    dùng muốn tự đặt chỗ)."""
    if dest_dir:
        return [("thu muc chi dinh", os.path.join(os.path.normpath(dest_dir), name + ".lnk"))]
    f = shell_folders()
    out = []
    if start_menu:
        out.append(("Start Menu", os.path.join(f["programs"], name + ".lnk")))
    if desktop:
        out.append(("Desktop", os.path.join(f["desktop"], name + ".lnk")))
    return out


# ---------------------------------------------------------------- .lnk

def write_shortcut(path, spec, hotkey=None):
    """Ghi .lnk. MỌI đường dẫn phải chuẩn hoá về dấu `\\` của Windows: `CreateProcess`
    chấp nhận `C:/…/pythonw.exe` nên shortcut vẫn CHẠY, nhưng shell resolve link khắt
    khe hơn — link "không hợp lệ" thì Explorer vẽ **biểu tượng file generic (tờ giấy
    trắng)** và bỏ qua cả IconLocation. Bug 28/07: `--python` nhận đường dẫn kiểu Unix."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    icon = spec.get("icon") or ""
    _powershell(_PS_WRITE, {
        "G3D_LNK": os.path.normpath(path),
        "G3D_TARGET": os.path.normpath(spec["target"]),
        "G3D_ARGS": spec["args"],
        "G3D_WORKDIR": os.path.normpath(spec["workdir"]),
        "G3D_DESC": spec["desc"],
        "G3D_ICON": os.path.normpath(icon) if os.path.isfile(icon) else "",
        "G3D_HOTKEY": hotkey or ""})
    return path


def read_shortcut(path):
    return json.loads(_powershell(_PS_READ, {"G3D_LNK": path}))


def refresh_shell():
    """Xin Explorer làm mới icon — LỚP PHỤ. Lớp chính là tên icon mang hash nội dung
    (xem `write_icon`): cache bám theo đường dẫn, nên đổi nội dung là đổi luôn tên.
    Hàm này chỉ để Explorer vẽ lại ngay thay vì đợi lần refresh sau; nó KHÔNG đủ để
    cứu một tên file cố định đã bị cache (đo thật 28/07: gọi xong vẫn trắng).
    SHCNE_ASSOCCHANGED (0x08000000) — nhẹ, không phải giết explorer.exe."""
    if os.name != "nt":
        return False
    ok = False
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        ok = True
    except Exception:                              # noqa: BLE001
        pass
    try:
        # Cache icon còn có phần GHI RA ĐĨA (iconcache_*.db) mà SHChangeNotify không
        # phải lúc nào cũng dọn; ie4uinit là tiện ích sẵn của Windows làm đúng việc đó.
        subprocess.run([os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                     "System32", "ie4uinit.exe"), "-show"],
                       capture_output=True, timeout=15, **no_window_kwargs())
    except Exception:                              # noqa: BLE001
        pass
    return ok


# ---------------------------------------------------------------- icon

# Node + link của icon: một mảnh graph neon — cùng bảng màu synthwave với app.
_NODES = ((0.00, -0.10, (0.22, 0.95, 1.00), 0.19),
          (-0.45, 0.30, (1.00, 0.31, 0.85), 0.12),
          (0.44, 0.26, (1.00, 0.84, 0.35), 0.11),
          (0.26, -0.55, (0.62, 0.45, 1.00), 0.10))


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _lit(base, color, k):
    """Chồng một lớp phát sáng theo kiểu SCREEN chứ không cộng thẳng: cộng thì chỗ
    node giao link bão hoà thành khối TRẮNG (nhìn rõ nhất ở 16/32px — icon mất hết
    màu), screen thì càng sáng càng giữ đúng sắc neon."""
    return tuple(c + col * k - c * col * k for c, col in zip(base, color))


def _pixel(x, y):
    """Màu (r,g,b,a) 0..1 tại điểm (x,y) trong hình vuông [-1,1]."""
    d = math.hypot(x, y)
    if d > 1.0:
        return (0.0, 0.0, 0.0, 0.0)
    a = 1.0 if d < 0.965 else max(0.0, (1.0 - d) / 0.035)
    t = min(1.0, d) ** 2
    c = (0.09 * (1 - t) + 0.02 * t, 0.05 * (1 - t) + 0.01 * t, 0.18 * (1 - t) + 0.05 * t)
    c = _lit(c, (0.16, 0.85, 1.0), math.exp(-((d - 0.93) / 0.05) ** 2))   # viền neon
    hx, hy = _NODES[0][0], _NODES[0][1]
    for nx, ny, _c, _rad in _NODES[1:]:            # link toả từ node trung tâm
        c = _lit(c, (0.55, 0.36, 1.0),
                 0.85 * math.exp(-(_seg_dist(x, y, hx, hy, nx, ny) / 0.045) ** 2))
    for nx, ny, col, rad in _NODES:
        dd = math.hypot(x - nx, y - ny)
        c = _lit(c, col, 1.0 if dd < rad * 0.5 else math.exp(-((dd - rad * 0.5) / (rad * 0.8)) ** 2))
    return (min(1.0, c[0]), min(1.0, c[1]), min(1.0, c[2]), a)


def _bmp(size, ss=3):
    """Một ảnh trong .ico: BITMAPINFOHEADER + pixel BGRA bottom-up + AND mask rỗng.
    Dùng BMP chứ không PNG-in-ICO để không phụ thuộc Windows đời nào; khử răng cưa
    bằng supersample ss×ss."""
    rows = []
    n = ss * ss
    for py in range(size - 1, -1, -1):             # bottom-up
        row = bytearray()
        for px in range(size):
            sr = sg = sb = sa = 0.0
            for j in range(ss):
                y = ((py + (j + 0.5) / ss) / size) * 2 - 1
                for i in range(ss):
                    x = ((px + (i + 0.5) / ss) / size) * 2 - 1
                    r, g, b, a = _pixel(x, y)
                    sr, sg, sb, sa = sr + r * a, sg + g * a, sb + b * a, sa + a
            al = sa / n
            # premultiplied trung bình -> tách lại, tránh viền đen quanh mép mềm
            k = (1.0 / sa) if sa > 1e-6 else 0.0
            row += bytes((int(sb * k * 255 + 0.5), int(sg * k * 255 + 0.5),
                          int(sr * k * 255 + 0.5), int(al * 255 + 0.5)))
        rows.append(bytes(row))
    pix = b"".join(rows)
    mask = b"\x00" * (((size + 31) // 32) * 4 * size)
    # biSizeImage = kích thước ẢNH XOR, KHÔNG gồm AND mask. GDI+/System.Drawing bỏ qua
    # field này (đo bằng chúng thì file nào cũng "hợp lệ"), nhưng đường vẽ icon của
    # Explorer dùng nó để tìm mask — ghi dư mask vào đây là icon hỏng và shell rơi về
    # biểu tượng tờ giấy trắng. Đúng bug 28/07: mọi API đọc được, riêng Explorer trắng.
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      len(pix), 0, 0, 0, 0)
    return hdr + pix + mask


def icon_bytes(sizes=(16, 32, 48, 64, 128)):
    imgs = [(s, _bmp(s)) for s in sizes]
    entries, data = b"", b""
    offset = 6 + 16 * len(imgs)
    for s, blob in imgs:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        data += blob
    return struct.pack("<HHH", 0, 1, len(imgs)) + entries + data


def write_icon(directory=None, sizes=(16, 32, 48, 64)):
    """Ghi icon ra đĩa với TÊN MANG HASH NỘI DUNG (`graph3d-<hash8>.ico`) và dọn các
    bản cũ.

    Vì sao không dùng một tên cố định: icon cache của Explorer bám theo **đường dẫn**.
    Ghi đè cùng tên bằng nội dung mới thì Explorer vẫn vẽ bản đã cache — đúng triệu
    chứng "icon tờ giấy trắng" báo 28/07, và dọn cache (SHChangeNotify / ie4uinit)
    KHÔNG phải lúc nào cũng ăn. Đổi nội dung ⇒ đổi tên ⇒ cache cũ không còn dính vào
    đâu; cùng nội dung thì tên không đổi nên chạy lại không rác thêm file."""
    directory = directory or icon_dir()
    raw = icon_bytes(sizes)
    name = "graph3d-%s.ico" % hashlib.sha1(raw).hexdigest()[:8]
    path = os.path.join(directory, name)
    os.makedirs(directory, exist_ok=True)
    if not os.path.isfile(path) or open(path, "rb").read() != raw:
        with open(path, "wb") as f:
            f.write(raw)
    for old in icon_files(directory):
        if os.path.normcase(old) != os.path.normcase(path):
            try:
                os.remove(old)                     # bản cũ: shortcut trỏ tên mới rồi
            except OSError:
                pass
    return path


def icon_files(directory=None):
    """Mọi icon do app sinh (kể cả tên cố định của bản v1.48.0/.1) — để dọn/gỡ."""
    directory = directory or icon_dir()
    return sorted(glob.glob(os.path.join(directory, "graph3d*.ico")))


# ---------------------------------------------------------------- lệnh

def install(name=APP_NAME, desktop=True, start_menu=True, hotkey=None, port=8321,
            app_mode=True, dest_dir=None, python=None):
    paths = shortcut_paths(name, desktop, start_menu, dest_dir)
    if not paths:
        raise LauncherError("khong chon dich nao (--no-desktop lan --no-start-menu?)")
    try:
        icon = write_icon()
    except Exception as exc:                       # noqa: BLE001
        print("  ! khong tao duoc icon (%s) — shortcut dung icon mac dinh" % exc)
        icon = None
    spec = shortcut_spec(port, app_mode, name, python, icon)
    made = []
    for label, p in paths:
        # Hotkey chỉ gán cho MỘT shortcut: hai .lnk cùng hotkey thì Windows chọn bừa.
        write_shortcut(p, spec, hotkey if (hotkey and not made) else None)
        made.append((label, p))
    refresh_shell()
    return {"paths": made, "spec": spec, "icon": icon, "hotkey": hotkey}


def uninstall(name=APP_NAME, dest_dir=None):
    removed, kept = [], []
    for _label, p in shortcut_paths(name, True, True, dest_dir):
        if not os.path.isfile(p):
            continue
        # Chỉ xoá shortcut CỦA MÌNH: trùng tên nhưng trỏ chỗ khác thì để yên.
        try:
            info = read_shortcut(p)
            mine = ENSURE in (info.get("args") or "")
        except Exception:                          # noqa: BLE001
            mine = False
        if mine:
            os.remove(p)
            removed.append(p)
        else:
            kept.append(p)
    for icon in icon_files():                      # gồm cả tên cố định của bản cũ
        try:
            os.remove(icon)
        except OSError:
            pass
    refresh_shell()
    return {"removed": removed, "kept": kept}


def status(name=APP_NAME, dest_dir=None):
    out = []
    for label, p in shortcut_paths(name, True, True, dest_dir):
        if not os.path.isfile(p):
            out.append({"label": label, "path": p, "exists": False})
            continue
        try:
            info = read_shortcut(p)
        except Exception as exc:                   # noqa: BLE001
            info = {"error": str(exc)}
        info.update({"label": label, "path": p, "exists": True})
        out.append(info)
    return out


def main():
    ap = argparse.ArgumentParser(description="Cai shortcut mo KB Graph 3D (Windows)")
    ap.add_argument("--name", default=APP_NAME, help="ten shortcut (mac dinh: %s)" % APP_NAME)
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--hotkey", default=None,
                    help='phim tat, vd "CTRL+ALT+G" (chi gan cho shortcut dau tien)')
    ap.add_argument("--no-desktop", action="store_true")
    ap.add_argument("--no-start-menu", action="store_true")
    ap.add_argument("--no-app", action="store_true",
                    help="mo bang tab trinh duyet thuong thay vi cua so app rieng")
    ap.add_argument("--dir", dest="dest_dir", default=None,
                    help="tao .lnk vao thu muc chi dinh thay vi Desktop/Start Menu")
    ap.add_argument("--python", default=None,
                    help="chi dinh python chay app (mac dinh: Python Registry, roi moi fallback)")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                              # noqa: BLE001
        pass

    if os.name != "nt":
        print("install_launcher.py: chi chay tren Windows (shortcut .lnk).")
        return 2

    try:
        if args.status:
            for row in status(args.name, args.dest_dir):
                if not row["exists"]:
                    print("  - %s: CHUA CAI (%s)" % (row["label"], row["path"]))
                else:
                    print("  + %s: %s" % (row["label"], row["path"]))
                    print("      %s %s" % (row.get("target"), row.get("args")))
                    if managed_python_path(row.get("target")):
                        print("      ! python nam trong venv/runtime tam — nen cai lai shortcut.")
                    if row.get("hotkey"):
                        print("      phim tat: %s" % row["hotkey"])
            return 0
        if args.uninstall:
            res = uninstall(args.name, args.dest_dir)
            for p in res["removed"]:
                print("  - da xoa %s" % p)
            for p in res["kept"]:
                print("  . giu nguyen %s (khong phai shortcut cua KB Graph 3D)" % p)
            if not res["removed"] and not res["kept"]:
                print("  (khong co gi de go)")
            return 0
        res = install(args.name, not args.no_desktop, not args.no_start_menu,
                      args.hotkey, args.port, not args.no_app, args.dest_dir, args.python)
    except LauncherError as exc:
        print("install_launcher.py: %s" % exc)
        return 2

    print("TON618: da tao shortcut")
    for label, p in res["paths"]:
        print("  + %s: %s" % (label, p))
    print("  chay: %s %s" % (res["spec"]["target"], res["spec"]["args"]))
    if managed_python_path(res["spec"]["target"]):
        print("  ! python nay do cong cu khac quan ly (venv/runtime tam) — go no la shortcut chet.")
        print("    Muon chac: --python \"<duong dan pythonw.exe cai chuan>\"")
    if res["hotkey"]:
        print("  phim tat: %s (Windows chi nhan hotkey cua .lnk o Desktop/Start Menu)" % res["hotkey"])
    print("  Ghim Taskbar: chuot phai vao shortcut -> Pin to taskbar")
    print("  Go bo: python install_launcher.py --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
