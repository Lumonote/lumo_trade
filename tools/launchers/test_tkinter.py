#!/usr/local/bin/python3.11
"""
tkinter完整测试脚本 - 验证所有GUI组件功能
"""

import sys

print(f"使用Python: {sys.executable}")
print(f"Python版本: {sys.version}")

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, font as tkFont, scrolledtext

    print("✅ 成功导入所有tkinter模块")

    # 测试基础窗口创建
    root = tk.Tk()
    root.title("tkinter 功能测试")
    root.geometry("400x300")

    # 测试基础控件
    label = tk.Label(root, text="🎉 tkinter 完全正常工作！",
                     font=("SF Pro Display", 18, "bold"))
    label.pack(pady=20)

    button = tk.Button(root, text="测试按钮",
                       command=lambda: messagebox.showinfo("成功", "所有GUI功能正常！"))
    button.pack(pady=10)

    text = scrolledtext.ScrolledText(root, height=5, width=40)
    text.pack(pady=10)
    text.insert('1.0', "这是一个滚动文本框测试\n所有GUI组件都工作正常！")

    # 自动关闭窗口
    root.after(3000, root.destroy)

    print("✅ tkinter测试窗口启动成功")
    root.mainloop()
    print("✅ tkinter测试完成 - 所有功能正常！")

except ImportError as e:
    print(f"❌ tkinter导入失败: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ tkinter测试失败: {e}")
    sys.exit(1)
