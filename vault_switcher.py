# -*- coding: utf-8 -*-
"""Active-vault selection for KB Graph 3D.

The app code may live in one ``.graph3d`` directory while the data comes from any
folder chosen by the user.  Selection is persisted outside every vault so opening a
vault never writes configuration into it.  A server process receives one immutable
vault through ``GRAPH3D_VAULT``; changing vault writes the config and asks the
supervisor to restart the server on the same port.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

from activity_paths import local_data_dir, no_window_kwargs

CONFIG_ENV = "GRAPH3D_VAULT_CONFIG"
VAULT_ENV = "GRAPH3D_VAULT"
LOCKED_ENV = "GRAPH3D_VAULT_LOCKED"
RECENT_LIMIT = 8


class VaultSwitchError(Exception):
    """Expected validation/picker error with a stable code for the UI."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def config_path():
    override = os.environ.get(CONFIG_ENV, "").strip()
    return os.path.normpath(override) if override else os.path.join(local_data_dir(), "vaults.json")


def normalize_vault(path):
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise VaultSwitchError("invalid_path", "đường dẫn vault không hợp lệ")
    expanded = os.path.expandvars(os.path.expanduser(path.strip()))
    return os.path.normpath(os.path.realpath(os.path.abspath(expanded)))


def validate_vault(path):
    root = normalize_vault(path)
    if not os.path.isdir(root):
        raise VaultSwitchError("not_found", "thư mục vault không còn tồn tại")
    try:
        with os.scandir(root) as rows:
            next(rows, None)                 # empty vault is valid; this probes read permission
    except PermissionError as exc:
        raise VaultSwitchError("permission", "không có quyền đọc thư mục vault") from exc
    except OSError as exc:
        raise VaultSwitchError("unreadable", "không đọc được thư mục vault: %s" % exc) from exc
    return root


def vault_id(path):
    """Stable per-machine namespace; never expose the absolute path in localStorage keys."""
    root = os.path.normcase(normalize_vault(path))
    return hashlib.sha256(root.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def same_vault(a, b):
    try:
        return os.path.normcase(normalize_vault(a)) == os.path.normcase(normalize_vault(b))
    except VaultSwitchError:
        return False


def _read_config():
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_config(data):
    path = config_path()
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="vaults-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def save_selection(path):
    root = validate_vault(path)
    old = _read_config()
    recent = [root]
    for item in old.get("recent", []):
        if isinstance(item, str) and not any(same_vault(item, x) for x in recent):
            recent.append(os.path.normpath(item))
        if len(recent) >= RECENT_LIMIT:
            break
    data = {"version": 1, "vault": root, "recent": recent,
            "updated": int(time.time())}
    _write_config(data)
    return data


def resolve_active_vault(app_dir, explicit=None):
    """Resolve one immutable vault for the next server process.

    ``explicit`` is used by ``--vault`` and demo mode and is strict.  A stale saved
    path falls back to the folder containing the app and returns a warning for UI.
    """
    app_vault = validate_vault(os.path.dirname(os.path.abspath(app_dir)))
    if explicit:
        root = validate_vault(explicit)
        return _context(root, app_vault, source="explicit", locked=True)

    cfg = _read_config()
    saved = cfg.get("vault") if isinstance(cfg.get("vault"), str) else ""
    warning = ""
    if saved:
        try:
            root = validate_vault(saved)
            return _context(root, app_vault, source="saved", locked=False,
                            recent=cfg.get("recent", []))
        except VaultSwitchError as exc:
            warning = exc.code
    return _context(app_vault, app_vault, source="app", locked=False,
                    warning=warning, saved_path=saved, recent=cfg.get("recent", []))


def _context(root, app_vault, source, locked, warning="", saved_path="", recent=None):
    clean_recent = []
    for item in recent or []:
        if isinstance(item, str):
            clean_recent.append({"path": os.path.normpath(item),
                                 "name": os.path.basename(os.path.normpath(item)) or item,
                                 "exists": os.path.isdir(item)})
    return {
        "path": root,
        "name": os.path.basename(root) or root,
        "id": vault_id(root),
        "app_vault": app_vault,
        "source": source,
        "locked": bool(locked),
        "warning": warning,
        "saved_path": saved_path,
        "recent": clean_recent,
    }


_POWERSHELL_PICKER = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Windows.Forms;
public sealed class Graph3dWindowOwner : IWin32Window {
    private readonly IntPtr _handle;
    public Graph3dWindowOwner(IntPtr handle) { _handle = handle; }
    public IntPtr Handle { get { return _handle; } }
}
'@ -ReferencedAssemblies System.Windows.Forms
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = 'Chọn thư mục vault / Choose a vault folder'
$dlg.ShowNewFolderButton = $true
try { $dlg.AutoUpgradeEnabled = $true } catch {}
if ($env:GRAPH3D_PICK_INITIAL -and (Test-Path -LiteralPath $env:GRAPH3D_PICK_INITIAL)) {
  $dlg.SelectedPath = $env:GRAPH3D_PICK_INITIAL
}
$owner = $null
try {
  $rawHwnd = [long]$env:GRAPH3D_PICK_OWNER_HWND
  if ($rawHwnd -ne 0) { $owner = [Graph3dWindowOwner]::new([IntPtr]$rawHwnd) }
} catch {}
$result = if ($null -ne $owner) { $dlg.ShowDialog($owner) } else { $dlg.ShowDialog() }
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Out.Write($dlg.SelectedPath)
}
"""


def foreground_window_handle(platform=None):
    """Return the current Windows foreground HWND, or 0 when unavailable.

    The HTTP request arrives while the user is still in the app window.  Capture its
    HWND *before* starting hidden PowerShell, then give it to ``ShowDialog(owner)`` so
    Windows keeps the folder picker above that app and minimizes/restores them together.
    """
    platform = platform or os.name
    if platform != "nt":
        return 0
    try:
        import ctypes
        fn = ctypes.windll.user32.GetForegroundWindow
        fn.restype = ctypes.c_void_p
        hwnd = fn()
        return int(hwnd or 0)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def choose_folder(initial=None, runner=None, platform=None):
    """Open the OS folder picker.  Empty result means the user cancelled."""
    # Deterministic seam for the live supervisor regression test.  Both flags are
    # required so an unrelated user env can never bypass the native consent dialog.
    if os.environ.get("GRAPH3D_TESTING") == "1" and "GRAPH3D_PICK_TEST_RESULT" in os.environ:
        chosen = os.environ.get("GRAPH3D_PICK_TEST_RESULT", "").strip()
        return validate_vault(chosen) if chosen else None
    platform = platform or os.name
    if platform == "nt":
        exe = "powershell" if runner else (shutil.which("powershell") or shutil.which("pwsh"))
        if not exe:
            raise VaultSwitchError("picker_unavailable", "không tìm thấy PowerShell để mở hộp chọn folder")
        env = os.environ.copy()
        env["GRAPH3D_PICK_INITIAL"] = initial or ""
        env["GRAPH3D_PICK_OWNER_HWND"] = str(foreground_window_handle(platform=platform))
        call = runner or subprocess.run
        try:
            res = call([exe, "-NoProfile", "-STA", "-Command", _POWERSHELL_PICKER],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, **no_window_kwargs())
        except OSError as exc:
            raise VaultSwitchError("picker_failed", "không mở được hộp chọn folder: %s" % exc) from exc
        if res.returncode:
            detail = (res.stderr or res.stdout or "PowerShell lỗi").strip()
            raise VaultSwitchError("picker_failed", detail[:500])
        chosen = (res.stdout or "").strip()
        return validate_vault(chosen) if chosen else None

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=initial or os.path.expanduser("~"),
                                         title="Choose a vault folder")
        root.destroy()
    except Exception as exc:
        raise VaultSwitchError("picker_unavailable", "không mở được hộp chọn folder: %s" % exc) from exc
    return validate_vault(chosen) if chosen else None
