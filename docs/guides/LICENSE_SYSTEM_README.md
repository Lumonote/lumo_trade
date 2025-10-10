# Kronos 独立授权系统

## 📋 系统概述

这是一个为Kronos金融预测系统设计的独立授权系统，支持一次性永久授权，设备硬件绑定，防止多设备使用和拷贝传播。

## 🏗️ 目录结构

```
Kronos/
├── license_admin/                 # 🔧 管理端（仅开发者使用）
│   ├── license_generator.py      # 授权码生成工具
│   ├── json_storage.py           # 数据存储工具
│   ├── config.json               # 管理端配置
│   ├── keys/                     # RSA密钥对
│   │   ├── private.pem           # 私钥（绝密）
│   │   └── public.pem            # 公钥
│   └── data/                     # 生成的授权码数据
│       ├── licenses.json         # 授权码数据库
│       └── activations.json      # 激活记录
│
├── finetune/license_system/       # 🔐 客户端授权系统
│   ├── device_fingerprint.py     # 设备指纹识别
│   ├── json_storage.py           # JSON存储工具
│   ├── license_validator.py      # 授权验证器
│   ├── activate.py               # 激活工具
│   ├── config.json               # 客户端配置
│   └── data/                     # 客户端数据
│       ├── licenses.json         # 授权码记录
│       ├── activations.json      # 激活记录
│       └── .license_cache        # 本地授权缓存
│
└── tools/launchers/kronos_with_license.py         # 📊 集成示例
```

## 🚀 使用流程

### 1. 管理端操作（开发者/授权方）

```bash
# 进入管理目录
cd license_admin/

# 生成授权码
python license_generator.py
# 选择"1. 生成授权码"，输入数量如：100

# 查看统计信息
python license_generator.py
# 选择"2. 查看统计信息"
```

### 2. 客户端操作（用户）

```bash
# 激活授权码
python finetune/license_system/activate.py
# 选择"2. 🔑 激活授权码"，输入获得的授权码

# 检查授权状态
python finetune/license_system/activate.py
# 选择"1. 🔍 检查授权状态"
```

### 3. 程序集成

```python
# 在Kronos主程序中添加授权检查
from finetune.license_system.license_validator import LicenseValidator


def check_license():
    validator = LicenseValidator('finetune/license_system/data')
    is_valid, message = validator.validate_license()
    if not is_valid:
        print(f"授权验证失败: {message}")
        exit(1)
    return True


# 在main函数开头调用
if __name__ == "__main__":
    check_license()
    # 原有程序逻辑...
```

## 🔒 安全特性

### 硬件绑定

- ✅ CPU ID + 主板序列号 + 硬盘序列号 + MAC地址
- ✅ 多重硬件特征组合，75%一致性验证
- ✅ 防止虚拟机和硬件克隆

### 数字签名

- ✅ RSA-2048数字签名防伪造
- ✅ 私钥与客户端隔离
- ✅ 公钥验证授权码真实性

### 一次激活

- ✅ 每个授权码仅能激活一台设备
- ✅ 激活后与设备永久绑定
- ✅ 无法在其他设备上使用

### 离线验证

- ✅ 激活后完全脱机运行
- ✅ 本地加密缓存验证
- ✅ 无需网络连接

## 📦 部署清单

### 开发端保留文件

```
license_admin/           # 整个目录保留
├── license_generator.py # 生成工具
├── keys/private.pem    # 私钥（绝密）
└── data/              # 授权码数据库
```

### 客户端分发文件

```
finetune/license_system/ # 客户端授权系统
├── device_fingerprint.py
├── license_validator.py  
├── activate.py
├── json_storage.py
├── config.json
└── keys/public.pem     # 仅公钥
```

### 删除清单（客户端不包含）

```
license_admin/          # 整个管理目录
├── license_generator.py
├── keys/private.pem    # 私钥绝不能泄露
└── data/licenses.json  # 完整授权码数据库
```

## ⚙️ 安装依赖

```bash
pip install cryptography psutil
```

## 🎯 授权码格式

```
KRONOS-A1B21-C3D4E-F5G6H-7I8J9
│      │     │     │     │
│      │     │     │     └── 校验码（MD5前5位）
│      │     │     └────────── 随机段3
│      │     └──────────────── 随机段2  
│      └────────────────────── 随机段1（末位标识类型）
└───────────────────────────── 产品标识
```

## 🛡️ 防护机制

1. **防拷贝**: 授权文件与设备硬件深度绑定
2. **防破解**: RSA数字签名 + 硬件指纹双重验证
3. **防篡改**: SHA256完整性校验
4. **防逆向**: 关键逻辑分散，代码混淆保护

## 📈 系统优势

- **极简部署**: 无数据库依赖，JSON文件存储
- **强安全性**: 多重防护机制，有效防盗版
- **用户友好**: 一次激活永久使用，操作简单
- **完全离线**: 激活后无需网络，保护隐私
- **跨平台**: 支持Windows/Linux/macOS

## 🔧 故障排除

### 激活失败

1. 检查授权码格式是否正确
2. 确认授权码未被使用
3. 验证设备网络连接
4. 检查系统时间是否正确

### 验证失败

1. 检查硬件是否发生重大变更
2. 确认授权缓存文件未损坏
3. 重新激活授权码

### 无法获取设备信息

1. Linux系统可能需要sudo权限
2. 确保psutil库正确安装
3. 检查系统安全软件是否阻止

---

**⚠️ 重要提醒**: `license_admin` 目录包含私钥和完整授权码数据库，绝不能分发给客户！