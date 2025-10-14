#!/bin/bash
# Kronos 一键打包脚本（使用kronos_macos.spec）

set -e

echo "🚀 Kronos 一键打包工具"
echo "======================"
echo ""

# 检查当前目录
if [ ! -f "kronos_macos.spec" ]; then
    echo "❌ 错误：未找到 kronos_macos.spec"
    echo "   请在Kronos项目根目录下运行此脚本"
    exit 1
fi

# 检查Python和PyInstaller
echo "📋 检查环境..."
python --version || { echo "❌ Python未安装"; exit 1; }

if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "📦 安装PyInstaller..."
    pip install pyinstaller
fi

# 验证修复代码存在
echo "🔍 验证价格断层修复代码..."
if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" examples/prediction_batch_example.py; then
    echo "✅ 价格断层修复代码已包含"
else
    echo "❌ 警告：未找到价格断层修复代码"
    echo "   请确认 examples/prediction_batch_example.py 包含修复代码"
    read -p "是否继续打包？(y/n): " CONTINUE
    if [ "$CONTINUE" != "y" ]; then
        exit 1
    fi
fi

# 清理旧文件
echo "🧹 清理构建文件..."
rm -rf build/ dist/ packaging/builds/*.dmg packaging/builds/*.exe 2>/dev/null || true

# 运行PyInstaller
echo "⚙️ 开始打包（使用 kronos_macos.spec）..."
pyinstaller --clean --noconfirm kronos_macos.spec

# 检查结果
if [ ! -d "dist/Kronos.app" ]; then
    echo "❌ 打包失败，未找到 Kronos.app"
    exit 1
fi

echo "✅ macOS应用包创建成功！"

# 验证打包结果
echo ""
echo "🔍 验证打包结果..."

# 检查examples目录是否被打包
if [ -d "dist/Kronos/examples" ]; then
    echo "✅ examples/ 目录已打包到 dist/Kronos/examples/"

    if [ -f "dist/Kronos/examples/prediction_batch_example.py" ]; then
        echo "✅ prediction_batch_example.py 已包含"

        # 验证修复代码
        if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" dist/Kronos/examples/prediction_batch_example.py; then
            echo "✅ 修复代码已正确包含到打包文件中"
        else
            echo "❌ 警告：打包的文件中不包含修复代码"
        fi
    else
        echo "❌ 警告：prediction_batch_example.py 未找到"
    fi
elif [ -d "dist/Kronos.app/Contents/Resources/examples" ]; then
    echo "✅ examples/ 目录在 .app/Contents/Resources/ 中"

    if [ -f "dist/Kronos.app/Contents/Resources/examples/prediction_batch_example.py" ]; then
        echo "✅ prediction_batch_example.py 已包含到.app包"

        # 验证修复代码
        if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" "dist/Kronos.app/Contents/Resources/examples/prediction_batch_example.py"; then
            echo "✅ 修复代码已正确包含到.app包中"
        else
            echo "❌ 警告：.app包中的文件不包含修复代码"
        fi
    else
        echo "❌ 警告：.app包中未找到 prediction_batch_example.py"
    fi
else
    echo "❌ 错误：examples/ 目录未被打包！"
    echo "   spec文件配置可能有问题"
    exit 1
fi

# 创建DMG（可选）
echo ""
read -p "是否创建DMG安装包？(y/n): " CREATE_DMG

if [ "$CREATE_DMG" = "y" ]; then
    echo "💿 创建DMG安装包..."
    mkdir -p packaging/builds
    TS=$(date +%Y%m%d_%H%M%S)
    VERSION=$(python3 -c 'import json;print(json.load(open("packaging/version.json"))['"'version'"'])' 2>/dev/null)
    if [ -z "$VERSION" ]; then VERSION="1.0.0"; fi
    DMG_PATH="packaging/builds/Kronos_v${VERSION}_macOS_${TS}.dmg"
    rm -f "$DMG_PATH"

    hdiutil create -volname "Kronos" -srcfolder "dist/Kronos.app" -ov -format UDZO "$DMG_PATH"

    if [ -f "$DMG_PATH" ]; then
        SIZE=$(du -h "$DMG_PATH" | cut -f1)
        echo "✅ DMG安装包创建成功！"
        echo "📏 安装包大小: $SIZE"
        echo "📦 位置: $DMG_PATH"
    else
        echo "❌ DMG创建失败"
    fi
fi

# 清理临时文件
echo ""
echo "🎉 打包完成！"
echo "📁 应用位置: dist/Kronos.app"
echo ""
echo "🧪 建议测试步骤："
echo "1. 运行打包的应用"
echo "2. 测试股票 300290 的批量预测功能"
echo "3. 检查预测图表中的价格连续性"
echo ""
