# -*- coding: utf-8 -*-
"""Test den bao toan ven vault (W11 + W41) — integrity.scan_vault + build_integrity + collect:

  - 4 check cau truc: wikilink gay, nhung gay, anchor lech heading, anh mo coi
  - 6 check contract: YAML frontmatter vo (W149), thieu truong bat buoc, file nhi phan
    chua "mo nilon", tag ngoai vocabulary, index sai tag, title != ten file != H1 (W41)
  - ngoai le title (policy.title_rule.exceptions) PIN gia tri: note trong danh sach van
    bi bat neu title troi tiep; ngoai le khai cho note khong con ton tai cung bi bao
  - thieu LE mot khoa policy -> chi check do tat, cac check contract khac van chay
  - tieu chi BO QUA note lay cua gate: ten file bat dau '_' HOAC gate_ignore: true
    (gate_ignore nam CUOI khoi frontmatter dai van phai bat duoc — bug 39 bao oan 25/07)
  - app NOI hon gate co chu y: hoa/thuong khong phan biet; anh duoc nhac bang
    [[x.png]] hay ![](attachments/x.png) van tinh la co nguoi dung
  - W73: wikilink/nhung/heading trong inline code va code fence chi la vi du;
    scanner phai bo qua, dong thoi tiep tuc quet dung van xuoi sau fence
  - pham vi = pham vi scanner graph: node_modules/.trash/dot-folder khong bi quet
  - thieu nguon luat (vault-rules.json) -> 5 check policy TAT em, YAML + cau truc van chay
  - parse frontmatter dung parser cua vault_rules.py: tags dang YAML list nhieu dong
    KHONG bi bao thieu (bug regex chi bat 'tags: [...]' inline, audit 26/07)
  - cache theo chu ky mtime: goi 2 lan tra CUNG object, sua note thi do lai
"""
import json, os, shutil, sys
sys.dont_write_bytecode = True   # khong sinh __pycache__ trong vault
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252
except Exception:
    pass

from _scratch import SCRATCH, G3D, VAULT
os.environ.setdefault("GRAPH3D_ACTIVITY_FILE", os.path.join(SCRATCH, "act_integrity.jsonl"))
sys.path.insert(0, G3D)

import integrity as ITG

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)


VAULT_DIR = os.path.join(SCRATCH, "itg-vault")
RULES_DIR = os.path.join(SCRATCH, "itg-rules")
EMPTY_RULES = os.path.join(SCRATCH, "itg-rules-empty")
PARTIAL_RULES = os.path.join(SCRATCH, "itg-rules-partial")   # co frontmatter, thieu index/title
NOPY_RULES = os.path.join(SCRATCH, "itg-rules-nopy")         # co json, KHONG co vault_rules.py

# Parser frontmatter dung chung: lay ban THAT trong vault neu co (test luon ca tuong
# thich voi nguon chan ly), khong co (ban public clone ra ngoai vault) thi stub toi thieu.
STUB_RULES_PY = '''# -*- coding: utf-8 -*-
import re
def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\\n---", 3)
    if end == -1:
        return {}
    data, key = {}, None
    for raw in text[3:end].splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if key:
                data.setdefault(key, [])
                if isinstance(data[key], list):
                    data[key].append(line.split("- ", 1)[1].strip().strip("\\"'"))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            data[key] = [v.strip().strip("\\"'") for v in val[1:-1].split(",") if v.strip()]
        elif val == "":
            data[key] = []
        else:
            data[key] = val.strip("\\"'")
    return data
'''

RULES_JSON = {
    "policy": {
        "mandatory_frontmatter": ["title", "aliases", "summary", "tags"],
        "binary_digest_ext": [".xlsx", ".pdf"],
        "tag_vocabulary": {
            "jxm": [{"tag": "JXM"}, {"tag": "hoai-niem"}],
            "area": [{"tag": "index"}],
        },
        "index_rule": {"name_prefix": "Index", "type_field": "index",
                       "tag": "index", "only_tag": True},
        "title_rule": {
            "require_h1": True,
            "exceptions": [
                {"file": "Ngoai Le", "title": "Ngoai Le — Ban Day Du"},
                {"file": "Ngoai Le Troi", "title": "Ngoai Le Troi — Ban Khai"},
                {"file": "Ba Chan", "title": "Ba Chan — Title Khai", "h1": "H1 Khai Rieng"},
                {"file": "Khong Con Nua", "title": "Khong Con Nua — Note da bi xoa"},
                {"file": "Khai Hong", "why": "ngoai le khai THIEU title — audit W41"},
            ],
        },
    }
}
# Bo luat "mot nua": du de chay frontmatter/digest/tag nhung KHONG khai index_rule/title_rule
PARTIAL_JSON = {"policy": {k: v for k, v in RULES_JSON["policy"].items()
                           if k not in ("index_rule", "title_rule")}}


def w(rel, text):
    p = os.path.join(VAULT_DIR, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


def blob(rel, data=b"xx"):
    p = os.path.join(VAULT_DIR, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def fm(title, aliases=True, summary=True, tags="[JXM]", extra="", h1=None):
    """Note test. `h1=None` → H1 trung title (ca sach); chuoi khac → H1 lech; False → khong H1."""
    L = ["---", "title: " + title]
    if aliases:
        L.append('aliases: ["%s"]' % title[:3])
    if summary:
        L.append('summary: "note test %s"' % title)
    if tags is not None:
        L.append("tags: " + tags if tags.startswith("[") else "tags:\n" + tags)
    if extra:
        L.append(extra)
    L += ["---", ""]
    if h1 is not False:
        L += ["# " + (title if h1 is None else h1), ""]
    return "\n".join(L)


def build_fake_vault():
    shutil.rmtree(VAULT_DIR, ignore_errors=True)
    os.makedirs(EMPTY_RULES, exist_ok=True)
    shutil.rmtree(RULES_DIR, ignore_errors=True)
    os.makedirs(RULES_DIR)
    with open(os.path.join(RULES_DIR, "vault-rules.json"), "w", encoding="utf-8") as f:
        json.dump(RULES_JSON, f)
    real_py = os.path.join(ITG.RULES_DIR, "vault_rules.py")
    if os.path.isfile(real_py):
        shutil.copyfile(real_py, os.path.join(RULES_DIR, "vault_rules.py"))
    else:
        print("[SKIP] dung parser THAT — khong thay vault_rules.py, dung stub")
        with open(os.path.join(RULES_DIR, "vault_rules.py"), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(STUB_RULES_PY)
    shutil.rmtree(PARTIAL_RULES, ignore_errors=True)
    os.makedirs(PARTIAL_RULES)
    with open(os.path.join(PARTIAL_RULES, "vault-rules.json"), "w", encoding="utf-8") as f:
        json.dump(PARTIAL_JSON, f)
    shutil.copyfile(os.path.join(RULES_DIR, "vault_rules.py"),
                    os.path.join(PARTIAL_RULES, "vault_rules.py"))
    # Bo luat CO json nhung KHONG co vault_rules.py — dung canh ban public clone ra ngoai
    shutil.rmtree(NOPY_RULES, ignore_errors=True)
    os.makedirs(NOPY_RULES)
    with open(os.path.join(NOPY_RULES, "vault-rules.json"), "w", encoding="utf-8") as f:
        json.dump(RULES_JSON, f)

    # Alpha: sach — link + anchor dung, nhung anh co that
    w("Work/Alpha/Alpha.md", fm("Alpha") +
      "Xem [[Beta]] va [[Beta#Heading co that]].\n\n![[a.png]]\n")
    blob("Work/Alpha/attachments/a.png")

    # Beta: 1 wikilink gay + 1 anchor gay; attachments co .xlsx ma KHONG khai file_digest
    w("Work/Beta/Beta.md", fm("Beta") +
      "## Heading co that\n\nLink hong [[Khong Ton Tai]].\n"
      "Anchor hong [[Alpha#Khong co heading nay]].\n"
      "Hoa thuong van khop: [[alpha]].\n")
    blob("Work/Beta/attachments/orphan.png")          # khong ai nhac -> mo coi
    blob("Work/Beta/attachments/data.xlsx")           # chua "mo nilon"

    # Gamma: thieu aliases + summary; 1 nhung gay
    w("Work/Gamma/Gamma.md", fm("Gamma", aliases=False, summary=False) +
      "![[mat-tieu.png]]\n")

    # W149: parser dong van boc du field, nhung YAML that phai nem loi o dong summary
    w("Work/Vo YAML/Vo YAML.md",
      '---\ntitle: Vo YAML\naliases: ["Vo"]\n'
      'summary: "noi dung co "dau nhay kep" khong escape"\n'
      'tags: [JXM]\n---\n\n# Vo YAML\n')

    # Delta: gate_ignore CUOI khoi frontmatter dai -> mien bao loi
    w("Work/Delta/Delta.md",
      "---\ntitle: Delta\n" + 'aliases: ["%s"]\n' % ("x" * 600) +
      'summary: "%s"\ntags: [JXM]\ngate_ignore: true\n---\n\n' % ("y" * 600) +
      "# Delta\n\n[[Khong Ton Tai 2]]\n")

    # _Meta: ten bat dau '_' -> mien bao loi (khong can frontmatter)
    w("Work/_Meta/_Meta.md", "# _Meta\n\n[[Khong Ton Tai 3]]\n")

    # Eps: tags dang YAML list nhieu dong + file_digest day du + 2 kieu nhac anh
    w("Work/Eps/Eps.md",
      "---\ntitle: Eps\naliases: [\"Ep\"]\nsummary: \"note test Eps\"\ntags:\n  - JXM\n"
      "  - hoai-niem\nfile_digest: [\"so-lieu.xlsx\"]\n---\n\n# Eps\n\n"
      "Anh nhac kieu wikilink: [[wiki.png]]\n"
      "Anh nhac kieu markdown: ![](attachments/md.png)\n")
    blob("Work/Eps/attachments/so-lieu.xlsx")
    blob("Work/Eps/attachments/wiki.png")
    blob("Work/Eps/attachments/md.png")

    # --- W41: 3 check contract con lai ---
    # Theta: tag ngoai vocabulary
    w("Work/Theta/Theta.md", fm("Theta", tags="[JXM, tag-tu-che]"))
    # Index - Work: file index nhung deo them tag content
    w("Work/Index - Work/Index - Work.md", fm("Index - Work", tags="[index, JXM]"))
    # Iota: note thuong muon tag `index`
    w("Work/Iota/Iota.md", fm("Iota", tags="[JXM, index]"))
    # Kappa: title != ten file · Lambda: H1 != title · Mu: khong co H1
    w("Work/Kappa/Kappa.md", fm("Kappa Doi Ten Roi"))
    w("Work/Lambda/Lambda.md", fm("Lambda", h1="Lambda Nhung Khac"))
    w("Work/Mu/Mu.md", fm("Mu", h1=False) + "Than note khong co H1.\n")
    # Ngoai le khai trong nguon luat: title dai hon ten file -> SACH
    w("Work/Ngoai Le/Ngoai Le.md", fm("Ngoai Le — Ban Day Du"))
    # Ngoai le van bi bat khi title TROI TIEP khoi gia tri da pin
    w("Work/Ngoai Le Troi/Ngoai Le Troi.md", fm("Ngoai Le Troi — Da Troi Tiep"))
    # Ngoai le pin ca H1 rieng (ca CLAUDE.md ngoai doi that) -> SACH
    w("Work/Ba Chan/Ba Chan.md", fm("Ba Chan — Title Khai", h1="H1 Khai Rieng"))

    # --- 3 ca do AUDIT DOC LAP W41 bat duoc (27/07) ---
    # Ten bat dau bang "Index" nhung KHONG phai file index -> KHONG duoc doi bo tag
    w("Work/Indexing Chien Luoc/Indexing Chien Luoc.md", fm("Indexing Chien Luoc"))
    # Note duoc mien (gate_ignore) ma vi pham CA 3 check moi -> phai im
    w("Work/Mien Ca 3/Mien Ca 3.md",
      "---\ntitle: Ten Khac Han\naliases: [\"x\"]\nsummary: \"s\"\ntags: [tu-che, index]\n"
      "gate_ignore: true\n---\n\nkhong co H1\n")
    # Ngoai le khai HONG (thieu title) -> noi thang, khong so voi chuoi rong
    w("Work/Khai Hong/Khai Hong.md", fm("Khai Hong — Ban Dai Hon"))

    # Wikilink trong BANG markdown phai escape dau ngan alias: [[Alpha\|ten hien thi]]
    w("Work/Bang/Bang.md", fm("Bang") +
      "| Cot | Gia tri |\n|---|---|\n| Link | [[Alpha\\|ten hien thi]] |\n")

    # W73: code khong duoc sinh link/nhung/reference that. Fence 4 backtick co the
    # chua 3 backtick ben trong; tilde fence va inline delimiter 1/2 backtick deu phu.
    w("Work/Code/Code.md", fm("Code") +
      "Inline `[[Inline Ao]]` va ``![[inline-ao.png]]``.\n\n"
      "````markdown\n[[Fence Ao]]\n![[fence-ao.png]]\n```\n````\n\n"
      "~~~md\n[[Tilde Ao]]\n![[tilde-ao.png]]\n~~~\n\n"
      "Anh chi duoc nhac trong code: `[[code-only.png]]`.\n"
      "Ngoai code van phai bat: [[Khong Ton Tai Sau Code]].\n")
    blob("Work/Code/attachments/code-only.png")

    # Ngoai pham vi scanner: khong duoc quet (loi trong day PHAI im)
    w("node_modules/junk.md", "# junk\n\n[[Khong Ton Tai 4]]\n")
    w(".trash/rac.md", "# rac\n\n[[Khong Ton Tai 5]]\n")


def by_id(rep):
    return {c["id"]: c for c in rep["checks"]}


build_fake_vault()
rep = ITG.collect(vault=VAULT_DIR, rules_dir=RULES_DIR, use_cache=False)
C = by_id(rep)

# --- pham vi + tieu chi bo qua ---
check("1 dem dung so note trong pham vi (bo node_modules/.trash)", rep["vault"]["notes"] == 21,
      rep["vault"])
check("1 mien 3 note (_Meta + 2 gate_ignore), kiem 18",
      (rep["vault"]["ignored"], rep["vault"]["checked"]) == (3, 18), rep["vault"])

# --- check cau truc ---
check("2 wikilink gay = 2 (Beta + van xuoi sau code fence; link trong bang `[[Note\\|alias]]` KHONG bi bao - audit W41)", C["link"]["total"] == 2,
      C["link"]["list"])
check("2 wikilink gay chi ra dung file + so dong",
      C["link"]["list"] and C["link"]["list"][0]["file"] == "Work/Beta/Beta.md"
      and C["link"]["list"][0]["line"] > 0, C["link"]["list"])
code_links = [i for i in C["link"]["list"] if i["file"] == "Work/Code/Code.md"]
check("2 W73 bo link trong inline/fence, van bat dung link ngoai code",
      len(code_links) == 1 and code_links[0]["target"] == "Khong Ton Tai Sau Code",
      code_links)
check("2 note mien KHONG bi bao (Delta gate_ignore + _Meta)",
      all("Delta" not in i["file"] and "_Meta" not in i["file"] for i in C["link"]["list"]),
      C["link"]["list"])
check("2 anchor lech = 1 (Alpha#Khong co heading nay)", C["anchor"]["total"] == 1,
      C["anchor"]["list"])
check("2 nhung gay = 1 (Gamma -> mat-tieu.png)", C["embed"]["total"] == 1,
      C["embed"]["list"])
check("2 anh mo coi = 2 (orphan.png + code-only.png chi duoc nhac trong code; wiki.png/md.png nhac kieu [[x.png]]/markdown KHONG mo coi)",
      C["orphan"]["total"] == 2
      and {os.path.basename(i["file"]) for i in C["orphan"]["list"]}
      == {"orphan.png", "code-only.png"},
      C["orphan"]["list"])

# --- check contract ---
# W222: PyYAML la thu vien ben thu ba DUY NHAT ma .graph3d can. Thieu no thi integrity
# chay degraded DUNG Y DO (case 6 cuoi file kiem chinh duong do) — nhung cac khang dinh
# duoi day thi khong con do duoc gi, va truoc W222 chung no thang IndexError, doc len
# nhu "integrity.py hong". Dung cai bay W218: phep do hong bi tuong la code hong.
# Khai [SKIP] co kem "No module named 'yaml'" de selfcheck xep vao THIEU-LIB (CHAN, vi
# pip va duoc) chu khong phai bo qua chinh dang kieu thieu `node`.
try:
    import yaml as _yaml_that                                   # noqa: F401
    CO_YAML = True
except ImportError as _e_yaml:
    CO_YAML = False
    print("[SKIP] khang dinh can PyYAML that (%s) — cac check YAML/CLI/tong problems"
          % _e_yaml)

if CO_YAML:
    check("3 YAML vo bi bat dung note + dong + cot",
          C["yaml"]["total"] == 1
          and C["yaml"]["list"][0]["file"] == "Work/Vo YAML/Vo YAML.md"
          and C["yaml"]["list"][0]["line"] == 4
          and C["yaml"]["list"][0]["column"] > 1,
          C["yaml"]["list"])
    summary_lines = []
    ITG.print_summary(rep, out=summary_lines.append)
    check("3 YAML vo hien du file:dong:cot tren CLI",
          any("Work/Vo YAML/Vo YAML.md:4:%s" % C["yaml"]["list"][0]["column"] in line
              for line in summary_lines), summary_lines)
check("3 YAML vo khong bi parser dong tao them bao loi contract gia",
      all("Vo YAML" not in i["file"]
          for k in ("frontmatter", "tag", "index_tag", "title") for i in C[k]["list"]),
      {k: [i["file"] for i in C[k]["list"]]
       for k in ("frontmatter", "tag", "index_tag", "title")})
check("3 thieu truong frontmatter = 1 (Gamma thieu aliases+summary; Eps tags YAML list nhieu dong KHONG bi bao)",
      C["frontmatter"]["total"] == 1
      and set(C["frontmatter"]["list"][0]["missing"]) == {"aliases", "summary"},
      C["frontmatter"]["list"])
check("3 file nhi phan chua mo nilon = 1 (Beta/data.xlsx; Eps da khai file_digest thi sach)",
      C["digest"]["total"] == 1 and C["digest"]["list"][0]["file"] == "Work/Beta/Beta.md",
      C["digest"]["list"])
check("3 nguon luat bao da nap", rep["rules"]["loaded"] is True, rep["rules"])

# --- W41: tag vocabulary · index 1 tag · title = ten file = H1 ---
check("3b tag ngoai vocabulary = 1 (Theta: tag-tu-che; tag trong vocabulary KHONG bi bao)",
      C["tag"]["total"] == 1 and C["tag"]["list"][0]["missing"] == ["tag-tu-che"],
      C["tag"]["list"])
check("3b index sai tag = 2 (index thua tag content + note thuong muon tag index)",
      C["index_tag"]["total"] == 2,
      [(i["file"], i["detail"]) for i in C["index_tag"]["list"]])
check("3b index sai tag chi dung 2 thu pham (Indexing Chien Luoc KHONG bi bao oan - audit W41)",
      {os.path.basename(i["file"]) for i in C["index_tag"]["list"]}
      == {"Index - Work.md", "Iota.md"},
      [i["file"] for i in C["index_tag"]["list"]])
T = {os.path.basename(i["file"]): i["detail"] for i in C["title"]["list"]}
check("3b title lech = 6 (title!=file · H1!=title · thieu H1 · ngoai le troi · ngoai le mo coi · ngoai le khai hong)",
      C["title"]["total"] == 6, T)
check("3b bat title != ten file (Kappa)", "title" in T.get("Kappa.md", ""), T)
check("3b bat H1 != title (Lambda)", "H1" in T.get("Lambda.md", ""), T)
check("3b bat note khong co H1 (Mu)", "H1" in T.get("Mu.md", ""), T)
check("3b ngoai le da khai thi SACH (Ngoai Le + Ba Chan pin ca H1 rieng)",
      "Ngoai Le.md" not in T and "Ba Chan.md" not in T, T)
check("3b ngoai le KHONG phai mien kiem: title troi tiep van bi bat",
      "Ngoai Le Troi.md" in T and "ngoai le" in T["Ngoai Le Troi.md"].lower(), T)
check("3b ngoai le khai cho note khong con ton tai bi bao",
      any("Khong Con Nua" in i["detail"] for i in C["title"]["list"]),
      [i["detail"] for i in C["title"]["list"]])
# --- 3 ca AUDIT DOC LAP W41 (27/07) ---
check("3c note gate_ignore vi pham ca 3 check moi van duoc MIEN",
      all("Mien Ca 3" not in i["file"]
          for k in ("tag", "index_tag", "title") for i in C[k]["list"]),
      {k: [i["file"] for i in C[k]["list"]] for k in ("tag", "index_tag", "title")})
check("3c ngoai le khai HONG (thieu title) duoc noi thang, khong so voi chuoi rong",
      "khai thiếu" in T.get("Khai Hong.md", "") and '“”' not in T.get("Khai Hong.md", ""),
      T.get("Khai Hong.md"))
check("3b tong so van de = 18", rep["problems"] == 18,
      {c["id"]: c["total"] for c in rep["checks"]})

# --- thieu nguon luat: contract TAT em, cau truc van chay ---
rep2 = ITG.collect(vault=VAULT_DIR, rules_dir=EMPTY_RULES, use_cache=False)
C2 = by_id(rep2)
check("4 thieu vault-rules.json -> ca 5 check contract available=False",
      not any(C2[k]["available"]
              for k in ("frontmatter", "digest", "tag", "index_tag", "title")), rep2["rules"])
check("4 check cau truc VAN chay khi thieu nguon luat",
      all(C2[k]["available"] for k in ("link", "embed", "anchor", "orphan")))
if CO_YAML:                                  # thieu PyYAML thi 1 problem YAML khong sinh ra
    check("4 problems gom cau truc + YAML doc lap nguon luat = 7", rep2["problems"] == 7,
          {c["id"]: c["total"] for c in rep2["checks"]})
check("4 rules.reason noi ro vi sao tat", bool(rep2["rules"].get("reason")), rep2["rules"])

# --- thieu LE mot khoa policy: chi check do tat ---
rep3 = ITG.collect(vault=VAULT_DIR, rules_dir=PARTIAL_RULES, use_cache=False)
C3 = by_id(rep3)
check("4b thieu index_rule/title_rule -> dung 2 check do tat",
      not C3["index_tag"]["available"] and not C3["title"]["available"], rep3["rules"])
check("4b cac check contract khac VAN chay (frontmatter/digest/tag)",
      all(C3[k]["available"] for k in ("frontmatter", "digest", "tag")), rep3["rules"])

# --- CO vault-rules.json nhung KHONG co vault_rules.py (ban public) ---
rep4 = ITG.collect(vault=VAULT_DIR, rules_dir=NOPY_RULES, use_cache=False)
C4 = by_id(rep4)
check("4c thieu vault_rules.py -> van chay contract bang parser du phong",
      all(C4[k]["available"] for k in ("frontmatter", "digest", "tag", "index_tag", "title")),
      rep4["rules"])
check("4c parser du phong dem RA CUNG KET QUA voi parser cua vault",
      {k: C4[k]["total"] for k in ("frontmatter", "digest", "tag", "index_tag", "title")}
      == {k: C[k]["total"] for k in ("frontmatter", "digest", "tag", "index_tag", "title")},
      {"du phong": {k: C4[k]["total"] for k in C4}, "that": {k: C[k]["total"] for k in C}})
# UI/bao cao doc `parser` de noi dang do bang parser nao: phai ghi DUNG ten, ca hai chieu.
check("4c rules.parser noi dung parser dang dung (du phong vs vault_rules.py)",
      (rep4["rules"].get("parser"), rep["rules"].get("parser"))
      == (ITG.PARSER_BASIC, "vault_rules.py"),
      (rep4["rules"].get("parser"), rep["rules"].get("parser")))

# --- cache theo chu ky mtime ---
a = ITG.collect(vault=VAULT_DIR, rules_dir=RULES_DIR)
b = ITG.collect(vault=VAULT_DIR, rules_dir=RULES_DIR)
check("5 goi 2 lan lien tiep tra CUNG object (cache chu ky)", a is b)
w("Work/Zeta/Zeta.md", fm("Zeta") + "[[Cung Khong Ton Tai]]\n")
c = ITG.collect(vault=VAULT_DIR, rules_dir=RULES_DIR)
check("5 them note gay -> cache tu het han, dem lai", c is not a and by_id(c)["link"]["total"] == 3,
      by_id(c)["link"]["list"])

# --- ham thuan + tien ich ---
check("6 is_ignored bat gate_ignore o CUOI khoi frontmatter dai",
      ITG.is_ignored("X", "---\ntitle: X\nsummary: \"%s\"\ngate_ignore: true\n---\n\n# X\n"
                     % ("z" * 900)))
check("6 is_ignored KHONG an nham dong gate_ignore trong THAN note",
      not ITG.is_ignored("X", "---\ntitle: X\n---\n\n# X\n\ngate_ignore: true\n"))
check("6 split_target tach alias + anchor",
      ITG.split_target("Note#Heading|alias") == ("Note", "Heading"))
check("6 is_index_note: khop token chu khong phai startswith tran",
      (ITG.is_index_note("Index", None, "index", "index"),
       ITG.is_index_note("Index - Work", None, "index", "index"),
       ITG.is_index_note("Indexing Chien Luoc", None, "index", "index"),
       ITG.is_index_note("Ghi Chu", "index", "index", "index")) == (True, True, False, True))
check("6 _title_problems im khi note THIEU han title (check frontmatter da bao roi)",
      ITG._title_problems({"stem": "X", "h1": None}, "", None, True) == [])

# --- W149: thieu PyYAML phai DEGRADE + exit 2, tuyet doi khong bao sach gia ---
rules6, info6 = ITG.load_rules(RULES_DIR)
rep6 = ITG.build_integrity(ITG.scan_vault(VAULT_DIR), rules=rules6, rules_info=info6,
                           yaml_loader=None, yaml_reason="ImportError test")
C6 = by_id(rep6)
check("6 thieu PyYAML -> check yaml TAT co ly do ro",
      not C6["yaml"]["available"] and "PyYAML" in C6["yaml"]["reason"], C6["yaml"])
check("6 thieu PyYAML -> degraded + ok=False + exit 2 (khong xanh gia)",
      rep6["degraded"] and not rep6["ok"] and rep6["warnings"]
      and ITG.result_exit_code(rep6) == 2,
      {"degraded": rep6["degraded"], "ok": rep6["ok"],
       "warnings": rep6["warnings"], "exit": ITG.result_exit_code(rep6)})

print("\nKET QUA: " + ("FAIL %d muc: %s" % (len(fails), ", ".join(fails)) if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
