# Kronos Skills

Claude Code技能模块目录，包含专业的金融分析和投资决策工具。

## Available Skills

### Investment Opportunity Discovery

**完整功能**: 7维度股票分析 + 6阶段筛选 + LLM智能分析

**目录**: `investment-opportunity-discovery/`

**快速开始**:
```bash
cd investment-opportunity-discovery
python scripts/discover_opportunities.py --limit 50 --test-codes 600977,000001 --no-llm
```

**完整文档**:
- `SKILL.md` - 技能完整参考 (4,000+ 词)
- `README.md` - 使用指南 (3,000+ 词)
- `GETTING_STARTED.md` - 5分钟快速入门
- `references/` - 详细技术文档

## Usage

所有技能都遵循Claude Code标准格式：
- **SKILL.md** - 技能文档和元数据
- **scripts/** - 可执行脚本
- **references/** - 技术参考文档
- **assets/** - 配置文件和模板
- **examples/** - 使用示例

## Documentation

- `INVESTMENT_SKILL_SUMMARY.md` - 投资机会挖掘Skill完整总结
- 各技能目录内的详细文档
