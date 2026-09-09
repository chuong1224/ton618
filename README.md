# TON618

Formerly Agents Knowledge Base / KB Graph 3D. The 3D graph remains a view inside TON618. See [upgrade and rollback](docs/migration-v2.md). Existing screenshots show the previous branding.

**A 3D cockpit for your markdown knowledge vault — and a live window into the AI agents working inside it.**

**🌐 Landing page: [chuong1224.github.io/ton618](https://chuong1224.github.io/ton618/)**

Point it at a folder of markdown notes (an Obsidian-style vault) and it serves a local web app: an interactive, synthwave-styled 3D force graph of every note, tag and attachment — with a built-in reader, full-text finder, tabbed workspace, and a layer no PKM tool has: **real-time visualization, replay and analytics of AI-agent activity** (Claude Code out of the box; any agent via a simple JSONL hook).

> Python stdlib server + vanilla ES modules + vendored three.js. **No pip install to run the app, no npm, no build step.** Optional `PyYAML` enables the strict YAML-frontmatter integrity lamp.

![The vault as a synthwave galaxy — tag groups form colored continents](docs/hero.png)

<p align="center"><em>Two agents tearing through 120 notes at full speed — comet trails, hyperspace hops, impact ripples, live</em></p>

![Two agents jumping across the vault continuously — live capture](docs/agent-storm.gif)

<p align="center"><em>The full cockpit: reader, finder tree, live agent feed and retrieval chains around the graph</em></p>

![Full cockpit UI with reader, agent feed and retrieval chains](docs/cockpit-ui.png)

<p align="center"><em>The aftermath — Claude's blue and Nova's yellow trails woven across every continent</em></p>

![Agent activity lighting up the graph](docs/agent-activity.png)

*All screenshots come from the bundled synthetic [demo vault](demo/vault) — spin it up yourself.*

## How it works

![Architecture: vault → Python server → 3D cockpit, agents feed the activity layer](docs/how-it-works.svg)

## Features

![Feature map](docs/features.svg)

### Vault roots
- Click the folder name beside the logo to choose **any markdown vault on this machine** with the native folder picker. The supervisor restarts on the same port and the graph, Reader, Finder, search, onboarding, integrity and insight all move to the selected root together
- The choice is stored outside every vault in `%LOCALAPPDATA%/claude-graph3d/vaults.json`. Tabs, pins, recent notes, tree expansion and content filters are namespaced by a stable vault id, so vaults do not inherit each other's working state
- For a fixed session, run `python ensure_graph3d.py --vault "path/to/AnyVault"`; this locks the picker. A selected vault is treated as untrusted data: real paths cannot escape through symlinks/junctions, active HTML/SVG assets are sandboxed, and its `work.py` is never imported

### 🌌 The graph
- Force-directed 3D graph of notes, tags and attachments, colored by tag groups, with a bloom "neon" glow and adjustable intensity
- Degree-aware physics (hubs get room, leaves hug their hub), optional 🧲 cluster-magnet mode per color group, collision guard, smooth settling when filtering
- Layout presets — Expand, Calm, and 🪐 Universe (arranges notes by the index tree: root at the center, each index a hub, leaves on a Fibonacci sphere around it), deterministic across reloads
- Two deliberate filter semantics: color groups *spotlight* (dim but keep context), tag/extension filters *declutter* (remove entirely); your tag and color-group choices persist across sessions
- Accessibility: AA-contrast panel palette, keyboard-operable controls, respects `prefers-reduced-motion`

### 🤖 Agent activity, live on the graph
- A `PostToolUse` hook (Claude Code example below) logs every file operation an agent performs in the vault
- Events fire cinematic effects: comet chains along retrieval paths, three-phase "hyperspace jump" hops between notes, per-agent colors, dwell trails that linger like a starfield
- Retrieval chains are grouped and replayable; hot links glow in the agent's color
- ⏱ **Cockpit** — scrub through a full day of agent activity on a timeline (play/pause/speed), plus a dashboard: per-agent stats, hourly histogram, top notes
- 🔥 Heatmaps — recent-window and long-term cumulative access frequency; hot notes swell and glow

### 📖 Reading & finding
- Click a node → read the note in place (markdown-it): wikilinks resolve, image/video embeds, backlinks
- Drag the rail just outside the Reader's right edge to make dense notes wider without blocking the vertical scrollbar; it tracks the pointer instantly while dragging. Single-pane and split-pane widths are remembered separately and clamped to the available viewport. Double-click resets the current mode; ←/→ nudges it from the keyboard
- Click or press Enter on a Reader image → open an in-app lightbox: natural-size 100%, 80vw × 80vh fit, cursor-anchored zoom, clamped pan, keyboard focus trap, and Copy image/link/Open/Download with honest GIF/SVG/large-image fallbacks
- Folder-tree sidebar (drag to resize) + quick switcher `Ctrl+P`: note names, `#tags`, diacritic-insensitive full-text search, and attachments by name/path/extension
- Pick an attachment from the Reader, vault tree, graph, quick switcher, or right search → one shared menu: **Open file** in the OS default app, **Show in folder**, or context-aware **View in KB / Download file**. Browser-renderable images, PDF, text and media open for viewing; Office/archive files download in place without leaving a blank app window. Windows reveal uses Explorer's exact `/select,"path"` syntax, including paths with spaces or commas. Native actions are same-origin POSTs constrained to real non-hidden files inside the vault
- Workspace: multi-tab reading, ⧉ two-pane split, ☆ pinned notes, 🕘 reading history — all persisted across sessions

### 🩺 Vault health — retrieval and integrity
- **Retrieval health** (`/insight`): what your agents actually reach — hottest notes this week vs last, notes cooling off, notes nobody has touched in a while (with an age histogram that needs no threshold), notes never on any retrieval path, weakly connected clusters on the *note-to-note* graph, and coverage per area. It also describes taxonomy adherence with deterministic lexical TF-IDF: **B3 scope leakage** flags leaf sections closer to a sibling note than their parent note, while **B4** reports the Spearman relationship between tree distance and content distance. A deterministic **review worklist** turns those measurements into prioritized proposals with a stable ID, exact target, and evidence: connect an unseen note to its nearest ancestor index, reduce repeated reads, add a shortcut across a long retrieval chain, or review a high-margin scope leak. The worklist is always `proposal_only`, requires human review, and never edits or moves notes automatically. The same function powers a CLI report generator (`python insight.py --report`)
- **Integrity lamps** (`/integrity`): what is actually *broken*. Four **structural** checks need no configuration — dangling `[[wikilinks]]`, broken `![[embeds]]`, `[[Note#Heading]]` anchors that no longer match, orphaned images/videos. Wikilinks, embeds and headings shown inside inline or fenced code are treated as documentation, not graph edges. A strict YAML check parses each complete frontmatter block with `yaml.safe_load` and reports the exact file, line and column. Five more **contract** checks read your own rules — required frontmatter fields, binary attachments never summarised in the note, tags outside your controlled vocabulary, index files carrying the wrong tags, and `title` that no longer matches the filename and the H1. Click any finding to open the note right where it is
- Both refresh on demand (no background polling). Integrity honours per-note opt-outs (`_`-prefixed filenames, `gate_ignore: true`)
- **Turning the contract checks on:** copy [`docs/vault-rules.example.json`](docs/vault-rules.example.json) to your vault root as `vault-rules.json` (or into `.graph3d/`, or point `GRAPH3D_VAULT_RULES` at its folder) and **edit it to your own vocabulary** — it is a template, not a drop-in. Each check reads only its own slice, so a file declaring just `mandatory_frontmatter` lights that one lamp and leaves the rest off; add keys as you go. No file at all: the five lamps switch off cleanly and the structural four still run
- Deliberate exceptions are declared, not guessed: `title_rule.exceptions` pins the allowed `title` (and `h1`) for a file whose name cannot match its heading. Being listed is not an exemption — drift past the pinned value is still reported, and an exception naming a note that no longer exists is reported too, so the list cannot rot
- `python integrity.py` prints the same report in a terminal and exits **0 when clean, 1 when something is broken, or 2 when PyYAML is unavailable**. Install the optional checker with `python -m pip install pyyaml`; without it the app still runs, but integrity is explicitly **degraded** instead of reporting a false clean result

### 🌱 Starts from nothing
- Point the app at a folder with **no notes at all** and it offers three ways in — the bundled demo vault (own port, your real server untouched), a **starter vault written into that folder on one click**, or a one-minute guide with a rescan button
- Until the first note exists, the empty tree, graph controls, and technical `0/0` health figures stay out of the way — the onboarding choices are the whole first screen
- It also catches the most common first-run mistake: if the app folder isn't named `.graph3d`, it is reading the folder *above the clone* as your vault — the app says which folder that is, shows the right clone command, and offers a "this really is my vault" button if you know better
- Scaffolding the starter vault opens the first note for you, and the invitation stays one click away at the bottom of the screen until the vault has notes
- Writing files is deliberately narrow: the in-app action only scaffolds an empty vault; the CLI can add the guide notes to an existing vault with `--force`, but **neither path ever overwrites an existing file**
- Side-effect endpoints are POST-only and check the request origin; native file actions additionally reuse the vault path/traversal guard. Everything else is read-only

### 🌳 Work map (optional)
- If your vault keeps a machine-readable map of open work, the app renders it as a **branching tree**: one section per area, visible dependency levels stacked from top to bottom, arrows meaning *must be done first*. Long chains stay within the viewport, titles wrap, and hidden completed ancestors leave no empty levels
- Click any item to open the note where that work was declared; the "ready only" filter shows just what is actionable **on the machine you are sitting at**
- The active vault supplies `work.json`; the server loads the trusted classification engine from the app's own vault, never a script in a newly selected vault. `GRAPH3D_WORKMAP_DIR` selects the registry folder and `GRAPH3D_WORKMAP_ENGINE` can explicitly select a trusted engine exposing `export_data(cfg)`. Results are cached by registry and engine mtime. Without both inputs, the endpoint returns 404 and the panel says so

### 🖥 Multi-machine, self-healing
- Per-host activity journals live inside the vault → two machines syncing the same vault (OneDrive, Drive, Syncthing…) merge their histories automatically; no server needed on the second machine
- Single-instance server keyed by port: verifies health by boot id, auto-restarts when source changes, cleans up stale processes — and refuses to kill anything it cannot verify as its own
- Loopback only (`127.0.0.1`) — your vault is never exposed to the network

## Quickstart

Requirements: **Python 3.9+** and a modern browser. `PyYAML` is optional for the app and required only for strict YAML-frontmatter validation (`python -m pip install pyyaml`). Primary platform is **Windows** (process management shells out to PowerShell); the server itself is cross-platform and mac/linux support is on the roadmap.

### 🚀 Try it in 60 seconds — no vault needed

```bash
git clone https://github.com/chuong1224/ton618
cd ton618
python try_demo.py
```

That runs the cockpit on the **bundled 120-note demo vault** — the same one every screenshot and GIF above comes from. Fly around, click nodes to read them, press `Ctrl+P` to search, hit **▶ Demo hiệu ứng** to see the agent effects.

### 📁 Install into your own vault

```bash
# clone INTO your vault as a dot-folder (keeps it invisible to your note tools)
# ⚠ replace "path/to/YourVault" with the real path to YOUR vault — the folder
#   that holds your markdown notes, e.g. "D:/Notes" or ~/Documents/Vault
git clone https://github.com/chuong1224/ton618 "path/to/YourVault/.graph3d"
cd "path/to/YourVault/.graph3d"
python ensure_graph3d.py
```

That's it — the app opens at `http://127.0.0.1:8321`. It starts on the parent folder of `.graph3d/`; click the folder name beside the logo to switch to any vault on the machine, or launch a fixed root with `python ensure_graph3d.py --vault "path/to/AnyVault"`. Re-running `ensure_graph3d.py` is idempotent (reuses a healthy server only when both version and vault match, and replaces a stale one). On Windows you can also double-click `Start-Graph3D.bat`.

**Give it a real launcher (Windows).** Once per machine:

```bash
python install_launcher.py --hotkey "CTRL+ALT+G"
```

You get a Start Menu + Desktop shortcut that runs `pythonw ensure_graph3d.py --app` — so a click opens the cockpit in **its own app window**: no address bar, no tab lost among twenty others. To give the *running taskbar button* its own neon icon too, open the app once in Edge and choose **⋯ → Apps → Install this site as an app**. On later launches, `ensure` opens the packaged AppUserModelID registered in Windows through `shell:AppsFolder` (current Edge), or uses an installed Chromium shortcut's `--app-id` on older setups; if no site-app is installed it falls back to `--app=<url>` exactly as before. Set `GRAPH3D_PWA_SHORTCUT` only if an older Chromium setup uses a renamed or moved shortcut. `--status` shows what is installed, `--uninstall` removes the Python launcher, and `--python` pins a specific interpreter. By default, the installer discovers a registered Python before falling back to the current runtime; Microsoft Store package paths are converted to their stable app-execution alias when available, so a Store update does not strand the shortcut. Because there is no console, everything `ensure` prints goes to `%LOCALAPPDATA%\claude-graph3d\launcher.log`.

The point isn't the icon — it's that the path to your vault belongs to the *machine*, so it lives in the shortcut instead of in a note you have to open first.

### 🌱 No vault yet? Start from zero

Here's the secret: **a vault is just a folder of markdown files.** You don't need Obsidian or any special app to start one — any text editor works, and an AI agent can do the writing for you. ([Obsidian](https://obsidian.md) is a great *editor* to adopt later; it opens the exact same folder.)

This repo ships a [`starter-vault/`](starter-vault/) — 9 short notes that teach notes, `[[wikilinks]]`, tags, and hub notes *by being read inside the app itself* (Vietnamese summary included).

**The app offers all of this to you, in the UI.** Open it on a folder with no notes and instead of an empty void you get three doors:

- **🌌 See the demo vault** — starts a second server on port **8322** for the bundled 120-note vault; the one on your own vault is left running, untouched
- **🌱 Create your first vault right here** — copies `starter-vault/` into the folder you opened, reloads the graph in place, and never overwrites a file that already exists
- **📖 Do it yourself — 1 minute** — three steps and a **rescan** button

Same two actions from a terminal, if you prefer:

```bash
python ensure_graph3d.py --demo                              # demo vault, own port, nothing installed
python ensure_graph3d.py --init-starter "path/to/MyVault"   # create a new starter vault
python ensure_graph3d.py --init-starter "path/to/MyVault" --force  # add guides safely; never overwrite
```

Or lay it out by hand:

```bash
# copy the starter vault anywhere you like, then install the app into it
cp -r starter-vault "path/to/MyVault"
git clone https://github.com/chuong1224/ton618 "path/to/MyVault/.graph3d"
cd "path/to/MyVault/.graph3d"
python ensure_graph3d.py
```

Open **Start Here** in the Reader and follow along — in ten minutes you'll have edited your first note and watched the graph react.

## Hook up an agent

**Claude Code** — add to your vault's `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.graph3d/log_activity.py\"",
            "shell": "bash",
            "async": true,
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

**Any other agent or script**: pipe the same hook-style JSON payload into `log_activity.py` and label the stream with `--agent "MyAgent"` — each agent gets a stable color on the graph. See the module docstring for the payload shape.

Remove the hook and the app still works fully — you just lose the live layer.

## Configuration

| What | Where |
|---|---|
| Tag → color groups | `TAG_COLORS` in `build_graph_data.py` (order = priority) + `GROUP_ORDER` in `src/state.js` |
| Folders excluded from the graph | `EXCLUDED_DIRS` in `build_graph_data.py` |
| Port | `python ensure_graph3d.py --port 9000` |
| Physics feel | constants in `physics()` in `src/graph.js` |
| Default neon intensity | `S.neon` in `src/state.js` |

The default tag taxonomy reflects the author's vault — moving it to a config file is the top roadmap item.

> **Note on language:** the UI ships in **English and Vietnamese**. It picks up your browser language on first run; the **VI | EN** switch next to the logo changes it any time and the choice is remembered. Your own content is never translated — note names, tags, colour groups and paths appear exactly as they are in your vault.

## Tests

```bash
python tests/selfcheck.py        # ~19s: compile checks + behavior contracts + unit tests
python tests/selfcheck.py --slow # adds port/kill-policy integration tests (~30s)
```

The suite is designed to run with the app installed inside a real vault.
Each run gets an isolated scratch directory, so private and public clones can be checked in parallel without deleting each other's journal fixtures (v1.54.1).

A suite that cannot measure something says so on a `[SKIP] <reason>` line, and the runner
counts those items instead of hiding them behind a zero exit code (v1.59.6). So read the
last line carefully: `ALL PASS · BO QUA n muc` means the rest passed and *n* items went
unmeasured. A clone checked outside a vault reports several of these, which is expected —
the hook matcher, the real rules parser and the cross-check against the vault's own gate
simply are not there to measure.

But a suite can also skip without saying anything: `if not condition: pass` prints
nothing, and neither do deleted assertions. So from v1.60.0 the runner measures instead of
asking — it counts the assertions each item actually ran, keeps the count in a per-machine
mark outside the repo, and compares it on the next run. Fewer assertions, or a whole suite
missing from disk, prints `TUT VUNG PHU` and exits 1 **even when every suite reports
`ALL PASS`**. Read the exit code, not the text; `ALL PASS` alone no longer proves a thing.
When the drop is intentional, lower the mark on the record with
`python tests/selfcheck.py --chap-nhan "why"` rather than working around it.

## Roadmap

- Config file for tag groups & colors (no code edits needed)
- Cross-platform process management (mac/linux)
- Semantic search for vaults that outgrow full-text

## Origin

This is the daily driver for the author's own agent-operated knowledge base: AI agents read and write the vault all day, and this cockpit is how that work is watched, replayed and measured. It has grown through 30+ versioned iterations — graph first, then reader, finder, cockpit and workspace — pair-programmed with Claude, with a contract-encoded test suite guarding against every regression that ever actually happened.

## License

[MIT](LICENSE)

---

# 🇻🇳 Tiếng Việt

**Buồng lái 3D cho vault ghi chú markdown — và cửa sổ realtime nhìn các AI agent đang làm việc bên trong.** (Toàn bộ ảnh chụp phía trên lấy từ [demo vault](demo/vault) tổng hợp kèm repo — không phải dữ liệu thật.)

Trỏ vào một thư mục note markdown (vault kiểu Obsidian), app phục vụ giao diện web local: graph 3D synthwave toàn bộ note/tag/file, kèm panel đọc note, tìm kiếm full-text, workspace đa tab — và lớp đặc sản: **hiển thị realtime + replay + thống kê hoạt động AI agent** (Claude Code dùng ngay; agent khác qua hook JSONL đơn giản).

- **Chạy thử 60 giây (không cần vault):** clone repo → `python try_demo.py` → mở ngay demo vault 120 note (nguồn của mọi ảnh/GIF phía trên).
- **Cài đặt vào vault của bạn:** chỉ cần Python 3.9+ — clone vào vault thành thư mục `.graph3d` (trong lệnh mẫu, thay `YourVault` bằng **đường dẫn thư mục vault của bạn** — thư mục chứa các note markdown, ví dụ `D:/Notes`), chạy `python ensure_graph3d.py`, app mở tại `http://127.0.0.1:8321`. Không npm, không build; `PyYAML` là tuỳ chọn để bật phép kiểm cú pháp frontmatter thật (`python -m pip install pyyaml`). Windows có thể double-click `Start-Graph3D.bat`.
- **Chọn vault root ngay trên UI:** bấm tên folder cạnh logo để mở hộp chọn folder của hệ điều hành; chọn một vault bất kỳ trên máy thì graph, Reader, Finder, tìm kiếm, onboarding, integrity và insight cùng chuyển sang root đó sau khi server khởi động lại trên đúng port cũ. Lựa chọn lưu ngoài mọi vault ở `%LOCALAPPDATA%/claude-graph3d/vaults.json`; tab, ghim, lịch sử, cây folder và bộ lọc nội dung được tách riêng theo vault. Muốn cố định một phiên: `python ensure_graph3d.py --vault "đường/dẫn/Vault"` — nút đổi vault sẽ bị khoá. Vault được chọn được coi là dữ liệu không tin cậy: chặn symlink/junction thoát root, sandbox asset HTML/SVG và không bao giờ import `work.py` của folder đó.
- **Lối vào đàng hoàng (Windows):** chạy MỘT lần mỗi máy `python install_launcher.py --hotkey "CTRL+ALT+G"` → shortcut Start Menu + Desktop chạy `pythonw ensure_graph3d.py --app`: click là ra **cửa sổ app riêng**, không thanh địa chỉ, không lẫn giữa hai chục tab. Muốn **nút taskbar đang chạy** cũng có icon neon riêng, mở app một lần trong Edge rồi chọn **⋯ → Apps → Install this site as an app**; các lần sau `ensure` mở AppUserModelID packaged mà Windows đăng ký qua `shell:AppsFolder` (Edge hiện hành), hoặc dùng `--app-id` từ shortcut Chromium kiểu cũ; chưa cài thì lùi về `--app=<url>`. Chỉ cần đặt `GRAPH3D_PWA_SHORTCUT` khi bản Chromium kiểu cũ dùng shortcut đã đổi tên/di chuyển. `--status` xem launcher đang cài gì · `--uninstall` gỡ launcher · `--python` ghim interpreter cụ thể. Mặc định installer tìm Python đã đăng ký trước khi lùi về runtime hiện hành; đường Store Python có số build được đổi sang app-exec alias ổn định khi alias tồn tại, nên Store cập nhật không làm shortcut chết. Không có console nên thông báo của ensure nằm ở `%LOCALAPPDATA%\claude-graph3d\launcher.log`. Ý nghĩa thật: đường dẫn vault là thuộc tính của **máy**, nên nó nằm trong shortcut chứ không nằm trong một note mà bạn phải mở ra trước.
- **Chưa có vault? KHÔNG cần Obsidian trước.** Vault chỉ là một thư mục chứa file `.md` — soạn bằng Notepad cũng được. Obsidian là editor tuỳ chọn về sau, dùng chung đúng thư mục này.
- **Mở app trên thư mục chưa có note nào → app tự mời 3 lối đi** thay vì graph rỗng: **🌌 xem demo** 120 note (server riêng cổng 8322, server trên vault thật của bạn vẫn chạy nguyên), **🌱 tạo vault đầu tiên ngay tại đó** (chép [`starter-vault/`](starter-vault/) 9 note — dạy note/wikilink/tag/hub ngay trong app, có bản tiếng Việt; **không bao giờ đè file đã có**), **📖 tự làm 1 phút** + nút quét lại. Khi chưa có note, app ẩn cây/panel/control graph và các số kỹ thuật `0/0` để màn đầu chỉ còn đúng hướng dẫn cần thiết.
- **CLI có lối an toàn cho vault đang dùng:** `python ensure_graph3d.py --init-starter "đường/dẫn/VaultCuaBan" --force` thêm bộ note hướng dẫn nhưng vẫn **tuyệt đối không đè file trùng tên**. Cài nhầm chỗ thì app cũng nói rõ thư mục đang bị đọc, đưa lệnh clone đúng, và có nút "đây đúng là vault của tôi" nếu bạn cố ý. Tạo starter vault xong app mở luôn note đầu tiên; lời mời vẫn nằm sẵn một nút ở đáy màn hình chừng nào vault còn trống.
- **Graph:** physics co giãn theo degree, 🧲 gom cụm theo nhóm màu, chống chồng node, preset bố cục 🪐 Vũ Trụ (xếp note theo cây index: root làm tâm, lá quây quanh index, deterministic qua reload), lọc tag / đuôi file / nhóm màu (spotlight vs declutter, **nhớ qua phiên**), heatmap tần suất truy cập, độ chói neon chỉnh được, hỗ trợ tiếp cận (AA, bàn phím, reduced-motion).
- **Agent:** hook `PostToolUse` của Claude Code (mẫu ở phần tiếng Anh) ghi mọi thao tác đọc/sửa → hiệu ứng sao chổi, cú nhảy siêu không gian giữa các note, chuỗi truy xuất replay được, thanh tua cả ngày + dashboard per-agent. Agent khác truyền `--agent "Tên"` là có màu riêng.
- **Đọc & tìm:** click node đọc note ngay (wikilink, ảnh, backlink); kéo rail ngay ngoài mép phải Reader để co giãn ngang mà không đè scrollbar dọc, rail bám con trỏ tức thời, nhớ riêng độ rộng một-pane/hai-pane và tự clamp theo chỗ trống (click đúp reset, ←/→ chỉnh bằng bàn phím); click/Enter ảnh mở lightbox nội bộ với 100% tự nhiên, fit 80vw × 80vh, zoom neo con trỏ, pan clamp và menu copy/link/mở/tải có fallback đúng; cây thư mục kéo-giãn, `Ctrl+P` tìm note theo tên / `#tag` / nội dung không dấu và tìm file theo tên/đường dẫn/đuôi. Chọn attachment từ Reader, cây vault, graph hoặc hai ô tìm sẽ mở một menu chung: **Mở file · Hiện trong thư mục · Xem trong KB/Tải file**. Ảnh/PDF/text/media được xem; Office/archive tải tại chỗ không để lại cửa sổ app trống. Explorer dùng đúng `/select,"path"` kể cả đường dẫn có space/dấu phẩy; tab + 2 pane + ghim + lịch sử đọc vẫn persist.
- **Sức khoẻ vault:** 🩺 *truy xuất* (`/insight`) — note nóng tuần này so với tuần trước, note đang nguội đi, phân bố tuổi lần đụng cuối, note chưa bao giờ vào đường truy xuất, cụm ít kết nối trên đồ thị note–note, coverage theo khu vực; thêm hai descriptor taxonomy bằng TF-IDF lexical xác định: **B3 scope leakage** bắt section lá gần note anh em hơn note cha, còn **B4** đo tương quan Spearman giữa khoảng cách cây và khoảng cách nội dung. Một **worklist để người duyệt** chuyển số đo thành đề xuất có ưu tiên, ID ổn định, đích chính xác và bằng chứng: nối note chưa được thấy vào index tổ tiên gần nhất, giảm đọc lặp, rút ngắn chuỗi truy xuất dài, hoặc duyệt lại scope leak có margin cao. Worklist luôn ở chế độ `proposal_only`, bắt buộc người duyệt và không tự sửa hay di chuyển note (kèm CLI `python insight.py --report` sinh note báo cáo); 🧪 *toàn vẹn* (`/integrity`) — 4 check **cấu trúc** không cần cấu hình, bỏ qua wikilink/nhúng/heading minh hoạ trong inline code hoặc code fence, 1 check YAML thật báo đúng file/dòng/cột, và 5 check **contract** đọc luật của chính bạn. Click một mục là mở đúng note đó. CLI `python integrity.py` trả exit **0 sạch · 1 có lỗi · 2 thiếu PyYAML**; thiếu dependency thì đèn báo degraded, không xanh giả. Bật phép kiểm YAML bằng `python -m pip install pyyaml`. Bật 5 check đọc policy: chép `docs/vault-rules.example.json` ra gốc vault thành `vault-rules.json` (hoặc vào `.graph3d/`, hoặc trỏ `GRAPH3D_VAULT_RULES`) rồi **sửa theo vocabulary của bạn** — đây là bản mẫu, không phải bản dùng ngay; mỗi check chỉ đọc phần luật của nó nên khai một khoá là sáng đúng một đèn; không có file thì 5 đèn policy tự tắt êm, còn YAML + 4 check cấu trúc vẫn chạy.
- **Work map (tuỳ chọn):** vault nào giữ bản đồ việc-đang-mở dạng máy đọc thì app vẽ luôn thành **cây rẽ nhánh** — mỗi nhóm đọc từ trên xuống theo các tầng phụ thuộc còn hiển thị, mũi tên nghĩa là *phải xong trước*. Chuỗi dài nằm gọn trong khung, tiêu đề xuống dòng, tổ tiên đã đóng không để lại tầng trống; click một việc mở note đã khai nó; lọc "chỉ việc làm được" theo đúng máy đang ngồi. Vault đang xem cung cấp `work.json`; server chỉ nạp engine phân loại tin cậy từ vault của app, không thực thi script trong vault vừa chọn. `GRAPH3D_WORKMAP_DIR` chọn thư mục registry, `GRAPH3D_WORKMAP_ENGINE` chọn engine tin cậy có `export_data(cfg)`; cache theo mtime của cả hai. Thiếu một trong hai đầu vào thì endpoint trả 404 và panel nói rõ.
- **2 máy:** journal per-máy nằm trong vault — 2 máy sync chung vault (OneDrive/Drive/Syncthing) tự thấy lịch sử của nhau, máy thứ hai không cần chạy server.
- **Ngôn ngữ:** giao diện có **song ngữ VI/EN** — lần đầu tự nhận theo ngôn ngữ trình duyệt, đổi bằng nút **VI | EN** cạnh logo (nhớ lựa chọn). Nội dung của bạn không bị dịch: tên note, tag, nhóm màu, đường dẫn giữ nguyên như trong vault.
- **Cấu hình:** nhóm màu tag ở `TAG_COLORS` (`build_graph_data.py`) + `GROUP_ORDER` (`src/state.js`); loại folder ở `EXCLUDED_DIRS`; đổi port bằng `--port`. Taxonomy mặc định đang theo vault của tác giả — tách ra file config là mục roadmap số một.
- **Test:** `python tests/selfcheck.py` (~19s; thêm `--slow` cho test port/kill ~30s). Mỗi lượt có scratch theo run-id, nên clone private/public có thể tự kiểm song song mà không xoá fixture journal của nhau (v1.54.1). Từ v1.59.6, bộ test nào không đo được thì phải tự khai bằng dòng `[SKIP] <lý do>` và runner **đếm** các mục đó — nên `ALL PASS · BO QUA n muc` nghĩa là phần còn lại xanh. Clone chạy ngoài vault sẽ thấy vài mục như vậy, đúng như thiết kế. Từ **v1.60.0**, runner còn **đếm số khẳng định** mỗi mục vừa chạy thật và so với mốc lần trước: đo ít hơn — hoặc mất cả một bộ test — thì in `TUT VUNG PHU` và **exit 1 dù mọi bộ đều `ALL PASS`**, vì đó là cách duy nhất bắt được bộ bỏ qua *im lặng*. **Đọc mã thoát, đừng đọc chữ**; hạ mốc có chủ ý thì dùng `--chap-nhan "lý do"`.

Giấy phép [MIT](LICENSE).
