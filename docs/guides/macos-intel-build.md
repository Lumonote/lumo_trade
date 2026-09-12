# macOS Intel（x86_64）打包指南

> ⚠️ **本文档已过时（历史记录）**：文中「在 Apple Silicon 机器上经 Rosetta 搭 x86_64 venv 本地构建」的方案
> 已被 CI 取代——`.github/workflows/build.yml` 的构建矩阵现在直接用 GitHub 托管的 **`macos-15-intel`**
> 原生 Intel runner 产出 `*.dmg`（x64），不需要 Rosetta、不需要本地 x86_64 venv，§4 的五处补丁也未并入。
> 当前安装与打包说明见 [README「快速开始」](../../README.md#快速开始)。本文仅保留当时的方案推演。

> 关联 spec：[`2026-05-31-v2-ux-and-data-completion-design.md`](../superpowers/specs/2026-05-31-v2-ux-and-data-completion-design.md) 模块 F。
> 本期产出**独立 x86_64 dmg**（非 Universal2 单包——torch 等重型 wheel 缺 universal2）。

## 1. 目标与现状

- 现状：`packaging/scripts/build_universal.sh` 无架构标志，PyInstaller 后端与 `tauri build`
  均产出**宿主机原生架构**（Apple Silicon → arm64，产物 `*_aarch64.dmg`）。
- 目标：在 Apple Silicon 机器上经 Rosetta 产出可在 Intel Mac / Rosetta 运行的 `*_x86_64.dmg`。

## 2. 架构决定因素（两条独立链，都要切到 x86_64）

| 链 | 谁决定架构 | x86_64 做法 |
|---|---|---|
| **PyInstaller 后端** | 跑 `build_backend.py` 的 **Python 解释器**架构（脚本用 `sys.executable -m PyInstaller`） | 用 x86_64（Rosetta）Python venv 调它 |
| **Tauri / Rust 壳** | `tauri build --target <triple>` | `--target x86_64-apple-darwin` |

> 因此 **`build_backend.py` 无需改动**——它的产物架构完全随调用它的解释器走。x86_64 改动**全部落在
> `build_universal.sh`**（选 x86_64 解释器 + 透传 tauri target + 修正产物路径）。
> 后端以 Tauri **resource** 形式嵌入（`src-tauri/tauri.conf.json` 第 58 行），故必须**先**产出 x86_64
> 后端，**再** `tauri build`，壳才会打包到正确架构的后端。

## 3. 一次性环境搭建

```bash
# 3.1 Rosetta（Apple Silicon 上跑 x86_64 进程）
softwareupdate --install-rosetta --agree-to-license

# 3.2 Rust x86_64 target
rustup target add x86_64-apple-darwin

# 3.3 x86_64 Python venv（关键：解释器与所有 wheel 都要 x86_64）
#   用 Rosetta 下的 x86_64 Homebrew Python（/usr/local/...），或任意 x86_64 python3.11+。
arch -x86_64 /usr/local/bin/python3.11 -m venv .venv-x86_64
arch -x86_64 .venv-x86_64/bin/python -m pip install --upgrade pip
arch -x86_64 .venv-x86_64/bin/python -m pip install -r requirements.txt pyinstaller

# 3.4 校验解释器确为 x86_64
.venv-x86_64/bin/python -c "import platform; print(platform.machine())"   # 期望 x86_64
```

> **wheel 风险**（spec §7.3）：torch/onnx 等需逐一确认有 x86_64 wheel。
> **规避**：后端默认 `--mode lite` 已排除 torch/modelscope（见 `build_backend.py` `--mode`），
> Intel 构建优先用 lite，可绕开 torch 的 x86_64 wheel 问题；如需 `full`，须先确认 x86_64 torch 可装。

## 4. build_universal.sh 待集成补丁（gated，不动 arm64 默认路径）

> ⚠️ 截至本指南撰写，`build_universal.sh` / `build_backend.py` / `kronos_webui_backend.spec`
> 正处于**他人未提交改动**中（整条打包工具链在重构）。为遵循 [[clean-commit-on-shared-dirty-branch]]，
> 本补丁**未直接写入脚本**，待该 WIP 落地后再并入，避免同文件 hunk 缠绕。
> 下列片段均已 `bash -n` 语法校验，并验证参数展开在「带/不带 target」两种情况下行为正确。

新增平台 `macos-intel`：经环境变量 `KRONOS_TARGET_ARCH` / `TAURI_TARGET` 驱动，不设时一切照旧。

**(1) 新增解释器选择函数**（置于 `check_python` 附近）：

```bash
# 选择目标架构的 Python 解释器（Intel x86_64 构建用）。
# 置 PYTHON_CMD 后，既有 check_python 会校验其版本并复用（其 candidates 以 ${PYTHON_CMD:-} 起头）。
resolve_target_python() {
    [ "${KRONOS_TARGET_ARCH:-}" = "x86_64" ] || return 0
    local venv="${KRONOS_X86_VENV:-$PROJECT_ROOT/.venv-x86_64}"
    local py="$venv/bin/python"
    if [ ! -x "$py" ]; then
        echo -e "${RED}❌ 未找到 x86_64 venv: $py${NC}"
        echo -e "${YELLOW}💡 见 docs/guides/macos-intel-build.md 第 3 节搭建 Rosetta x86_64 venv${NC}"
        exit 1
    fi
    # 校验解释器确为 x86_64（避免误用原生 arm Python）
    if ! "$py" -c 'import platform,sys; sys.exit(0 if platform.machine()=="x86_64" else 1)' 2>/dev/null; then
        echo -e "${RED}❌ $py 不是 x86_64 解释器（machine != x86_64）${NC}"
        exit 1
    fi
    PYTHON_CMD="$py"
    echo -e "${GREEN}🎯 Intel 构建：使用 x86_64 解释器 $py${NC}"
}
```

**(2) `build_bundled_backend()` 开头**调用它（在 `check_python` 之前）：

```bash
build_bundled_backend() {
    if [ "${KRONOS_SKIP_BACKEND_BUNDLE:-0}" = "1" ]; then
        echo -e "${YELLOW}⚠️  已跳过内置 WebUI backend 构建${NC}"
        return 0
    fi
    resolve_target_python      # ← 新增：x86_64 时改写 PYTHON_CMD
    echo -e "${BLUE}📦 构建内置 WebUI backend (PyInstaller)...${NC}"
    check_python
    # ... 其余照旧 ...
}
```

**(3) `build_tauri_desktop()` 的构建命令**透传 target：

```bash
    # 原：npm run desktop:build
    if [ -n "${TAURI_TARGET:-}" ]; then
        npm run desktop:build -- --target "$TAURI_TARGET"
    else
        npm run desktop:build
    fi
```

**(4) `copy_tauri_artifacts()` 的 `bundle_dir`** 必须含 target 子目录（否则拷不到 x86_64 产物）：

```bash
    # 原：local bundle_dir="$PROJECT_ROOT/src-tauri/target/release/bundle"
    local bundle_dir="$PROJECT_ROOT/src-tauri/target/${TAURI_TARGET:+$TAURI_TARGET/}release/bundle"
```

> `tauri build --target x86_64-apple-darwin` 的产物落在 `target/x86_64-apple-darwin/release/bundle`，
> 不带 `--target` 才是 `target/release/bundle`。`${TAURI_TARGET:+$TAURI_TARGET/}` 仅在设值时插入
> `x86_64-apple-darwin/`，default 路径不变。

**(5) 参数解析 / 分发**新增 `macos-intel` 平台：

```bash
# show_help() 平台列表追加：
#   macos-intel    - 经 Rosetta 构建 macOS Intel(x86_64) 版本

# main() 内 case $PLATFORM 追加分支（紧邻 "macos")）：
        "macos-intel")
            export KRONOS_TARGET_ARCH="x86_64"
            export TAURI_TARGET="x86_64-apple-darwin"
            build_macos
            ;;
```

> 注：`main()` 中「是否跳过 Docker」的判断含 `[ "$PLATFORM" = "macos" ]`，需一并加上
> `|| [ "$PLATFORM" = "macos-intel" ]`，确保 Intel 走本地构建链。

## 5. 构建与验证

```bash
# 集成补丁后：
./packaging/scripts/build_universal.sh macos-intel --clean
```

验证（前两项本机可验，第三项需 Intel/Rosetta 实机）：

```bash
# 5.1 后端二进制为 x86_64
file packaging/backend/kronos_webui_backend/kronos_webui_backend
#   期望: Mach-O 64-bit executable x86_64

# 5.2 .app 主程序为 x86_64
file src-tauri/target/x86_64-apple-darwin/release/bundle/macos/*.app/Contents/MacOS/*
#   期望: Mach-O 64-bit executable x86_64

# 5.3 dmg 在 Intel Mac 或 `arch -x86_64` 下启动冒烟（需实机/CI runner）
```

## 6. 限制与后续

- **二进制未在本环境验证**：撰写时无 Intel/Rosetta 构建环境，§4 补丁仅经语法 + 参数展开校验；
  实际 x86_64 产物与启动需在 Intel 机 / CI runner 上跑通后方可标记模块 F 验收完成（spec §7.3 同此口径）。
- **集成时机**：待打包工具链（`build_universal.sh`/`build_backend.py`/`.spec`）的在途未提交改动落地后，
  再把 §4 五处补丁并入，单独提交。
- **签名**：`build_backend.py` 的 `_adhoc_codesign_macos` 对 dylib/.so/主程序 ad-hoc 重签，
  架构无关，x86_64 产物同样适用，无需改。
- **开放问题**（spec §10）：是否在本仓 CI 增 x86_64 构建任务，还是仅保留本地脚本 + 本指南，待定。
