# Kronos 项目目录结构

## 根目录文件

```
Kronos/
├── README.md                 # 项目说明文档
├── LICENSE                   # 开源许可证
├── CLAUDE.md                # Claude开发指南
├── requirements.txt          # Python依赖包
├── quick_start.sh           # 快速启动脚本(Linux/macOS)
├── quick_start.bat          # 快速启动脚本(Windows)
└── kronos_app.py           # 主应用程序(跨平台GUI)
```

## 目录结构

```
Kronos/
├── analysis/               # 技术分析模块
├── assets/                 # 资源文件(图标、图片等)
├── config/                 # 配置文件
├── data/                   # 数据存储目录
├── docs/                   # 文档目录
│   ├── guides/            # 使用指南
│   ├── implementation/    # 实现文档
│   └── version_info.txt   # 版本信息
├── examples/              # 示例代码
├── finetune/              # 微调和授权系统
│   └── license_system/    # 授权管理
├── license_admin/         # 授权管理后台
├── logs/                  # 日志文件
├── model/                 # 模型定义
├── models/                # 预训练模型
├── packaging/             # 打包相关
│   ├── builds/           # 构建输出
│   ├── scripts/          # 打包脚本
│   └── specs/            # PyInstaller配置
├── results/               # 预测结果
├── scripts/               # 工具脚本
├── tools/                 # 工具集合
│   └── launchers/        # 启动器程序
└── webui/                 # Web界面
```

## 核心功能模块

### 主程序

- **kronos_app.py**: 跨平台GUI主程序，支持Windows/macOS/Linux

### 启动方式

- **quick_start.sh**: 命令行交互式启动(推荐)
- **kronos_app.py**: GUI界面启动

### 打包部署

- **packaging/scripts/build.py**: Python跨平台打包工具
- **packaging/scripts/build.sh**: Shell一键打包脚本

### 工具程序

- **tools/launchers/**: 各种启动器和辅助程序
- **tools/deploy_license_system.py**: 授权系统部署工具

## 使用说明

### 快速开始

```bash
# 1. 交互式启动(推荐)
./quick_start.sh

# 2. GUI界面启动
python kronos_app.py
```

### 打包发布

```bash
# 方式1: 使用Shell脚本(简单)
bash packaging/scripts/build.sh

# 方式2: 使用Python工具(高级)
python packaging/scripts/build.py
```

## 文件分类说明

| 类型   | 位置         | 说明          |
|------|------------|-------------|
| 核心程序 | 根目录        | 用户直接使用的主要文件 |
| 文档资料 | docs/      | 各类说明文档和指南   |
| 工具程序 | tools/     | 开发和管理工具     |
| 打包文件 | packaging/ | 构建和发布相关     |
| 功能模块 | 各子目录       | 按功能划分的代码模块  |