"""机构调研 provider。

akshare 的 stock_jgdy_detail_em 按交易日返回全市场，无单股直拉路径 —— 历史上本
provider 只读库、靠 E2 市场级回填脚本填充。新增 Tushare ``stk_surv`` 单股直拉作为
回退：库里无近 90 日记录时按 ts_code 拉取并落库（stk_surv 多为业绩说明会/集体接待，
机构粒度不如 jgdy，但为真实调研事件，可消除「数据不足」）。
"""
from __future__ import annotations

import datetime as _dt
import logging

from analysis.institutional.base import BaseProvider, ProviderResult
from data_store import survey_repo, tushare_client

logger = logging.getLogger(__name__)

_NO_DATA_REASON = (
    "机构调研：近 90 日无记录（Tushare stk_surv 与回填脚本均无该股调研事件）"
)


class SurveyProvider(BaseProvider):
    def __init__(self, akshare_adapter):
        self._adapter = akshare_adapter

    def _fetch_tushare(self, ts_code: str) -> None:
        """Tushare stk_surv 单股直拉 → jgdy_detail 落库。"""
        pro = tushare_client.get_pro()
        if pro is None:
            return
        try:
            df = pro.stk_surv(ts_code=tushare_client.to_ts_code(ts_code))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tushare stk_surv failed for %s: %s", ts_code, exc)
            return
        if df is None or df.empty:
            return
        rows = []
        for r in df.itertuples(index=False):
            inst = (getattr(r, "rece_org", "") or getattr(r, "org_type", "") or "机构调研").strip()
            if inst in ("--", ""):
                inst = "机构调研"
            rows.append({
                "ts_code": ts_code,
                "survey_date": tushare_client.yyyymmdd_to_iso(getattr(r, "surv_date", "")),
                "inst_name": inst,
                "reception": (getattr(r, "rece_mode", "") or "").replace("--", "").strip() or None,
                "topic": (getattr(r, "rece_place", "") or "").replace("--", "").strip() or None,
            })
        if rows:
            survey_repo.upsert_rows(rows)
            logger.info("tushare stk_surv: saved %d rows for %s", len(rows), ts_code)

    def get(self, ts_code: str, days: int = 90, **kwargs) -> ProviderResult:
        since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
        df = survey_repo.get_by_code(ts_code, since=since)
        if df.empty:
            self._fetch_tushare(ts_code)
            df = survey_repo.get_by_code(ts_code, since=since)
        if df.empty:
            return ProviderResult.unavailable(reason=_NO_DATA_REASON)
        return ProviderResult(
            data={"recent_90d": df.to_dict("records")},
            data_status="stale",
            last_updated=str(df["survey_date"].max()),
        )
