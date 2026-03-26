from __future__ import annotations

from typing import Dict, Iterable, Optional

import pandas as pd

from src.anomaly_v2.local_model import calc_absolute_humidity


COLUMN_ALIASES = {
    "time": ["time", "时间", "timestamp", "date", "datetime"],
    "in_temp": ["in_temp", "内部温度", "内温", "温度_内", "in_temperature"],
    "in_hum": ["in_hum", "内部湿度", "内湿", "湿度_内", "in_humidity"],
    "out_temp": ["out_temp", "外部温度", "外温", "温度_外", "out_temperature"],
    "out_hum": ["out_hum", "外部湿度", "外湿", "湿度_外", "out_humidity"],
}


def find_column(df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = str(alias).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map: Dict[str, str] = {}
    for std_name, aliases in COLUMN_ALIASES.items():
        found = find_column(df, aliases)
        if found is None:
            raise ValueError(f"缺少必要列：{std_name}，候选别名={aliases}")
        col_map[found] = std_name
    out = df.rename(columns=col_map).copy()
    return out[["time", "in_temp", "in_hum", "out_temp", "out_hum"]]


def preprocess_excel_df(df: pd.DataFrame) -> pd.DataFrame:
    out = standardize_columns(df)
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    out = out.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    for col in ["in_temp", "in_hum", "out_temp", "out_hum"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["in_temp", "in_hum", "out_temp", "out_hum"]).copy()
    out["AH_in"] = calc_absolute_humidity(out["in_temp"], out["in_hum"])
    out["AH_out"] = calc_absolute_humidity(out["out_temp"], out["out_hum"])
    out["dT"] = out["in_temp"] - out["out_temp"]
    out["dRH"] = out["in_hum"] - out["out_hum"]
    out["dAH"] = out["AH_in"] - out["AH_out"]
    return out
