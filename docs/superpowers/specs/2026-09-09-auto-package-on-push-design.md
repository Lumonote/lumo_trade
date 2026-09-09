# V2.1.4：push 自动打包 + tag 自动发 Release

日期：2026-09-09
分支：V2.1.4（自 V2.1.3 切出，工作区已暂存的 kronos→lumo 改名一并带入）

## 背景

工作区暂存了 92 个文件的 kronos→lumo 改名。审查后确认改名主体自洽，但留下 4 处问题；
同时现有 CI（`.github/workflows/build.yml`）的触发分支仍停在 `V2.1.2`，新分支推上去不会触发打包。

## 决策

| 项 | 选择 | 理由 |
|---|---|---|
| 打包方式 | GitHub Actions 云端打包 | 不占本机资源，三平台并行 |
| 产物交付 | 分支 push→Actions Artifacts；push `v*` tag→GitHub Release | Artifacts 会过期，Release 便于分发 |
| 测试包 | 非 main、非 tag 的分支 push 也构建，产物名带 `-test`、保留 7 天 | 每个分支推上去都能拿到可下载的测试包 |
| 数据目录常量 | 统一到 `com.lumo.trade` | 与 `tauri.conf.json` identifier 一致，且避开 Tauri 对 `.app` 结尾 bundle id 的告警 |
| 分支创建 | 由 Claude 执行 `git checkout -b V2.1.4` | 用户明确要求 |

## 一、修复项

### 1. favicon 404（会挂测试）

`webui/robyn_app.py:432` 仍读 `assets/kronos_ai_stock.ico`，该文件已改名为 `lumo_ai_stock.ico`。

```python
_file_response(_safe_child_path(webui_core.PROJECT_ROOT / "assets", "lumo_ai_stock.ico"))
```

失败测试：`tests/test_license_gate.py::test_gate_whitelists_activation_surface`。

### 2. 用户数据目录分裂

`src-tauri/tauri.conf.json:6` 的 identifier 是 `com.lumo.trade`，但三处常量仍是 `com.lumo.app`。
`src-tauri/src/main.rs:155,423,518` 用 `app.path().app_data_dir()`（由 identifier 决定）注入
`KRONOS_USER_DIR`，因此打包 App 写 `.../com.lumo.trade`，而 dev/CLI 写 `.../com.lumo.app`。

统一改成 `com.lumo.trade`：

- `webui/services/paths.py:17` — `user_root(app_name: str = "com.lumo.trade")`
- `packaging/scripts/lumo_webui_backend.py:12` — `CANONICAL_USER_DIR_NAME = "com.lumo.trade"`
- `packaging/scripts/lumo_macos.spec:114` — `bundle_identifier='com.lumo.trade'`

无测试断言该常量，改动安全。副作用：dev/CLI 数据目录随之变为
`~/Library/Application Support/com.lumo.trade`，旧数据（`com.kronos.app`）需另行迁移，不在本 spec 范围。

### 3. `lumo_app.py` 工作区被清空

索引中为 30316 字节，磁盘上为 0 字节。`tools/launchers/lumo_universal.py`、
`tools/launchers/lumo_modern_gui.py` 均 `from lumo_app import main`。

恢复方式（读操作 + 重定向，不执行 git 写命令）：

```bash
git show :lumo_app.py > lumo_app.py
```

### 4. CI 触发分支与产物名过期

见下节。

## 二、CI 设计

```yaml
on:
  push:
    branches: ["**"]      # 所有分支：main 出正式包，其余出测试包
    tags: ["v*"]
  pull_request:
    branches: [V2.1.4]
  workflow_dispatch:
```

- **build job**：三平台矩阵不变（macos-latest / windows-latest / ubuntu-latest）。
  产物名由 job 级 `PACKAGE_KIND` 决定：

  | 触发 | PACKAGE_KIND | Artifact 名 | 保留 |
  |---|---|---|---|
  | 非 main、非 tag 分支 push | `test` | `Lumo-<平台>-test` | 7 天 |
  | main 分支 push / `v*` tag | `release` | `Lumo-<平台>-release` | 14 天 |
  | pull_request | `test`（ref_name 为 `<n>/merge`） | `Lumo-<平台>-test` | 7 天 |

- **release job**（新增）：
  - `if: startsWith(github.ref, 'refs/tags/v')`、`needs: build`、`permissions: contents: write`
  - `actions/download-artifact@v4`（`path: dist`、`merge-multiple: true`）拉齐三平台产物
  - `softprops/action-gh-release@v2` 发布，`generate_release_notes: true`
  - 只附文件：`dist/*.dmg`、`*.exe`、`*.msi`、`*.deb`、`*.AppImage`、`*.rpm`；
    排除 `.app` 目录（GitHub Release 只接受文件，`.app` 已包含在 `.dmg` 内）

## 三、实施顺序

1. `git checkout -b V2.1.4` ✅ 已完成
2. 修复项 1、2、3
3. 改写 `.github/workflows/build.yml`
4. 验证：`pytest tests/test_license_gate.py tests/test_desktop_packaging_parity.py` +
   `python -c "import yaml; yaml.safe_load(open('.github/workflows/build.yml'))"`
5. 不提交，停在工作区，输出 `git add` 清单

## 四、验证标准

- `tests/test_license_gate.py::test_gate_whitelists_activation_surface` 转绿
- 全仓 `git grep kronos_ai_stock.ico` 无命中（docs 除外）
- 三处用户目录常量与 `tauri.conf.json` identifier 一致
- `lumo_app.py` 恢复为 30316 字节
- workflow YAML 可解析，release job 仅在 tag push 时进入

## 五、风险与已知限制

- GitHub Actions 无法本地执行，真实跑通需用户 push 后在 Actions 页确认。
- 打包 App 需重新打包才能生效（identifier 与后端可执行名均变化）。
- 旧的 `com.kronos.app` 用户数据不会自动迁移。
