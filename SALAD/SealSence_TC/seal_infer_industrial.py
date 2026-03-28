# -*- coding: utf-8 -*-
"""
工业推理模块：
加载模型并对单个24小时窗口DataFrame进行异常判别
"""

import os
import torch
import pandas as pd

from seal_model_core_v24a import (
    load_model_bundle,
    resample_df,
    build_features,
    df_to_scaled_array,
    compute_residual_series,
    attach_accumulation_metrics,
    summarize_24h_window,
)


class SealInferIndustrial:
    """
    单窗口异常检测模型
    输入：一个24小时窗口的 DataFrame
    输出：UNSEALED / SEALED / UNKNOWN
    """

    def __init__(self, model_dir: str):
        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"模型目录不存在: {model_dir}")

        self.model_dir = model_dir
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model = None
        self.scaler = None
        self.baseline = None
        self.feature_names = None
        self.config = None

        self._load_model()

    def _load_model(self):
        model, scaler, baseline, feature_names, config = load_model_bundle(self.model_dir)
        self.model = model
        self.scaler = scaler
        self.baseline = baseline
        self.feature_names = feature_names
        self.config = config

    def predict_one_window_df(self, df: pd.DataFrame) -> dict:
        """
        输入：
            一个24小时窗口DataFrame
            必须至少包含：
            time, in_temp, in_hum, out_temp, out_hum
            或者 time 已为索引，且包含其余四列
        输出：
            {
                "ok": True/False,
                "status": "abnormal"/"warning"/"normal"/"unknown",
                "label": "UNSEALED"/"SEALED"/"UNKNOWN",
                "summary": {...},
                "message": "..."
            }
        """
        try:
            if df is None or len(df) == 0:
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": "输入DataFrame为空"
                }

            x = df.copy()
            time_col = self.config["time_col"]

            # 统一时间索引
            if time_col in x.columns:
                x[time_col] = pd.to_datetime(x[time_col], errors="coerce")
                x = x.dropna(subset=[time_col]).sort_values(time_col).set_index(time_col)
            elif not isinstance(x.index, pd.DatetimeIndex):
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": "缺少时间列，且索引不是DatetimeIndex"
                }

            required_cols = ["in_temp", "in_hum", "out_temp", "out_hum"]
            missing = [c for c in required_cols if c not in x.columns]
            if missing:
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": f"缺少必要字段: {missing}"
                }

            for c in required_cols:
                x[c] = pd.to_numeric(x[c], errors="coerce")

            x = x.dropna(subset=required_cols)
            x = x[~x.index.duplicated(keep="first")].sort_index()

            if len(x) == 0:
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": "有效数据为空"
                }

            rule = self.config["rule"]
            W = int(self.config["W"])
            H = int(self.config["H"])
            inner_stride = int(self.config["inner_stride"])
            smooth_ddah_window = int(self.config["smooth_ddah_window"])
            rule_minutes = int(rule.replace("min", ""))

            # 预处理
            x = resample_df(x, rule=rule)
            x = build_features(x, rule_minutes=rule_minutes, smooth_ddah_window=smooth_ddah_window)

            if len(x) < (W + H + 1):
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": f"有效点数不足，当前 {len(x)}，至少需要 {W + H + 1}"
                }

            seq = df_to_scaled_array(x, self.feature_names, self.scaler)
            if len(seq) < (W + H + 1):
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": f"缩放后有效序列不足，当前 {len(seq)}，至少需要 {W + H + 1}"
                }

            # 残差评分
            score_df = compute_residual_series(
                model=self.model,
                seq_scaled=seq,
                W=W,
                H=H,
                stride=inner_stride,
                feature_names=self.feature_names,
                device=self.device,
            )

            if score_df is None or len(score_df) == 0:
                return {
                    "ok": False,
                    "status": "unknown",
                    "label": "UNKNOWN",
                    "summary": {},
                    "message": "残差评分为空"
                }

            # EWMA / CUSUM
            score_df = attach_accumulation_metrics(
                score_df,
                resid_mean=self.baseline["resid_mean"],
                resid_std=self.baseline["resid_std"],
                alpha=self.baseline["alpha"],
                cusum_k=self.baseline["cusum_k"],
            )

            # 恢复时间索引
            times = x.index.to_list()
            score_df["time"] = score_df["pos"].apply(
                lambda p: times[int(p)] if int(p) < len(times) else times[-1]
            )
            score_df = score_df.drop(columns=["pos"]).set_index("time")

            # 窗口级判定
            summary = summarize_24h_window(score_df, self.baseline)
            status = str(summary.get("status", "unknown")).lower()

            if status == "abnormal":
                label = "UNSEALED"
            elif status in ["warning", "normal"]:
                label = "SEALED"
            else:
                label = "UNKNOWN"

            return {
                "ok": True,
                "status": status,
                "label": label,
                "summary": summary,
                "message": "检测完成"
            }

        except Exception as e:
            return {
                "ok": False,
                "status": "unknown",
                "label": "UNKNOWN",
                "summary": {},
                "message": f"检测失败: {e}"
            }