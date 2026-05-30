# -*- coding: utf-8 -*-
"""PyInstaller hook：收集 akshare 随包数据文件。

问题：打包后 akshare 的 .py 模块会被收进 ``_internal/akshare/``，但其随包数据文件
（交易日历 ``akshare/file_fold/calendar.json`` 等）默认不被收集。运行期 akshare 读
``calendar.json`` 抛 ``FileNotFoundError: ... /akshare/file_fold/calendar.json``，
导致依赖 akshare 的机构/资金/龙虎榜等功能集体报「数据源暂不可用」。

修复：``collect_data_files`` 按包内相对路径收集这些数据文件，还原成
``_internal/akshare/file_fold/calendar.json``。本 hook 位于 ``packaging/hooks``，
凡 hookspath 含该目录的 spec（kronos_webui_backend.spec / kronos_windows.spec）
导入 akshare 时自动生效。
"""
from PyInstaller.utils.hooks import collect_data_files

# 收集 akshare 全部随包数据（calendar.json 及其余 file_fold 数据）。
datas = collect_data_files("akshare")
