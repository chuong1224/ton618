# TON618 v2: upgrade and rollback

TON618 is the product name. KB Graph 3D is its graph view. Version 2 introduces the new product identity with compatibility for existing installations.

## What stays compatible

- Keep the physical `.graph3d` directory, Python entry points, local URL/port and browser profile. Do not move your vault or clear browser data.
- `Start-TON618.bat` delegates to `Start-Graph3D.bat` with the same arguments. Both remain supported.
- Run `python install_launcher.py` to add TON618 shortcuts. Existing KB Graph 3D shortcuts and their hotkeys remain valid. Avoid assigning the same hotkey twice.
- The launcher discovers both names and uses the packaged AUMID registered by Windows. It does not invent or rewrite an Edge package ID. Existing installed site-apps keep working; if both names exist, the exact TON618 title wins.
- `TON618_PWA_SHORTCUT` and `TON618_GITHUB_TOKEN` take precedence over their supported `GRAPH3D_` aliases.
- State stays at `%LOCALAPPDATA%/claude-graph3d` and under `kbgraph3d.*` browser keys. This deliberately avoids copying or splitting state: selected vault, workspace, pins, reading history and update consent are read in place. New and old versions use the same store, including edits after upgrading. Vault-scoped keys still isolate different vaults.
- Updates still require consent. Forks use their own origin. Pull remains `--ff-only` and requires a clean working tree.

## Repository and website

The canonical repository is https://github.com/chuong1224/ton618 (the same repository, renamed). GitHub redirects old Git URLs; do not recreate a repository at the old name. The updater maps the former canonical origin to TON618 while preserving fork origins. Update local clones with `git remote set-url origin https://github.com/chuong1224/ton618.git`. The new website is https://chuong1224.github.io/ton618/; the old Pages URL is retired and does not redirect.

## Roll back an installation

In a clean public clone, run `git checkout v1.60.5`, then open `Start-Graph3D.bat`. The TON618 shortcut also continues to work because its target is the unchanged entry point. Do not delete local state, change port, or choose a new browser profile. Detached checkouts cannot use the in-app update button; run `git switch main` before returning to normal updates.

The rename does not change note data or storage schemas. Existing documentation titles and historical screenshots may retain the former name.

## Nâng cấp và quay lui

TON618 là tên sản phẩm; KB Graph 3D là view đồ thị. Giữ nguyên thư mục `.graph3d`, địa chỉ/cổng, profile trình duyệt và dữ liệu. Chạy `python install_launcher.py` để thêm shortcut TON618; lối mở cũ và phím tắt vẫn dùng được. Hai tên dùng cùng nơi lưu workspace, ghim, lịch sử đọc, vault đã chọn và sự đồng ý kiểm tra cập nhật; không sao chép rồi để hai bản dữ liệu lệch nhau.

Để quay lui, tại clone public sạch chạy `git checkout v1.60.5`, rồi mở `Start-Graph3D.bat`. Không xoá thiết lập. Muốn cập nhật tiếp thì chạy `git switch main`. Tên note lịch sử và ảnh chụp cũ được giữ nguyên.
