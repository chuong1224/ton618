# -*- coding: utf-8 -*-
"""KB Graph 3D — đèn báo TOÀN VẸN vault ngay trong app (W11 / backlog #14).

Bộ ba câu hỏi về vault, mỗi cái một module:
  `/dashboard` → "agent đã làm gì hôm nay"
  `/insight`   → "vault có đang được dùng đủ khắp không" (insight.py)
  `/integrity` → **"vault có đang GÃY chỗ nào không"** — module này.

Mười check cơ học, chia hai họ:
  CẤU TRÚC (không cần nguồn luật — vault nào cũng chạy được)
    1 link    wikilink `[[Note]]` trỏ tới note/file không tồn tại
    2 embed   nhúng `![[file]]` trỏ tới file không tồn tại
    3 anchor  `[[Note#Heading]]` mà Note không có heading đó
    4 orphan  ảnh/video trong vault không note nào nhắc tới
  CONTRACT (đọc luật từ `vault-rules.json` — thiếu luật nào thì check đó tắt êm)
    5 yaml         frontmatter không parse được bằng YAML thật (`yaml.safe_load`)
    6 frontmatter  note thiếu trường BẮT BUỘC (`policy.mandatory_frontmatter`)
    7 digest       file nhị phân trong `attachments/` chưa "mở nilon"
                   (thiếu tên trong `file_digest` — §VI Q18, `policy.binary_digest_ext`)
    8 tag          note dùng tag ngoài controlled vocabulary (`policy.tag_vocabulary`)
    9 index_tag    file index không đúng 1 tag `index`, hoặc note thường mượn tag
                   `index` (§IV, `policy.index_rule`)
   10 title        `title` ≠ tên file ≠ H1 (§V, `policy.title_rule` — ngoại lệ khai
                   trong `title_rule.exceptions`, KHÔNG đoán)

KHÔNG thay thế gate `verify_vault_integrity.py`: gate vẫn là chuẩn NGHIỆM THU
(nó còn bắt "CN remnant dính chữ" mà module này cố ý không làm). Từ W50, gate
soft-import chính module này làm engine cho 4 check cấu trúc; thiếu/lỗi `.graph3d`
thì gate tự lùi về implementation legacy để vẫn dùng được với vault bất kỳ. Đây
là ĐÈN BÁO: mở app là thấy, không phải chạy tay, không phải đợi audit 08:00.

Quan hệ số liệu với gate — chốt để hai bên không cãi nhau:
  * Tiêu chí BỎ QUA note lấy NGUYÊN của gate: tên file bắt đầu `_`, hoặc frontmatter
    có `gate_ignore: true` (dò trên TRỌN khối frontmatter — bản vá 2026-07-25).
  * 4 check cấu trúc: một implementation duy nhất ở module này. Gate gọi
    `build_integrity()` nên cùng so khớp không phân biệt hoa/thường và cùng tính
    `[[x.png]]` / `![](attachments/x.png)` là reference hợp lệ.
  * Contract: app có 6 check — YAML thật độc lập với nguồn luật + 5 check đọc
    policy; gate chỉ giữ các check nghiệm thu riêng (CN và digest). Đuôi digest
    của cả hai cùng đọc `policy.binary_digest_ext`.
  * Phạm vi: app đo phạm vi graph (bỏ dot-folder + `EXCLUDED_DIRS`); gate chủ động
    cấp cho engine một walk rộng hơn để giữ contract nghiệm thu cũ. Vì đầu vào khác,
    tổng note có thể lệch dù ngữ nghĩa 4 check hoàn toàn giống nhau.

Không chép luật (CLAUDE.md — quy tắc đếm được có nguồn sinh duy nhất): trường
frontmatter bắt buộc, đuôi file phải "mở nilon", tag vocabulary, luật index và
DANH SÁCH NGOẠI LỆ title đều đọc thẳng `vault-rules.json`, còn frontmatter parse
bằng chính `parse_frontmatter` của `vault_rules.py` trong vault (cùng parser mà
audit dùng — hết cảnh mỗi bên một regex). Vault khác/bản public không có hai file
đó: 4 check cấu trúc vẫn chạy, check contract nào thiếu luật thì báo "thiếu nguồn
luật" thay vì đoán bừa — mỗi check tự soi phần luật của mình.

Chạy tay:
  python .graph3d/integrity.py            # exit 0 sạch · 1 có lỗi · 2 thiếu PyYAML
  python .graph3d/integrity.py --json     # đổ nguyên JSON (debug)
  python .graph3d/integrity.py --list 100 # nới trần danh sách mỗi check

Hồ sơ đợt + định nghĩa từng check: note vault "Đèn Báo Toàn Vẹn Vault — KB Graph 3D".
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time

try:
    import yaml as _yaml
    YAML_SAFE_LOAD = _yaml.safe_load
    YAML_IMPORT_ERROR = ""
except Exception as exc:                                  # noqa: BLE001 — dependency tùy chọn
    YAML_SAFE_LOAD = None
    YAML_IMPORT_ERROR = "%s: %s" % (type(exc).__name__, exc)

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_graph_data  # noqa: E402  (EXCLUDED_DIRS + đuôi media: CÙNG luật phạm vi với scanner graph)

# Nguồn chân lý quy tắc đếm được (H1). Vault khác đặt chỗ khác: GRAPH3D_VAULT_RULES.
# Không có env thì dò lần lượt: chỗ của vault này → hai chỗ QUY ƯỚC cho vault bất kỳ.
# (Audit W41: mặc định cũ chỉ có đường dẫn của vault này, nên bản public muốn bật check
#  contract phải sửa code hoặc đặt env — không ai đoán ra.)
def rules_candidates(vault):
    """Nơi có thể đặt `vault-rules.json`, theo thứ tự ưu tiên — TÍNH THEO VAULT ĐANG ĐO.

    Đừng dựng theo hằng module: `--vault <chỗ khác>` (hay bản demo) phải soi nguồn luật
    CỦA CHÍNH vault đó, không phải của vault chứa file này.
    """
    return [os.path.join(vault, "Vault Operation", "Quy Tắc & Vận Hành",
                         "Nguồn Chân Lý Quy Tắc Vault", "attachments"),
            os.path.join(vault, ".graph3d"),
            vault]


def _default_rules_dir(vault=None):
    env = os.environ.get("GRAPH3D_VAULT_RULES")
    if env:
        return env
    cands = rules_candidates(vault or VAULT)
    for d in cands:
        if os.path.isfile(os.path.join(d, "vault-rules.json")):
            return d
    return cands[-1]        # không thấy đâu cả → chỉ về chỗ QUY ƯỚC (gốc vault): thông
                            # báo "không thấy …" phải nêu chỗ người ta nên đặt file, chứ
                            # không phải cây thư mục riêng của vault nào đó (audit W41)


RULES_DIR = _default_rules_dir()

# Nguồn dùng chung cho 4 check structure. Gate W50 import module này; regex legacy
# trong gate chỉ còn phục vụ fallback khi vault không có `.graph3d`.
EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")            # ![[target]]
WIKILINK_RE = re.compile(r"(?<!\!)\[\[([^\]]+)\]\]")   # [[target]] (không phải embed)
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
H1_RE = re.compile(r"^#\s+(.*?)\s*$")                  # riêng H1 — check title=H1 (§V)
FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
GATE_IGNORE_RE = re.compile(r"(?mi)^\s*gate_ignore:\s*true\b")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

MEDIA_EXTS = build_graph_data.IMG_EXTS | build_graph_data.VIDEO_EXTS
ATTACH_DIR = "attachments"
LIST_N = 40          # trần danh sách mỗi check (UI/console hiện đầu danh sách, `total` là số thật)
PARSER_BASIC = "parser tối thiểu của app"   # rules.parser khi vault không có vault_rules.py

CHECKS = [
    ("link", "Wikilink gãy", "structure",
     "[[Note]] trỏ tới note/file không tồn tại trong vault",
     "Sửa tên đích, hoặc tạo note đích. Đích là file thật (.py/.pdf…) thì phải tồn tại đúng tên."),
    ("embed", "Nhúng gãy", "structure",
     "![[file]] nhúng một file không tồn tại",
     "Ảnh/file đính kèm đã đổi tên hay chưa chép vào attachments/ của note."),
    ("anchor", "Anchor lệch heading", "structure",
     "[[Note#Heading]] mà Note không có heading khớp CHÍNH XÁC (kể cả emoji/dấu câu)",
     "Heading đích vừa bị sửa chữ → cập nhật anchor ở note nguồn."),
    ("orphan", "Ảnh/video mồ côi", "structure",
     "file media trong vault không note nào nhắc tới",
     "Nhúng vào note đúng chỗ, hoặc xoá nếu là rác của lần import cũ."),
    ("yaml", "Frontmatter YAML vỡ", "contract",
     "khối frontmatter không parse được bằng YAML thật (`yaml.safe_load`)",
     "Sửa cú pháp YAML tại dòng/cột được báo; dấu nháy nằm trong chuỗi phải escape hoặc đổi kiểu nháy."),
    ("frontmatter", "Thiếu trường frontmatter", "contract",
     "note thiếu trường BẮT BUỘC theo vault-rules.json (policy.mandatory_frontmatter)",
     "Bổ sung trường còn thiếu — aliases/summary là 'bìa' để agent triage, thiếu là bị bỏ sót."),
    ("digest", "File nhị phân chưa mở nilon", "contract",
     "file .xlsx/.pdf… trong attachments/ nhưng tên chưa có trong frontmatter file_digest",
     "Tóm tắt nội dung file vào thân note rồi khai tên file vào file_digest (§VI Q18)."),
    ("tag", "Tag ngoài vocabulary", "contract",
     "note gắn tag không có trong controlled vocabulary của vault-rules.json",
     "Đổi sang tag đúng nghĩa. Cần tag MỚI thì thêm vào vault-rules.json trước (nguồn chân lý), đừng chế tag lẻ."),
    ("index_tag", "Index sai tag", "contract",
     "file index phải có ĐÚNG 1 tag `index`; note thường không được mượn tag `index`",
     "Index là node điều hướng trung lập: bỏ mọi tag content khỏi index, và gỡ tag `index` khỏi note thường (§IV)."),
    ("title", "title ≠ tên file ≠ H1", "contract",
     "title (frontmatter) phải trùng tên file .md và trùng H1 — trừ ngoại lệ khai trong vault-rules.json",
     "Sửa cho khớp. Lệch CÓ CHỦ Ý (rút gọn path) thì khai vào policy.title_rule.exceptions, đừng để đèn tự đoán."),
]

CRITICAL_CHECKS = {"yaml"}       # tắt check này thì không được phép báo "sạch"
_YAML_DEFAULT = object()


# --------------------------------------------------------------------- tiện ích

def _rel(path, vault=VAULT):
    try:
        return os.path.relpath(path, vault).replace("\\", "/")
    except ValueError:                                   # ổ đĩa khác
        return path.replace("\\", "/")


def frontmatter_block(text):
    """NGUYÊN khối YAML đầu file (giữa 2 dòng `---`), '' nếu không có.

    Quét TRỌN khối chứ không cắt `text[:500]` như gate bản cũ — note có aliases/summary
    dài đẩy `gate_ignore: true` ra ngoài cửa sổ 500 ký tự từng gây 39 báo oan (vá 2026-07-25).
    """
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def is_ignored(stem, text):
    """Note được MIỄN báo lỗi (vẫn dùng để phân giải link/ảnh) — tiêu chí của gate."""
    return stem.startswith("_") or GATE_IGNORE_RE.search(frontmatter_block(text)) is not None


def split_target(t):
    """'Note#Heading|alias' → ('Note', 'Heading'); mirror split_target của gate.

    `\\|` là cách Obsidian viết dấu ngăn alias khi wikilink nằm TRONG bảng markdown
    (`[[Vector Databases\\|vector DB]]`) — không gỡ escape thì đích thành `Vector
    Databases\\`, trên Windows `basename` nuốt luôn phần trước dấu `\\` và đèn báo
    "wikilink gãy" cho một link hoàn toàn hợp lệ (audit W41 bắt được trên vault demo
    của bản public). Gate `verify_vault_integrity.py` đã vá cùng lúc, cùng luật.
    """
    t = t.replace("\\|", "|").split("|", 1)[0].strip()
    if "#" in t:
        base, anchor = t.split("#", 1)
        return base.strip(), anchor.strip()
    return t, None


def strip_markdown_code(text):
    """Che code fence + inline code bằng khoảng trắng, giữ nguyên newline/độ dài.

    Bốn check cấu trúc cần nhìn Markdown *được render*, không được coi cú pháp minh
    hoạ trong code là wikilink/nhúng/heading thật. Giữ nguyên độ dài và newline để
    số dòng trong báo cáo không trôi. Fence hỗ trợ cả backtick lẫn tilde theo luật
    CommonMark cơ bản (tối đa 3 space đầu dòng; fence đóng cùng ký tự, dài >= mở).
    Inline code hỗ trợ delimiter nhiều backtick; delimiter không có cặp được giữ như
    văn xuôi thay vì nuốt phần còn lại của note.
    """
    out = []
    fence_char = None
    fence_len = 0

    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        ending = raw[len(body):]

        if fence_char is not None:
            stripped = body.lstrip(" ")
            indent = len(body) - len(stripped)
            run = len(stripped) - len(stripped.lstrip(fence_char))
            closes = indent <= 3 and run >= fence_len \
                and not stripped[run:].strip(" \t")
            out.append(" " * len(body) + ending)
            if closes:
                fence_char = None
                fence_len = 0
            continue

        fm = FENCE_OPEN_RE.match(body)
        if fm:
            fence = fm.group(1)
            info = fm.group(2)
            # Backtick info string không được chứa backtick; nếu có thì đây là văn
            # xuôi, không phải fence mở. Tilde fence không có hạn chế tương ứng.
            if fence[0] == "~" or "`" not in info:
                fence_char = fence[0]
                fence_len = len(fence)
                out.append(" " * len(body) + ending)
                continue

        chars = list(body)
        i = 0
        while i < len(body):
            if body[i] != "`":
                i += 1
                continue
            run_end = i + 1
            while run_end < len(body) and body[run_end] == "`":
                run_end += 1
            width = run_end - i
            j = run_end
            close_end = None
            while j < len(body):
                j = body.find("`", j)
                if j < 0:
                    break
                end = j + 1
                while end < len(body) and body[end] == "`":
                    end += 1
                if end - j == width:
                    close_end = end
                    break
                j = end
            if close_end is None:
                i = run_end
                continue
            chars[i:close_end] = " " * (close_end - i)
            i = close_end
        out.append("".join(chars) + ending)

    return "".join(out)


FM_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")


def _parse_frontmatter_basic(text):
    """Parser frontmatter TỐI THIỂU — chỉ dùng khi vault KHÔNG có `vault_rules.py`.

    Cùng phạm vi với parser của nguồn chân lý: field một dòng + list (inline `[a, b]`
    hoặc block `- a`). Không phải PyYAML, cố ý: app zero-dep. Vault nào có nguồn chân lý
    thì KHÔNG chạy hàm này — luật "một parser dùng chung" vẫn giữ nguyên ở đó.
    """
    block = frontmatter_block(text)
    if not block:
        return {}
    data, key = {}, None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if key:
                data.setdefault(key, [])
                if isinstance(data[key], list):
                    data[key].append(line.split("- ", 1)[1].strip().strip("\"'"))
            continue
        m = FM_KEY_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        elif val == "":
            data[key] = []
        else:
            data[key] = val.strip("\"'")
    return data


def _empty(val):
    """Trường frontmatter coi như THIẾU: vắng mặt, rỗng, hoặc list toàn chuỗi rỗng."""
    if val is None:
        return True
    if isinstance(val, (list, tuple, set)):
        return not [x for x in val if str(x).strip()]
    return not str(val).strip()


# ------------------------------------------------------------------------ I/O

def vault_signature(vault):
    """(rel, mtime_ns, size) của mọi file trong phạm vi — khoá cache + danh sách để đọc.

    Phạm vi = ĐÚNG phạm vi scanner graph (dot-folder + EXCLUDED_DIRS bị loại) nên
    không bao giờ có chuyện đèn báo lỗi ở file mà graph/Reader không biết tới.
    """
    out = []
    for root, dirs, fnames in os.walk(vault):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in build_graph_data.EXCLUDED_DIRS]
        for fn in fnames:
            full = os.path.join(root, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append((_rel(full, vault), st.st_mtime_ns, st.st_size))
    out.sort()
    return tuple(out)


def scan_vault(vault, sig=None):
    """Đọc vault → dữ liệu thô cho build_integrity (I/O tách hẳn khỏi phép tính).

    `notes[rel]` = {stem, text, headings, h1, ignored}; `files[rel]` = đuôi (mọi file
    không phải .md — kể cả file rác: gate cũng cho chúng vào bảng basename nên
    `[[attachments/x.py]]` không bị báo gãy oan).
    """
    sig = vault_signature(vault) if sig is None else sig
    notes, files = {}, {}
    for rel, _mt, _sz in sig:
        if not rel.lower().endswith(".md"):
            files[rel] = os.path.splitext(rel)[1].lower().lstrip(".")
            continue
        try:
            with open(os.path.join(vault, rel), "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        heads, h1 = set(), None
        for line in strip_markdown_code(text).splitlines():
            hm = HEADING_RE.match(line)
            if hm:
                heads.add(hm.group(1).strip().lower())
                if h1 is None and H1_RE.match(line):
                    h1 = hm.group(1).strip()      # H1 ĐẦU TIÊN — cái đóng vai tiêu đề note
        notes[rel] = {"stem": stem, "text": text, "headings": heads, "h1": h1,
                      "ignored": is_ignored(stem, text)}
    return {"vault": vault, "notes": notes, "files": files}


def load_rules(rules_dir=None):
    """Nạp nguồn chân lý: policy trong `vault-rules.json` + parser của `vault_rules.py`.

    KHÔNG chép luật vào module này — vault không có nguồn luật thì trả rules rỗng
    kèm lý do, mọi check contract tự tắt (UI hiện "thiếu nguồn luật", không đoán bừa).
    Thiếu LẺ một khoá policy (vault khác chưa khai `index_rule`/`title_rule`) thì chỉ
    check đó tắt, các check còn lại vẫn chạy.
    Đọc mỗi lần gọi (file nhỏ) — sửa vault-rules.json là lần đo sau ăn ngay.
    """
    rules_dir = rules_dir or _default_rules_dir()
    js = os.path.join(rules_dir, "vault-rules.json")
    py = os.path.join(rules_dir, "vault_rules.py")
    info = {"loaded": False, "path": _rel(js), "reason": ""}
    if not os.path.isfile(js):
        info["reason"] = "không thấy vault-rules.json"
        return {}, info
    try:
        with open(js, encoding="utf-8") as f:
            policy = (json.load(f) or {}).get("policy", {})
    except (OSError, ValueError) as exc:
        info["reason"] = "vault-rules.json đọc không được: %s" % exc
        return {}, info
    # Parser frontmatter: ƯU TIÊN `vault_rules.py` của vault (cùng parser mà audit dùng
    # — hết cảnh mỗi bên một regex). Vault không có file đó (bản public clone ra ngoài)
    # thì rơi về parser tối thiểu ngay trong module: audit W41 phát hiện 5 đèn contract
    # KHÔNG THỂ bật ở bản public vì đòi một script chỉ tồn tại trong vault này.
    mod, parse_fm, engine = None, _parse_frontmatter_basic, PARSER_BASIC
    if os.path.isfile(py):
        try:
            spec = importlib.util.spec_from_file_location("kb_vault_rules", py)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            parse_fm = mod.parse_frontmatter
            engine = "vault_rules.py"
        except Exception as exc:                          # noqa: BLE001
            info["reason"] = "vault_rules.py nạp lỗi (%s) — dùng parser tối thiểu" % exc
            mod = None
    info["parser"] = engine
    # Vocabulary nằm dạng {nhóm: [{tag, meaning}…]} — dàn phẳng đúng như vault_rules.py.
    vocab = sorted({str(t.get("tag", "")).strip()
                    for grp in (policy.get("tag_vocabulary") or {}).values()
                    for t in (grp or []) if str(t.get("tag", "")).strip()})
    title_rule = dict(policy.get("title_rule") or {})
    info.update(loaded=True,
                mandatory=list(policy.get("mandatory_frontmatter") or []),
                digest_ext=sorted(e.lower() for e in (policy.get("binary_digest_ext") or [])),
                vocab_n=len(vocab),
                exceptions_n=len(title_rule.get("exceptions") or []))
    return {"mandatory_frontmatter": info["mandatory"],
            "binary_digest_ext": info["digest_ext"],
            "tag_vocabulary": vocab,
            "index_rule": dict(policy.get("index_rule") or {}),
            "title_rule": title_rule,
            # phép so "tên này có phải tên file index không" dùng CHUNG với bên đếm
            "is_index_name": getattr(mod, "is_index_name", None) if mod else None,
            "parse_frontmatter": parse_fm}, info


# ------------------------------------------------------------------ phép tính

def build_integrity(scan, rules=None, rules_info=None, list_n=LIST_N,
                    yaml_loader=_YAML_DEFAULT, yaml_reason=""):
    """Ảnh chụp toàn vẹn vault — HÀM THUẦN (không đọc đĩa; chỉ `generated` lấy giờ đo).

    scan       — kết quả scan_vault()
    rules      — {} hoặc {mandatory_frontmatter, binary_digest_ext, tag_vocabulary,
                 index_rule, title_rule, parse_frontmatter}
    rules_info — mô tả nguồn luật để UI giải thích khi check contract tắt
    yaml_loader — mặc định `yaml.safe_load`; truyền None trong test để mô phỏng thiếu
                  PyYAML. Thiếu validator là trạng thái DEGRADED, không được báo sạch.
    """
    now = time.time()
    notes, files = scan["notes"], scan["files"]
    rules = rules or {}
    mandatory = list(rules.get("mandatory_frontmatter") or [])
    digest_ext = {("." + e.lstrip(".")).lower() for e in (rules.get("binary_digest_ext") or [])}
    vocab = {str(t).strip() for t in (rules.get("tag_vocabulary") or []) if str(t).strip()}
    index_rule = dict(rules.get("index_rule") or {})
    title_rule = dict(rules.get("title_rule") or {})
    parse_fm = rules.get("parse_frontmatter")
    if yaml_loader is _YAML_DEFAULT:
        yaml_loader = YAML_SAFE_LOAD
        yaml_reason = YAML_IMPORT_ERROR

    idx_tag = str(index_rule.get("tag") or "").strip()
    idx_prefix = str(index_rule.get("name_prefix") or "").strip().lower()
    idx_type = str(index_rule.get("type_field") or "").strip().lower()
    idx_only = bool(index_rule.get("only_tag"))
    idx_name_fn = rules.get("is_index_name")
    require_h1 = bool(title_rule.get("require_h1"))
    # Ngoại lệ title khoá theo TÊN FILE (không đuôi, không phân biệt hoa/thường) — note
    # hay bị dời folder, tên file thì bền; đây cũng là cách §V và gate gọi tên chúng.
    excs = {str(e.get("file", "")).strip().lower(): e
            for e in (title_rule.get("exceptions") or []) if str(e.get("file", "")).strip()}

    # Mỗi check contract tự soi phần luật CỦA MÌNH: vault khai thiếu `index_rule` thì chỉ
    # đèn index tắt, đừng kéo cả họ contract tắt theo (bản public/vault khác dùng dần).
    avail = {"link": True, "embed": True, "anchor": True, "orphan": True,
             "yaml": bool(yaml_loader),
             "frontmatter": bool(parse_fm and mandatory),
             "digest": bool(parse_fm and digest_ext),
             "tag": bool(parse_fm and vocab),
             "index_tag": bool(parse_fm and idx_tag),
             "title": bool(parse_fm and title_rule)}
    need_fm = any(avail[k] for k in ("frontmatter", "tag", "index_tag", "title"))

    # Bảng tra: stem note (thường hoá) và basename MỌI file — gate so khớp theo
    # basename chứ không theo path, giữ nguyên để hai bên cùng một phép so.
    note_stems, base_files, headings = {}, {}, {}
    for rel, n in notes.items():
        low = n["stem"].lower()
        note_stems.setdefault(low, []).append(rel)
        headings.setdefault(low, set()).update(n["headings"])
        base_files.setdefault(os.path.basename(rel).lower(), []).append(rel)
    for rel in files:
        base_files.setdefault(os.path.basename(rel).lower(), []).append(rel)

    hits = {cid: [] for cid, _l, _f, _d, _h in CHECKS}
    referenced = set()          # basename mọi đích link — dùng tìm media mồ côi
    yaml_invalid = set()        # note YAML vỡ: không chạy tiếp parser dòng khoan dung
    checked = ignored = 0

    for rel in sorted(notes):
        n = notes[rel]
        active = not n["ignored"]
        checked += 1 if active else 0
        ignored += 0 if active else 1

        if active and avail["yaml"]:
            block = frontmatter_block(n["text"])
            if block:
                try:
                    parsed_yaml = yaml_loader(block)
                    if parsed_yaml is not None and not isinstance(parsed_yaml, dict):
                        yaml_invalid.add(rel)
                        hits["yaml"].append(
                            {"file": rel, "line": 2, "column": 1, "target": "",
                             "detail": "frontmatter phải là mapping `key: value`, đang là %s"
                                       % type(parsed_yaml).__name__})
                except Exception as exc:                  # noqa: BLE001 — lỗi parser là dữ liệu cần báo
                    yaml_invalid.add(rel)
                    mark = getattr(exc, "problem_mark", None)
                    line = int(getattr(mark, "line", 0)) + 2
                    col = int(getattr(mark, "column", 0)) + 1
                    problem = str(getattr(exc, "problem", "") or str(exc)).splitlines()[0]
                    hits["yaml"].append(
                        {"file": rel, "line": line, "column": col, "target": "",
                         "detail": "YAML không hợp lệ tại dòng %d, cột %d: %s"
                                   % (line, col, problem)})

        # W73: cấu trúc trong code chỉ là ví dụ. Quét trên bản đã che code để cả
        # wikilink/nhúng/anchor lẫn phép đếm reference media cùng một ngữ nghĩa.
        structure_text = strip_markdown_code(n["text"])
        for i, line in enumerate(structure_text.splitlines(), 1):
            for m in EMBED_RE.finditer(line):
                base, _anchor = split_target(m.group(1))
                b = os.path.basename(base).lower()
                if not b:
                    continue
                referenced.add(b)
                if active and b not in base_files and b not in note_stems:
                    hits["embed"].append({"file": rel, "line": i, "target": m.group(1),
                                          "detail": "không có file tên %s" % os.path.basename(base)})
            for m in WIKILINK_RE.finditer(line):
                base, anchor = split_target(m.group(1))
                if not base:
                    continue
                b = os.path.basename(base).lower()
                # Nới hơn gate CÓ CHỦ Ý: ảnh được nhắc bằng [[x.png]] vẫn tính là có
                # người dùng → không báo mồ côi oan (gate chỉ đếm dạng ![[…]]).
                referenced.add(b)
                if not active:
                    continue
                stem = b[:-3] if b.endswith(".md") else b
                if stem in note_stems:
                    if anchor and not anchor.startswith("^") \
                            and anchor.lower() not in headings.get(stem, set()):
                        hits["anchor"].append({"file": rel, "line": i, "target": m.group(1),
                                               "detail": "note đích không có heading “%s”" % anchor})
                elif b not in base_files:
                    hits["link"].append({"file": rel, "line": i, "target": m.group(1),
                                         "detail": "không có note/file tên %s" % os.path.basename(base)})
            for m in build_graph_data.MDLINK_RE.finditer(line):
                tgt = m.group(1).strip()
                tgt = re.sub(r'\s+"[^"]*"$', "", tgt).strip("<>").strip()
                if not tgt or tgt.startswith("#") or build_graph_data.SCHEME_RE.match(tgt):
                    continue        # anchor nội bộ / URL ngoài
                referenced.add(os.path.basename(tgt.split("#")[0]).lower())

        if active and need_fm and rel not in yaml_invalid:
            fm = parse_fm(n["text"])              # parse MỘT lần cho cả 4 check contract
            tags = fm.get("tags") or []
            tags = [tags] if isinstance(tags, str) else list(tags)
            tags = [str(t).strip() for t in tags if str(t).strip()]

            if avail["frontmatter"]:
                miss = [k for k in mandatory if _empty(fm.get(k))]
                if miss:
                    hits["frontmatter"].append({"file": rel, "line": 1, "target": "",
                                                "missing": miss,
                                                "detail": "thiếu " + ", ".join(miss)})
            if avail["tag"]:
                unknown = [t for t in tags if t not in vocab]
                if unknown:
                    hits["tag"].append({"file": rel, "line": 1, "target": "", "missing": unknown,
                                        "detail": "tag ngoài vocabulary: " + ", ".join(unknown)})
            if avail["index_tag"]:
                is_index = is_index_note(n["stem"], fm.get("type"), idx_prefix, idx_type,
                                         idx_name_fn)
                why = ""
                if is_index and idx_only and tags != [idx_tag]:
                    extra = [t for t in tags if t != idx_tag]
                    why = ("index chỉ được đúng 1 tag `%s`" % idx_tag) + \
                        (" — thừa: " + ", ".join(extra) if extra else " — đang thiếu tag đó")
                elif is_index and not idx_only and idx_tag not in tags:
                    why = "file index thiếu tag `%s`" % idx_tag
                elif not is_index and idx_tag in tags:
                    why = "note thường mượn tag `%s` (chỉ dành cho file index)" % idx_tag
                if why:
                    hits["index_tag"].append({"file": rel, "line": 1, "target": "", "detail": why})
            if avail["title"]:
                probs = _title_problems(n, str(fm.get("title") or "").strip(),
                                        excs.get(n["stem"].lower()), require_h1)
                if probs:
                    hits["title"].append({"file": rel, "line": 1, "target": "",
                                          "detail": " · ".join(probs)})

    # --- media mồ côi: file ảnh/video không basename nào nhắc tới ---
    for rel, ext in sorted(files.items()):
        if ext in MEDIA_EXTS and os.path.basename(rel).lower() not in referenced:
            hits["orphan"].append({"file": rel, "line": None, "target": "",
                                   "detail": "không note nào nhắc tới file này"})

    # --- "mở nilon": file nhị phân trong attachments/ phải có tên trong file_digest ---
    if parse_fm and digest_ext:
        notes_by_folder = {}
        for rel in notes:
            notes_by_folder.setdefault(os.path.dirname(rel), []).append(rel)
        binary_by_folder = {}
        for rel in files:
            d = os.path.dirname(rel)
            if os.path.basename(d).lower() != ATTACH_DIR:
                continue
            if os.path.splitext(rel)[1].lower() in digest_ext:
                binary_by_folder.setdefault(os.path.dirname(d), []).append(rel)
        for folder, bins in sorted(binary_by_folder.items()):
            owner = _owner_note(folder, notes_by_folder, notes)
            if owner is None or notes[owner]["ignored"] or owner in yaml_invalid:
                continue      # folder không xác định được chủ (không phải folder-per-note)
            declared = parse_fm(notes[owner]["text"]).get("file_digest")
            declared = [str(x).strip().lower() for x in (declared or [])] \
                if isinstance(declared, (list, tuple)) else [str(declared or "").strip().lower()]
            miss = [os.path.basename(b) for b in sorted(bins)
                    if os.path.basename(b).lower() not in declared]
            if miss:
                hits["digest"].append({"file": owner, "line": 1, "target": "",
                                       "missing": miss,
                                       "detail": "chưa khai trong file_digest: " + ", ".join(miss)})

    # --- ngoại lệ title khai cho note không còn tồn tại: danh sách TỰ DỌN ---
    # Đúng lớp lỗi làm luật này mãi không máy-đọc-được: danh sách ngoại lệ nằm ở văn xuôi
    # rồi rữa dần theo từng lần đổi tên note. Khai trong nguồn chân lý thì đèn coi được.
    if avail["title"] and excs:
        stems = {n["stem"].lower() for n in notes.values()}
        for key in sorted(excs):
            if key not in stems:
                hits["title"].append(
                    {"file": (rules_info or {}).get("path", ""), "line": None, "target": "",
                     "detail": "ngoại lệ title khai cho note không còn tồn tại: %s"
                               % excs[key].get("file", key)})

    unavailable = {
        "yaml": "không nạp được PyYAML — check cú pháp YAML thật đã TẮT%s"
                % ((": " + yaml_reason) if yaml_reason else ""),
        "frontmatter": "thiếu parser frontmatter hoặc policy.mandatory_frontmatter",
        "digest": "thiếu parser frontmatter hoặc policy.binary_digest_ext",
        "tag": "thiếu parser frontmatter hoặc policy.tag_vocabulary",
        "index_tag": "thiếu parser frontmatter hoặc policy.index_rule.tag",
        "title": "thiếu parser frontmatter hoặc policy.title_rule",
    }
    checks = []
    for cid, label, family, desc, fix in CHECKS:
        ok = avail[cid]
        checks.append({"id": cid, "label": label, "family": family, "desc": desc,
                       "fix": fix, "available": ok, "critical": cid in CRITICAL_CHECKS,
                       "reason_code": "" if ok else
                                      ("missing_pyyaml" if cid == "yaml" else "missing_rule"),
                       "reason": "" if ok else unavailable.get(cid, "check không khả dụng"),
                       "total": len(hits[cid]) if ok else 0,
                       "list": hits[cid][:list_n] if ok else []})
    problems = sum(c["total"] for c in checks)
    degraded = any(c["critical"] and not c["available"] for c in checks)
    warnings = [c["reason"] for c in checks if c["critical"] and not c["available"]]
    media = sum(1 for ext in files.values() if ext in MEDIA_EXTS)
    return {
        "generated": now,
        "ok": problems == 0 and not degraded,
        "degraded": degraded,
        "warnings": warnings,
        "problems": problems,
        "vault": {"notes": len(notes), "checked": checked, "ignored": ignored,
                  "files": len(files), "media": media},
        "rules": rules_info or {"loaded": False, "reason": "chưa nạp nguồn luật"},
        "checks": checks,
        "limit": list_n,
    }


def _name_is_index(stem, prefix):
    """Dự phòng khi vault không có `vault_rules.py` (bản public) — CÙNG luật token."""
    s, p = str(stem).lower(), str(prefix or "").lower()
    if not p:
        return False
    return s == p or (s.startswith(p) and not s[len(p):len(p) + 1].isalnum())


def is_index_note(stem, fm_type, prefix, type_field, name_fn=None):
    """File index = frontmatter `type: <type_field>`, HOẶC tên khớp `prefix` dạng TOKEN.

    `Index` và `Index - Work` là index; `Indexing Chiến Lược` thì KHÔNG — prefix trần
    (`startswith`) khớp cả từ dài hơn và sẽ đòi note đó bỏ hết tag content: đúng kiểu
    báo oan làm mất niềm tin vào đèn (audit W41 bắt được khi vault chưa có ca nào).

    Phép so tên lấy THẲNG `is_index_name` của `vault_rules.py` khi có (`name_fn`) — cùng
    hàm mà nguồn chân lý dùng để ĐẾM index, nên hai bên không thể lệch định nghĩa.
    """
    if type_field and str(fm_type or "").strip().lower() == type_field:
        return True
    return (name_fn or _name_is_index)(stem, prefix)


def _title_problems(note, title, exc, require_h1):
    """Lệch của bộ ba `title` = tên file = H1 trên MỘT note → danh sách lý do (rỗng = sạch).

    `exc` là mục ngoại lệ đã khai (hoặc None). Ngoại lệ KHÔNG phải "miễn kiểm": nó pin
    luôn giá trị được phép, nên note trong danh sách vẫn bị bắt nếu title trôi tiếp.
    Thiếu hẳn `title` thì im — check frontmatter đã báo trường bắt buộc, đừng báo hai lần.
    Ngoại lệ khai HỎNG (thiếu `title`) thì nói thẳng ra rồi kiểm theo luật thường — trước
    đây nó lặng lẽ so với chuỗi rỗng, đẻ ra thông báo `≠ ngoại lệ đã khai ""` vô nghĩa
    và che mất chuyện nguồn luật đang sai (audit W41).
    """
    if not title:
        return []
    probs = []
    if exc and not str(exc.get("title") or "").strip():
        probs.append("ngoại lệ trong vault-rules.json khai thiếu `title` → tạm kiểm theo luật thường")
        exc = None
    want_title = str(exc.get("title") or "").strip() if exc else note["stem"]
    want_h1 = (str(exc.get("h1") or exc.get("title") or "").strip()) if exc else title
    if title != want_title:
        probs.append("title “%s” ≠ %s “%s”"
                     % (title, "ngoại lệ đã khai" if exc else "tên file", want_title))
    h1 = note.get("h1")
    if h1 is None:
        if require_h1:
            probs.append("note không có heading H1")
    elif h1 != want_h1:
        probs.append("H1 “%s” ≠ %s “%s”"
                     % (h1, "H1 đã khai" if exc and exc.get("h1") else "title", want_h1))
    return probs


def _owner_note(folder, notes_by_folder, notes):
    """Note "chủ" của một folder-per-note: note trùng tên folder, hoặc note DUY NHẤT.

    Folder có nhiều note mà không note nào trùng tên folder → trả None: thà bỏ qua
    còn hơn quy trách nhiệm file_digest cho nhầm note (báo oan là mất niềm tin vào đèn).
    """
    cands = notes_by_folder.get(folder, [])
    if not cands:
        return None
    base = os.path.basename(folder).lower()
    for rel in cands:
        if notes[rel]["stem"].lower() == base:
            return rel
    return cands[0] if len(cands) == 1 else None


# --------------------------------------------------------------------- cửa vào

_cache = {"key": None, "data": None}


def collect(vault=VAULT, rules_dir=None, list_n=LIST_N, use_cache=True):
    """Đo toàn vẹn vault (I/O + phép tính). Cache theo (chữ ký file, mtime nguồn luật)
    — mở section/overlay liên tiếp không quét lại; sửa note là lần sau đo lại ngay."""
    sig = vault_signature(vault)
    # Dò nguồn luật theo CHÍNH vault đang đo (không phải vault chứa module) — cũng là
    # lý do dò LẠI mỗi lần gọi: thêm vault-rules.json xong là lần đo sau ăn ngay,
    # không phải restart server.
    rules_dir = rules_dir or _default_rules_dir(vault)
    rsig = tuple(sorted(
        (os.path.basename(p), os.path.getmtime(p))
        for p in (os.path.join(rules_dir, "vault-rules.json"),
                  os.path.join(rules_dir, "vault_rules.py"))
        if os.path.isfile(p)))
    key = (vault, sig, rsig, list_n)
    if use_cache and _cache["key"] == key:
        return _cache["data"]
    rules, info = load_rules(rules_dir)
    data = build_integrity(scan_vault(vault, sig), rules=rules, rules_info=info,
                           list_n=list_n)
    _cache.update(key=key, data=data)
    return data


def print_summary(rep, out=print):
    v = rep["vault"]
    out("== TOÀN VẸN VAULT — %s ==" % time.strftime("%Y-%m-%d %H:%M",
                                                    time.localtime(rep["generated"])))
    out("Phạm vi: %d note (%d được kiểm, %d miễn theo gate_ignore/_) · %d file · %d media"
        % (v["notes"], v["checked"], v["ignored"], v["files"], v["media"]))
    if not rep["rules"].get("loaded"):
        out("⚠ check contract TẮT — %s (%s)"
            % (rep["rules"].get("reason", "?"), rep["rules"].get("path", "?")))
    for warning in rep.get("warnings", []):
        out("⚠ %s" % warning)
    for c in rep["checks"]:
        if not c["available"]:
            out("  —  %-28s (tắt: %s)" % (c["label"], c.get("reason", "không khả dụng")))
            continue
        out("  %s %-28s %d" % ("🔴" if c["total"] else "🟢", c["label"], c["total"]))
        for it in c["list"][:8]:
            if it.get("line"):
                loc = "%s:%s" % (it["file"], it["line"])
                if it.get("column"):
                    loc += ":%s" % it["column"]
            else:
                loc = it["file"]
            out("      %s — %s" % (loc, it["detail"]))
        if c["total"] > 8:
            out("      … còn %d mục" % (c["total"] - 8))
    out("TỔNG: %d vấn đề" % rep["problems"])
    if rep.get("degraded"):
        out("KẾT QUẢ: KHÔNG ĐỦ PHÉP ĐO — không được coi là sạch")


def result_exit_code(rep):
    """0=sạch thật · 1=có lỗi dữ liệu · 2=thiếu checker bắt buộc (không xanh giả)."""
    if rep.get("degraded"):
        return 2
    return 1 if rep["problems"] else 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        pass                        # console cp1252 không in được tiếng Việt
    ap = argparse.ArgumentParser(description="Kiểm tra toàn vẹn vault (KB Graph 3D)")
    ap.add_argument("--vault", default=VAULT, help="gốc vault (mặc định: cha của .graph3d)")
    ap.add_argument("--list", type=int, default=LIST_N, dest="list_n",
                    help="trần số mục liệt kê mỗi check (mặc định %d)" % LIST_N)
    ap.add_argument("--json", action="store_true", help="đổ nguyên JSON thay vì tóm tắt")
    args = ap.parse_args(argv)
    rep = collect(vault=os.path.abspath(args.vault), list_n=args.list_n, use_cache=False)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print_summary(rep)
    return result_exit_code(rep)


if __name__ == "__main__":
    sys.exit(main())
