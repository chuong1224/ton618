# -*- coding: utf-8 -*-
"""Kiểm tra bản mới trên repo public — "bạn đang thiếu N bản" + changelog ngắn (W69).

Vì sao có file này: người clone repo về rồi chạy thì KHÔNG có đường nào biết đã có bản
mới; app không tự cập nhật, không có store, không có kênh thông báo nào cả.

BA RÀNG BUỘC ĐỊNH HÌNH TOÀN BỘ THIẾT KẾ — đọc trước khi sửa:

1. **App hứa "chạy hoàn toàn local, không cần internet"** (README cả bản private lẫn
   public). Đây là chỗ ĐẦU TIÊN app mở kết nối ra ngoài, nên:
      - Không gọi gì cho tới khi người dùng **đồng ý tường minh** (`consent`).
      - Offline / lỗi mạng / bị chặn ⇒ **im lặng**, giữ kết quả cache cũ, không nổ, không
        hiện lỗi đỏ. Mất mạng không phải là hỏng app.

2. **GitHub API không token = 60 request/GIỜ tính THEO IP.** Đo thật ở văn phòng
   29/07: 403 `rate limit exceeded` vì cả toà nhà đi chung một IP NAT và quota đã bị
   người khác đốt sạch. Nên: tối đa **1 lượt kiểm/ngày**, kết quả ghi ra đĩa, và khi bị
   chặn thì tôn trọng `X-RateLimit-Reset` chứ không thử lại mù. Ai ở sau IP dùng chung
   có thể đặt `GRAPH3D_GITHUB_TOKEN` để dùng hạn mức riêng (tuỳ chọn, không bắt buộc).

3. **Repo KHÔNG có GitHub Releases, chỉ có tag.** Changelog vì thế lấy từ *tag →
   commit message* qua một lần `/compare`, không phải từ release notes.

Số version so bằng semver đọc từ badge `index.html` (`activity_paths.app_version`) —
không khai hằng số version thứ hai ở đây.

CLI: `python update_check.py` in trạng thái hiện tại (đọc cache, không hỏi mạng);
     `python update_check.py --check` ép kiểm ngay, bỏ qua TTL.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from activity_paths import (app_version, local_data_dir,   # noqa: E402
                            no_window_kwargs, parse_semver)

# Repo gốc — chỉ dùng khi bản cài KHÔNG phải một clone (ví dụ working tree private của
# người bảo trì, vốn có git dir riêng và không có remote nào).
CANONICAL_REPO = "chuong1224/ton618"
LEGACY_REPO = "chuong1224/agents-knowledge-base"
API = "https://api.github.com"
TTL = 24 * 3600          # tối đa 1 lượt kiểm/ngày (xem ràng buộc 2)
TIMEOUT = 6              # giây; thà bỏ lượt kiểm còn hơn treo request của UI


def state_path():
    return os.path.join(local_data_dir(), "update_check.json")


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        os.makedirs(local_data_dir(), exist_ok=True)
        tmp = state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, state_path())
    except OSError:
        pass                                   # không ghi được cache thì thôi, đừng nổ


# ---------------------------------------------------------------- repo đang dùng

def _git(args, cwd=HERE):
    """Chạy git, trả stdout đã strip hoặc None. Máy không có git cũng phải sống được.

    `no_window_kwargs()` là BẮT BUỘC, không phải trang trí: server chạy bằng `pythonw`
    (không console) nên mỗi lần spawn `git` mà thiếu cờ đó là Windows loé một khung
    console đen rồi tắt. Bản đầu của đợt W69 quên, và vì `status()` gọi **tới 5** lệnh
    git mỗi request nên người dùng thấy nhấp nháy mấy lần quanh lúc bấm Cho phép —
    đó là phản hồi đầu tiên nhận được sau khi phát hành. Đo lại sau khi vá + cache: lượt đầu 3
    lệnh (precheck dừng sớm ở `no_remote`), các lượt trong 30s kế tiếp **0 lệnh**."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10,
                           **no_window_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repo_slug(here=HERE):
    """`owner/repo` của bản cài này, suy từ `origin`. Người FORK thì được kiểm đúng
    fork của họ chứ không phải repo gốc. Không có remote (bản private của người bảo
    trì) ⇒ rơi về repo gốc."""
    url = _git(["remote", "get-url", "origin"], here) or ""
    url = url.strip()
    for pre in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(pre):
            slug = url[len(pre):]
            if slug.endswith(".git"):
                slug = slug[:-4]
            if slug.count("/") == 1 and all(slug.split("/")):
                return CANONICAL_REPO if slug.casefold() == LEGACY_REPO.casefold() else slug
    return CANONICAL_REPO


# ---------------------------------------------------------------- GitHub API

def _api(path):
    """(dữ liệu, lỗi, reset_ts). Không ném ra ngoài bao giờ — mọi hỏng hóc thành `lỗi`
    dạng chuỗi mã ngắn để UI dịch được, và `reset_ts` để biết khi nào thử lại."""
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        # User-Agent đi kèm MỌI request ra ngoài nên nó là nội dung công khai: đừng
        # nhét tên repo private vào đây. Bản đầu ghi tên repo private và bị denylist
        # của publish chặn thẳng — đúng vai trò của nó, và đúng lúc.
        "User-Agent": "ton618-update-check"})
    token = (os.environ.get("TON618_GITHUB_TOKEN") or
             os.environ.get("GRAPH3D_GITHUB_TOKEN", "")).strip()
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None, 0
    except urllib.error.HTTPError as exc:
        reset = 0
        try:
            reset = int(exc.headers.get("X-RateLimit-Reset") or 0)
        except (TypeError, ValueError):
            pass
        if exc.code in (403, 429) and (exc.headers.get("X-RateLimit-Remaining") == "0"
                                       or reset):
            return None, "rate_limit", reset
        return None, "http_%d" % exc.code, 0
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None, "offline", 0              # mất mạng/DNS/proxy — im lặng, không phải lỗi app


def _tags(slug):
    return _api("/repos/%s/tags?per_page=100" % slug)


def _compare(slug, base, head):
    return _api("/repos/%s/compare/%s...%s" % (slug, base, head))


# ---------------------------------------------------------------- lượt kiểm

def _newer_tags(tags, local):
    """[(tag, sha)] các tag mới hơn `local`, mới nhất trước. Tag không phải semver bị
    bỏ qua (repo có thể mang tag khác cho việc khác)."""
    cur = parse_semver(local)
    out = []
    for t in tags or []:
        name = (t or {}).get("name") or ""
        v = parse_semver(name)
        if v and cur and v > cur:
            out.append((name, ((t.get("commit") or {}).get("sha") or "")))
    out.sort(key=lambda p: parse_semver(p[0]), reverse=True)
    return out


def refresh(force=False, here=HERE):
    """Đi hỏi GitHub nếu ĐẾN HẠN và ĐÃ ĐƯỢC ĐỒNG Ý. Trả state đã cập nhật.

    Thứ tự các cửa chặn (đúng 3 ràng buộc ở đầu file): chưa đồng ý → không hỏi · chưa
    tới hạn → không hỏi · đang bị rate limit và chưa tới `reset` → không hỏi."""
    st = load_state()
    if not st.get("consent"):
        return st
    now = time.time()
    if not force:
        if now - float(st.get("checked_at") or 0) < TTL:
            return st
        if now < float(st.get("retry_after") or 0):
            return st

    local = app_version(here)
    if not local:
        st["error"] = "no_local_version"
        save_state(st)
        return st

    slug = repo_slug(here)
    tags, err, reset = _tags(slug)
    if err:
        st["error"] = err
        st["retry_after"] = reset or (now + 3600)
        save_state(st)                          # giữ nguyên kết quả cũ, chỉ ghi lỗi
        return st

    newer = _newer_tags(tags, local)
    versions = [{"tag": t, "summary": ""} for t, _ in newer]

    # Tóm tắt mỗi bản = dòng đầu commit message của commit mang tag đó. Một lần
    # /compare lấy hết, thay vì N lần /commits/{sha} — quota chỉ có 60/giờ.
    if newer:
        cmp_data, cmp_err, _r = _compare(slug, local, newer[0][0])
        if not cmp_err and isinstance(cmp_data, dict):
            by_sha = {}
            for c in cmp_data.get("commits") or []:
                msg = ((c or {}).get("commit") or {}).get("message") or ""
                by_sha[(c or {}).get("sha") or ""] = msg.split("\n")[0].strip()
            for item, (_t, sha) in zip(versions, newer):
                item["summary"] = by_sha.get(sha, "")

    st.update({"repo": slug, "local": local,
               "latest": newer[0][0] if newer else local,
               "behind": len(newer), "versions": versions,
               "checked_at": now, "error": None, "retry_after": 0})
    save_state(st)
    return st


# ---------------------------------------------------------------- cập nhật tại chỗ

def pull_precheck(here=HERE):
    """(cho_phep, ly_do). Nút "cập nhật" chỉ được sáng khi CẢ BỐN điều kiện đạt.

    Vì sao khắt khe: bản của người bảo trì có git dir RIÊNG và KHÔNG có remote nào —
    `git pull` ở đó là sai hoàn toàn. Và bất kỳ ai sửa code tại chỗ mà bị pull đè lên
    thì mất việc của họ. Thà không cho bấm còn hơn."""
    if _git(["rev-parse", "--is-inside-work-tree"], here) != "true":
        return False, "not_a_repo"
    if not _git(["remote", "get-url", "origin"], here):
        return False, "no_remote"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], here)
    if not branch or branch == "HEAD":
        return False, "detached"
    if _git(["status", "--porcelain"], here):
        return False, "dirty"
    return True, "ok"


def pull(here=HERE):
    """`git pull --ff-only` sau khi precheck đạt. **ff-only là cố ý**: không merge,
    không rebase, không đè — pull mà phải hoà giải thì trả về lỗi cho người dùng tự xử,
    app không tự ý viết lại lịch sử của ai.

    Kéo xong thì `serve.py` tự thấy nguồn đổi và khởi động lại; nút ⟳ (W64) sẽ nháy lên
    mời nạp lại giao diện — không cần làm gì thêm ở đây."""
    ok, why = pull_precheck(here)
    if not ok:
        return {"ok": False, "reason": why}
    try:
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=here, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=120,
                           **no_window_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": "git_failed", "detail": str(exc)}
    if r.returncode != 0:
        return {"ok": False, "reason": "pull_failed",
                "detail": (r.stderr or r.stdout or "").strip()[:400]}
    st = load_state()
    st["checked_at"] = 0                       # vừa cập nhật → lượt kiểm sau tính lại từ đầu
    save_state(st)
    return {"ok": True, "detail": (r.stdout or "").strip()[:400]}


# ---------------------------------------------------------------- cho UI / CLI

def set_consent(value, here=HERE):
    st = load_state()
    st["consent"] = bool(value)
    st["asked"] = True
    save_state(st)
    return refresh(force=bool(value), here=here) if value else st


_probe_cache = {"ts": 0.0, "val": None}


def _repo_probe(here):
    """(slug, can_pull, lý_do) — gộp 5 lệnh git thành MỘT lượt và nhớ 30 giây.

    Vì sao: `status()` chạy mỗi lần UI hỏi `/update`, mà mỗi lượt cũ tốn 1 lệnh cho
    `repo_slug` + 4 lệnh cho `pull_precheck`. Năm tiến trình con cho một câu hỏi chỉ
    đổi khi người dùng commit/checkout là quá phí — và trước khi có `no_window_kwargs`
    thì đó cũng chính là năm lần loé cửa sổ đen. Nhịp 30s mượn đúng của
    `activity_log_candidates`."""
    now = time.time()
    if _probe_cache["val"] is not None and now - _probe_cache["ts"] < 30:
        return _probe_cache["val"]
    val = (repo_slug(here),) + pull_precheck(here)
    _probe_cache["ts"], _probe_cache["val"] = now, val
    return val


def status(here=HERE):
    """Trạng thái cho UI. KHÔNG tự đi hỏi mạng ở đây — `serve.py` gọi `refresh()`
    riêng, để một lần bấm F5 không bao giờ biến thành một lần gọi ra internet ngoài ý
    muốn người dùng."""
    st = load_state()
    slug, can, why = _repo_probe(here)
    return {"asked": bool(st.get("asked")), "consent": bool(st.get("consent")),
            "local": app_version(here), "latest": st.get("latest"),
            "behind": int(st.get("behind") or 0), "versions": st.get("versions") or [],
            "repo": st.get("repo") or slug,
            "checked_at": st.get("checked_at") or 0, "error": st.get("error"),
            "can_pull": can, "pull_reason": why}


def main():
    ap = argparse.ArgumentParser(description="Kiem tra ban moi cua KB Graph 3D")
    ap.add_argument("--check", action="store_true", help="ep di hoi GitHub ngay (bo qua TTL)")
    ap.add_argument("--consent", choices=["on", "off"], help="bat/tat viec cho phep kiem tra")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                          # noqa: BLE001
        pass

    if args.consent:
        set_consent(args.consent == "on")
    if args.check:
        refresh(force=True)

    st = status()
    print("repo      : %s" % st["repo"])
    print("ban dang chay: %s" % (st["local"] or "?"))
    if not st["consent"]:
        print("=> CHUA bat kiem tra ban moi (--consent on de bat)")
        return 0
    if st["error"]:
        print("=> lan kiem gan nhat that bai: %s (giu ket qua cu)" % st["error"])
    if st["behind"]:
        print("=> dang THIEU %d ban, moi nhat %s" % (st["behind"], st["latest"]))
        for v in st["versions"]:
            print("   - %-10s %s" % (v["tag"], v.get("summary") or ""))
        print("   cap nhat duoc tai cho: %s (%s)" % (st["can_pull"], st["pull_reason"]))
    elif st["checked_at"]:
        print("=> dang o ban moi nhat")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
