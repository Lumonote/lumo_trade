#!/usr/local/bin/python3.11
"""
Kronos macOS现代化GUI - Big Sur/Monterey风格
采用Apple最新设计语言：毛玻璃效果、圆角、阴影和现代化控件
使用具有完整tkinter支持的系统Python环境
"""

import sys
import os
import json
import hashlib
import platform
import subprocess
import threading
import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path
import webbrowser

# 首先尝试导入tkinter
HAS_TKINTER = False
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, font as tkFont, scrolledtext

    HAS_TKINTER = True
except ImportError:
    pass

# PIL是可选的
HAS_PIL = False
try:
    from PIL import Image, ImageTk, ImageFilter, ImageDraw

    HAS_PIL = True
except ImportError:
    pass

import tempfile

# 添加项目路径 - 修复打包后的路径问题
if getattr(sys, 'frozen', False):
    # 如果是打包后的应用
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 临时目录
        project_root = Path(sys._MEIPASS)
    else:
        # 回退方案 - 修复.app包路径
        executable_path = Path(sys.executable)
        if ".app" in str(executable_path):
            # 在.app包内，查找正确的Resources目录
            app_path = None
            current = executable_path
            while current.parent != current:
                if current.name.endswith('.app'):
                    app_path = current
                    break
                current = current.parent

            if app_path:
                project_root = app_path / "Contents" / "Resources"
            else:
                # 备选方案：从当前路径推断
                executable_str = str(executable_path)
                if "/Contents/" in executable_str:
                    contents_index = executable_str.find("/Contents/")
                    app_root = executable_str[:contents_index + len("/Contents")]
                    project_root = Path(app_root) / "Resources"
                else:
                    project_root = executable_path.parent.parent / "Resources"
        else:
            project_root = executable_path.parent
else:
    # 开发环境
    project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))


# 全局Python命令检测
def detect_python_command():
    """检测系统中最适合的Python命令，优先使用pyenv管理的Python"""

    # 首先尝试使用pyenv中的Python 3.11.13
    try:
        # 检查pyenv是否可用
        pyenv_path = shutil.which('pyenv')
        if pyenv_path:
            # 尝试获取pyenv global版本
            result = subprocess.run([pyenv_path, 'global'],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                global_version = result.stdout.strip()
                print(f"检测到pyenv全局版本: {global_version}")

                # 如果是3.11.x版本，直接使用pyenv中的python
                if global_version.startswith('3.11.'):
                    # 尝试获取pyenv python路径
                    result = subprocess.run([pyenv_path, 'which', 'python'],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        pyenv_python = result.stdout.strip()
                        print(f"使用pyenv Python: {pyenv_python}")
                        return pyenv_python

                # 检查是否有可用的3.11.13版本
                result = subprocess.run([pyenv_path, 'versions', '--bare'],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    versions = result.stdout.strip().split('\n')
                    for version in versions:
                        if version.startswith('3.11.'):
                            # 尝试使用特定版本的python
                            try:
                                result = subprocess.run([pyenv_path, 'exec', '-g', version, 'python', '--version'],
                                                        capture_output=True, text=True, timeout=5)
                                if result.returncode == 0:
                                    print(f"使用pyenv Python {version}")
                                    return f"{pyenv_path} exec python"
                            except:
                                continue
    except Exception as e:
        print(f"pyenv检测失败: {e}")

    # 在应用包内部，sys.executable指向的是Kronos应用本身，不是Python
    # 所以我们需要跳过sys.executable检测，直接检测系统Python

    # 动态检测系统中的Python
    python_names = ['python3.11', 'python3', 'python']
    if os.name == 'nt':  # Windows
        python_names = ['python3.11.exe', 'python3.exe', 'python.exe'] + python_names

    best_python = None
    best_version = ""

    for py_name in python_names:
        try:
            py_path = shutil.which(py_name)
            if py_path:
                result = subprocess.run([py_path, "--version"],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout)
                    if version_match:
                        version = version_match.group(0)
                        print(f"发现Python {version} at {py_path}")
                        # 优先选择3.11.x
                        if version.startswith('3.11.'):
                            print(f"使用Python 3.11: {py_path}")
                            return py_path
                        elif version.startswith('3.') and (not best_python or version > best_version):
                            best_python = py_path
                            best_version = version
        except:
            continue

    if best_python:
        print(f"使用最佳Python {best_version}: {best_python}")
    else:
        print("使用默认Python: python3")

    return best_python or 'python3'


# 设置全局Python命令
PYTHON_COMMAND = detect_python_command()
print(f"GUI检测到的Python命令: {PYTHON_COMMAND}")  # 调试信息


class MacOSTheme:
    """macOS Big Sur/Monterey 设计系统 - 增强版"""
    # 主色调 - Apple 设计语言 (优化后的颜色)
    SYSTEM_BLUE = "#007AFF"  # iOS/macOS 系统蓝
    SYSTEM_BLUE_LIGHT = "#4DA6FF"  # 浅蓝色变体
    SYSTEM_BLUE_DARK = "#0056CC"  # 深蓝色变体
    SYSTEM_INDIGO = "#5856D6"  # 系统靛蓝
    SYSTEM_PURPLE = "#AF52DE"  # 系统紫色
    SYSTEM_TEAL = "#32D74B"  # 系统青色 (更鲜艳)
    SYSTEM_GREEN = "#30D158"  # 系统绿色 (更鲜艳)
    SYSTEM_YELLOW = "#FFD60A"  # 系统黄色 (更鲜艳)
    SYSTEM_ORANGE = "#FF9F0A"  # 系统橙色 (更鲜艳)
    SYSTEM_RED = "#FF453A"  # 系统红色 (更鲜艳)

    # 背景色系 - 毛玻璃效果 (优化对比度和层次感) - Windows优化
    PRIMARY_BG = "#FFFFFF" if platform.system() == "Windows" else "#F8F9FA"  # 主背景色 (Windows使用纯白)
    SECONDARY_BG = "#FFFFFF"  # 次级背景 (卡片背景)
    TERTIARY_BG = "#F8F9FA" if platform.system() == "Windows" else "#F1F3F4"  # 三级背景 (Windows使用更亮的色彩)
    CARD_BG = "#FFFFFF"  # 卡片背景
    CARD_BG_HOVER = "#F0F4F8" if platform.system() == "Windows" else "#FAFBFC"  # 卡片悬停背景 (Windows使用更明显的颜色)
    CARD_BG_TRANSLUCENT = "#F8FAFC" if platform.system() == "Windows" else "#FAFBFC"  # 半透明卡片背景
    SIDEBAR_BG = "#F8F9FA" if platform.system() == "Windows" else "#F5F6F7"  # 侧边栏背景
    GLASS_BG = "#F8F9FA" if platform.system() == "Windows" else "#F5F5F5"  # 毛玻璃背景

    # 深色模式
    DARK_PRIMARY_BG = "#000000"  # 深色主背景
    DARK_SECONDARY_BG = "#1C1C1E"  # 深色次级背景
    DARK_TERTIARY_BG = "#2C2C2E"  # 深色三级背景
    DARK_CARD_BG = "#1C1C1E"  # 深色卡片背景
    DARK_GLASS_BG = "#2C2C2E"  # 深色毛玻璃背景

    # 文字色彩 (优化可读性) - Windows优化对比度
    PRIMARY_LABEL = "#000000" if platform.system() == "Windows" else "#1A1A1A"  # 主要标签 (Windows使用纯黑)
    SECONDARY_LABEL = "#333333" if platform.system() == "Windows" else "#424242"  # 次要标签 (Windows使用更深的颜色)
    TERTIARY_LABEL = "#666666" if platform.system() == "Windows" else "#8A8A8E"  # 三级标签 (Windows使用更深的颜色)
    QUATERNARY_LABEL = "#999999" if platform.system() == "Windows" else "#C4C4C6"  # 四级标签 (Windows使用更深的颜色)

    # 深色模式文字
    DARK_PRIMARY_LABEL = "#FFFFFF"
    DARK_SECONDARY_LABEL = "#EBEBF5"
    DARK_TERTIARY_LABEL = "#8E8E93"
    DARK_QUATERNARY_LABEL = "#C7C7CC"

    # 分隔线和边框 (优化视觉层次)
    SEPARATOR = "#E1E1E6"  # 分隔线 (更精致)
    SEPARATOR_LIGHT = "#F0F0F5"  # 浅色分隔线
    OPAQUE_SEPARATOR = "#38383A"  # 不透明分隔线
    BORDER_COLOR = "#E8E8ED"  # 边框颜色 (更柔和)
    BORDER_COLOR_FOCUS = "#007AFF"  # 焦点边框颜色

    # 圆角和阴影系统 (增强层次感)
    CORNER_RADIUS = 12  # 标准圆角
    LARGE_CORNER_RADIUS = 20  # 大圆角
    SMALL_CORNER_RADIUS = 8  # 小圆角

    # 多层次阴影系统
    SHADOW_SUBTLE = "#F8F8F8"  # 微妙阴影
    SHADOW_SMALL = "#F5F5F5"  # 小阴影
    SHADOW_MEDIUM = "#F0F0F0"  # 中等阴影
    SHADOW_LARGE = "#EBEBEB"  # 大阴影
    SHADOW_EXTRA_LARGE = "#E6E6E6"  # 超大阴影

    # 阴影颜色系统
    SHADOW_LIGHT = "#F0F0F5"  # 浅色阴影
    SHADOW_DARK = "#E0E0E8"  # 深色阴影
    SHADOW_DARKER = "#D0D0D8"  # 更深阴影

    # 渐变色系统 (tkinter不支持渐变，使用单色替代)
    GRADIENT_BLUE = "#007AFF"
    GRADIENT_PURPLE = "#5856D6"
    GRADIENT_GREEN = "#30D158"
    GRADIENT_CARD = "#FFFFFF"

    # 界面渐变背景
    GRADIENT_PRIMARY_START = "#F8F9FA"  # 主渐变起始色
    GRADIENT_PRIMARY_END = "#E8EAF0"  # 主渐变结束色
    GRADIENT_SECONDARY_START = "#FFFFFF"  # 次级渐变起始色
    GRADIENT_SECONDARY_END = "#F5F6F7"  # 次级渐变结束色

    # 精致分隔线系统
    SEPARATOR_GRADIENT = "#D1D1D6"  # 渐变分隔线
    SEPARATOR_GRADIENT_START = "#E1E1E6"  # 渐变分隔线起始色
    SEPARATOR_HIGHLIGHT = "#FFFFFF"  # 高亮分隔线
    SEPARATOR_SHADOW = "#E5E5EA"  # 阴影分隔线

    # 交互状态颜色
    HOVER_BG = "#F0F2F5"  # 悬停背景
    PRESSED_BG = "#E8EAF0"  # 按下背景
    SYSTEM_BLUE_HOVER = "#0056CC"  # 系统蓝悬停色

    # 强调色系统
    ACCENT_BLUE = "#007AFF"  # 强调蓝色
    ACCENT_BLUE_LIGHT = "#4DA6FF"  # 浅蓝色强调色
    ACCENT_PURPLE = "#5856D6"  # 强调紫色
    ACCENT_GREEN = "#30D158"  # 强调绿色

    # 字体大小系统 (优化层次) - 进一步优化紧凑性
    FONT_SIZE_LARGE_TITLE = 20  # 大标题 (从18进一步调整为20)
    FONT_SIZE_TITLE = 18  # 标题 (从16调整为18)
    FONT_SIZE_TITLE3 = 16  # 三级标题 (从14调整为16)
    FONT_SIZE_LARGE = 17  # 大字体 (从15调整为17)
    FONT_SIZE_HEADLINE = 16  # 副标题 (从15调整为16)
    FONT_SIZE_BODY = 14  # 正文 (从13调整为14)
    FONT_SIZE_CALLOUT = 12  # 说明文字 (从12调整为12)
    FONT_SIZE_SUBHEAD = 11  # 小标题 (从11调整为11)
    FONT_SIZE_FOOTNOTE = 10  # 脚注 (从10调整为10)
    FONT_SIZE_CAPTION = 9  # 标注 (从9调整为9)

    # 动画和过渡
    ANIMATION_DURATION_FAST = 150  # 快速动画 (ms)
    ANIMATION_DURATION_NORMAL = 250  # 正常动画 (ms)
    ANIMATION_DURATION_SLOW = 350  # 慢速动画 (ms)


class DeviceFingerprint:
    """设备指纹管理"""

    def get_device_id(self):
        """获取设备ID"""
        try:
            import uuid
            info = {
                'system': platform.system(),
                'node': platform.node(),
                'machine': platform.machine(),
                'processor': platform.processor()[:50] if platform.processor() else 'unknown',
                'mac': format(uuid.getnode(), '012x')
            }
            combined = json.dumps(info, sort_keys=True)
            device_id = hashlib.sha256(combined.encode()).hexdigest()[:16].upper()
            return device_id
        except Exception:
            fallback_id = hashlib.md5(platform.node().encode()).hexdigest()[:16].upper()
            return fallback_id


class LicenseValidator:
    """授权验证管理"""

    def __init__(self):
        self.device_fp = DeviceFingerprint()
        self.cache_file = self._get_cache_path()

    def _get_cache_path(self):
        """获取缓存文件路径"""
        cache_dir = Path.home() / '.kronos'
        cache_dir.mkdir(exist_ok=True)
        return cache_dir / '.license_cache'

    def validate_license(self):
        """验证授权状态"""
        if not self.cache_file.exists():
            return False, "设备未激活"

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            current_device_id = self.device_fp.get_device_id()
            stored_device_id = cache_data.get('device_id')

            if current_device_id != stored_device_id:
                return False, "设备硬件发生变更"

            return True, "授权有效"

        except Exception:
            return False, "授权文件损坏"

    def activate_license(self, license_code):
        """激活授权码"""
        import re

        pattern = r'^KRONOS-[A-F0-9]{5}-[A-F0-9]{5}-[A-F0-9]{5}-[A-F0-9]{5}$'
        if not re.match(pattern, license_code.upper()):
            return False, "授权码格式错误"

        device_id = self.device_fp.get_device_id()

        # 验证授权码是否与设备ID匹配
        if not self._verify_license_code(license_code.upper(), device_id):
            return False, "授权码与当前设备不匹配"

        cache_data = {
            'license_code': license_code.upper(),
            'device_id': device_id,
            'activation_time': datetime.now().isoformat(),
            'system_info': {
                'system': platform.system(),
                'release': platform.release()
            }
        }

        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            return True, "授权激活成功"
        except Exception as e:
            return False, f"激活失败: {e}"

    def _verify_license_code(self, license_code, device_id):
        """验证授权码是否与设备ID匹配"""
        try:
            # 移除 KRONOS- 前缀和连字符
            code_parts = license_code.replace('KRONOS-', '').replace('-', '')

            # 使用设备ID作为盐值生成校验码
            combined = f"{device_id}:KRONOS:2025"
            expected_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()

            # 比较授权码（取前20位）与期望的哈希值
            return code_parts == expected_hash
        except Exception:
            return False

    @staticmethod
    def generate_license_code(device_id):
        """根据设备ID生成授权码（用于管理员生成授权码）"""
        combined = f"{device_id}:KRONOS:2025"
        code_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()

        # 格式化为 KRONOS-XXXXX-XXXXX-XXXXX-XXXXX
        parts = [code_hash[i:i + 5] for i in range(0, 20, 5)]
        return f"KRONOS-{'-'.join(parts)}"

    def get_license_info(self):
        """获取授权信息"""
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None


class MacOSWidget:
    """macOS风格控件工具类"""

    @staticmethod
    def create_window_frame(parent, title="", closable=False):
        """创建macOS风格的窗口框架 - 简化版，不重复窗口控制"""
        # 创建主框架
        frame = tk.Frame(parent, bg=MacOSTheme.PRIMARY_BG, relief="flat", bd=0)

        if title:
            # 标题栏
            title_bar = tk.Frame(frame, bg=MacOSTheme.SECONDARY_BG, height=44, relief="flat", bd=0)
            title_bar.pack(fill=tk.X)
            title_bar.pack_propagate(False)

            # 标题文字
            title_label = tk.Label(title_bar, text=title,
                                   font=("SF Pro Display", MacOSTheme.FONT_SIZE_TITLE, "bold"),
                                   fg=MacOSTheme.PRIMARY_LABEL,
                                   bg=MacOSTheme.SECONDARY_BG)
            title_label.pack(pady=12)

            # 分隔线
            separator = tk.Frame(frame, bg=MacOSTheme.SEPARATOR, height=1)
            separator.pack(fill=tk.X)

        return frame

    @staticmethod
    def create_card(parent, padding=20, corner_radius=None, shadow_level="medium", hover_effect=True):
        """创建macOS风格卡片 - 增强版"""
        corner_radius = corner_radius or MacOSTheme.CORNER_RADIUS

        # 卡片容器 (用于阴影效果)
        card_container = tk.Frame(parent, bg=MacOSTheme.PRIMARY_BG, relief="flat", bd=0)

        # 多层阴影效果
        outer_shadow = tk.Frame(card_container, bg="#E0E0E5", relief="flat", bd=0)
        outer_shadow.pack(fill=tk.BOTH, expand=True, padx=3, pady=4)

        middle_shadow = tk.Frame(outer_shadow, bg="#E8E8ED", relief="flat", bd=0)
        middle_shadow.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        inner_shadow = tk.Frame(middle_shadow, bg="#F0F0F5", relief="flat", bd=0)
        inner_shadow.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 卡片背景 - 添加精致边框
        card = tk.Frame(inner_shadow, bg=MacOSTheme.CARD_BG, relief="flat", bd=0)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 精致边框系统
        card.configure(highlightbackground=MacOSTheme.BORDER_COLOR, highlightthickness=1)

        # 内部高亮边框
        highlight_frame = tk.Frame(card, bg=MacOSTheme.SEPARATOR_HIGHLIGHT, height=1)
        highlight_frame.pack(fill=tk.X, side=tk.TOP)

        # 增强悬停效果
        if hover_effect:
            def on_enter(e):
                card.configure(bg=MacOSTheme.CARD_BG_HOVER)
                outer_shadow.configure(bg="#D0D0D5")
                middle_shadow.configure(bg="#D8D8DD")
                inner_shadow.configure(bg="#E8E8ED")
                card.configure(highlightbackground=MacOSTheme.ACCENT_BLUE, highlightthickness=2)
                highlight_frame.configure(bg=MacOSTheme.SYSTEM_BLUE_LIGHT)

            def on_leave(e):
                card.configure(bg=MacOSTheme.CARD_BG)
                outer_shadow.configure(bg="#E0E0E5")
                middle_shadow.configure(bg="#E8E8ED")
                inner_shadow.configure(bg="#F0F0F5")
                card.configure(highlightbackground=MacOSTheme.BORDER_COLOR, highlightthickness=1)
                highlight_frame.configure(bg=MacOSTheme.SEPARATOR_HIGHLIGHT)

            # 绑定悬停事件到卡片和容器
            card.bind("<Enter>", on_enter)
            card.bind("<Leave>", on_leave)
            card_container.bind("<Enter>", on_enter)
            card_container.bind("<Leave>", on_leave)

        return card_container, card

    @staticmethod
    def create_button(parent, text, command=None, style="primary", size="medium", icon=None):
        """创建跨平台风格按钮 - Windows优化版"""
        # Windows平台使用优化的按钮样式
        if platform.system() == "Windows":
            # Windows按钮样式配置
            if style == "primary":
                bg_color = "#0066CC"
                hover_color = "#0052A3"
                text_color = "#FFFFFF"
            elif style == "destructive":
                bg_color = "#DC3545"
                hover_color = "#C82333"
                text_color = "#FFFFFF"
            elif style == "success":
                bg_color = "#28A745"
                hover_color = "#218838"
                text_color = "#FFFFFF"
            else:  # default/secondary
                bg_color = "#F8F9FA"
                hover_color = "#E2E6EA"
                text_color = "#495057"

            # Windows按钮尺寸
            if size == "large":
                font_size = 14
                padx, pady = 30, 12
            elif size == "small":
                font_size = 11
                padx, pady = 20, 8
            else:  # medium
                font_size = 12
                padx, pady = 25, 10

            # 创建Windows优化按钮
            button = tk.Button(parent, text=text,
                               font=("Microsoft YaHei", font_size, "normal"),
                               fg=text_color, bg=bg_color, relief="flat", bd=0,
                               padx=padx, pady=pady, command=command,
                               cursor="hand2", activebackground=hover_color)

            # Windows按钮悬停效果
            def on_hover(e):
                button.configure(bg=hover_color)

            def on_leave(e):
                button.configure(bg=bg_color)

            button.bind("<Enter>", on_hover)
            button.bind("<Leave>", on_leave)

            return button

        else:
            # macOS按钮样式配置
            if style == "primary":
                bg_color = "#007AFF"
                hover_color = "#005ECC"
                pressed_color = "#004099"
                text_color = "white"
                border_color = "#007AFF"
            elif style == "secondary":
                bg_color = "#E5E5EA"
                hover_color = "#DCDCE0"
                pressed_color = "#D1D1D6"
                text_color = "#1C1C1E"
                border_color = "#E5E5EA"
            elif style == "destructive":
                bg_color = "#FF3B30"
                hover_color = "#E0342A"
                pressed_color = "#C22E24"
                text_color = "white"
                border_color = "#FF3B30"
            elif style == "success":
                bg_color = "#34C759"
                hover_color = "#2DAA4D"
                pressed_color = "#268E41"
                text_color = "white"
                border_color = "#34C759"
            else:  # default
                bg_color = "#E5E5EA"
                hover_color = "#DCDCE0"
                pressed_color = "#D1D1D6"
                text_color = "#1C1C1E"
                border_color = "#C7C7CC"

            # macOS按钮尺寸
            if size == "large":
                font_size = MacOSTheme.FONT_SIZE_HEADLINE
                height = 50
                min_width = 120
            elif size == "small":
                font_size = MacOSTheme.FONT_SIZE_SUBHEAD
                height = 32
                min_width = 80
            else:  # medium
                font_size = MacOSTheme.FONT_SIZE_BODY
                height = 40
                min_width = 100

            # macOS按钮容器
            button_container = tk.Frame(parent, height=height, width=min_width)
            button_container.pack_propagate(False)
            button_container.config(bg=bg_color, relief="flat", bd=0)

            # 按钮标签
            button_label = tk.Label(button_container, text=text, fg=text_color, bg=bg_color,
                                    font=("SF Pro Display", font_size, "bold"), cursor="hand2")
            button_label.place(relx=0.5, rely=0.5, anchor="center")

            # 绑定事件
            def on_enter(e):
                button_container.config(bg=hover_color)
                button_label.config(bg=hover_color)

            def on_leave(e):
                button_container.config(bg=bg_color)
                button_label.config(bg=bg_color)

            def on_press(e):
                button_container.config(bg=pressed_color)
                button_label.config(bg=pressed_color)

            def on_release(e):
                button_container.config(bg=hover_color)
                button_label.config(bg=hover_color)
                if command:
                    command()

            for w in (button_container, button_label):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", on_press)
                w.bind("<ButtonRelease-1>", on_release)

            return button_container

    @staticmethod
    def create_text_field(parent, placeholder="", secure=False, size="medium"):
        """创建macOS风格文本输入框 - 增强版"""
        # 尺寸配置
        if size == "large":
            font_size = MacOSTheme.FONT_SIZE_HEADLINE
            padx, pady = 20, 18
            min_height = 52
        elif size == "small":
            font_size = MacOSTheme.FONT_SIZE_SUBHEAD
            padx, pady = 14, 12
            min_height = 36
        else:  # medium
            font_size = MacOSTheme.FONT_SIZE_BODY
            padx, pady = 16, 14
            min_height = 44

        # 容器
        field_container = tk.Frame(parent, bg=MacOSTheme.PRIMARY_BG)

        # 外层阴影框架（深层阴影）
        outer_shadow = tk.Frame(field_container, bg=MacOSTheme.SHADOW_LIGHT, relief="flat", bd=0)
        outer_shadow.pack(fill=tk.BOTH, expand=True, padx=2, pady=3)

        # 中层阴影框架
        middle_shadow = tk.Frame(outer_shadow, bg=MacOSTheme.SHADOW_MEDIUM, relief="flat", bd=0)
        middle_shadow.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 内层边框框架
        inner_border = tk.Frame(middle_shadow, bg=MacOSTheme.SEPARATOR_HIGHLIGHT, relief="flat", bd=0)
        inner_border.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 输入框背景
        field_bg = tk.Frame(inner_border, bg=MacOSTheme.SECONDARY_BG,
                            relief="flat", bd=0, height=min_height)
        field_bg.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        field_bg.pack_propagate(False)
        field_bg.configure(highlightbackground=MacOSTheme.BORDER_COLOR, highlightthickness=1)

        # 输入框
        entry_config = {
            "font": ("SF Pro Display", font_size, "normal"),
            "bg": MacOSTheme.SECONDARY_BG,
            "fg": MacOSTheme.PRIMARY_LABEL,
            "relief": "flat",
            "bd": 0,
            "insertbackground": MacOSTheme.SYSTEM_BLUE,
            "highlightthickness": 0,
            "selectbackground": MacOSTheme.SYSTEM_BLUE,
            "selectforeground": "white"
        }

        if secure:
            entry_config["show"] = "*"

        entry = tk.Entry(field_bg, **entry_config)
        entry.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)

        # 增强占位符效果
        if placeholder:
            entry.insert(0, placeholder)
            entry.configure(fg=MacOSTheme.TERTIARY_LABEL)

            def on_focus_in(e):
                if entry.get() == placeholder:
                    entry.delete(0, tk.END)
                    entry.configure(fg=MacOSTheme.PRIMARY_LABEL)
                # 焦点状态的视觉反馈 - 多层效果，与按钮颜色协调
                field_bg.configure(highlightbackground="#0066FF", highlightthickness=2)  # 现代蓝色边框
                outer_shadow.configure(bg="#E8F4FF")  # 浅蓝阴影
                middle_shadow.configure(bg="#D1E9FF")  # 中蓝阴影
                inner_border.configure(bg="#B8DDFF")  # 深蓝高亮
                field_bg.configure(bg="#F0F8FF")  # 现代浅蓝背景

            def on_focus_out(e):
                if not entry.get():
                    entry.insert(0, placeholder)
                    entry.configure(fg=MacOSTheme.TERTIARY_LABEL)
                # 失去焦点的视觉反馈 - 恢复多层效果
                field_bg.configure(highlightbackground=MacOSTheme.BORDER_COLOR, highlightthickness=1)
                outer_shadow.configure(bg=MacOSTheme.SHADOW_LIGHT)
                middle_shadow.configure(bg=MacOSTheme.SHADOW_MEDIUM)
                inner_border.configure(bg=MacOSTheme.SEPARATOR_HIGHLIGHT)
                field_bg.configure(bg=MacOSTheme.SECONDARY_BG)

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)
        else:
            # 无占位符时的焦点效果 - 多层边框，与按钮颜色协调
            def on_focus_in(e):
                field_bg.configure(highlightbackground="#0066FF", highlightthickness=2)  # 现代蓝色边框
                outer_shadow.configure(bg="#E8F4FF")  # 浅蓝阴影
                middle_shadow.configure(bg="#D1E9FF")  # 中蓝阴影
                inner_border.configure(bg="#B8DDFF")  # 深蓝高亮
                field_bg.configure(bg="#F0F8FF")  # 现代浅蓝背景

            def on_focus_out(e):
                field_bg.configure(highlightbackground=MacOSTheme.BORDER_COLOR, highlightthickness=1)
                outer_shadow.configure(bg=MacOSTheme.SHADOW_LIGHT)
                middle_shadow.configure(bg=MacOSTheme.SHADOW_MEDIUM)
                inner_border.configure(bg=MacOSTheme.SEPARATOR_HIGHLIGHT)
                field_bg.configure(bg=MacOSTheme.SECONDARY_BG)

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

        return field_container, entry

    @staticmethod
    def create_list_item(parent, icon, title, subtitle="", chevron=True, command=None, style="default"):
        """创建macOS风格列表项 - 增强版"""
        # 样式配置
        if style == "compact":
            icon_size = MacOSTheme.FONT_SIZE_LARGE + 2
            padx, pady = 16, 12
            title_font_size = MacOSTheme.FONT_SIZE_BODY
        elif style == "large":
            icon_size = MacOSTheme.FONT_SIZE_LARGE + 6
            padx, pady = 16, 12
            title_font_size = MacOSTheme.FONT_SIZE_TITLE3
        else:  # default
            icon_size = MacOSTheme.FONT_SIZE_LARGE + 4
            padx, pady = 20, 16
            title_font_size = MacOSTheme.FONT_SIZE_HEADLINE

        # 外层容器（用于阴影效果）
        container = tk.Frame(parent, bg=MacOSTheme.PRIMARY_BG)

        # 阴影框架
        shadow_frame = tk.Frame(container, bg="#F0F0F5", relief="flat", bd=0)
        shadow_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 主项目框架
        item_frame = tk.Frame(shadow_frame, bg=MacOSTheme.CARD_BG, relief="flat", bd=0, cursor="hand2")
        item_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 图标容器 - 确保垂直居中对齐
        icon_container = tk.Frame(item_frame, bg=MacOSTheme.CARD_BG, width=40, height=40)
        icon_container.pack(side=tk.LEFT, padx=(padx, 16), pady=pady)
        icon_container.pack_propagate(False)

        # 图标 - 优化对齐和间距
        icon_label = tk.Label(icon_container, text=icon,
                              font=("SF Pro Display", icon_size, "normal"),
                              bg=MacOSTheme.CARD_BG, fg=MacOSTheme.SYSTEM_BLUE)
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

        # 文字容器
        text_frame = tk.Frame(item_frame, bg=MacOSTheme.CARD_BG)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=pady)

        # 标题
        title_label = tk.Label(text_frame, text=title,
                               font=("SF Pro Display", title_font_size, "normal"),
                               fg=MacOSTheme.PRIMARY_LABEL,
                               bg=MacOSTheme.CARD_BG,
                               anchor="w")
        title_label.pack(fill=tk.X)

        # 副标题
        subtitle_label = None
        if subtitle:
            subtitle_label = tk.Label(text_frame, text=subtitle,
                                      font=("SF Pro Display", MacOSTheme.FONT_SIZE_FOOTNOTE, "normal"),
                                      fg=MacOSTheme.SECONDARY_LABEL,
                                      bg=MacOSTheme.CARD_BG,
                                      anchor="w")
            subtitle_label.pack(fill=tk.X, pady=(3, 0))

        # 右箭头
        chevron_label = None
        if chevron:
            chevron_label = tk.Label(item_frame, text="›",
                                     font=("SF Pro Display", MacOSTheme.FONT_SIZE_LARGE + 2, "normal"),
                                     fg=MacOSTheme.TERTIARY_LABEL,
                                     bg=MacOSTheme.CARD_BG)
            chevron_label.pack(side=tk.RIGHT, padx=(8, padx), pady=pady)

        # 增强悬停效果
        def on_enter(e):
            # 悬停时的渐变效果
            shadow_frame.configure(bg="#E8E8ED")
            item_frame.configure(bg=MacOSTheme.HOVER_BG)
            icon_container.configure(bg=MacOSTheme.HOVER_BG)
            icon_label.configure(bg=MacOSTheme.HOVER_BG, fg=MacOSTheme.SYSTEM_BLUE_HOVER)
            text_frame.configure(bg=MacOSTheme.HOVER_BG)
            title_label.configure(bg=MacOSTheme.HOVER_BG, fg=MacOSTheme.PRIMARY_LABEL)
            if subtitle_label:
                subtitle_label.configure(bg=MacOSTheme.HOVER_BG, fg=MacOSTheme.SECONDARY_LABEL)
            if chevron_label:
                chevron_label.configure(bg=MacOSTheme.HOVER_BG, fg=MacOSTheme.SECONDARY_LABEL)

        def on_leave(e):
            # 恢复默认状态
            shadow_frame.configure(bg="#F0F0F5")
            item_frame.configure(bg=MacOSTheme.CARD_BG)
            icon_container.configure(bg=MacOSTheme.CARD_BG)
            icon_label.configure(bg=MacOSTheme.CARD_BG, fg=MacOSTheme.SYSTEM_BLUE)
            text_frame.configure(bg=MacOSTheme.CARD_BG)
            title_label.configure(bg=MacOSTheme.CARD_BG, fg=MacOSTheme.PRIMARY_LABEL)
            if subtitle_label:
                subtitle_label.configure(bg=MacOSTheme.CARD_BG, fg=MacOSTheme.SECONDARY_LABEL)
            if chevron_label:
                chevron_label.configure(bg=MacOSTheme.CARD_BG, fg=MacOSTheme.TERTIARY_LABEL)

        def on_click(e):
            # 点击反馈效果
            if command:
                shadow_frame.configure(bg="#D1D1D6")
                item_frame.configure(bg=MacOSTheme.PRESSED_BG)
                icon_container.configure(bg=MacOSTheme.PRESSED_BG)
                icon_label.configure(bg=MacOSTheme.PRESSED_BG)
                text_frame.configure(bg=MacOSTheme.PRESSED_BG)
                title_label.configure(bg=MacOSTheme.PRESSED_BG)
                if subtitle_label:
                    subtitle_label.configure(bg=MacOSTheme.PRESSED_BG)
                if chevron_label:
                    chevron_label.configure(bg=MacOSTheme.PRESSED_BG)
                # 延迟恢复和执行命令
                container.after(100, lambda: on_leave(None))
                container.after(150, command)

        # 绑定事件到所有组件
        widgets = [item_frame, icon_container, icon_label, text_frame, title_label]
        if subtitle_label:
            widgets.append(subtitle_label)
        if chevron_label:
            widgets.append(chevron_label)

        for widget in widgets:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            if command:
                widget.bind("<Button-1>", on_click)

        return container


class LicenseActivationSheet:
    """现代化授权激活表单"""

    def __init__(self, parent, validator):
        self.validator = validator
        self.success = False
        self.parent = parent

        # 创建模态窗口
        self.sheet = tk.Toplevel(parent)
        self.sheet.title("Kronos 授权激活")
        self.sheet.geometry("600x500")
        self.sheet.resizable(False, False)
        self.sheet.transient(parent)
        self.sheet.grab_set()
        self.sheet.configure(bg="#FFFFFF")

        # 居中显示
        self.center_window()
        self.create_interface()

    def center_window(self):
        """窗口居中"""
        self.sheet.update_idletasks()
        x = (self.sheet.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.sheet.winfo_screenheight() // 2) - (500 // 2)
        self.sheet.geometry(f"600x500+{x}+{y}")

    def create_interface(self):
        """创建界面"""
        # 主容器
        main_frame = tk.Frame(self.sheet, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)

        # 移除重复的关闭按钮，只保留底部的取消按钮

        # 图标和标题
        header_frame = tk.Frame(main_frame, bg="#FFFFFF")
        header_frame.pack(fill=tk.X, pady=(0, 30))

        # 系统图标
        icon_label = tk.Label(header_frame, text="🔐",
                              font=("Apple Color Emoji", 48),
                              bg="#FFFFFF")
        icon_label.pack(pady=(0, 16))

        # 主标题
        title_label = tk.Label(header_frame, text="激活 Kronos 专业版",
                               font=("SF Pro Display", 20, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack()

        # 描述文字
        desc_label = tk.Label(header_frame, text="输入授权码以解锁所有高级功能",
                              font=("SF Pro Display", 14, "normal"),
                              fg="#6B7280", bg="#FFFFFF")
        desc_label.pack(pady=(8, 0))

        # 设备信息卡片
        device_frame = tk.Frame(main_frame, bg="#F9FAFB", relief="flat", bd=0)
        device_frame.pack(fill=tk.X, pady=(0, 24))

        device_content = tk.Frame(device_frame, bg="#F9FAFB")
        device_content.pack(fill=tk.X, padx=20, pady=16)

        device_title = tk.Label(device_content, text="设备信息",
                                font=("SF Pro Display", 14, "bold"),
                                fg="#1F2937", bg="#F9FAFB")
        device_title.pack(anchor="w", pady=(0, 8))

        device_id = self.validator.device_fp.get_device_id()

        # 设备ID行（带复制按钮）
        device_id_row = tk.Frame(device_content, bg="#F9FAFB")
        device_id_row.pack(anchor="w", fill=tk.X, pady=(0, 8))

        device_id_label = tk.Label(device_id_row, text=f"设备 ID: {device_id}",
                                   font=("SF Mono", 12),
                                   fg="#6B7280", bg="#F9FAFB",
                                   anchor="w")
        device_id_label.pack(side=tk.LEFT)

        # 复制按钮
        def copy_device_id():
            self.sheet.clipboard_clear()
            self.sheet.clipboard_append(device_id)
            copy_btn.config(text="✓ 已复制", fg="#10B981")
            self.sheet.after(2000, lambda: copy_btn.config(text="📋 复制", fg="#6B7280"))

        copy_btn = tk.Button(device_id_row, text="📋 复制",
                             font=("SF Pro Display", 11, "normal"),
                             fg="#6B7280", bg="#E5E7EB",
                             relief="flat", bd=0, padx=12, pady=4,
                             cursor="hand2", command=copy_device_id)
        copy_btn.pack(side=tk.LEFT, padx=(12, 0))

        # 悬停效果
        def on_copy_hover(e):
            copy_btn.config(bg="#D1D5DB")

        def on_copy_leave(e):
            copy_btn.config(bg="#E5E7EB")

        copy_btn.bind("<Enter>", on_copy_hover)
        copy_btn.bind("<Leave>", on_copy_leave)

        # 系统信息
        system_info = f"系统: {platform.system()} {platform.release()}"
        system_label = tk.Label(device_content, text=system_info,
                                font=("SF Mono", 12),
                                fg="#6B7280", bg="#F9FAFB",
                                justify=tk.LEFT)
        system_label.pack(anchor="w")

        # 输入区域
        input_frame = tk.Frame(main_frame, bg="#FFFFFF")
        input_frame.pack(fill=tk.X, pady=(0, 30))

        input_label = tk.Label(input_frame, text="授权码",
                               font=("SF Pro Display", 16, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        input_label.pack(anchor="w", pady=(0, 8))

        # 输入框
        entry_frame = tk.Frame(input_frame, bg="#FFFFFF")
        entry_frame.pack(fill=tk.X, pady=(0, 8))

        self.license_entry = tk.Entry(entry_frame, font=("SF Pro Display", 16, "normal"),
                                      bg="#F9FAFB", fg="#1F2937", relief="flat", bd=0,
                                      highlightthickness=2, highlightcolor="#4F46E5",
                                      highlightbackground="#E5E7EB")
        self.license_entry.pack(fill=tk.X, ipady=12, ipadx=16)
        self.license_entry.insert(0, "KRONOS-XXXXX-XXXXX-XXXXX-XXXXX")
        self.license_entry.configure(fg="#9CA3AF")
        self.license_entry.focus_set()

        # 占位符效果
        def on_focus_in(e):
            if self.license_entry.get() == "KRONOS-XXXXX-XXXXX-XXXXX-XXXXX":
                self.license_entry.delete(0, tk.END)
                self.license_entry.configure(fg="#1F2937")

        def on_focus_out(e):
            if not self.license_entry.get():
                self.license_entry.insert(0, "KRONOS-XXXXX-XXXXX-XXXXX-XXXXX")
                self.license_entry.configure(fg="#9CA3AF")

        self.license_entry.bind("<FocusIn>", on_focus_in)
        self.license_entry.bind("<FocusOut>", on_focus_out)

        # 格式提示
        hint_label = tk.Label(input_frame,
                              text="格式：KRONOS + 4组5位字符，用短横线分隔",
                              font=("SF Pro Display", 12, "normal"),
                              fg="#9CA3AF", bg="#FFFFFF")
        hint_label.pack(anchor="w")

        # 按钮区域
        button_frame = tk.Frame(main_frame, bg="#FFFFFF")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # Windows平台按钮优化 - 改进显示效果
        if platform.system() == "Windows":
            # Windows使用标准tkinter按钮，确保文字显示正常
            cancel_btn = tk.Button(button_frame, text="取消",
                                   font=("Microsoft YaHei", 14, "normal"),
                                   fg="#FFFFFF", bg="#DC3545", relief="flat", bd=0,
                                   padx=30, pady=10, command=self.close_sheet,
                                   cursor="hand2", activebackground="#C82333")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            activate_btn = tk.Button(button_frame, text="激活",
                                     font=("Microsoft YaHei", 14, "normal"),
                                     fg="#FFFFFF", bg="#28A745", relief="flat", bd=0,
                                     padx=30, pady=10, command=self.activate_license,
                                     cursor="hand2", activebackground="#218838")
            activate_btn.pack(side=tk.LEFT)

            # Windows按钮悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#C82333")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#DC3545")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_activate_hover(e):
                activate_btn.configure(bg="#218838")

            def on_activate_leave(e):
                activate_btn.configure(bg="#28A745")

            activate_btn.bind("<Enter>", on_activate_hover)
            activate_btn.bind("<Leave>", on_activate_leave)
        else:
            # macOS使用现代风格按钮
            cancel_container = MacOSWidget.create_button(button_frame, "取消", command=self.close_sheet,
                                                         style="destructive", size="large")
            cancel_container.pack(side=tk.LEFT, padx=(0, 12))

            activate_container = MacOSWidget.create_button(button_frame, "激活", command=self.activate_license,
                                                           style="success", size="large")
            activate_container.pack(side=tk.LEFT)

        # 绑定回车键
        self.sheet.bind('<Return>', lambda e: self.activate_license())
        self.sheet.bind('<Escape>', lambda e: self.close_sheet())

    def activate_license(self):
        """激活授权码"""
        license_code = self.license_entry.get().strip().upper()

        if not license_code or license_code.startswith("KRONOS-X"):
            messagebox.showwarning("输入错误", "请输入有效的授权码", parent=self.sheet)
            return

        try:
            success, message = self.validator.activate_license(license_code)

            if success:
                messagebox.showinfo("激活成功",
                                    f"🎉 恭喜！{message}\n\nKronos 专业版已激活，您现在可以使用所有高级功能！",
                                    parent=self.sheet)
                self.success = True
                self.sheet.destroy()
            else:
                messagebox.showerror("激活失败",
                                     f"❌ 激活失败：{message}\n\n请检查授权码是否正确，或联系技术支持。",
                                     parent=self.sheet)

        except Exception as e:
            messagebox.showerror("系统错误", f"激活过程中发生异常：{str(e)}", parent=self.sheet)

    def close_sheet(self):
        """关闭表单"""
        self.sheet.destroy()


class KronosMacOSGUI:
    """Kronos macOS现代化GUI主程序"""

    def __init__(self):
        self.root = tk.Tk()
        self.validator = LicenseValidator()
        self.setup_main_window()
        self._apply_windows_style()

        # 启动时检查授权
        if not self.check_authorization():
            return

        self.create_main_interface()
        self.start_updates()

    def _apply_windows_style(self):
        """在 Windows 上应用主题和字体回退，避免样式错乱"""
        if platform.system() != "Windows":
            # 非 Windows 不处理
            self.TITLE_FONT = ("SF Pro Display", 18, "bold")
            self.MONO_FONT = ("SF Mono", 12)
            return
        try:
            import tkinter.ttk as ttk
            style = ttk.Style()
            for theme in ("vista", "xpnative", "clam"):
                try:
                    style.theme_use(theme)
                    break
                except Exception:
                    pass
            # 字体回退
            default_font = ("Segoe UI", 11)
            title_font = ("Segoe UI", 18, "bold")
            mono_font = ("Consolas", 12)
            self.root.option_add("*Font", default_font)
            self.root.option_add("*Label.Font", default_font)
            self.root.option_add("*Button.Font", default_font)
            self.TITLE_FONT = title_font
            self.MONO_FONT = mono_font
        except Exception:
            # 失败则维持原字体
            self.TITLE_FONT = ("SF Pro Display", 18, "bold")
            self.MONO_FONT = ("SF Mono", 12)

    def setup_main_window(self):
        """设置主窗口"""
        self.root.title("Kronos 专业版")
        self.root.geometry("1000x650")
        self.root.minsize(900, 600)
        self.root.configure(bg=MacOSTheme.PRIMARY_BG)

        # 居中显示窗口
        self.root.update_idletasks()
        width = 1000
        height = 650
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # 设置窗口图标
        try:
            # 优先使用新的AI股票分析图标
            icon_path = project_root / 'assets' / 'kronos_ai_stock.icns'
            if not icon_path.exists():
                # 备用图标
                icon_path = project_root / 'assets' / 'kronos.icns'

            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except:
            pass

        # macOS窗口样式
        if platform.system() == "Darwin":
            try:
                # 设置macOS窗口外观
                self.root.tk.call('::tk::unsupported::MacWindowStyle', 'style', self.root._w, 'document',
                                  'closeBox collapseBox resizable')
            except:
                pass

    def check_authorization(self):
        """检查授权状态"""
        is_valid, message = self.validator.validate_license()

        if is_valid:
            return True

        # 显示激活表单
        sheet = LicenseActivationSheet(self.root, self.validator)
        self.root.wait_window(sheet.sheet)

        if hasattr(sheet, 'success') and sheet.success:
            return True
        else:
            # 优雅的退出提示
            result = messagebox.askyesno("Kronos",
                                         "感谢您对 Kronos 的关注！\n\n是否希望了解如何获取授权码？",
                                         parent=self.root)
            if result:
                webbrowser.open("https://kronos.ai/license")
            self.root.destroy()
            return False

    def create_main_interface(self):
        """创建主界面"""
        # 窗口框架
        self.main_frame = MacOSWidget.create_window_frame(self.root, "Kronos 金融预测系统", closable=True)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 创建导航栏
        self.create_navigation_bar()

        # 创建主内容区域
        self.create_content_area()

        # 创建状态栏
        self.create_status_bar()

    def create_navigation_bar(self):
        """创建导航栏"""
        # 导航栏容器 - 纯白背景
        nav_container = tk.Frame(self.main_frame, bg="#FFFFFF", height=60)
        nav_container.pack(fill=tk.X)
        nav_container.pack_propagate(False)

        # 内容框架
        nav_frame = tk.Frame(nav_container, bg="#FFFFFF")
        nav_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=16)

        # 左侧：Logo和标题
        left_frame = tk.Frame(nav_frame, bg="#FFFFFF")
        left_frame.pack(side=tk.LEFT)

        # App图标
        app_icon = tk.Label(left_frame, text="🚀", font=("Apple Color Emoji", 20),
                            bg="#FFFFFF")
        app_icon.pack(side=tk.LEFT, padx=(0, 12))

        # 应用名称
        app_name = tk.Label(left_frame, text="Kronos",
                            font=("SF Pro Display", 18, "bold"),
                            fg="#1A1A1A", bg="#FFFFFF")
        app_name.pack(side=tk.LEFT, anchor="w")

        # 版本标签
        version_label = tk.Label(left_frame, text="专业版",
                                 font=("SF Pro Display", 12, "normal"),
                                 fg="#4F46E5", bg="#FFFFFF")
        version_label.pack(side=tk.LEFT, padx=(8, 0), anchor="s")

        # 右侧：状态指示器
        right_frame = tk.Frame(nav_frame, bg="#FFFFFF")
        right_frame.pack(side=tk.RIGHT)

        status_frame = tk.Frame(right_frame, bg="#FFFFFF")
        status_frame.pack(side=tk.RIGHT)

        status_dot = tk.Label(status_frame, text="●", font=("SF Pro Display", 12),
                              fg="#10B981", bg="#FFFFFF")
        status_dot.pack(side=tk.LEFT, padx=(0, 8))

        status_text = tk.Label(status_frame, text="已授权",
                               font=("SF Pro Display", 14, "normal"),
                               fg="#374151", bg="#FFFFFF")
        status_text.pack(side=tk.LEFT)

        # 底部分隔线
        separator = tk.Frame(nav_container, bg="#E5E7EB", height=1)
        separator.pack(fill=tk.X, side=tk.BOTTOM)

    def create_content_area(self):
        """创建主内容区域"""
        # 主容器 - 纯净背景
        content_container = tk.Frame(self.main_frame, bg="#FAFAFA")
        content_container.pack(fill=tk.BOTH, expand=True)

        # 直接创建功能网格，去掉多余的标题
        self.create_modern_grid(content_container)

    def create_modern_grid(self, parent):
        """创建现代化功能网格"""
        # 功能数据
        functions = [
            {"title": "批量分析", "desc": "多股票分析", "icon": "📈", "color": "#EA580C", "command": self.batch_predict},
            {"title": "环境检查", "desc": "检查系统环境", "icon": "🔍", "color": "#4F46E5",
             "command": self.check_environment},
            {"title": "安装依赖", "desc": "一键安装所有依赖", "icon": "📦", "color": "#059669",
             "command": self.install_dependencies},
            # {"title": "配置数据源", "desc": "设置API和数据源", "icon": "⚙️", "color": "#DC2626", "command": self.config_wizard},
            # {"title": "获取数据", "desc": "获取股票数据", "icon": "📊", "color": "#7C3AED", "command": self.fetch_data_unified},
            # {"title": "AI预测", "desc": "运行股票预测", "icon": "🤖", "color": "#0891B2", "command": self.run_prediction},
            {"title": "授权管理", "desc": "查看授权状态", "icon": "🔐", "color": "#BE185D",
             "command": self.manage_license},
            # {"title": "帮助文档", "desc": "使用说明", "icon": "📖", "color": "#6B7280", "command": self.show_help},
        ]

        # 网格容器
        grid_frame = tk.Frame(parent, bg="#FAFAFA")
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=(20, 40))

        # 配置网格
        for i in range(4):
            grid_frame.columnconfigure(i, weight=1, uniform="col")
        for i in range(2):
            grid_frame.rowconfigure(i, weight=1, uniform="row")

        # 创建功能卡片
        for i, func in enumerate(functions):
            row = i // 4
            col = i % 4
            self.create_modern_card(grid_frame, func, row, col)

    def create_modern_card(self, parent, func_data, row, col):
        """创建现代化功能卡片"""
        # 卡片容器
        card = tk.Frame(parent, bg="#FFFFFF", relief="flat", bd=0)
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

        # 鼠标交互
        def on_enter(e):
            card.configure(bg="#F8FAFC")

        def on_leave(e):
            card.configure(bg="#FFFFFF")

        def on_click(e):
            card.configure(bg="#F1F5F9")
            if func_data["command"]:
                card.after(100, func_data["command"])

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)
        card.bind("<Button-1>", on_click)

        # 卡片内容
        content_frame = tk.Frame(card, bg="#FFFFFF")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        content_frame.bind("<Enter>", on_enter)
        content_frame.bind("<Leave>", on_leave)
        content_frame.bind("<Button-1>", on_click)

        # 图标区域
        icon_frame = tk.Frame(content_frame, bg=func_data["color"], width=48, height=48)
        icon_frame.pack(pady=(0, 16))
        icon_frame.pack_propagate(False)

        icon_label = tk.Label(icon_frame, text=func_data["icon"],
                              font=("Apple Color Emoji", 24),
                              bg=func_data["color"], fg="white")
        icon_label.place(relx=0.5, rely=0.5, anchor="center")
        icon_label.bind("<Button-1>", on_click)

        # 标题
        title_label = tk.Label(content_frame, text=func_data["title"],
                               font=("SF Pro Display", 16, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack(pady=(0, 8))
        title_label.bind("<Enter>", on_enter)
        title_label.bind("<Leave>", on_leave)
        title_label.bind("<Button-1>", on_click)

        # 描述
        desc_label = tk.Label(content_frame, text=func_data["desc"],
                              font=("SF Pro Display", 12, "normal"),
                              fg="#6B7280", bg="#FFFFFF")
        desc_label.pack()
        desc_label.bind("<Enter>", on_enter)
        desc_label.bind("<Leave>", on_leave)
        desc_label.bind("<Button-1>", on_click)

    def create_function_group_simple(self, parent, group, column):
        """创建简化的功能分组 - macOS风格"""
        # 分组卡片 - 使用macOS风格的圆角和阴影
        group_frame = tk.Frame(parent, bg="#FFFFFF", relief="flat", bd=0)
        group_frame.grid(row=0, column=column, sticky="nsew", padx=12, pady=8)

        # 添加微妙的边框
        group_frame.configure(highlightbackground="#E5E5EA", highlightthickness=1)

        # 标题
        title_label = tk.Label(group_frame, text=group["title"],
                               font=("SF Pro Display", MacOSTheme.FONT_SIZE_TITLE3, "bold"),
                               fg=MacOSTheme.PRIMARY_LABEL, bg="#FFFFFF")
        title_label.pack(pady=(20, 16))

        # 功能项目
        for i, item in enumerate(group["items"]):
            item_frame = tk.Frame(group_frame, bg="#FFFFFF")
            item_frame.pack(fill=tk.X, padx=16, pady=2)

            # 图标和文字的容器 - macOS风格悬停效果
            content_frame = tk.Frame(item_frame, bg="#FFFFFF", relief="flat", bd=0)
            content_frame.pack(fill=tk.X, pady=1)
            content_frame.configure(highlightbackground="#F2F2F7", highlightthickness=0)

            # macOS风格悬停效果
            def create_hover_effect(frame, cmd):
                def on_enter(e):
                    frame.configure(bg="#F2F2F7", highlightbackground="#E5E5EA", highlightthickness=1)
                    # 更新所有子控件背景
                    for child in frame.winfo_children():
                        if hasattr(child, 'configure'):
                            try:
                                child.configure(bg="#F2F2F7")
                            except:
                                pass
                        for grandchild in child.winfo_children():
                            if hasattr(grandchild, 'configure'):
                                try:
                                    grandchild.configure(bg="#F2F2F7")
                                except:
                                    pass

                def on_leave(e):
                    frame.configure(bg="#FFFFFF", highlightbackground="#F2F2F7", highlightthickness=0)
                    # 恢复所有子控件背景
                    for child in frame.winfo_children():
                        if hasattr(child, 'configure'):
                            try:
                                child.configure(bg="#FFFFFF")
                            except:
                                pass
                        for grandchild in child.winfo_children():
                            if hasattr(grandchild, 'configure'):
                                try:
                                    grandchild.configure(bg="#FFFFFF")
                                except:
                                    pass

                def on_click(e):
                    if cmd:
                        # 点击反馈
                        frame.configure(bg="#E5E5EA")
                        frame.after(100, lambda: on_leave(None))
                        frame.after(150, cmd)

                return on_enter, on_leave, on_click

            on_enter, on_leave, on_click = create_hover_effect(content_frame, item["command"])

            # 内容行
            content_row = tk.Frame(content_frame, bg="#FFFFFF")
            content_row.pack(fill=tk.X, padx=16, pady=12)

            # 图标
            icon_label = tk.Label(content_row, text=item["icon"],
                                  font=("Apple Color Emoji", 18),
                                  bg="#FFFFFF")
            icon_label.pack(side=tk.LEFT, padx=(0, 16))

            # 文字容器
            text_container = tk.Frame(content_row, bg="#FFFFFF")
            text_container.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 标题
            title_text = tk.Label(text_container, text=item["title"],
                                  font=("SF Pro Display", MacOSTheme.FONT_SIZE_BODY, "normal"),
                                  fg=MacOSTheme.PRIMARY_LABEL, bg="#FFFFFF", anchor="w")
            title_text.pack(fill=tk.X)

            # 副标题
            subtitle_text = tk.Label(text_container, text=item["subtitle"],
                                     font=("SF Pro Display", MacOSTheme.FONT_SIZE_FOOTNOTE, "normal"),
                                     fg=MacOSTheme.SECONDARY_LABEL, bg="#FFFFFF", anchor="w")
            subtitle_text.pack(fill=tk.X, pady=(2, 0))

            # 右箭头
            chevron_label = tk.Label(content_row, text="›",
                                     font=("SF Pro Display", 16, "normal"),
                                     fg=MacOSTheme.TERTIARY_LABEL, bg="#FFFFFF")
            chevron_label.pack(side=tk.RIGHT, padx=(8, 0))

            # 绑定事件到所有相关控件
            widgets = [content_frame, content_row, icon_label, text_container,
                       title_text, subtitle_text, chevron_label]

            for widget in widgets:
                widget.bind("<Enter>", on_enter)
                widget.bind("<Leave>", on_leave)
                widget.bind("<Button-1>", on_click)

            # 添加分隔线（除了最后一项）
            if i < len(group["items"]) - 1:
                separator = tk.Frame(group_frame, bg="#F2F2F7", height=1)
                separator.pack(fill=tk.X, padx=32, pady=(0, 2))

    def create_function_group(self, parent, group):
        """创建功能分组"""
        # 分组容器 - 减小间距，利用更多空间
        group_container, group_card = MacOSWidget.create_card(parent, padding=0, shadow_level="elevated")
        group_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # 分组标题 - 减小高度
        title_frame = tk.Frame(group_card, bg=MacOSTheme.CARD_BG, height=36)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        # 标题容器 - 减小边距
        title_container = tk.Frame(title_frame, bg=MacOSTheme.CARD_BG)
        title_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        title_label = tk.Label(title_container, text=group["title"],
                               font=("SF Pro Display", MacOSTheme.FONT_SIZE_TITLE3, "bold"),
                               fg=MacOSTheme.PRIMARY_LABEL,
                               bg=MacOSTheme.CARD_BG)
        title_label.pack(anchor="w")

        # 精致分隔线 - 使用渐变效果
        separator_container = tk.Frame(group_card, bg=MacOSTheme.CARD_BG, height=2)
        separator_container.pack(fill=tk.X)
        separator_container.pack_propagate(False)

        separator = tk.Frame(separator_container, bg=MacOSTheme.SEPARATOR_GRADIENT, height=1)
        separator.pack(fill=tk.X, pady=1)

        # 功能项目 - 优化间距
        for i, item in enumerate(group["items"]):
            item_widget = MacOSWidget.create_list_item(
                group_card, item["icon"], item["title"], item["subtitle"],
                chevron=True, command=item["command"], style="large"
            )
            item_widget.pack(fill=tk.X)

            # 添加精致分隔线（除了最后一项）
            if i < len(group["items"]) - 1:
                item_separator_container = tk.Frame(group_card, bg=MacOSTheme.CARD_BG, height=1)
                item_separator_container.pack(fill=tk.X, padx=72)
                item_separator_container.pack_propagate(False)

                item_separator = tk.Frame(item_separator_container, bg=MacOSTheme.SEPARATOR_LIGHT, height=1)
                item_separator.pack(fill=tk.X)

    def create_status_bar(self):
        """创建状态栏"""
        # 状态栏容器
        status_container = tk.Frame(self.main_frame, bg="#FFFFFF", height=44)
        status_container.pack(side=tk.BOTTOM, fill=tk.X)
        status_container.pack_propagate(False)

        # 顶部分隔线
        separator = tk.Frame(status_container, bg="#E5E7EB", height=1)
        separator.pack(fill=tk.X)

        # 状态内容
        status_content = tk.Frame(status_container, bg="#FFFFFF")
        status_content.pack(fill=tk.BOTH, expand=True, padx=40, pady=12)

        # 左侧状态
        status_frame = tk.Frame(status_content, bg="#FFFFFF")
        status_frame.pack(side=tk.LEFT)

        self.status_label = tk.Label(status_frame, text="🟢 系统就绪",
                                     font=("SF Pro Display", 13, "normal"),
                                     fg="#374151", bg="#FFFFFF")
        self.status_label.pack(side=tk.LEFT)

        # 右侧时间
        time_frame = tk.Frame(status_content, bg="#FFFFFF")
        time_frame.pack(side=tk.RIGHT)

        self.time_label = tk.Label(time_frame, text="",
                                   font=("SF Pro Display", 13, "normal"),
                                   fg="#6B7280", bg="#FFFFFF")
        self.time_label.pack(side=tk.RIGHT)

    def start_updates(self):
        """启动状态更新"""

        def update_time():
            current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
            self.time_label.config(text=current_time)
            self.root.after(1000, update_time)

        update_time()

    # ==== 新增功能实现方法 ====

    def fetch_data_unified(self):
        """统一数据获取入口"""
        self.get_stock_input_and_run("auto", "请输入股票代码:")

    def manage_license(self):
        """授权管理"""
        # 显示当前授权状态
        is_valid, message = self.validator.validate_license()

        if is_valid:
            license_info = self.validator.get_license_info()
            if license_info:
                info_text = f"授权状态: ✅ 已激活\n"
                info_text += f"授权码: {license_info.get('license_code', 'N/A')}\n"
                info_text += f"设备ID: {license_info.get('device_id', 'N/A')}\n"
                info_text += f"激活时间: {license_info.get('activation_time', 'N/A')[:19]}"
                messagebox.showinfo("授权信息", info_text)
            else:
                messagebox.showinfo("授权状态", "✅ 授权有效")
        else:
            # 显示激活对话框
            result = messagebox.askyesno("授权状态",
                                         f"❌ {message}\n\n是否现在激活授权码？")
            if result:
                self.activate_license()

    def fetch_tushare(self):
        """使用Tushare获取股票数据"""
        self.get_stock_input_and_run("tushare", "请输入股票代码 (格式: 000001.SZ):")

    def fetch_crawler(self):
        """使用爬虫获取股票数据"""
        self.get_stock_input_and_run("crawler", "请输入股票代码 (格式: 000001):")

    def check_license(self):
        """检查授权状态"""
        is_valid, message = self.validator.validate_license()
        status = "✅ 已授权" if is_valid else f"❌ {message}"
        messagebox.showinfo("授权状态", f"授权状态: {status}")

    def show_system_status(self):
        """查看系统状态"""
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 12", "12", "正在检查系统状态...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 12", "12", "正在检查系统状态...", auto_input=None)

    def test_crawler(self):
        """测试爬虫功能"""
        # 通过quick_start.sh调用，确保使用相同的Python环境
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 10", "10", "正在测试爬虫功能...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 10", "10", "正在测试爬虫功能...", auto_input=None)

    def install_dependencies(self):
        """一键安装所有依赖"""
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 1", "1", "正在执行一键安装...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 1", "1", "正在执行一键安装...", auto_input=None)

    def config_wizard(self):
        """配置数据源向导"""
        # 通过quick_start.sh调用，确保使用相同的Python环境
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 2", "2", "正在启动配置向导...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 2", "2", "正在启动配置向导...", auto_input=None)

    def check_environment(self):
        """检查环境状态"""
        # 通过quick_start.sh调用，确保使用相同的Python环境
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 3", "3", "正在检查环境状态...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 3", "3", "正在检查环境状态...", auto_input=None)

    def fetch_tushare(self):
        """使用Tushare获取股票数据"""
        self.get_stock_input_and_run("tushare", "请输入股票代码 (格式: 000001.SZ):")

    def fetch_crawler(self):
        """使用爬虫获取股票数据"""
        self.get_stock_input_and_run("crawler", "请输入股票代码 (格式: 000001):")

    def batch_predict(self):
        """批量获取数据及预测K线"""
        self.get_batch_input_and_run()

    def check_license(self):
        """检查授权状态"""
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 7", "7", "正在检查授权状态...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 7", "7", "正在检查授权状态...", auto_input=None)

    def activate_license(self):
        """激活授权码"""
        sheet = LicenseActivationSheet(self.root, self.validator)
        self.root.wait_window(sheet.sheet)

    def run_prediction(self):
        """运行预测示例 - 带股票代码输入"""
        self.get_stock_input_and_run_prediction()

    def test_crawler(self):
        """测试爬虫功能"""
        # 通过quick_start.sh调用，确保使用相同的Python环境
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 10", "10", "正在测试爬虫功能...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 10", "10", "正在测试爬虫功能...", auto_input=None)

    def show_help(self):
        """显示使用帮助"""
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 11", "11", "显示使用帮助", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 11", "11", "显示使用帮助", auto_input=None)

    def show_system_status(self):
        """查看系统状态"""
        if platform.system() == "Windows":
            self.run_shell_command("powershell quick_start.ps1 12", "12", "正在检查系统状态...", auto_input=None)
        else:
            self.run_shell_command("bash quick_start.sh 12", "12", "正在检查系统状态...", auto_input=None)

    # ==== 辅助方法 ====

    def get_stock_input_and_run(self, source, prompt):
        """获取股票代码输入并执行"""
        dialog = tk.Toplevel(self.root)
        dialog.title("输入股票代码")
        dialog.geometry("450x400")  # 增加高度从320到400
        dialog.configure(bg="#FFFFFF")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        # 居中
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)  # 更新y坐标
        dialog.geometry(f"450x400+{x}+{y}")

        # 主容器
        main_frame = tk.Frame(dialog, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=25)

        # 移除重复的关闭按钮，只保留底部的取消按钮

        # 头部区域
        header_frame = tk.Frame(main_frame, bg="#FFFFFF")
        header_frame.pack(fill=tk.X, pady=(0, 25))

        # 图标
        icon_label = tk.Label(header_frame, text="📈",
                              font=("Apple Color Emoji", 28),
                              bg="#FFFFFF")
        icon_label.pack(pady=(0, 8))

        # 标题
        title_label = tk.Label(header_frame, text="股票代码",
                               font=("SF Pro Display", 18, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack()

        # 提示文字
        prompt_label = tk.Label(header_frame, text=prompt,
                                font=("SF Pro Display", 13, "normal"),
                                fg="#6B7280", bg="#FFFFFF")
        prompt_label.pack(pady=(5, 0))

        # 输入区域
        input_frame = tk.Frame(main_frame, bg="#FFFFFF")
        input_frame.pack(fill=tk.X, pady=(0, 25))

        # 现代化输入框
        entry_container = tk.Frame(input_frame, bg="#F9FAFB", relief="flat", bd=0)
        entry_container.pack(fill=tk.X)

        entry = tk.Entry(entry_container, font=("SF Pro Display", 14, "normal"),
                         bg="#F9FAFB", fg="#1F2937", relief="flat", bd=0,
                         highlightthickness=0, justify="center")
        entry.pack(fill=tk.X, ipady=12, ipadx=16, pady=2, padx=2)
        entry.focus_set()

        def execute():
            symbol = entry.get().strip()
            if symbol:
                dialog.destroy()
                if source == "tushare":
                    cmd = f"{PYTHON_COMMAND} scripts/fetch_data.py --symbol {symbol} --source tushare"
                else:
                    cmd = f"{PYTHON_COMMAND} scripts/fetch_data.py --symbol {symbol} --source auto"
                self.run_shell_command(cmd, None, f"正在获取 {symbol} 的数据...")
            else:
                # 显示错误提示
                entry_container.configure(bg="#FEE2E2")
                entry.configure(bg="#FEE2E2")
                main_frame.after(2000, lambda: [
                    entry_container.configure(bg="#F9FAFB"),
                    entry.configure(bg="#F9FAFB")
                ])

        # 按钮区域 - 固定在底部
        btn_frame = tk.Frame(main_frame, bg="#FFFFFF")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(30, 0))

        # 创建右对齐容器
        btn_container = tk.Frame(btn_frame, bg="#FFFFFF")
        btn_container.pack(side=tk.RIGHT)

        # Windows和macOS使用不同的按钮创建方式
        if platform.system() == "Windows":
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("Microsoft YaHei", 14, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=35, pady=12, command=dialog.destroy,
                                   cursor="hand2", activebackground="#F9FAFB",
                                   highlightthickness=1, highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始获取按钮 - 深色蓝紫色
            ok_btn = tk.Button(btn_container, text="开始获取",
                               font=("Microsoft YaHei", 14, "bold"),
                               fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                               padx=35, pady=13, command=execute,
                               cursor="hand2", activebackground="#3730A3")
            ok_btn.pack(side=tk.LEFT)

            # 悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_ok_hover(e):
                ok_btn.configure(bg="#3730A3")

            def on_ok_leave(e):
                ok_btn.configure(bg="#4338CA")

            ok_btn.bind("<Enter>", on_ok_hover)
            ok_btn.bind("<Leave>", on_ok_leave)
        else:
            # macOS: 使用现代化设计的按钮
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("SF Pro Display", 15, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=40, pady=12, command=dialog.destroy,
                                   cursor="hand2", highlightthickness=1,
                                   highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始获取按钮 - 深色蓝紫色
            ok_btn = tk.Button(btn_container, text="开始获取",
                               font=("SF Pro Display", 15, "bold"),
                               fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                               padx=40, pady=13, command=execute,
                               cursor="hand2")
            ok_btn.pack(side=tk.LEFT)

            # macOS按钮悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_ok_hover(e):
                ok_btn.configure(bg="#3730A3")

            def on_ok_leave(e):
                ok_btn.configure(bg="#4338CA")

            ok_btn.bind("<Enter>", on_ok_hover)
            ok_btn.bind("<Leave>", on_ok_leave)

        dialog.bind('<Return>', lambda e: execute())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def get_stock_input_and_run_prediction(self):
        """获取股票代码输入并执行AI预测"""
        dialog = tk.Toplevel(self.root)
        dialog.title("AI预测分析")
        dialog.geometry("450x400")  # 增加高度从320到400
        dialog.configure(bg="#FFFFFF")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        # 居中
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)  # 更新y坐标
        dialog.geometry(f"450x400+{x}+{y}")

        # 主容器
        main_frame = tk.Frame(dialog, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=25)

        # 移除重复的关闭按钮，只保留底部的取消按钮

        # 头部区域
        header_frame = tk.Frame(main_frame, bg="#FFFFFF")
        header_frame.pack(fill=tk.X, pady=(0, 25))

        # 图标
        icon_label = tk.Label(header_frame, text="🤖",
                              font=("Apple Color Emoji", 28),
                              bg="#FFFFFF")
        icon_label.pack(pady=(0, 8))

        # 标题
        title_label = tk.Label(header_frame, text="AI预测分析",
                               font=("SF Pro Display", 18, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack()

        # 提示文字
        prompt_label = tk.Label(header_frame, text="请输入股票代码进行AI预测分析",
                                font=("SF Pro Display", 13, "normal"),
                                fg="#6B7280", bg="#FFFFFF")
        prompt_label.pack(pady=(5, 0))

        # 输入区域
        input_frame = tk.Frame(main_frame, bg="#FFFFFF")
        input_frame.pack(fill=tk.X, pady=(0, 25))

        # 现代化输入框
        entry_container = tk.Frame(input_frame, bg="#F9FAFB", relief="flat", bd=0)
        entry_container.pack(fill=tk.X)

        entry = tk.Entry(entry_container, font=("SF Pro Display", 14, "normal"),
                         bg="#F9FAFB", fg="#1F2937", relief="flat", bd=0,
                         highlightthickness=0, justify="center")
        entry.pack(fill=tk.X, ipady=12, ipadx=16, pady=2, padx=2)
        entry.insert(0, "")
        entry.focus_set()

        def execute():
            symbol = entry.get().strip()
            if symbol:
                dialog.destroy()
                cmd = f"{PYTHON_COMMAND} examples/prediction_batch_example.py --stock-code {symbol}"
                self.run_shell_command_with_analysis(cmd, f"正在进行 {symbol} 的AI预测分析...", symbol)
            else:
                # 显示错误提示
                entry_container.configure(bg="#FEE2E2")
                entry.configure(bg="#FEE2E2")
                main_frame.after(2000, lambda: [
                    entry_container.configure(bg="#F9FAFB"),
                    entry.configure(bg="#F9FAFB")
                ])

        # 按钮区域 - 固定在底部
        btn_frame = tk.Frame(main_frame, bg="#FFFFFF")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(30, 0))

        # 创建右对齐容器
        btn_container = tk.Frame(btn_frame, bg="#FFFFFF")
        btn_container.pack(side=tk.RIGHT)

        # Windows和macOS使用不同的按钮创建方式
        if platform.system() == "Windows":
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("Microsoft YaHei", 14, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=35, pady=12, command=dialog.destroy,
                                   cursor="hand2", activebackground="#F9FAFB",
                                   highlightthickness=1, highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始预测按钮 - 深色蓝紫色
            ok_btn = tk.Button(btn_container, text="开始预测",
                               font=("Microsoft YaHei", 14, "bold"),
                               fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                               padx=35, pady=13, command=execute,
                               cursor="hand2", activebackground="#3730A3")
            ok_btn.pack(side=tk.LEFT)

            # 悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_ok_hover(e):
                ok_btn.configure(bg="#3730A3")

            def on_ok_leave(e):
                ok_btn.configure(bg="#4338CA")

            ok_btn.bind("<Enter>", on_ok_hover)
            ok_btn.bind("<Leave>", on_ok_leave)
        else:
            # macOS: 使用现代化设计的按钮
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("SF Pro Display", 15, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=40, pady=12, command=dialog.destroy,
                                   cursor="hand2", highlightthickness=1,
                                   highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始预测按钮 - 深色蓝紫色
            ok_btn = tk.Button(btn_container, text="开始预测",
                               font=("SF Pro Display", 15, "bold"),
                               fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                               padx=40, pady=13, command=execute,
                               cursor="hand2")
            ok_btn.pack(side=tk.LEFT)

            # macOS按钮悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_ok_hover(e):
                ok_btn.configure(bg="#3730A3")

            def on_ok_leave(e):
                ok_btn.configure(bg="#4338CA")

            ok_btn.bind("<Enter>", on_ok_hover)
            ok_btn.bind("<Leave>", on_ok_leave)

        entry.bind('<Return>', lambda e: execute())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def get_batch_input_and_run(self):
        """获取批量输入并执行"""
        dialog = tk.Toplevel(self.root)
        dialog.title("批量获取数据及预测")
        dialog.geometry("550x550")  # 增加高度从450到550
        dialog.configure(bg="#FFFFFF")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        # 居中
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (550 // 2)
        y = (dialog.winfo_screenheight() // 2) - (550 // 2)  # 更新y坐标计算
        dialog.geometry(f"550x550+{x}+{y}")

        # 添加圆角效果和阴影
        dialog.configure(relief="flat", bd=0)

        # 主容器 - 调整padding给按钮留出空间
        main_frame = tk.Frame(dialog, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=(25, 20))

        # 移除重复的关闭按钮，只保留底部的取消按钮

        # 标题区域
        header_frame = tk.Frame(main_frame, bg="#FFFFFF")
        header_frame.pack(fill=tk.X, pady=(0, 25))

        # 图标
        icon_label = tk.Label(header_frame, text="📊",
                              font=("Apple Color Emoji", 32),
                              bg="#FFFFFF")
        icon_label.pack(pady=(0, 10))

        # 标题
        title_label = tk.Label(header_frame, text="批量获取数据及预测",
                               font=("SF Pro Display", 18, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack()

        # 描述
        desc_label = tk.Label(header_frame, text="批量获取多个股票的数据并进行AI预测分析",
                              font=("SF Pro Display", 13, "normal"),
                              fg="#6B7280", bg="#FFFFFF")
        desc_label.pack(pady=(5, 0))

        # 表单区域 - 减少底部间距
        form_frame = tk.Frame(main_frame, bg="#FFFFFF")
        form_frame.pack(fill=tk.X, pady=(0, 15))

        # 股票代码输入
        symbol_label = tk.Label(form_frame, text="股票代码",
                                font=("SF Pro Display", 14, "bold"),
                                fg="#1F2937", bg="#FFFFFF")
        symbol_label.pack(anchor="w", pady=(0, 5))

        symbol_hint = tk.Label(form_frame, text="多个股票代码用逗号分隔 (如: 000001.SZ,600000.SH)",
                               font=("SF Pro Display", 11, "normal"),
                               fg="#9CA3AF", bg="#FFFFFF")
        symbol_hint.pack(anchor="w", pady=(0, 8))

        # 现代化输入框
        symbol_container = tk.Frame(form_frame, bg="#F9FAFB", relief="flat", bd=0)
        symbol_container.pack(fill=tk.X, pady=(0, 20))

        symbol_entry = tk.Entry(symbol_container, font=("SF Pro Display", 13, "normal"),
                                bg="#F9FAFB", fg="#1F2937", relief="flat", bd=0,
                                highlightthickness=0,
                                insertbackground="#4338CA", insertwidth=2)
        symbol_entry.pack(fill=tk.X, ipady=10, ipadx=12, pady=2, padx=2)
        symbol_entry.insert(0, "")
        symbol_entry.focus_set()
        # 强制聚焦并确保插入光标可见（Windows 下偶发光标不可见）
        dialog.after(50, symbol_entry.focus_force)
        dialog.after(60, lambda: symbol_entry.icursor(tk.END))

        # 天数输入
        days_label = tk.Label(form_frame, text="获取天数",
                              font=("SF Pro Display", 14, "bold"),
                              fg="#1F2937", bg="#FFFFFF")
        days_label.pack(anchor="w", pady=(0, 5))

        days_hint = tk.Label(form_frame, text="建议获取365天以上的数据以提高预测准确性",
                             font=("SF Pro Display", 11, "normal"),
                             fg="#9CA3AF", bg="#FFFFFF")
        days_hint.pack(anchor="w", pady=(0, 8))

        days_container = tk.Frame(form_frame, bg="#F9FAFB", relief="flat", bd=0)
        days_container.pack(fill=tk.X)

        days_entry = tk.Entry(days_container, font=("SF Pro Display", 13, "normal"),
                              bg="#F9FAFB", fg="#1F2937", relief="flat", bd=0,
                              highlightthickness=0,
                              insertbackground="#4338CA", insertwidth=2)
        days_entry.pack(fill=tk.X, ipady=10, ipadx=12, pady=2, padx=2)
        days_entry.insert(0, "365")

        def execute():
            symbols = symbol_entry.get().strip()
            days = days_entry.get().strip() or "365"

            if symbols:
                dialog.destroy()
                # 准备输入参数，模拟用户在第六步中的输入
                symbols_param = symbols.replace(',', ' ')

                # Windows 无 printf/bash，做跨平台分支
                if platform.system() == "Windows":
                    # 通过 PowerShell quick_start.ps1 的 6 分支执行（不走 bash/printf）
                    work_dir = project_root  # 确保work_dir已定义
                    ps1_path = work_dir / "quick_start.ps1"
                    # 设置环境变量传入参数
                    os.environ['KRONOS_SYMBOLS'] = symbols
                    os.environ['KRONOS_SOURCE'] = 'auto'
                    os.environ['KRONOS_DAYS'] = days
                    # 修复Windows PowerShell命令执行，避免编码和路径问题
                    cmd = f'cmd /c "chcp 65001 >nul 2>&1 && powershell -NoProfile -ExecutionPolicy Bypass -File {ps1_path} 6"'
                else:
                    # 使用 bash + printf 的现有路径
                    cmd = f'printf "{symbols}\\n1\\n{days}\\n" | bash ./quick_start.sh 6'

                self.run_shell_command_with_analysis(cmd, f"正在批量获取数据和预测分析...", symbols)
            else:
                # 显示错误提示
                symbol_container.configure(bg="#FEE2E2")
                symbol_entry.configure(bg="#FEE2E2")
                main_frame.after(2000, lambda: [
                    symbol_container.configure(bg="#F9FAFB"),
                    symbol_entry.configure(bg="#F9FAFB")
                ])

        # 现代化按钮区域 - 固定在底部
        btn_frame = tk.Frame(main_frame, bg="#FFFFFF")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(30, 0))

        # 创建右对齐容器
        btn_container = tk.Frame(btn_frame, bg="#FFFFFF")
        btn_container.pack(side=tk.RIGHT)

        # Windows和macOS使用不同的按钮创建方式
        if platform.system() == "Windows":
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("Microsoft YaHei", 14, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=35, pady=12, command=dialog.destroy,
                                   cursor="hand2", activebackground="#F9FAFB",
                                   highlightthickness=1, highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始分析按钮 - 深色蓝紫色
            execute_btn = tk.Button(btn_container, text="开始获取分析",
                                    font=("Microsoft YaHei", 14, "bold"),
                                    fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                                    padx=35, pady=13, command=execute,
                                    cursor="hand2", activebackground="#3730A3")
            execute_btn.pack(side=tk.LEFT)

            # 悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_execute_hover(e):
                execute_btn.configure(bg="#3730A3")

            def on_execute_leave(e):
                execute_btn.configure(bg="#4338CA")

            execute_btn.bind("<Enter>", on_execute_hover)
            execute_btn.bind("<Leave>", on_execute_leave)
        else:
            # macOS: 使用现代化设计的按钮
            # 取消按钮 - 深色边框
            cancel_btn = tk.Button(btn_container, text="取消",
                                   font=("SF Pro Display", 15, "bold"),
                                   fg="#374151", bg="#FFFFFF", relief="solid", bd=1,
                                   padx=40, pady=12, command=dialog.destroy,
                                   cursor="hand2", highlightthickness=1,
                                   highlightbackground="#D1D5DB")
            cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

            # 开始分析按钮 - 深色蓝紫色
            execute_btn = tk.Button(btn_container, text="开始获取分析",
                                    font=("SF Pro Display", 15, "bold"),
                                    fg="#FFFFFF", bg="#4338CA", relief="flat", bd=0,
                                    padx=40, pady=13, command=execute,
                                    cursor="hand2")
            execute_btn.pack(side=tk.LEFT)

            # macOS按钮悬停效果
            def on_cancel_hover(e):
                cancel_btn.configure(bg="#F9FAFB")

            def on_cancel_leave(e):
                cancel_btn.configure(bg="#FFFFFF")

            cancel_btn.bind("<Enter>", on_cancel_hover)
            cancel_btn.bind("<Leave>", on_cancel_leave)

            def on_execute_hover(e):
                execute_btn.configure(bg="#3730A3")

            def on_execute_leave(e):
                execute_btn.configure(bg="#4338CA")

            execute_btn.bind("<Enter>", on_execute_hover)
            execute_btn.bind("<Leave>", on_execute_leave)

        # 绑定键盘事件
        dialog.bind('<Return>', lambda e: execute())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def run_shell_command_with_analysis(self, command, status_text="正在执行命令...", symbols=""):
        """执行shell命令并在完成后进行预测分析"""
        # 先执行数据获取
        cmd_window = self.create_command_window(status_text)

        def run_command():
            original_dir = os.getcwd()
            try:
                self.status_label.config(text=f"🔄 {status_text}")

                # 获取正确的工作目录
                if getattr(sys, 'frozen', False):
                    # 打包应用中，使用正确的工作目录
                    if hasattr(sys, '_MEIPASS'):
                        work_dir = Path(sys._MEIPASS)
                    else:
                        # 更强大的.app包检测
                        executable_path = Path(sys.executable)
                        # 检查是否在.app包内的多种情况
                        if ".app" in str(executable_path):
                            # 在.app包内，查找正确的Resources目录
                            app_path = None
                            current = executable_path
                            while current.parent != current:
                                if current.name.endswith('.app'):
                                    app_path = current
                                    break
                                current = current.parent

                            if app_path:
                                work_dir = app_path / "Contents" / "Resources"
                            else:
                                # 备选方案：从当前路径推断
                                executable_str = str(executable_path)
                                if "/Contents/" in executable_str:
                                    contents_index = executable_str.find("/Contents/")
                                    app_root = executable_str[:contents_index + len("/Contents")]
                                    work_dir = Path(app_root) / "Resources"
                                else:
                                    work_dir = executable_path.parent.parent / "Resources"
                        else:
                            work_dir = executable_path.parent
                else:
                    work_dir = project_root

                # 检测是否在应用包内，设置用户目录环境变量
                if str(work_dir).find('.app/Contents') != -1:
                    user_dir = Path.home() / "Documents" / "Kronos"
                    user_dir.mkdir(parents=True, exist_ok=True)
                    # 设置Kronos专用环境变量
                    os.environ['KRONOS_USER_DIR'] = str(user_dir)
                    os.environ['KRONOS_IS_APP_BUNDLE'] = 'true'
                    os.environ['KRONOS_DATA_DIR'] = str(user_dir / "data")
                    os.environ['KRONOS_LOGS_DIR'] = str(user_dir / "logs")
                    os.environ['KRONOS_RESULTS_DIR'] = str(user_dir / "results")
                    os.environ['KRONOS_MODELS_DIR'] = str(user_dir / "models")
                    os.environ['KRONOS_CONFIG_DIR'] = str(user_dir / "config")

                    # 设置Python命令环境变量，确保与GUI检测一致
                    os.environ['PYTHON_CMD'] = PYTHON_COMMAND
                    os.environ['PYTHON'] = PYTHON_COMMAND

                    # 复制配置文件到用户目录（如果不存在）
                    app_config_dir = work_dir / "config"
                    user_config_dir = user_dir / "config"
                    user_config_dir.mkdir(exist_ok=True)

                    if app_config_dir.exists() and not (user_config_dir / "tushare_config.json").exists():
                        import shutil
                        try:
                            shutil.copytree(app_config_dir, user_config_dir, dirs_exist_ok=True)
                        except:
                            pass
                else:
                    os.environ['KRONOS_USER_DIR'] = str(work_dir)
                    os.environ['KRONOS_IS_APP_BUNDLE'] = 'false'

                output_text = cmd_window.output_text
                output_text.insert(tk.END, f"工作目录: {work_dir}\n")
                output_text.insert(tk.END, f"原始命令: {command}\n")
                output_text.see(tk.END)
                cmd_window.window.update()

                # 切换到工作目录
                os.chdir(work_dir)

                # 修复命令路径
                final_command = command
                if command.startswith(f"{PYTHON_COMMAND} scripts/") or command.startswith(
                        f"{PYTHON_COMMAND} examples/"):
                    # 提取脚本部分
                    script_part = command.replace(f"{PYTHON_COMMAND} ", "").split()[0]  # 只取第一部分，去掉参数
                    script_path = work_dir / script_part
                    if script_path.exists():
                        # 使用引号包围路径以处理空格，并设置PYTHONPATH
                        script_args = command.replace(f"{PYTHON_COMMAND} {script_part}", "")  # 提取参数部分
                        final_command = f'PYTHONPATH="{work_dir}:{work_dir}/scripts:{work_dir}/examples:{work_dir}/model" "{PYTHON_COMMAND}" "{script_path}"{script_args}'
                    else:
                        output_text.insert(tk.END, f"警告：脚本文件不存在 {script_path}\n")
                        final_command = f'PYTHONPATH="{work_dir}" "{PYTHON_COMMAND}" {command.replace(f"{PYTHON_COMMAND} ", "")}'
                elif command.startswith("powershell quick_start.ps1"):
                    # Windows PowerShell脚本执行 - 提取参数
                    script_args = command.replace("powershell quick_start.ps1", "").strip()
                    ps1_path = work_dir / "quick_start.ps1"
                    if ps1_path.exists():
                        # 使用编码安全的PowerShell调用，避免乱码和路径问题
                        final_command = f'cmd /c "chcp 65001 >nul 2>&1 && powershell -NoProfile -ExecutionPolicy Bypass -File {ps1_path} {script_args}"'
                    else:
                        # 如果ps1不存在，尝试直接执行对应的Python命令
                        output_text.insert(tk.END, f"警告：PowerShell脚本不存在 {ps1_path}，尝试直接执行Python命令\n")
                        if script_args == "3":  # 环境检查
                            final_command = f'{PYTHON_COMMAND} scripts/check_environment.py'
                        elif script_args == "1":  # 安装依赖
                            final_command = f'{PYTHON_COMMAND} -m pip install -r requirements.txt'
                        else:
                            final_command = command

                output_text.insert(tk.END, f"执行命令: {final_command}\n\n")
                output_text.see(tk.END)
                cmd_window.window.update()

                # 设置环境变量
                env = os.environ.copy()
                env['TERM'] = 'xterm-256color'
                env['PYTHONPATH'] = f"{work_dir}:{work_dir}/scripts:{work_dir}/examples:{work_dir}/model"
                # 强制子进程使用UTF-8，避免Windows控制台乱码
                env['PYTHONIOENCODING'] = 'utf-8'
                env['PYTHONUTF8'] = '1'
                env['LC_ALL'] = 'C.UTF-8'
                env['LANG'] = 'C.UTF-8'

                # 在打包模式下，安装依赖（参数为"1"）时允许强制安装
                try:
                    if command.startswith("powershell quick_start.ps1"):
                        script_args_all = command.replace("powershell quick_start.ps1", "").strip()
                        if script_args_all == "1":
                            env['KRONOS_FORCE_INSTALL_IN_APP'] = 'true'
                except Exception:
                    pass

                # 跨平台PATH设置
                system = platform.system()
                if system == "Darwin":  # macOS
                    env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:' + env.get('PATH', '')
                elif system == "Linux":  # Linux
                    env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
                elif system == "Windows":  # Windows
                    env['PATH'] = 'C:\\Python311;C:\\Python311\\Scripts;' + env.get('PATH', '')

                # 智能Python路径检测
                def detect_python():
                    # 动态检测系统中的Python，而不使用sys.executable（应用包内会指向Kronos本身）
                    python_names = ['python3.11', 'python3', 'python']
                    if os.name == 'nt':
                        python_names = ['python3.11.exe', 'python3.exe', 'python.exe'] + python_names

                    import shutil
                    for py_name in python_names:
                        py_path = shutil.which(py_name)
                        if py_path:
                            try:
                                result = subprocess.run([py_path, "--version"],
                                                        capture_output=True, text=True, timeout=5)
                                if result.returncode == 0 and "3.11" in result.stdout:
                                    return py_path
                            except:
                                continue
                    return shutil.which('python3') or 'python3'

                env['PYTHON'] = detect_python()
                env['PYTHON_CMD'] = detect_python()  # 为了与quick_start.sh兼容

                # 执行数据获取命令
                process = subprocess.Popen(final_command, shell=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, universal_newlines=True,
                                           bufsize=1, cwd=work_dir, env=env, encoding='utf-8', errors='replace')

                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        output_text.insert(tk.END, output)
                        output_text.see(tk.END)
                        cmd_window.window.update()

                if process.returncode == 0:
                    output_text.insert(tk.END, "\n✅ 数据获取完成！\n")
                    output_text.see(tk.END)
                    cmd_window.window.update()

                    # quick_start.sh 脚本已经自动运行了预测分析，无需在GUI中重复执行
                    # 删除重复的预测分析代码，避免同一股票被分析两次

                    # 查找生成的HTML报告 - 修复：使用正确的结果目录
                    # 优先检查用户目录中的results目录（适配应用包环境）
                    results_dir_env = os.environ.get('KRONOS_RESULTS_DIR')
                    if results_dir_env:
                        results_dir = Path(results_dir_env)
                    else:
                        # 检查用户文档目录中的Kronos/results
                        user_results_dir = Path.home() / "Documents" / "Kronos" / "results"
                        if user_results_dir.exists():
                            results_dir = user_results_dir
                        else:
                            results_dir = work_dir / "results"

                    if results_dir.exists():
                        html_files = list(results_dir.glob("*.html"))
                        if html_files:
                            # 按修改时间排序，显示最新的报告
                            html_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                            output_text.insert(tk.END, f"\n🎉 分析完成！找到 {len(html_files)} 个分析报告\n")
                            output_text.insert(tk.END, f"📁 报告位置: {results_dir}\n\n")

                            # 添加打开报告的按钮
                            self.add_report_buttons(cmd_window.content_frame, html_files)
                        else:
                            output_text.insert(tk.END, f"\n⚠️  分析完成，但在 {results_dir} 未找到HTML报告文件\n")
                    else:
                        output_text.insert(tk.END, f"\n⚠️  分析完成，但results目录不存在: {results_dir}\n")
                else:
                    output_text.insert(tk.END, f"\n❌ 数据获取失败，返回码: {process.returncode}\n")

                self.status_label.config(text="🟢 系统就绪")
                cmd_window.status_label.config(text="✅ 执行完成", fg="#10B981")

            except Exception as e:
                output_text.insert(tk.END, f"\n❌ 执行失败: {str(e)}\n")
                self.status_label.config(text="❌ 执行失败")
                cmd_window.status_label.config(text="❌ 执行失败", fg="#EF4444")
            finally:
                # 恢复原目录
                try:
                    os.chdir(original_dir)
                except:
                    pass

        # 在后台线程中运行命令
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()

        return cmd_window

    def add_report_buttons(self, parent_frame, html_files):
        """添加打开报告的按钮"""
        button_frame = tk.Frame(parent_frame, bg="#FFFFFF")
        button_frame.pack(fill=tk.X, pady=(10, 0))

        for i, html_file in enumerate(html_files):
            btn_text = f"📊 打开报告 {i + 1}: {html_file.name}"

            # Windows平台优化的报告按钮
            if platform.system() == "Windows":
                report_btn = tk.Button(button_frame, text=btn_text,
                                       font=("Microsoft YaHei", 12, "normal"),
                                       fg="#FFFFFF", bg="#28A745", relief="flat", bd=0,
                                       padx=20, pady=10, cursor="hand2",
                                       command=lambda f=html_file: self.open_html_report(f),
                                       activebackground="#218838")
                report_btn.pack(fill=tk.X, pady=3)

                # Windows悬停效果
                def on_hover(e, btn=report_btn):
                    btn.configure(bg="#218838")

                def on_leave(e, btn=report_btn):
                    btn.configure(bg="#28A745")

                report_btn.bind("<Enter>", on_hover)
                report_btn.bind("<Leave>", on_leave)
            else:
                # macOS按钮
                report_btn = tk.Button(button_frame, text=btn_text,
                                       font=("SF Pro Display", 14, "bold"),
                                       fg="#000000", bg="#10B981", relief="flat", bd=0,
                                       padx=20, pady=8, cursor="hand2",
                                       command=lambda f=html_file: self.open_html_report(f))
                report_btn.pack(fill=tk.X, pady=2)

                # macOS悬停效果
                def on_hover(e, btn=report_btn):
                    btn.configure(bg="#059669")

                def on_leave(e, btn=report_btn):
                    btn.configure(bg="#10B981")

                report_btn.bind("<Enter>", on_hover)
                report_btn.bind("<Leave>", on_leave)

    def open_html_report(self, html_file):
        """打开HTML报告"""
        try:
            import webbrowser
            # 确保文件路径使用正确编码，避免路径中的特殊字符导致问题
            safe_path = str(html_file).encode('utf-8', errors='replace').decode('utf-8')
            webbrowser.open(f"file://{safe_path}")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开报告文件: {e}")

    def create_command_window(self, status_text):
        """创建命令输出窗口"""
        cmd_window = tk.Toplevel(self.root)
        cmd_window.title("命令执行")
        cmd_window.geometry("1000x700")
        cmd_window.configure(bg="#FFFFFF")
        cmd_window.transient(self.root)

        # 居中
        cmd_window.update_idletasks()
        x = (cmd_window.winfo_screenwidth() // 2) - (1000 // 2)
        y = (cmd_window.winfo_screenheight() // 2) - (700 // 2)
        cmd_window.geometry(f"1000x700+{x}+{y}")

        # 主容器
        main_frame = tk.Frame(cmd_window, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题栏
        header_frame = tk.Frame(main_frame, bg="#FFFFFF", height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        # 标题
        title_label = tk.Label(header_frame, text="命令执行",
                               font=getattr(self, 'TITLE_FONT', ("SF Pro Display", 18, "bold")),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack(side=tk.LEFT, padx=40, pady=20)

        # 分隔线
        separator = tk.Frame(main_frame, bg="#E5E7EB", height=1)
        separator.pack(fill=tk.X)

        # 内容区域
        content_frame = tk.Frame(main_frame, bg="#FFFFFF")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)

        # 状态标签
        status_label = tk.Label(content_frame, text=status_text,
                                font=("SF Pro Display", 16, "bold"),
                                fg="#4F46E5", bg="#FFFFFF")
        status_label.pack(pady=(0, 20))

        # 输出区域
        output_frame = tk.Frame(content_frame, bg="#F9FAFB", relief="flat", bd=0)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

        # Windows平台使用Consolas字体，macOS使用SF Mono
        if platform.system() == "Windows":
            mono_font = ("Consolas", 10)
        else:
            mono_font = getattr(self, 'MONO_FONT', ("SF Mono", 12))

        output_text = scrolledtext.ScrolledText(output_frame,
                                                bg="#1F2937", fg="#F9FAFB",
                                                font=mono_font,
                                                insertbackground="#F9FAFB",
                                                relief="flat", bd=0,
                                                selectbackground="#374151")
        output_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 底部按钮 - Windows优化
        button_frame = tk.Frame(content_frame, bg="#FFFFFF")
        button_frame.pack(fill=tk.X)

        if platform.system() == "Windows":
            close_bottom_btn = tk.Button(button_frame, text="关闭",
                                         font=("Microsoft YaHei", 12, "normal"),
                                         fg="#495057", bg="#F8F9FA", relief="flat", bd=0,
                                         padx=30, pady=10, command=cmd_window.destroy,
                                         cursor="hand2", activebackground="#E2E6EA")
            close_bottom_btn.pack(side=tk.RIGHT)

            # Windows按钮悬停效果
            def on_close_hover(e):
                close_bottom_btn.configure(bg="#E2E6EA")

            def on_close_leave(e):
                close_bottom_btn.configure(bg="#F8F9FA")

            close_bottom_btn.bind("<Enter>", on_close_hover)
            close_bottom_btn.bind("<Leave>", on_close_leave)
        else:
            close_bottom_btn = tk.Button(button_frame, text="关闭",
                                         font=("SF Pro Display", 14, "bold"),
                                         fg="#1A1A1A", bg="#F0F2F5", relief="flat", bd=0,
                                         padx=32, pady=12, command=cmd_window.destroy,
                                         cursor="hand2")
            close_bottom_btn.pack(side=tk.RIGHT)

        # 创建返回对象
        class CommandWindow:
            def __init__(self):
                self.window = cmd_window
                self.status_label = status_label
                self.output_text = output_text
                self.content_frame = content_frame

        return CommandWindow()

    def run_shell_command(self, command, menu_choice=None, status_text="正在执行命令...", auto_input=None):
        """执行shell命令"""
        # 创建命令输出窗口
        cmd_window = tk.Toplevel(self.root)
        cmd_window.title("命令执行")
        cmd_window.geometry("1000x700")
        cmd_window.configure(bg="#FFFFFF")
        cmd_window.transient(self.root)

        # 居中
        cmd_window.update_idletasks()
        x = (cmd_window.winfo_screenwidth() // 2) - (1000 // 2)
        y = (cmd_window.winfo_screenheight() // 2) - (700 // 2)
        cmd_window.geometry(f"1000x700+{x}+{y}")

        # 主容器
        main_frame = tk.Frame(cmd_window, bg="#FFFFFF")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题栏
        header_frame = tk.Frame(main_frame, bg="#FFFFFF", height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        # 标题
        title_label = tk.Label(header_frame, text="命令执行",
                               font=("SF Pro Display", 18, "bold"),
                               fg="#1F2937", bg="#FFFFFF")
        title_label.pack(side=tk.LEFT, padx=40, pady=20)

        # 分隔线
        separator = tk.Frame(main_frame, bg="#E5E7EB", height=1)
        separator.pack(fill=tk.X)

        # 内容区域
        content_frame = tk.Frame(main_frame, bg="#FFFFFF")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)

        # 状态标签
        status_label = tk.Label(content_frame, text=status_text,
                                font=("SF Pro Display", 16, "bold"),
                                fg="#4F46E5", bg="#FFFFFF")
        status_label.pack(pady=(0, 20))

        # 输出区域
        output_frame = tk.Frame(content_frame, bg="#F9FAFB", relief="flat", bd=0)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

        # Windows平台使用Consolas字体，macOS使用SF Mono
        if platform.system() == "Windows":
            mono_font = ("Consolas", 10)
        else:
            mono_font = ("SF Mono", 12)

        output_text = scrolledtext.ScrolledText(output_frame,
                                                bg="#1F2937", fg="#F9FAFB",
                                                font=mono_font,
                                                insertbackground="#F9FAFB",
                                                relief="flat", bd=0,
                                                selectbackground="#374151")
        output_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 底部按钮 - Windows优化
        button_frame = tk.Frame(content_frame, bg="#FFFFFF")
        button_frame.pack(fill=tk.X)

        if platform.system() == "Windows":
            close_bottom_btn = tk.Button(button_frame, text="关闭",
                                         font=("Microsoft YaHei", 12, "normal"),
                                         fg="#495057", bg="#F8F9FA", relief="flat", bd=0,
                                         padx=30, pady=10, command=cmd_window.destroy,
                                         cursor="hand2", activebackground="#E2E6EA")
            close_bottom_btn.pack(side=tk.RIGHT)

            # Windows按钮悬停效果
            def on_close_hover_2(e):
                close_bottom_btn.configure(bg="#E2E6EA")

            def on_close_leave_2(e):
                close_bottom_btn.configure(bg="#F8F9FA")

            close_bottom_btn.bind("<Enter>", on_close_hover_2)
            close_bottom_btn.bind("<Leave>", on_close_leave_2)
        else:
            close_bottom_btn = tk.Button(button_frame, text="关闭",
                                         font=("SF Pro Display", 14, "bold"),
                                         fg="#1A1A1A", bg="#F0F2F5", relief="flat", bd=0,
                                         padx=32, pady=12, command=cmd_window.destroy,
                                         cursor="hand2")
            close_bottom_btn.pack(side=tk.RIGHT)

        def run_command():
            original_dir = os.getcwd()
            try:
                self.status_label.config(text=f"🔄 {status_text}")

                # 获取正确的工作目录
                if getattr(sys, 'frozen', False):
                    # 打包应用中，使用正确的工作目录
                    if hasattr(sys, '_MEIPASS'):
                        work_dir = Path(sys._MEIPASS)
                    else:
                        # 更强大的.app包检测
                        executable_path = Path(sys.executable)
                        # 检查是否在.app包内的多种情况
                        if ".app" in str(executable_path):
                            # 在.app包内，查找正确的Resources目录
                            app_path = None
                            current = executable_path
                            while current.parent != current:
                                if current.name.endswith('.app'):
                                    app_path = current
                                    break
                                current = current.parent

                            if app_path:
                                work_dir = app_path / "Contents" / "Resources"
                            else:
                                # 备选方案：从当前路径推断
                                executable_str = str(executable_path)
                                if "/Contents/" in executable_str:
                                    contents_index = executable_str.find("/Contents/")
                                    app_root = executable_str[:contents_index + len("/Contents")]
                                    work_dir = Path(app_root) / "Resources"
                                else:
                                    work_dir = executable_path.parent.parent / "Resources"
                        else:
                            work_dir = executable_path.parent
                else:
                    work_dir = project_root

                # 检测是否在应用包内，设置用户目录环境变量
                if str(work_dir).find('.app/Contents') != -1:
                    user_dir = Path.home() / "Documents" / "Kronos"
                    user_dir.mkdir(parents=True, exist_ok=True)
                    # 设置Kronos专用环境变量
                    os.environ['KRONOS_USER_DIR'] = str(user_dir)
                    os.environ['KRONOS_IS_APP_BUNDLE'] = 'true'
                    os.environ['KRONOS_DATA_DIR'] = str(user_dir / "data")
                    os.environ['KRONOS_LOGS_DIR'] = str(user_dir / "logs")
                    os.environ['KRONOS_RESULTS_DIR'] = str(user_dir / "results")
                    os.environ['KRONOS_MODELS_DIR'] = str(user_dir / "models")
                    os.environ['KRONOS_CONFIG_DIR'] = str(user_dir / "config")

                    # 设置Python命令环境变量，确保与GUI检测一致
                    os.environ['PYTHON_CMD'] = PYTHON_COMMAND
                    os.environ['PYTHON'] = PYTHON_COMMAND

                    # 复制配置文件到用户目录（如果不存在）
                    app_config_dir = work_dir / "config"
                    user_config_dir = user_dir / "config"
                    user_config_dir.mkdir(exist_ok=True)

                    if app_config_dir.exists() and not (user_config_dir / "tushare_config.json").exists():
                        import shutil
                        try:
                            shutil.copytree(app_config_dir, user_config_dir, dirs_exist_ok=True)
                        except:
                            pass
                else:
                    os.environ['KRONOS_USER_DIR'] = str(work_dir)
                    os.environ['KRONOS_IS_APP_BUNDLE'] = 'false'

                output_text.insert(tk.END, f"工作目录: {work_dir}\n")
                output_text.insert(tk.END, f"原始命令: {command}\n")
                output_text.see(tk.END)
                cmd_window.update()

                # 切换到工作目录
                os.chdir(work_dir)

                # 修复命令路径 - 创建本地变量，正确处理包含空格的路径
                final_command = command
                if command.startswith(f"{PYTHON_COMMAND} scripts/") or command.startswith(
                        f"{PYTHON_COMMAND} examples/"):
                    # 提取脚本部分
                    script_part = command.replace(f"{PYTHON_COMMAND} ", "").split()[0]  # 只取第一部分，去掉参数
                    script_path = work_dir / script_part
                    if script_path.exists():
                        # 使用引号包围路径以处理空格，并设置PYTHONPATH
                        script_args = command.replace(f"{PYTHON_COMMAND} {script_part}", "")  # 提取参数部分
                        final_command = f'PYTHONPATH="{work_dir}:{work_dir}/scripts:{work_dir}/examples:{work_dir}/model" "{PYTHON_COMMAND}" "{script_path}"{script_args}'
                    else:
                        output_text.insert(tk.END, f"警告：脚本文件不存在 {script_path}\n")
                        # 尝试使用相对路径
                        final_command = f'PYTHONPATH="{work_dir}:{work_dir}/scripts:{work_dir}/examples:{work_dir}/model" "{PYTHON_COMMAND}" {command.replace(f"{PYTHON_COMMAND} ", "")}'
                elif command.startswith("bash quick_start.sh"):
                    # 跨平台脚本执行支持 - 提取参数
                    script_args = command.replace("bash quick_start.sh", "").strip()
                    system = platform.system()
                    if system == "Windows":
                        # Windows：使用编码安全的PowerShell调用
                        ps1_path = work_dir / "quick_start.ps1"
                        if ps1_path.exists():
                            # 使用编码安全的PowerShell调用，避免乱码和路径问题
                            final_command = f'cmd /c "chcp 65001 >nul 2>&1 && powershell -NoProfile -ExecutionPolicy Bypass -File {ps1_path} {script_args}"'
                        else:
                            # 如果ps1不存在，尝试创建一个临时的基本PowerShell命令
                            output_text.insert(tk.END, f"警告：PowerShell脚本不存在 {ps1_path}，尝试直接执行Python命令\n")
                            if script_args == "3":  # 环境检查
                                final_command = f'{PYTHON_COMMAND} scripts/check_environment.py'
                            else:
                                final_command = command
                elif command.startswith("powershell quick_start.ps1"):
                    # Windows PowerShell脚本执行 - 提取参数
                    script_args = command.replace("powershell quick_start.ps1", "").strip()
                    ps1_path = work_dir / "quick_start.ps1"
                    if ps1_path.exists():
                        # 使用编码安全的PowerShell调用，避免乱码和路径问题
                        final_command = f'cmd /c "chcp 65001 >nul 2>&1 && powershell -NoProfile -ExecutionPolicy Bypass -File {ps1_path} {script_args}"'
                    else:
                        # 如果ps1不存在，尝试直接执行对应的Python命令
                        output_text.insert(tk.END, f"警告：PowerShell脚本不存在 {ps1_path}，尝试直接执行Python命令\n")
                        if script_args == "3":  # 环境检查
                            final_command = f'{PYTHON_COMMAND} scripts/check_environment.py'
                        elif script_args == "1":  # 安装依赖
                            final_command = f'{PYTHON_COMMAND} -m pip install -r requirements.txt'
                        else:
                            final_command = command

                output_text.insert(tk.END, f"执行命令: {final_command}\n\n")
                output_text.see(tk.END)
                cmd_window.update()

                # 设置环境变量，确保在app包环境中正常执行
                env = os.environ.copy()
                env['TERM'] = 'xterm-256color'
                env['PYTHONPATH'] = f"{work_dir}:{work_dir}/scripts:{work_dir}/examples:{work_dir}/model"  # 设置终端类型
                # 强制子进程使用UTF-8，避免Windows控制台乱码
                env['PYTHONIOENCODING'] = 'utf-8'
                env['PYTHONUTF8'] = '1'
                env['LC_ALL'] = 'C.UTF-8'
                env['LANG'] = 'C.UTF-8'

                # 在打包模式下，安装依赖（参数为"1"）时允许强制安装
                try:
                    if command.startswith("powershell quick_start.ps1"):
                        script_args_all = command.replace("powershell quick_start.ps1", "").strip()
                        if script_args_all == "1":
                            env['KRONOS_FORCE_INSTALL_IN_APP'] = 'true'
                    elif command.startswith("bash quick_start.sh"):
                        script_args_all = command.replace("bash quick_start.sh", "").strip()
                        if script_args_all == "1":
                            env['KRONOS_FORCE_INSTALL_IN_APP'] = 'true'
                except Exception:
                    pass

                # 跨平台PATH设置
                system = platform.system()
                if system == "Darwin":  # macOS
                    env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:' + env.get('PATH', '')
                elif system == "Linux":  # Linux
                    env['PATH'] = '/usr/local/bin:/usr/bin:/bin:' + env.get('PATH', '')
                elif system == "Windows":  # Windows
                    env['PATH'] = 'C:\\Python311;C:\\Python311\\Scripts;' + env.get('PATH', '')

                # 其他系统保持原PATH

                # 智能检测Python路径 - 动态检测而非硬编码
                def detect_python():
                    # 动态检测系统中的Python，而不使用sys.executable（应用包内会指向Kronos本身）
                    python_names = ['python3.11', 'python3', 'python']
                    if os.name == 'nt':  # Windows
                        python_names = ['python3.11.exe', 'python3.exe', 'python.exe'] + python_names

                    best_python = None
                    best_version = ""

                    for py_name in python_names:
                        try:
                            # 使用shutil.which()动态查找
                            import shutil
                            py_path = shutil.which(py_name)
                            if py_path:
                                result = subprocess.run([py_path, "--version"],
                                                        capture_output=True, text=True, timeout=5)
                                if result.returncode == 0:
                                    version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout)
                                    if version_match:
                                        version = version_match.group(0)
                                        # 优先选择3.11.x
                                        if version.startswith('3.11.'):
                                            return py_path
                                        elif version.startswith('3.') and (not best_python or version > best_version):
                                            best_python = py_path
                                            best_version = version
                        except:
                            continue

                    return best_python or 'python3'

                python_path = detect_python()
                if python_path:
                    env['PYTHON'] = python_path
                    env['PYTHON_CMD'] = python_path  # 为了与quick_start.sh兼容

                # 执行命令 - 确保工作目录正确设置
                if auto_input:
                    process = subprocess.Popen(final_command, shell=True, stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               universal_newlines=True, bufsize=1, cwd=str(work_dir), env=env,
                                               encoding='utf-8', errors='replace')

                    stdout, _ = process.communicate(input=f"{auto_input}\n")
                    output_text.insert(tk.END, stdout)
                    output_text.see(tk.END)
                else:
                    process = subprocess.Popen(final_command, shell=True, stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT, universal_newlines=True,
                                               bufsize=1, cwd=str(work_dir), env=env,
                                               encoding='utf-8', errors='replace')

                    while True:
                        output = process.stdout.readline()
                        if output == '' and process.poll() is not None:
                            break
                        if output:
                            output_text.insert(tk.END, output)
                            output_text.see(tk.END)
                            cmd_window.update()

                self.status_label.config(text="🟢 系统就绪")
                status_label.config(text="✅ 执行完成", fg="#10B981")

            except Exception as e:
                output_text.insert(tk.END, f"\n❌ 执行失败: {str(e)}\n")
                self.status_label.config(text="❌ 执行失败")
                status_label.config(text="❌ 执行失败", fg="#EF4444")
            finally:
                # 恢复原目录
                try:
                    os.chdir(original_dir)
                except:
                    pass

        # 在后台线程中运行命令
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()

    def run(self):
        """运行应用程序"""
        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.mainloop()


def main():
    """主程序入口"""
    try:
        if not HAS_TKINTER:
            # 如果没有tkinter，使用原生macOS界面
            print("tkinter不可用，启动原生macOS界面...")
            from kronos_native_macos import main as native_main
            native_main()
            return

        # 检查tkinter可用性
        test_root = tk.Tk()
        test_root.withdraw()
        test_root.destroy()

        # 启动macOS现代化GUI
        app = KronosMacOSGUI()
        app.run()

    except ImportError as e:
        print(f"GUI界面需要tkinter支持: {e}")
        print("启动原生macOS界面...")
        # 回退到原生macOS版本
        try:
            from kronos_native_macos import main as native_main
            native_main()
        except Exception as e2:
            print(f"原生界面也启动失败: {e2}")
            # 显示简单的原生对话框
            subprocess.run(['osascript', '-e', f'''
                display dialog "Kronos GUI启动失败
                
错误信息: {str(e)}

正在尝试使用原生界面..." with title "Kronos" buttons {{"确定"}} default button 1 with icon note
            '''], check=False)
            # 最后尝试使用kronos_app.py
            try:
                from kronos_app import main as fallback_main
                fallback_main()
            except:
                subprocess.run(['osascript', '-e', '''
                    display dialog "所有界面都启动失败，请检查系统环境" with title "Kronos错误" buttons {"确定"} default button 1 with icon stop
                '''], check=False)

    except Exception as e:
        print(f"程序启动失败: {e}")
        # 使用原生macOS对话框
        subprocess.run(['osascript', '-e', f'''
            display dialog "程序启动失败: {str(e)}" with title "Kronos错误" buttons {{"确定"}} default button 1 with icon stop
        '''], check=False)


if __name__ == "__main__":
    main()
