"""财务三大表取数 provider:免费(akshare 东方财富)优先,付费(Tushare)兜底。

只抽取关键行项目(curated EM/Tushare 字段→中文标签),避免存全部上百列。
所有联网依赖(akshare/tushare)惰性导入,torch-less / 无网测试环境不受影响。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 东方财富(akshare EM)字段 → 中文标签
_EM_FIELDS = {
    "balance": {
        "MONETARYFUNDS": "货币资金", "ACCOUNTS_RECE": "应收账款", "INVENTORY": "存货",
        "TOTAL_CURRENT_ASSETS": "流动资产合计", "FIXED_ASSET": "固定资产",
        "INTANGIBLE_ASSET": "无形资产", "TOTAL_NONCURRENT_ASSETS": "非流动资产合计",
        "TOTAL_ASSETS": "资产总计", "TOTAL_CURRENT_LIAB": "流动负债合计",
        "TOTAL_NONCURRENT_LIAB": "非流动负债合计", "TOTAL_LIABILITIES": "负债合计",
        "TOTAL_PARENT_EQUITY": "归属母公司股东权益", "MINORITY_EQUITY": "少数股东权益",
        "TOTAL_EQUITY": "股东权益合计",
    },
    "income": {
        "TOTAL_OPERATE_INCOME": "营业总收入", "OPERATE_INCOME": "营业收入",
        "TOTAL_OPERATE_COST": "营业总成本", "OPERATE_COST": "营业成本",
        "SALE_EXPENSE": "销售费用", "MANAGE_EXPENSE": "管理费用",
        "RESEARCH_EXPENSE": "研发费用", "FINANCE_EXPENSE": "财务费用",
        "OPERATE_PROFIT": "营业利润", "TOTAL_PROFIT": "利润总额",
        "INCOME_TAX": "所得税费用", "NETPROFIT": "净利润",
        "PARENT_NETPROFIT": "归母净利润", "DEDUCT_PARENT_NETPROFIT": "扣非归母净利润",
    },
    "cashflow": {
        "TOTAL_OPERATE_INFLOW": "经营活动现金流入", "TOTAL_OPERATE_OUTFLOW": "经营活动现金流出",
        "NETCASH_OPERATE": "经营活动现金流量净额", "TOTAL_INVEST_INFLOW": "投资活动现金流入",
        "TOTAL_INVEST_OUTFLOW": "投资活动现金流出", "NETCASH_INVEST": "投资活动现金流量净额",
        "TOTAL_FINANCE_INFLOW": "筹资活动现金流入", "TOTAL_FINANCE_OUTFLOW": "筹资活动现金流出",
        "NETCASH_FINANCE": "筹资活动现金流量净额", "END_CASH_EQUIVALENTS": "期末现金及现金等价物余额",
    },
}

# Tushare 字段 → 中文标签(兜底)
_TS_FIELDS = {
    "balance": {
        "money_cap": "货币资金", "accounts_receiv": "应收账款", "inventories": "存货",
        "total_cur_assets": "流动资产合计", "fix_assets": "固定资产", "intan_assets": "无形资产",
        "total_nca": "非流动资产合计", "total_assets": "资产总计", "total_cur_liab": "流动负债合计",
        "total_ncl": "非流动负债合计", "total_liab": "负债合计",
        "total_hldr_eqy_exc_min_int": "归属母公司股东权益", "minority_int": "少数股东权益",
        "total_hldr_eqy_inc_min_int": "股东权益合计",
    },
    "income": {
        "total_revenue": "营业总收入", "revenue": "营业收入", "total_cogs": "营业总成本",
        "oper_cost": "营业成本", "sell_exp": "销售费用", "admin_exp": "管理费用",
        "rd_exp": "研发费用", "fin_exp": "财务费用", "operate_profit": "营业利润",
        "total_profit": "利润总额", "income_tax": "所得税费用", "n_income": "净利润",
        "n_income_attr_p": "归母净利润",
    },
    "cashflow": {
        "c_inf_fr_operate_a": "经营活动现金流入", "st_cash_out_act": "经营活动现金流出",
        "n_cashflow_act": "经营活动现金流量净额", "stot_inflows_inv_act": "投资活动现金流入",
        "stot_out_inv_act": "投资活动现金流出", "n_cashflow_inv_act": "投资活动现金流量净额",
        "stot_cash_in_fnc_act": "筹资活动现金流入", "stot_cashout_fnc_act": "筹资活动现金流出",
        "n_cash_flows_fnc_act": "筹资活动现金流量净额", "c_cash_equ_end_period": "期末现金及现金等价物余额",
    },
}


def _digits(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def _em_symbol(code: str) -> str:
    d = _digits(code)
    if d.startswith("6"):
        return f"SH{d}"
    if d.startswith(("0", "3")):
        return f"SZ{d}"
    if d.startswith(("4", "8")):
        return f"BJ{d}"
    return f"SH{d}"


def _to_float(v):
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def _normalize_em(df, field_map, limit=8) -> List[Dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    if "REPORT_DATE" in df.columns:
        df = df.sort_values("REPORT_DATE", ascending=False)
    out = []
    for _, row in df.head(limit).iterrows():
        rd = str(row.get("REPORT_DATE") or "")[:10]
        if not rd:
            continue
        items = {}
        for key, label in field_map.items():
            if key in row:
                val = _to_float(row.get(key))
                if val is not None:
                    items[label] = val
        if not items:
            continue
        out.append({
            "report_date": rd,
            "period": row.get("REPORT_DATE_NAME") or "",
            "currency": row.get("CURRENCY") or "",
            "items": items,
        })
    return out


def _fetch_em(code: str) -> Dict[str, List[Dict[str, Any]]]:
    import akshare as ak  # 惰性导入
    symbol = _em_symbol(code)
    fns = {
        "balance": ak.stock_balance_sheet_by_report_em,
        "income": ak.stock_profit_sheet_by_report_em,
        "cashflow": ak.stock_cash_flow_sheet_by_report_em,
    }
    result = {}
    for stype, fn in fns.items():
        try:
            df = fn(symbol=symbol)
            result[stype] = _normalize_em(df, _EM_FIELDS[stype])
        except Exception as exc:  # 单表失败不影响其他表
            logger.info("akshare EM %s %s 失败: %s", stype, symbol, exc)
            result[stype] = []
    return result


def _normalize_ts(df, field_map, limit=8) -> List[Dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    if "end_date" in df.columns:
        df = df.sort_values("end_date", ascending=False).drop_duplicates("end_date")
    out = []
    for _, row in df.head(limit).iterrows():
        rd = str(row.get("end_date") or "")[:10]
        if not rd:
            continue
        items = {}
        for key, label in field_map.items():
            if key in row:
                val = _to_float(row.get(key))
                if val is not None:
                    items[label] = val
        if items:
            out.append({"report_date": rd, "period": "", "currency": "CNY", "items": items})
    return out


def _fetch_tushare(code: str) -> Dict[str, List[Dict[str, Any]]]:
    from data_store import tushare_client  # 惰性导入
    pro = tushare_client.get_pro()
    if pro is None:
        return {"balance": [], "income": [], "cashflow": []}
    ts_code = tushare_client.to_ts_code(code)
    calls = {"balance": pro.balancesheet, "income": pro.income, "cashflow": pro.cashflow}
    result = {}
    for stype, fn in calls.items():
        try:
            df = fn(ts_code=ts_code)
            result[stype] = _normalize_ts(df, _TS_FIELDS[stype])
        except Exception as exc:
            logger.info("tushare %s %s 失败: %s", stype, ts_code, exc)
            result[stype] = []
    return result


def fetch_three_statements(code: str) -> Dict[str, Any]:
    """免费(akshare EM)优先,失败/全空再付费(Tushare)兜底。

    返回 {balance:[...], income:[...], cashflow:[...], source, partial}。
    """
    code = str(code or "").strip()
    if not code:
        return {"balance": [], "income": [], "cashflow": [], "source": None, "partial": True}
    source = "akshare"
    try:
        data = _fetch_em(code)
    except Exception as exc:
        logger.info("akshare EM 整体失败 %s: %s", code, exc)
        data = {"balance": [], "income": [], "cashflow": []}
    if not any(data.get(s) for s in ("balance", "income", "cashflow")):
        # 免费源全空 → 付费兜底
        try:
            ts_data = _fetch_tushare(code)
            if any(ts_data.get(s) for s in ("balance", "income", "cashflow")):
                data = ts_data
                source = "tushare"
        except Exception as exc:
            logger.info("tushare 兜底失败 %s: %s", code, exc)
    partial = not all(data.get(s) for s in ("balance", "income", "cashflow"))
    return {
        "balance": data.get("balance", []),
        "income": data.get("income", []),
        "cashflow": data.get("cashflow", []),
        "source": source,
        "partial": partial,
    }
