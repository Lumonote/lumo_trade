# 贡献指南 (Contributing)

感谢你对 **Lumo Trade**（底层基于 Kronos 金融 K 线基础模型）的关注与贡献！以下指南帮助你高效、规范地参与项目。

## 📋 目录

- [开发环境](#开发环境)
- [提交规范 (Commit)](#提交规范-commit)
- [分支管理](#分支管理)
- [文档](#文档)
- [测试](#测试)
- [Pull Request](#pull-request)
- [行为准则](#行为准则)

---

## 🛠️ 开发环境

本项目为 Python 3.11+（分析引擎 / Robyn API）+ Rust（Tauri 桌面壳）。

```bash
# 克隆仓库后
pip install -r requirements.txt

# 爬虫依赖（可选）
pip install playwright && playwright install chromium

# 运行测试
python -m pytest tests/ -v

# 启动 Web UI
cd webui && python run.py
```

> 建议使用虚拟环境（`.venv`），Python 3.11+。

---

## ✍️ 提交规范 (Commit)

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<type>(<scope>): <subject>
```

**常用类型**：

| Type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `refactor` | 重构（不改功能） |
| `perf` | 性能优化 |
| `test` | 测试 |
| `chore` | 构建/工具链 |

**scope 示例**：`opportunity`（机会挖掘）、`desktop`（桌面端）、`webui`、`data`、`model`。

示例：

```
feat(opportunity): 新增期指门控评分因子
docs(desktop): 更新 Lumo Trade 桌面端完整指南
```

---

## 🌿 分支管理

- 主分支：`main`（稳定版）
- 版本分支：`V1.0` ~ `V2.1.3`（里程碑版本）
- 功能分支：从主分支切出，命名 `feat/<描述>` 或 `fix/<描述>`

---

## 📄 文档

- 项目文档统一存放于 `docs/`，根目录仅保留 `README.md`、`CLAUDE.md`（AI 助手指南）、`AGENTS.md`。
- 修改文档后，请同步更新 [docs/00_文档导航索引.md](docs/00_文档导航索引.md)。
- 新增 Markdown 文档时，**避免引用不存在的图片/链接**；引用真实存在的 `docs/images/` 资源。

---

## 🧪 测试

- 测试文件位于 `tests/`，命名 `test_*.py`。
- 运行：`python -m pytest tests/ -v`。
- 涉及评分规则改动时，请提供**回测证据**（规则改动必须数据驱动，见 `analysis/scoring_rules.py`）。

---

## 🔀 Pull Request

1. 基于最新 `main` 分支创建功能分支。
2. 保持提交清晰、单 commit 聚焦一个改动。
3. 在 PR 描述中说明：改动动机、影响范围、验证结果。
4. 遵循本仓库的代码风格（见 `CLAUDE.md`）。
5. 至少 1 名维护者审核后合并。

---

## 🤝 行为准则

请遵循 [Code of Conduct](CODE_OF_CONDUCT.md)。参与交流时保持尊重、建设性。

---

> ⚠️ **免责声明**：本项目所有分析、预测与报告仅供技术研究与学习参考，**不构成投资建议**。股市有风险，投资需谨慎。
