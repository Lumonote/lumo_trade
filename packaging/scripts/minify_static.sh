#!/usr/bin/env bash
# 源码保护（务实级）：打包前压缩混淆前端静态资源。
#
# webui/static/kronos_desktop_app.js（~633KB）是明文开发格式，原样打进 app
# 后既能被直接阅读，也暴露了大量符号/逻辑。本脚本用 terser 做压缩 + 混淆
# (mangle) + 去注释，原地替换 webui/static 下的 .js（dev 文件由 git 保留原版，
# 这里仅作用于打包产物的源；如需还原创原版 `git checkout -- webui/static/`）。
#
# 与 build_universal.sh 集成：在 `npm run desktop:build` 之前调用本脚本。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATIC_DIR="$PROJECT_ROOT/webui/static"

if [ ! -d "$STATIC_DIR" ]; then
  echo "[minify] webui/static 不存在，跳过" >&2
  exit 0
fi

cd "$PROJECT_ROOT"

# 优先用本地 node_modules 的 terser；缺失则临时 npx 拉取。
if [ -x "node_modules/.bin/terser" ]; then
  TERSER="./node_modules/.bin/terser"
else
  if ! command -v npx >/dev/null 2>&1; then
    echo "[minify] 未找到 terser 且无 npx，跳过前端压缩" >&2
    exit 0
  fi
  TERSER="npx --yes terser"
fi

# CSS 用 esbuild（若可用），否则跳过 CSS 压缩（不影响 JS 保护）。
CSS_MIN=""
if [ -x "node_modules/.bin/esbuild" ]; then
  CSS_MIN="./node_modules/.bin/esbuild"
elif command -v esbuild >/dev/null 2>&1; then
  CSS_MIN="esbuild"
fi

echo "[minify] 压缩混淆前端静态资源..."

for js in "$STATIC_DIR"/*.js; do
  [ -f "$js" ] || continue
  name="$(basename "$js")"
  # --compress 去注释/死代码/折行；--mangle 混淆变量名；不生成 sourcemap（防泄漏映射）。
  if $TERSER "$js" --compress --mangle --comments=false -o "$js.min" 2>/dev/null; then
    mv "$js.min" "$js"
    echo "  ✔ $name ($(wc -c < "$js") bytes)"
  else
    echo "  ✘ $name 压缩失败，保留原文件" >&2
    rm -f "$js.min"
  fi
done

if [ -n "$CSS_MIN" ]; then
  for css in "$STATIC_DIR"/*.css; do
    [ -f "$css" ] || continue
    name="$(basename "$css")"
    if $CSS_MIN "$css" --minify --loader=css -o "$css.min" 2>/dev/null; then
      mv "$css.min" "$css"
      echo "  ✔ $name ($(wc -c < "$css") bytes)"
    else
      echo "  ✘ $name CSS 压缩失败，保留原文件" >&2
      rm -f "$css.min"
    fi
  done
else
  echo "[minify] 未找到 esbuild，跳过 CSS 压缩（JS 已保护）"
fi

echo "[minify] 完成。dev 原版可由 git 恢复：git checkout -- webui/static/"
