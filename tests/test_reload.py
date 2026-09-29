# -*- coding: utf-8 -*-
"""Test nut ⟳ + vung click brand o cua so hep (W64/W65) — kiem TINH tren ma nguon.

Vi sao co bo nay: tu W58 app mo bang cua so app Edge/Chrome (`--app=`) nen KHONG con
thanh dia chi ⇒ khong con nut reload cua trinh duyet. Nut nay la loi thoat duy nhat bam
duoc, va no con la CHO BAO "server da nap ma moi" — mat mot trong hai deu am tham.

Ba dieu de vo nhat, moi dieu mot may gac:
  - nut roi ra khoi dong version  -> rot xuong vung #sidebar (top 64px) la bi an mat
    click. Bai hoc W43, do bang elementFromPoint chu khong phai element.click().
  - nhanh boot_id doi quen bat .hot -> nguoi dung ngoi tren ban cu ma khong biet, vi
    refreshData() chi nap lai DU LIEU chu khong nap lai ma UI.
  - pollActivity roi khoi __fx -> khong con nghiem thu duoc nhanh do khi tab bi an
    (tab an => vong poll gan nhu dung, gotcha #9): chinh bay nay da lam lan nghiem thu
    dau tuong nham la code hong.
  - panel phai de len dong brand o viewport hep -> VI/EN va nut reload van ve ra nhung
    elementFromPoint tra ve DIV.stats. W65 day panel + toggle xuong duoi brand <=700px.
"""
import io, os, re, sys
sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _scratch import G3D

SRC = os.path.join(G3D, "src")
INDEX = os.path.join(G3D, "index.html")

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  ->  " + repr(info)) if not cond else ""))
    if not cond:
        fails.append(name)


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def css_block(text, selector):
    """Lay block {...} cua selector, co dem ngoac de dung duoc cho @media long rule."""
    start = text.find(selector)
    if start < 0:
        return ""
    left = text.find("{", start + len(selector))
    if left < 0:
        return ""
    depth = 0
    for i in range(left, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[left + 1:i]
    return ""


def px_prop(block, prop):
    m = re.search(r"(?:^|;)\s*%s\s*:\s*(\d+)px\b" % re.escape(prop), block)
    return int(m.group(1)) if m else None


html = read(INDEX)
ui = read(os.path.join(SRC, "ui.js"))
main = read(os.path.join(SRC, "main.js"))
act = read(os.path.join(SRC, "activity.js"))
css = read(os.path.join(SRC, "style.css"))
vault_js = read(os.path.join(SRC, "vault-switcher.js"))
state_js = read(os.path.join(SRC, "state.js"))
finder_js = read(os.path.join(SRC, "finder.js"))
workspace_js = read(os.path.join(SRC, "workspace.js"))

# --- 1: nut ton tai, dung mot lan ---
check("1 index.html co dung 1 nut #reload-b", html.count('id="reload-b"') == 1,
      html.count('id="reload-b"'))

# --- 2: nut nam CUNG DONG version (trong div.sub) ---
# Khong doi cho: dong duoi la vung #sidebar (top 64px) — nut roi xuong do la bi an mat
# click du CSS van ve ra nut. Do bang cach cat dung khoi div.sub roi tim nut trong do.
m = re.search(r'<div class="sub">(.*?)</div>', html, re.S)
check("2 nut nam trong div.sub (cung dong voi so version)",
      bool(m) and 'id="reload-b"' in m.group(1))

# --- 3/4 (W426): khoa dich cua nut (title/aria + du VI/EN) do test_i18n gac tong quat
# (#2 VI==EN, #3 khoa markup - ca data-i18n-title/aria - co that, #4 tr() co that,
# #10 attribute tieng Viet phai co khoa i18n).

# --- 5: hanh vi bam = nap lai trang ---
check("5 ui.js export initReload", "export function initReload" in ui)
init_reload = re.search(r"export function initReload\(\)\s*\{(.*?)\n\}", ui, re.S)
check("5 initReload goi location.reload() trong than ham (khong tinh chu thich)",
      bool(init_reload) and "location.reload()" in init_reload.group(1),
      init_reload.group(1) if init_reload else None)

# --- 6: main.js that su NOI nut vao (khai ma khong goi = nut chet) ---
imported = re.search(r"import \{(.*?)\} from '\./ui\.js'", main, re.S)
check("6 main.js import initReload", bool(imported) and "initReload" in imported.group(1))
check("6 main.js goi initReload()", "initReload();" in main)

# --- 7: nhanh boot_id doi phai bat .hot + doi tooltip ---
# Cat dung khoi lenh cua nhanh do roi soi ben trong: de o ngoai nhanh la nut sang den
# ca khi khong co ban moi.
br = re.search(r"if \(data\.boot_id && serverBoot(.*?)\n    \}", act, re.S)
body = br.group(1) if br else ""
check("7 tim thay nhanh boot_id doi trong activity.js", bool(body))
check("7 nhanh do bat class hot cho #reload-b",
      "'reload-b'" in body and "classList.add('hot')" in body, body[:120])
check("7 nhanh do doi tooltip sang reload.tip.new", "reload.tip.new" in body, body[:120])

# --- 8: KHONG duoc tu location.reload() trong activity.js ---
# Tu reload khong hoi se cuop mat tab dang doc / ghim / bo loc / vi tri camera giua chung.
# Nut moi, nguoi dung bam.
check("8 activity.js khong tu goi location.reload()", "location.reload()" not in act)

# --- 9: CSS co nut va trang thai hot ---
check("9 style.css co rule #reload-b", "#reload-b {" in css)
check("9 style.css co rule #reload-b.hot", "#reload-b.hot" in css)

# --- 10: pollActivity nam trong __fx de nghiem thu duoc khi tab bi an ---
fx = re.search(r"window\.__fx\s*=\s*\{(.*?)\};", main, re.S)
check("10 pollActivity co trong __fx (nghiem thu tab an)",
      bool(fx) and "pollActivity" in fx.group(1))

# --- 11: W65, panel phai tranh TOAN BO dong brand o viewport hep ---
# Chi nang z-index se lam nut bam lai duoc nhung chu van chong len panel. Contract la
# responsive layout: panel + toggle cung lui xuong; live QA van phai do elementFromPoint.
narrow = css_block(css, "@media (max-width: 700px)")
panel_narrow = css_block(narrow, "#panel")
toggle_narrow = css_block(narrow, "#panel-toggle")
panel_top = px_prop(panel_narrow, "top")
toggle_top = px_prop(toggle_narrow, "top")
check("11 W65 co breakpoint hep <=700px", bool(narrow))
check("11 W65/W180 panel lui xuong duoi vault button (top >=68px)",
      panel_top is not None and panel_top >= 68, panel_top)
check("11 W65 panel-toggle lui theo panel (top >= panel+6px)",
      toggle_top is not None and panel_top is not None and toggle_top >= panel_top + 6,
      (panel_top, toggle_top))
sidebar_top = px_prop(css_block(css, "\n#sidebar "), "top")
check("11 W180 sidebar cung lui xuong duoi vault button (top >=68px)",
      sidebar_top is not None and sidebar_top >= 68, sidebar_top)

# --- 12: W180 Vault Switcher nằm đúng vùng click brand + có nhãn hiện hành ---
check("12 index.html co dung 1 nut #vault-switch", html.count('id="vault-switch"') == 1,
      html.count('id="vault-switch"'))
check("12 nut vault nam cung div.sub", bool(m) and 'id="vault-switch"' in m.group(1))
vault_btn = re.search(r'<button[^>]*id="vault-switch"[^>]*>', html)
vault_btn = vault_btn.group(0) if vault_btn else ""
check("12 nut vault la button ban phim + co aria", 'type="button"' in vault_btn and
      'data-i18n-aria="vault.choose"' in vault_btn, vault_btn)
check("12 nut vault co label ellipsis", 'id="vault-label"' in html and '#vault-label {' in css)
vault_css = css_block(css, "#vault-switch")
check("12 nut vault nhan pointer event that", "pointer-events: auto" in vault_css, vault_css)
check("12 hit-area vault phu border sub-pixel", "#vault-switch::before" in css and
      "inset: -3px" in css)

# --- 13: vault_id phải có TRƯỚC mọi localStorage restore ---
load_pos = main.find("await loadVaultState()")
graph_pos = main.find("fetch('/graph-data')")
restore_pos = main.find("restoreTagOffFromStorage()")
check("13 load vault-state truoc graph va restore storage",
      0 <= load_pos < graph_pos < restore_pos, (load_pos, graph_pos, restore_pos))
check("13 state.js co namespace vaultKey", "export const vaultKey" in state_js)
check("13 legacy state chi migrate vao app vault", "S.vaultMigrateLegacy" in vault_js and
      "value == null && S.vaultMigrateLegacy" in state_js)
check("13 finder dung vaultStore cho tree", "vaultStoreGet(TREE_OPEN_KEY)" in finder_js)
check("13 workspace namespace tab/ghim/recent", "VAULT_KEYS" in workspace_js and
      all(k in workspace_js for k in ("WS_KEY", "PINS_KEY", "RECENT_KEY")))

# --- 14: picker/restart contract + song ngữ ---
check("14 module POST /vault-pick", "fetch('/vault-pick', { method: 'POST' })" in vault_js)
check("14 client doi dung vault_id va boot_id moi", "h.vault_id === targetId" in vault_js and
      "h.boot_id !== oldBoot" in vault_js)
check("14 --vault/demo khoa nut UI", "b.disabled = S.vaultLocked || cls === 'busy'" in vault_js)

# --- 15: picker native phải có feedback lớn, không để user tưởng app treo ---
pick_wait = re.findall(r'<[^>]*id="vault-pick-wait"[^>]*>', html)
check("15 index co dung 1 lop bao picker dang mo, mang role=status",
      len(pick_wait) == 1 and 'role="status"' in pick_wait[0], pick_wait)
check("15 overlay picker phu viewport va tren moi chrome", "#vault-pick-wait" in css and
      "position: fixed" in css_block(css, "#vault-pick-wait") and
      "z-index: 10000" in css_block(css, "#vault-pick-wait"))
pick_order = (vault_js.find("showPickerWait('picking')"),
              vault_js.find("requestAnimationFrame"),
              vault_js.find("fetch('/vault-pick'"))
check("15 UI bat overlay truoc POST va cho browser ve mot frame",
      0 <= pick_order[0] < pick_order[1] < pick_order[2], pick_order)
hide_calls = vault_js.count("hidePickerWait()") - vault_js.count("function hidePickerWait()")
check("15 cancel va loi deu tat overlay (>=3 loi goi, khong tinh dinh nghia)",
      hide_calls >= 3, hide_calls)

print("\nTONG KET test_reload: %s" % (("FAIL %d: %s" % (len(fails), ", ".join(fails))) if fails else "ALL PASS"))
sys.exit(1 if fails else 0)
