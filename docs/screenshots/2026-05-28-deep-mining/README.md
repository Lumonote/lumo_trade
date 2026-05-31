# M1 (Foundation) 截图归档

> 本目录存放个股深度挖掘 M1 里程碑的手动冒烟截图。
> 截图需在 `python webui/run.py` 启动后，打开个股弹窗逐 Tab 采集。

## 待采集清单

- `m1-tab-nav-*.png` — 15 Tab 重排后导航（原 11 + 新 4）
- `m1-main-force-deep-{unavailable,stale}.png` — 主力深度 Tab 两态
- `m1-quant-matrix.png` — 量化矩阵 Tab（M4 占位）
- `m1-chip-radar.png` — 筹码·控盘雷达 Tab（M2/M3 占位）
- `m1-holdings-{unavailable,stale}.png` — 机构持仓 Tab 两态
- `m1-overview-radar.png` — 综合总览 7 维雷达（原 5 维 + 控盘度 + 量化活跃度）

## 实施说明

M1 阶段采用「新增 4 个独立 Tab」方案（非计划原定的 11→12 改名），
以保留既有雷达 5 维度渲染系统不受破坏：

- 既有雷达维度 Tab（主力阶段 / 量价博弈 / 筹码结构）保持不变
- 新增 4 个 Tab：主力深度 / 量化矩阵 / 筹码·控盘雷达 / 机构持仓
- 综合总览雷达由 5 维扩展到 7 维（追加 控盘度 + 量化活跃度，M1 默认 0）

骨架阶段所有新 Tab 均走 `data_status="unavailable"` 降级 UI；
向 SQLite 写入历史数据后，主力深度 / 机构持仓 Tab 可展示 `stale` 历史快照。
