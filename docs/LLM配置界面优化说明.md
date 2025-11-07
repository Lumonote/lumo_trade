# LLM配置界面优化说明

## 问题描述

在macOS打包版本中，AI模型配置界面存在以下问题：

1. **帮助文字样式错乱**: 多行帮助文字使用单个Label控件，导致换行和布局异常
2. **缺少API地址配置**: 用户无法自定义API base_url，只能使用默认地址

## 解决方案

### 1. 帮助文字布局重构

**问题原因**:
- 原本使用单个Label控件显示多行文字
- 依赖`wraplength`和自动换行，在不同平台和窗口大小下表现不一致

**修复方案**:
```python
# 重新设计的帮助文字布局
help_text_lines = [
    f"获取 API Key：1. 访问{config.get('register_url', '').split('//')[-1].split('/')[0]}",
    "2. 注册并登录账号",
    "3. 创建API Key",
    "4. 将API Key复制到配置中"
]

register_frame = tk.Frame(content_frame, bg="#FEF3C7", relief="flat", bd=0)
register_frame.pack(fill=tk.X, pady=(0, 10))

register_content = tk.Frame(register_frame, bg="#FEF3C7")
register_content.pack(fill=tk.X, padx=12, pady=10)

# 图标
info_icon = tk.Label(register_content, text="ℹ️",
                     font=("Apple Color Emoji", 14),
                     bg="#FEF3C7")
info_icon.pack(side=tk.LEFT, anchor="n", padx=(0, 8))

# 文字内容 - 使用多个Label逐行显示
text_container = tk.Frame(register_content, bg="#FEF3C7")
text_container.pack(side=tk.LEFT, fill=tk.X, expand=True)

for line in help_text_lines:
    line_label = tk.Label(text_container, text=line,
                         font=("SF Pro Display", 11, "normal"),
                         fg="#92400E", bg="#FEF3C7",
                         anchor="w")
    line_label.pack(anchor="w", pady=1)
```

**优势**:
- ✅ 每行使用独立的Label控件
- ✅ 布局更稳定，不受窗口大小影响
- ✅ 更容易控制行间距和对齐
- ✅ 支持emoji图标和文字的混合布局

### 2. API地址配置功能

**新增功能**: 允许用户自定义API base_url，支持私有部署和替代服务

**实现代码**:
```python
# API地址配置（可选）
base_url_label = tk.Label(content_frame, text="API 地址（可选，留空使用默认）",
                         font=("SF Pro Display", 13, "bold"),
                         fg="#1F2937", bg="#F9FAFB")
base_url_label.pack(anchor="w", pady=(10, 5))

base_url_entry = tk.Entry(content_frame, font=("SF Pro Display", 12, "normal"),
                         bg="#FFFFFF", fg="#1F2937", relief="flat", bd=0,
                         highlightthickness=1, highlightbackground="#E5E7EB",
                         highlightcolor="#4F46E5")
base_url_entry.pack(fill=tk.X, ipady=8, ipadx=12, pady=(0, 5))
base_url_entry.insert(0, config.get('base_url', ''))
setattr(self, f"{llm_name}_base_url_entry", base_url_entry)

# 默认地址提示
default_url_hint = tk.Label(content_frame,
                           text=f"默认: {config.get('base_url', '')}",
                           font=("SF Pro Display", 10, "normal"),
                           fg="#9CA3AF", bg="#F9FAFB")
default_url_hint.pack(anchor="w", pady=(0, 10))
```

**功能特性**:
- ✅ 可选字段，留空则使用默认URL
- ✅ 显示默认URL提示，用户知道留空时的行为
- ✅ 保存时持久化到配置文件
- ✅ 支持通义千问和DeepSeek两个模型的独立配置

### 3. 测试连接功能简化

**问题**: 原实现依赖`LLMAnalyzer`类，而该类需要导入pandas

**解决方案**: 直接使用`requests`库测试API连接

```python
def test_connection():
    api_key = api_key_entry.get().strip()
    base_url = base_url_entry.get().strip() or config.get('base_url', '')

    if not api_key:
        messagebox.showwarning("警告", "请先填写 API Key", parent=self.dialog)
        return

    test_btn.config(text="测试中...", state=tk.DISABLED)

    def do_test():
        try:
            import requests
            if llm_name == 'qwen':
                # 通义千问测试
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                test_url = f"{base_url}/services/aigc/text-generation/generation"
                response = requests.post(test_url, headers=headers,
                                       json={'model': 'qwen3-max', 'input': {'prompt': 'test'}},
                                       timeout=10)
                success = response.status_code in [200, 400, 401]
                result = "连接成功" if response.status_code == 200 else f"状态码: {response.status_code}"
            else:
                # DeepSeek测试 - 使用OpenAI兼容接口
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                test_url = f"{base_url}/chat/completions"
                response = requests.post(test_url, headers=headers,
                                       json={'model': 'deepseek-chat', 'messages': [{'role': 'user', 'content': 'test'}]},
                                       timeout=10)
                success = response.status_code in [200, 400, 401]
                result = "连接成功" if response.status_code == 200 else f"状态码: {response.status_code}"

            # 更新UI并显示结果
            self.dialog.after(0, lambda: test_btn.config(text="测试连接", state=tk.NORMAL))
            if success and response.status_code == 200:
                messagebox.showinfo("测试成功", f"✅ {display_name} 连接测试成功！", parent=self.dialog)
            else:
                messagebox.showwarning("测试结果", f"⚠️ 连接到服务器，但可能需要检查API Key\n\n{result}", parent=self.dialog)

        except Exception as e:
            self.dialog.after(0, lambda: test_btn.config(text="测试连接", state=tk.NORMAL))
            messagebox.showerror("测试失败", f"❌ 连接测试失败\n\n{str(e)}", parent=self.dialog)

    threading.Thread(target=do_test, daemon=True).start()
```

**优势**:
- ✅ 不依赖pandas，适合.app打包环境
- ✅ 异步测试，不阻塞UI
- ✅ 区分连接成功和API Key错误
- ✅ 支持自定义base_url测试

### 4. 配置保存优化

**更新保存逻辑**:
```python
def save_config(self):
    """保存配置"""
    try:
        import json
        for llm_name in ['qwen', 'deepseek']:
            enabled_var = getattr(self, f"{llm_name}_enabled_var", None)
            api_key_entry = getattr(self, f"{llm_name}_api_key_entry", None)
            base_url_entry = getattr(self, f"{llm_name}_base_url_entry", None)

            if enabled_var and api_key_entry:
                self.llm_config[llm_name]['enabled'] = enabled_var.get()
                self.llm_config[llm_name]['api_key'] = api_key_entry.get().strip()

                # 保存base_url（如果有）
                if base_url_entry:
                    custom_url = base_url_entry.get().strip()
                    if custom_url:
                        self.llm_config[llm_name]['base_url'] = custom_url

        # 保存到文件
        config_path = project_root / 'config' / 'llm_config.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.llm_config, f, indent=2, ensure_ascii=False)

        messagebox.showinfo("成功", "✅ 配置保存成功！", parent=self.dialog)
        self.dialog.destroy()

    except Exception as e:
        messagebox.showerror("错误", f"保存配置失败：{e}", parent=self.dialog)
```

**特性**:
- ✅ 同时保存enabled、api_key和base_url三个字段
- ✅ 使用纯Python json模块，无pandas依赖
- ✅ 自动创建配置目录
- ✅ 错误处理和用户提示

## 配置文件格式

`config/llm_config.json`:
```json
{
  "qwen": {
    "enabled": false,
    "api_key": "sk-xxxxx",
    "model": "qwen3-max",
    "base_url": "https://dashscope.aliyuncs.com/api/v1",
    "register_url": "https://help.aliyun.com/zh/dashscope/developer-reference/activate-dashscope-and-create-an-api-key",
    "description": "阿里云通义千问大模型"
  },
  "deepseek": {
    "enabled": false,
    "api_key": "sk-xxxxx",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "register_url": "https://platform.deepseek.com/api_keys",
    "description": "DeepSeek 大模型"
  }
}
```

## 使用场景

### 场景1: 使用默认API地址

1. 点击"AI模型配置"按钮
2. 选择模型（通义千问或DeepSeek）
3. 填写API Key
4. **留空** API地址字段（将使用默认地址）
5. 点击"测试连接"验证
6. 点击"保存配置"

### 场景2: 使用自定义API地址

1. 点击"AI模型配置"按钮
2. 选择模型
3. 填写API Key
4. **填写自定义** API地址（如私有部署地址）
5. 点击"测试连接"验证
6. 点击"保存配置"

### 场景3: 使用API代理

某些情况下，用户可能需要通过代理访问API：

```
通义千问代理: https://your-proxy.com/dashscope/api/v1
DeepSeek代理: https://your-proxy.com/deepseek
```

## 技术亮点

1. **无pandas依赖**: 完全使用Python标准库（json）和轻量级库（requests），适合.app打包
2. **响应式布局**: 使用Frame和Pack布局管理器，适应不同窗口大小
3. **异步测试**: 网络请求在后台线程执行，不阻塞UI
4. **视觉反馈**: 测试按钮状态变化、成功/失败对话框
5. **配置持久化**: JSON格式存储，易读易维护

## 兼容性

- ✅ macOS 11+ (Big Sur及更高版本)
- ✅ Python 3.11+
- ✅ 打包环境（.app bundle）
- ✅ 开发环境

## 相关文件

- 核心实现: `tools/launchers/kronos_modern_gui.py:1219-1710`
- LLM服务: `analysis/llm_service.py`
- 配置文件: `config/llm_config.json`

## 版本历史

- **v1.1.0** (2025-01-31):
  - 重构帮助文字布局
  - 新增API地址配置功能
  - 简化测试连接实现
  - 移除pandas依赖

## 后续优化建议

1. **配置模板**: 提供常用API服务的配置模板（官方、代理、私有部署）
2. **批量测试**: 支持同时测试多个已配置的LLM服务
3. **历史记录**: 保存最近使用的API地址，方便快速切换
4. **智能提示**: 根据选择的模型自动填充默认API地址
