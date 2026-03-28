# -*- coding: utf-8 -*-

import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, Optional

import pandas as pd

from condition_classifier import classify_24h_dataframe


# =========================================================
# 路径
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HIGH_HUM_DIR = os.path.join(BASE_DIR, "HighHumCond")
MOIST_DIR = os.path.join(BASE_DIR, "InternalMoistureAccumulationModel")
SEAL_TC_DIR = os.path.join(BASE_DIR, "SealSence_TC")
MODEL_DIR = os.path.join(SEAL_TC_DIR, "model")

for p in [HIGH_HUM_DIR, MOIST_DIR, SEAL_TC_DIR]:
    if p not in sys.path:
        sys.path.append(p)


# =========================================================
# 参数
# =========================================================
@dataclass
class RouterConfig:
    enable_debug: bool = True

    smooth_win: int = 5
    downsample_factor: int = 10
    sub_size: int = 36
    step: int = 12

    time_col: str = "time"
    hum_col: str = "in_hum"
    hum_threshold: float = 82.0
    min_duration_hours: float = 2.0


# =========================================================
# 标签校验（仅允许新标签）
# =========================================================
VALID_LABELS = {
    "SEALED",
    "UNSEALED",
    "MOISTURE_INGRESS",
    "MOISTURE_ACCUMULATION",
    "UNKNOWN",
}


def validate_label(label: Any) -> str:
    if label is None:
        return "UNKNOWN"

    s = str(label).strip().upper()

    if s in VALID_LABELS:
        return s

    # 不允许旧标签，直接报错更安全
    raise ValueError(f"非法标签（未统一）：{label}")


# =========================================================
# 模型调用
# =========================================================
def run_low_info(df, feat, cfg):
    return {
        "model": "NONE",
        "label": "UNKNOWN",
        "detail": None,
    }


def run_high_hum(df, feat, cfg):
    from high_hum_seal_model import predict_seal_state

    raw_label = predict_seal_state(
        df,
        smooth_win=cfg.smooth_win,
        downsample_factor=cfg.downsample_factor,
        sub_size=cfg.sub_size,
        step=cfg.step,
        return_features=False
    )

    label = validate_label(raw_label)

    return {
        "model": "HighHumCond",
        "label": label,
        "detail": None,
    }


def run_internal_moist(df, feat, cfg):
    from moisture_detector import detect_window_state

    result = detect_window_state(
        window_df=df,
        time_col=cfg.time_col,
        hum_col=cfg.hum_col,
        hum_threshold=cfg.hum_threshold,
        min_duration_hours=cfg.min_duration_hours
    )

    label = validate_label(result["state"])

    return {
        "model": "InternalMoisture",
        "label": label,
        "detail": result,
    }


def run_seal_tc(df, feat, cfg):
    from seal_infer_industrial import SealInferIndustrial

    infer = SealInferIndustrial(model_dir=MODEL_DIR)
    result = infer.predict_one_window_df(df)

    label = validate_label(result["label"])

    return {
        "model": "SealSence_TC",
        "label": label,
        "detail": result,
    }


# =========================================================
# 路由
# =========================================================
def dispatch(condition, df, feat, cfg):

    if condition == "LOW_INFO":
        return run_low_info(df, feat, cfg)

    if condition == "EXT_HIGH_HUM":
        return run_high_hum(df, feat, cfg)

    if condition in ("INTERNAL_MOIST", "MOIST_TRANSITION"):
        return run_internal_moist(df, feat, cfg)

    return run_seal_tc(df, feat, cfg)


# =========================================================
# 主函数
# =========================================================
def run_salad_model(df_24h: pd.DataFrame,
                   cfg: Optional[RouterConfig] = None) -> Dict[str, Any]:

    if cfg is None:
        cfg = RouterConfig()

    condition, feat, df = classify_24h_dataframe(df_24h)

    if cfg.enable_debug:
        print(f"[INFO] condition = {condition}")

    model_out = dispatch(condition, df, feat, cfg)

    return {
        "condition": condition,
        "model": model_out["model"],
        "label": model_out["label"],
        "feature": feat,
        "detail": model_out["detail"],
    }