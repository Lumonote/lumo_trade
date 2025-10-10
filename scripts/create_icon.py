#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos AI股票分析应用图标生成器
创建现代化的AI股票分析主题图标
"""

from PIL import Image, ImageDraw, ImageFont
import os
from pathlib import Path


def create_kronos_icon():
    """创建Kronos AI股票分析图标"""
    # 图标尺寸（macOS需要多个尺寸）
    sizes = [16, 32, 64, 128, 256, 512, 1024]

    # 创建assets目录
    assets_dir = Path(__file__).parent.parent / "assets"
    assets_dir.mkdir(exist_ok=True)

    # 主要颜色 - AI和金融主题
    bg_color = "#1E40AF"  # 深蓝色背景 - 代表AI技术
    ai_color = "#10B981"  # 绿色 - 代表AI和盈利
    chart_color = "#F59E0B"  # 橙色 - 代表增长和图表
    arrow_color = "#10B981"  # 绿色箭头 - 代表上涨
    text_color = "#FFFFFF"  # 白色文字

    images = []

    for size in sizes:
        # 创建画布
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 计算比例
        scale = size / 512.0

        # 1. 绘制背景 - 圆角矩形
        corner_radius = int(size * 0.2)  # 20% 圆角

        draw.rounded_rectangle(
            [0, 0, size, size],
            corner_radius,
            fill=bg_color
        )

        # 2. 绘制AI芯片图案 - 左上角
        chip_size = int(size * 0.22)
        chip_x = int(size * 0.12)
        chip_y = int(size * 0.12)

        # AI芯片主体
        draw.rounded_rectangle(
            [chip_x, chip_y, chip_x + chip_size, chip_y + chip_size],
            int(chip_size * 0.15),
            fill=ai_color
        )

        # 芯片引脚
        pin_width = int(chip_size * 0.08)
        pin_height = int(chip_size * 0.12)

        # 左侧引脚
        for i in range(3):
            pin_y = chip_y + int(chip_size * 0.2) + i * int(chip_size * 0.25)
            draw.rectangle([chip_x - pin_width, pin_y, chip_x, pin_y + pin_height], fill=text_color)

        # 右侧引脚
        for i in range(3):
            pin_y = chip_y + int(chip_size * 0.2) + i * int(chip_size * 0.25)
            draw.rectangle([chip_x + chip_size, pin_y, chip_x + chip_size + pin_width, pin_y + pin_height],
                           fill=text_color)

        # AI文字
        if size >= 64:
            try:
                font_size = int(chip_size * 0.3)
                font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
            except:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), "AI", font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            text_x = chip_x + (chip_size - text_width) // 2
            text_y = chip_y + (chip_size - text_height) // 2
            draw.text((text_x, text_y), "AI", fill=text_color, font=font)

        # 3. 绘制股票图表 - 右侧
        chart_width = int(size * 0.35)
        chart_height = int(size * 0.25)
        chart_x = int(size * 0.55)
        chart_y = int(size * 0.3)

        # 图表背景
        draw.rounded_rectangle(
            [chart_x, chart_y, chart_x + chart_width, chart_y + chart_height],
            int(chart_width * 0.05),
            fill=(255, 255, 255, 25),  # 半透明白色
            outline=text_color,
            width=max(1, int(1 * scale))
        )

        # K线图形 - 多个竖线表示K线
        line_count = 6
        line_spacing = chart_width // (line_count + 1)

        # 预定义K线数据 (开盘、收盘、最高、最低的相对位置)
        kline_data = [
            (0.7, 0.6, 0.8, 0.5),  # 上涨
            (0.6, 0.8, 0.9, 0.5),  # 上涨
            (0.8, 0.7, 0.8, 0.6),  # 下跌
            (0.7, 0.9, 0.95, 0.6),  # 上涨
            (0.9, 0.85, 0.9, 0.8),  # 下跌
            (0.85, 0.95, 1.0, 0.8)  # 上涨
        ]

        for i, (open_p, close_p, high_p, low_p) in enumerate(kline_data):
            x = chart_x + (i + 1) * line_spacing
            line_width = max(2, int(line_spacing * 0.6))

            # 计算实际坐标
            open_y = chart_y + int(chart_height * (1 - open_p))
            close_y = chart_y + int(chart_height * (1 - close_p))
            high_y = chart_y + int(chart_height * (1 - high_p))
            low_y = chart_y + int(chart_height * (1 - low_p))

            # K线颜色 - 绿色上涨，红色下跌
            color = ai_color if close_p > open_p else "#EF4444"

            # 绘制实体
            body_top = min(open_y, close_y)
            body_bottom = max(open_y, close_y)
            draw.rectangle(
                [x - line_width // 2, body_top, x + line_width // 2, body_bottom],
                fill=color
            )

            # 绘制上下影线
            draw.line([x, high_y, x, low_y], fill=color, width=max(1, int(1 * scale)))

        # 趋势线
        if size >= 64:
            trend_points = []
            for i in range(line_count):
                x = chart_x + (i + 1) * line_spacing
                # 整体上升趋势
                trend_y = chart_y + chart_height - int(chart_height * (0.5 + i * 0.08))
                trend_points.extend([x, trend_y])

            if len(trend_points) >= 4:
                draw.line(trend_points, fill=chart_color, width=max(2, int(2 * scale)))

        # 4. 绘制趋势箭头 - 右上角
        arrow_size = int(size * 0.12)
        arrow_x = int(size * 0.75)
        arrow_y = int(size * 0.15)

        # 向上箭头
        arrow_points = [
            (arrow_x + arrow_size // 2, arrow_y),  # 顶点
            (arrow_x, arrow_y + arrow_size // 2),  # 左点
            (arrow_x + arrow_size // 3, arrow_y + arrow_size // 2),  # 左内点
            (arrow_x + arrow_size // 3, arrow_y + arrow_size),  # 左下
            (arrow_x + arrow_size * 2 // 3, arrow_y + arrow_size),  # 右下
            (arrow_x + arrow_size * 2 // 3, arrow_y + arrow_size // 2),  # 右内点
            (arrow_x + arrow_size, arrow_y + arrow_size // 2),  # 右点
        ]

        draw.polygon(arrow_points, fill=arrow_color)

        # 5. 绘制货币符号 - 底部
        if size >= 64:
            dollar_size = int(size * 0.15)
            dollar_x = int(size * 0.4)
            dollar_y = int(size * 0.75)

            # 美元符号背景圆
            draw.ellipse(
                [dollar_x, dollar_y, dollar_x + dollar_size, dollar_y + dollar_size],
                fill=(16, 185, 129, 50),  # 半透明绿色
                outline=ai_color,
                width=max(1, int(2 * scale))
            )

            # 美元符号
            try:
                font_size = int(dollar_size * 0.6)
                font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
            except:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), "$", font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            text_x = dollar_x + (dollar_size - text_width) // 2
            text_y = dollar_y + (dollar_size - text_height) // 2
            draw.text((text_x, text_y), "$", fill=ai_color, font=font)

        # 5. 添加货币符号 - 底部
        if size >= 64:  # 只在较大尺寸上显示文字
            try:
                # 尝试使用系统字体
                font_size = max(int(size * 0.08), 8)
                # 使用默认字体
                font = ImageFont.load_default()

                # 绘制¥符号
                symbol = "¥"
                # 获取文本尺寸
                bbox = draw.textbbox((0, 0), symbol, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                text_x = (size - text_width) // 2
                text_y = int(size * 0.8)

                draw.text((text_x, text_y), symbol, fill="#F59E0B", font=font)

            except Exception:
                # 如果字体加载失败，跳过文字
                pass

        images.append(img)

    # 保存为ICO文件 (Windows)
    ico_path = assets_dir / "kronos_ai_stock.ico"
    images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes])
    print(f"✅ Windows图标已创建: {ico_path}")

    # 保存为PNG文件 (各种用途)
    png_path = assets_dir / "kronos_ai_stock.png"
    images[-1].save(png_path, format='PNG')
    print(f"✅ PNG图标已创建: {png_path}")

    # 创建macOS ICNS文件需要使用iconutil工具
    # 首先创建iconset目录结构
    iconset_dir = assets_dir / "kronos_ai_stock.iconset"
    iconset_dir.mkdir(exist_ok=True)

    # macOS iconset文件命名规范
    iconset_files = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    # 保存各种尺寸的PNG文件
    for i, (target_size, filename) in enumerate(iconset_files):
        # 找到对应尺寸的图像
        img_index = sizes.index(target_size)
        images[img_index].save(iconset_dir / filename, format='PNG')

    print(f"✅ macOS iconset已创建: {iconset_dir}")

    return ico_path, png_path, iconset_dir


def create_icns_file():
    """使用iconutil创建ICNS文件"""
    assets_dir = Path(__file__).parent.parent / "assets"
    iconset_dir = assets_dir / "kronos_ai_stock.iconset"
    icns_path = assets_dir / "kronos_ai_stock.icns"

    if iconset_dir.exists():
        import subprocess
        try:
            # 使用macOS的iconutil工具创建ICNS文件
            result = subprocess.run([
                'iconutil', '-c', 'icns', str(iconset_dir), '-o', str(icns_path)
            ], check=True, capture_output=True, text=True)

            print(f"✅ macOS ICNS文件已创建: {icns_path}")
            return icns_path

        except subprocess.CalledProcessError as e:
            print(f"⚠️  iconutil失败: {e}")
            print("💡 将PNG文件重命名为ICNS作为备用方案")

            # 备用方案：将最大的PNG文件复制为ICNS
            png_path = assets_dir / "kronos_ai_stock.png"
            if png_path.exists():
                import shutil
                shutil.copy2(png_path, icns_path)
                print(f"✅ 备用ICNS文件已创建: {icns_path}")
                return icns_path
        except FileNotFoundError:
            print("⚠️  iconutil工具未找到，使用备用方案")
            # 备用方案
            png_path = assets_dir / "kronos_ai_stock.png"
            if png_path.exists():
                import shutil
                shutil.copy2(png_path, icns_path)
                print(f"✅ 备用ICNS文件已创建: {icns_path}")
                return icns_path

    return None


if __name__ == "__main__":
    print("🎨 开始创建Kronos AI股票分析图标...")

    try:
        ico_path, png_path, iconset_dir = create_kronos_icon()
        icns_path = create_icns_file()

        print("\n🎉 图标创建完成！")
        print("📁 创建的文件:")
        print(f"  🖼️  PNG: {png_path}")
        print(f"  🪟 ICO: {ico_path}")
        if icns_path:
            print(f"  🍎 ICNS: {icns_path}")
        print(f"  📦 IconSet: {iconset_dir}")

        print("\n💡 图标设计说明:")
        print("  🤖 左上角：AI大脑/芯片 - 代表人工智能技术")
        print("  📊 右侧：K线图表 - 代表股票分析")
        print("  ⬆️  右上角：向上箭头 - 代表增长趋势")
        print("  💰 底部：货币符号 - 代表金融投资")
        print("  🎨 配色：蓝色(AI技术) + 绿色(盈利) + 橙色(增长)")

    except Exception as e:
        print(f"❌ 图标创建失败: {e}")
        import traceback

        traceback.print_exc()
