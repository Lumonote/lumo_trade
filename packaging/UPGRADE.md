# Kronos 升级内容说明

本文档用于记录各版本的升级内容、兼容性变化与注意事项。打包脚本会根据 `packaging/version.json` 中的 `notes_file` 定位此文档。

## 版本管理约定
- 版本格式：`主版本.次版本.修订版本`（例如 `1.0.0`）
- 简短版本：`主版本.次版本`（例如 `1.0`），用于 macOS `CFBundleShortVersionString`
- 渠道：`stable`、`beta`、` nightly` 等，用于标识发布渠道（可选）
- 构建产物命名：`Kronos_v{version}_{platform}_{timestamp}`
  - `{platform}` 取值：`Windows` 或 `macOS`
  - `{timestamp}` 格式：`YYYYMMDD_HHMMSS`

## 1.0.0
- 初始统一版本命名规则：Windows 与 macOS 打包产物均包含版本号与时间戳后缀。
- macOS DMG 示例：`Kronos_v1.0.0_macOS_20250101_120000.dmg`
- Windows EXE 示例：`Kronos_v1.0.0_Windows_20250101_120000.exe`

## 修改流程
1. 更新 `packaging/version.json` 的 `version` 与 `short_version`。
2. 如有升级说明，补充本文件对应版本章节。
3. 触发打包脚本，产物将按约定自动命名。

## 注意事项
- macOS `Info.plist` 中将同步写入 `CFBundleShortVersionString` 与 `CFBundleVersion`。
- Windows 构建产物会复制到 `packaging/builds/` 目录下，便于统一管理。