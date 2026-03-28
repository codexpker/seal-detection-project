# -*- coding: utf-8 -*-
"""
方案A：24小时作为判别单位，但训练仍基于完整文件的短上下文预测

核心思想：
1. 训练阶段：按“文件”读取密封正常数据，先重采样与构特征；
   使用短上下文窗口（如 W=48, H=6）在完整文件序列上训练 GRU。
2. 评分阶段：对每个测试文件切成 24h 窗口（步长 1h），
   在每个 24h 窗口内计算 score_dAH / EWMA / CUSUM，并给出窗口级判定。
3. 不做整文件跨窗口累积，只做 24h 窗口内判定。
"""
from __future__ import annotations

import glob
import json
import os
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

REQUIRED_COLS = ["in_temp", "in_hum", "out_temp", "out_hum"]


def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


@dataclass
class RobustScaler:
    median_: Optional[np.ndarray] = None
    iqr_: Optional[np.ndarray] = None
    eps: float = 1e-8

    def fit(self, X: np.ndarray) -> None:
        self.median_ = np.nanmedian(X, axis=0)
        q75 = np.nanpercentile(X, 75, axis=0)
        q25 = np.nanpercentile(X, 25, axis=0)
        self.iqr_ = np.maximum(q75 - q25, self.eps)

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.median_ is None or self.iqr_ is None:
            raise RuntimeError("Scaler not fitted.")
        return (X - self.median_) / self.iqr_

    def to_dict(self) -> Dict:
        return {"median": self.median_.tolist(), "iqr": self.iqr_.tolist(), "eps": self.eps}

    @staticmethod
    def from_dict(d: Dict) -> "RobustScaler":
        sc = RobustScaler(eps=float(d.get("eps", 1e-8)))
        sc.median_ = np.array(d["median"], dtype=np.float32)
        sc.iqr_ = np.array(d["iqr"], dtype=np.float32)
        return sc


def save_json(obj: Dict | List, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def calc_absolute_humidity(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    temp_c = pd.to_numeric(temp_c, errors="coerce")
    rh = pd.to_numeric(rh, errors="coerce").clip(lower=0, upper=100)
    e = (rh / 100.0) * 6.112 * np.exp((17.67 * temp_c) / (temp_c + 243.5))
    ah = 216.7 * e / (temp_c + 273.15)
    return ah


def rolling_slope(s: pd.Series, window: int, min_periods: Optional[int] = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(4, window // 2)

    def _slope(arr: np.ndarray) -> float:
        arr = np.asarray(arr, dtype=np.float64)
        if len(arr) < 2:
            return 0.0
        x = np.arange(len(arr), dtype=np.float64)
        xm = x.mean()
        ym = arr.mean()
        den = np.sum((x - xm) ** 2)
        if den < 1e-12:
            return 0.0
        num = np.sum((x - xm) * (arr - ym))
        return float(num / den)

    return s.rolling(window=window, min_periods=min_periods).apply(_slope, raw=True)


def rolling_turning_points(s: pd.Series, window: int, min_periods: Optional[int] = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(4, window // 2)

    def _count_turns(arr: np.ndarray) -> float:
        arr = np.asarray(arr, dtype=np.float64)
        if len(arr) < 3:
            return 0.0
        d = np.diff(arr)
        sign = np.sign(d)
        for i in range(1, len(sign)):
            if sign[i] == 0:
                sign[i] = sign[i - 1]
        for i in range(len(sign) - 2, -1, -1):
            if sign[i] == 0:
                sign[i] = sign[i + 1]
        return float(np.sum(sign[1:] * sign[:-1] < 0))

    return s.rolling(window=window, min_periods=min_periods).apply(_count_turns, raw=True)


def read_excel_timeseries(path: str, time_col: str = "time") -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl")
    if time_col not in df.columns:
        raise ValueError(f"[{os.path.basename(path)}] 缺少时间列 {time_col}")
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"[{os.path.basename(path)}] 缺少字段 {missing}")
    df = df[[time_col] + REQUIRED_COLS].copy()
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col]).sort_values(time_col).set_index(time_col)
    for c in REQUIRED_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=REQUIRED_COLS)


def read_csv_timeseries(path: str, time_col: str = "time", encoding: Optional[str] = None) -> pd.DataFrame:
    encodings = [encoding] if encoding else ["utf-8", "utf-8-sig", "gbk", "gb18030"]
    last_err = None
    for enc in encodings:
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except Exception as e:
            last_err = e
    else:
        raise ValueError(f"[{os.path.basename(path)}] CSV读取失败: {last_err}")
    if time_col not in df.columns:
        raise ValueError(f"[{os.path.basename(path)}] 缺少时间列 {time_col}")
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"[{os.path.basename(path)}] 缺少字段 {missing}")
    df = df[[time_col] + REQUIRED_COLS].copy()
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col]).sort_values(time_col).set_index(time_col)
    for c in REQUIRED_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=REQUIRED_COLS)


def read_timeseries(path: str, time_col: str = "time", csv_encoding: Optional[str] = None) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        return read_excel_timeseries(path, time_col=time_col)
    if ext == ".csv":
        return read_csv_timeseries(path, time_col=time_col, encoding=csv_encoding)
    raise ValueError(f"不支持的文件类型: {ext}")


def resample_df(df: pd.DataFrame, rule: str = "5min") -> pd.DataFrame:
    out = df.resample(rule).mean()
    out = out.interpolate(limit=3, limit_direction="both")
    return out.dropna()


FEATURE_NAMES = [
    "AH_in", "AH_out", "dAH", "ddAH",
    "AH_out_slope_30min", "AH_out_slope_60min",
    "delta_AH_out_30min", "delta_AH_out_60min", "volatility_AH_out_2h",
    "dT", "out_temp_slope_30min", "out_temp_slope_60min",
    "delta_out_temp_30min", "delta_out_temp_60min",
    "dT_slope_30min", "dT_slope_60min", "delta_dT_30min",
    "volatility_out_temp_2h", "volatility_dT_2h",
    "dAH_slope_30min", "dAH_slope_60min",
    "AH_in_slope_30min", "AH_out_level_slope_30min",
    "delta_dAH_30min", "delta_dAH_60min",
    "gap_close_speed_60min", "gap_close_speed_2h",
    "tau_proxy_2h",
    "local_amp_60min", "volatility_ddAH_2h", "turning_points_2h",
    "response_gain_30min", "response_gain_60min",
]


def build_features(df: pd.DataFrame, rule_minutes: int = 5, smooth_ddah_window: int = 3) -> pd.DataFrame:
    f = df.copy()
    f["AH_in"] = calc_absolute_humidity(f["in_temp"], f["in_hum"])
    f["AH_out"] = calc_absolute_humidity(f["out_temp"], f["out_hum"])
    f["dAH"] = f["AH_in"] - f["AH_out"]
    dAH_smooth = f["dAH"].rolling(window=smooth_ddah_window, min_periods=1).mean()
    f["ddAH"] = dAH_smooth.diff()

    win30 = max(2, int(30 / rule_minutes))
    win60 = max(3, int(60 / rule_minutes))
    win120 = max(6, int(120 / rule_minutes))

    f["AH_out_slope_30min"] = rolling_slope(f["AH_out"], win30)
    f["AH_out_slope_60min"] = rolling_slope(f["AH_out"], win60)
    f["delta_AH_out_30min"] = f["AH_out"] - f["AH_out"].shift(win30)
    f["delta_AH_out_60min"] = f["AH_out"] - f["AH_out"].shift(win60)
    f["volatility_AH_out_2h"] = f["AH_out"].rolling(win120, min_periods=max(4, win120 // 2)).std()

    f["dT"] = f["in_temp"] - f["out_temp"]
    f["out_temp_slope_30min"] = rolling_slope(f["out_temp"], win30)
    f["out_temp_slope_60min"] = rolling_slope(f["out_temp"], win60)
    f["delta_out_temp_30min"] = f["out_temp"] - f["out_temp"].shift(win30)
    f["delta_out_temp_60min"] = f["out_temp"] - f["out_temp"].shift(win60)
    f["dT_slope_30min"] = rolling_slope(f["dT"], win30)
    f["dT_slope_60min"] = rolling_slope(f["dT"], win60)
    f["delta_dT_30min"] = f["dT"] - f["dT"].shift(win30)
    f["volatility_out_temp_2h"] = f["out_temp"].rolling(win120, min_periods=max(4, win120 // 2)).std()
    f["volatility_dT_2h"] = f["dT"].rolling(win120, min_periods=max(4, win120 // 2)).std()

    f["dAH_slope_30min"] = rolling_slope(f["dAH"], win30)
    f["dAH_slope_60min"] = rolling_slope(f["dAH"], win60)
    f["AH_in_slope_30min"] = rolling_slope(f["AH_in"], win30)
    f["AH_out_level_slope_30min"] = rolling_slope(f["AH_out"], win30)

    abs_gap = f["dAH"].abs()
    f["delta_dAH_30min"] = f["dAH"] - f["dAH"].shift(win30)
    f["delta_dAH_60min"] = f["dAH"] - f["dAH"].shift(win60)
    f["gap_close_speed_60min"] = -rolling_slope(abs_gap, win60)
    f["gap_close_speed_2h"] = -rolling_slope(abs_gap, win120)

    ddah_abs_mean_2h = f["ddAH"].abs().rolling(win120, min_periods=max(4, win120 // 2)).mean()
    dah_abs_mean_2h = abs_gap.rolling(win120, min_periods=max(4, win120 // 2)).mean()
    f["tau_proxy_2h"] = dah_abs_mean_2h / (ddah_abs_mean_2h + 1e-6)

    f["local_amp_60min"] = (
        f["dAH"].rolling(win60, min_periods=max(3, win60 // 2)).max()
        - f["dAH"].rolling(win60, min_periods=max(3, win60 // 2)).min()
    )
    f["volatility_ddAH_2h"] = f["ddAH"].rolling(win120, min_periods=max(4, win120 // 2)).std()
    f["turning_points_2h"] = rolling_turning_points(f["dAH"], win120)

    delta_ah_in_30 = f["AH_in"] - f["AH_in"].shift(win30)
    delta_ah_in_60 = f["AH_in"] - f["AH_in"].shift(win60)
    delta_ah_out_30 = f["AH_out"] - f["AH_out"].shift(win30)
    delta_ah_out_60 = f["AH_out"] - f["AH_out"].shift(win60)
    f["response_gain_30min"] = (delta_ah_in_30 / (delta_ah_out_30 + 1e-6)).clip(-10, 10)
    f["response_gain_60min"] = (delta_ah_in_60 / (delta_ah_out_60 + 1e-6)).clip(-10, 10)

    return f.dropna()


def list_supported_files(dir_path: str) -> List[str]:
    files: List[str] = []
    for pat in ["*.xlsx", "*.xls", "*.csv"]:
        files.extend(glob.glob(os.path.join(dir_path, pat)))
    return sorted(files)


def make_24h_windows(
    df: pd.DataFrame,
    rule_minutes: int,
    window_hours: int = 24,
    step_hours: int = 1,
    allow_short_last: bool = True,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    """
    生成24h滑动窗口。
    当整段数据不足24h时，如果 allow_short_last=True，则返回一个“实际长度窗口”。
    """
    pts_per_hour = int(60 / rule_minutes)
    win = window_hours * pts_per_hour
    step = step_hours * pts_per_hour
    out: List[Tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]] = []

    if len(df) == 0:
        return out

    # 不足24h：直接按实际长度返回一个窗口
    if len(df) < win:
        if allow_short_last:
            sub = df.copy()
            out.append((sub.index[0], sub.index[-1], sub))
        return out

    # 正常24h滑窗
    for st in range(0, len(df) - win + 1, step):
        sub = df.iloc[st: st + win].copy()
        out.append((sub.index[0], sub.index[-1], sub))

    # 可选：如果最后剩下一小段，也可补一个尾部短窗口
    # 当前先不加，避免与原有逻辑差异过大

    return out


def load_dir_as_series(
    dir_path: str,
    time_col: str = "time",
    rule: str = "5min",
    smooth_ddah_window: int = 3,
    csv_encoding: Optional[str] = None,
    min_points: int = 120,
) -> List[Tuple[str, pd.DataFrame]]:
    files = list_supported_files(dir_path)
    if not files:
        raise FileNotFoundError(f"目录下没有支持文件: {dir_path}")
    rule_minutes = int(rule.replace("min", ""))
    rows: List[Tuple[str, pd.DataFrame]] = []
    for p in files:
        try:
            df = read_timeseries(p, time_col=time_col, csv_encoding=csv_encoding)
            df = resample_df(df, rule=rule)
            df = build_features(df, rule_minutes=rule_minutes, smooth_ddah_window=smooth_ddah_window)
            if len(df) >= min_points:
                rows.append((p, df))
            else:
                print(f"[SKIP] {os.path.basename(p)}: 点数不足 {len(df)} < {min_points}")
        except Exception as e:
            print(f"[SKIP] {os.path.basename(p)}: {e}")
    if not rows:
        raise RuntimeError("未生成任何有效训练序列")
    return rows


def split_series_by_file(items: List[Tuple[str, pd.DataFrame]], val_ratio: float = 0.2, seed: int = 42):
    file_names = sorted([x[0] for x in items])
    rng = np.random.default_rng(seed)
    idx = np.arange(len(file_names))
    rng.shuffle(idx)
    n_val = max(1, int(len(file_names) * val_ratio)) if len(file_names) > 1 else 0
    val_files = {file_names[i] for i in idx[:n_val]}
    train, val = [], []
    for item in items:
        (val if item[0] in val_files else train).append(item)
    return train, val


def df_to_scaled_array(df: pd.DataFrame, feature_names: List[str], scaler: RobustScaler) -> np.ndarray:
    X = df[feature_names].to_numpy(dtype=np.float32)
    Xs = scaler.transform(X)
    return np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)


class ForecastWindowDataset(Dataset):
    def __init__(self, sequences: List[np.ndarray], W: int, H: int, stride: int):
        self.samples: List[Tuple[int, int]] = []
        self.sequences = sequences
        self.W = W
        self.H = H
        for si, seq in enumerate(sequences):
            max_start = seq.shape[0] - (W + H)
            if max_start < 0:
                continue
            for st in range(0, max_start + 1, stride):
                self.samples.append((si, st))
        if not self.samples:
            raise RuntimeError("未生成任何训练样本，请检查 W/H 与序列长度")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        si, st = self.samples[idx]
        seq = self.sequences[si]
        x = seq[st: st + self.W]
        y = seq[st + self.W: st + self.W + self.H]
        return torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)


class GRUForecast(nn.Module):
    def __init__(self, d_in: int, hidden: int, num_layers: int, H: int, dropout: float = 0.1):
        super().__init__()
        self.H = H
        self.d_in = d_in
        self.gru = nn.GRU(
            input_size=d_in,
            hidden_size=hidden,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, H * d_in),
        )

    def forward(self, x):
        _, h = self.gru(x)
        h_last = h[-1]
        return self.head(h_last).view(-1, self.H, self.d_in)


def weighted_mae(y_pred: torch.Tensor, y_true: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    return (torch.abs(y_pred - y_true) * w.view(1, 1, -1)).mean()


def train_model(
    train_arrays: List[np.ndarray],
    val_arrays: List[np.ndarray],
    feature_names: List[str],
    out_dir: str,
    W: int = 48,
    H: int = 6,
    stride: int = 1,
    hidden: int = 64,
    layers: int = 2,
    dropout: float = 0.1,
    batch_size: int = 128,
    lr: float = 1e-3,
    epochs: int = 30,
    device: str = "cpu",
    seed: int = 42,
):
    os.makedirs(out_dir, exist_ok=True)
    set_seed(seed)
    train_ds = ForecastWindowDataset(train_arrays, W=W, H=H, stride=stride)
    val_ds = ForecastWindowDataset(val_arrays, W=W, H=H, stride=stride) if val_arrays else None
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False, drop_last=False) if val_ds else None

    model = GRUForecast(d_in=train_arrays[0].shape[1], hidden=hidden, num_layers=layers, H=H, dropout=dropout).to(device)
    weight_map = {
        "dAH": 2.0,
        "ddAH": 2.0,
        "gap_close_speed_60min": 1.5,
        "gap_close_speed_2h": 1.5,
        "tau_proxy_2h": 1.5,
        "dAH_slope_60min": 1.3,
    }
    w = np.ones(train_arrays[0].shape[1], dtype=np.float32)
    for i, fn in enumerate(feature_names):
        if fn in weight_map:
            w[i] = weight_map[fn]
    w_t = torch.tensor(w, dtype=torch.float32, device=device)

    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    best_metric = float("inf")
    history = {"train": [], "val": []}

    for ep in range(1, epochs + 1):
        model.train()
        tr_losses = []
        for x, y in train_dl:
            x = x.to(device)
            y = y.to(device)
            yhat = model(x)
            loss = weighted_mae(yhat, y, w_t)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tr_losses.append(loss.item())
        tr = float(np.mean(tr_losses))
        history["train"].append(tr)

        va = None
        if val_dl is not None:
            model.eval()
            va_losses = []
            with torch.no_grad():
                for x, y in val_dl:
                    x = x.to(device)
                    y = y.to(device)
                    yhat = model(x)
                    va_losses.append(weighted_mae(yhat, y, w_t).item())
            va = float(np.mean(va_losses)) if va_losses else float("nan")
            history["val"].append(va)

        metric = va if va is not None else tr
        if metric < best_metric:
            best_metric = metric
            torch.save(model.state_dict(), os.path.join(out_dir, "best_model.pt"))
        print(f"Epoch {ep:03d}/{epochs} | train={tr:.6f}" + (f" | val={va:.6f}" if va is not None else ""))

    save_json(history, os.path.join(out_dir, "train_history.json"))
    return history


def compute_residual_series(
    model: nn.Module,
    seq_scaled: np.ndarray,
    W: int,
    H: int,
    stride: int,
    feature_names: List[str],
    device: str = "cpu",
) -> pd.DataFrame:
    model.eval()
    dah_idx = feature_names.index("dAH")
    rows = []
    with torch.no_grad():
        T = seq_scaled.shape[0]
        max_start = T - (W + H)
        for st in range(0, max_start + 1, stride):
            x = torch.tensor(seq_scaled[st: st + W], dtype=torch.float32, device=device).unsqueeze(0)
            y_true = torch.tensor(seq_scaled[st + W: st + W + H], dtype=torch.float32, device=device).unsqueeze(0)
            y_pred = model(x)
            err = (y_true - y_pred)[0].cpu().numpy()
            abs_err = np.abs(err)
            rows.append({
                "pos": st + W,
                "score_all": float(abs_err.mean()),
                "score_dAH": float(abs_err[:, dah_idx].mean()),
                "resid_dAH_signed": float(err[:, dah_idx].mean()),
            })
    return pd.DataFrame(rows)


def ewma_series(x: np.ndarray, alpha: float = 0.2) -> np.ndarray:
    z = np.zeros_like(x, dtype=np.float64)
    if len(x) == 0:
        return z
    z[0] = x[0]
    for i in range(1, len(x)):
        z[i] = alpha * x[i] + (1 - alpha) * z[i - 1]
    return z


def cusum_two_sided(x: np.ndarray, k: float = 0.5):
    gp = np.zeros_like(x, dtype=np.float64)
    gn = np.zeros_like(x, dtype=np.float64)
    for i in range(1, len(x)):
        gp[i] = max(0.0, gp[i - 1] + x[i] - k)
        gn[i] = max(0.0, gn[i - 1] - x[i] - k)
    return gp, gn


def attach_accumulation_metrics(df_score: pd.DataFrame, resid_mean: float, resid_std: float, alpha: float = 0.2, cusum_k: float = 0.5) -> pd.DataFrame:
    out = df_score.copy()
    z = (out["resid_dAH_signed"].values - resid_mean) / max(resid_std, 1e-6)
    out["resid_dAH_z"] = z
    ew = ewma_series(z, alpha=alpha)
    gp, gn = cusum_two_sided(z, k=cusum_k)
    out["ewma_z"] = ew
    out["ewma_abs"] = np.abs(ew)
    out["cusum_pos"] = gp
    out["cusum_neg"] = gn
    out["cusum_abs"] = np.maximum(gp, gn)
    return out


def fit_window_baseline(
    model: nn.Module,
    train_arrays: List[np.ndarray],
    feature_names: List[str],
    W: int,
    H: int,
    stride: int,
    device: str = "cpu",
    alpha: float = 0.2,
    cusum_k: float = 0.5,
) -> Dict:
    seq_dfs = []
    all_signed = []
    for seq in train_arrays:
        df = compute_residual_series(model, seq, W, H, stride, feature_names, device=device)
        seq_dfs.append(df)
        all_signed.extend(df["resid_dAH_signed"].tolist())

    resid_mean = float(np.mean(all_signed))
    resid_std = float(np.std(all_signed) + 1e-6)

    score_vals, ewma_vals, cusum_vals = [], [], []
    for df in seq_dfs:
        tmp = attach_accumulation_metrics(df, resid_mean, resid_std, alpha=alpha, cusum_k=cusum_k)
        score_vals.extend(tmp["score_dAH"].tolist())
        ewma_vals.extend(tmp["ewma_abs"].tolist())
        cusum_vals.extend(tmp["cusum_abs"].tolist())

    return {
        "resid_mean": resid_mean,
        "resid_std": resid_std,
        "alpha": alpha,
        "cusum_k": cusum_k,
        "thr_score_dAH": float(np.quantile(score_vals, 0.995)),
        "thr_ewma_abs": float(np.quantile(ewma_vals, 0.995)),
        "thr_cusum_abs": float(np.quantile(cusum_vals, 0.995)),
    }


def summarize_24h_window(score_df: pd.DataFrame, baseline: Dict) -> Dict:
    valid = score_df.dropna()
    if len(valid) == 0:
        return {"status": "unknown", "reason": "no_valid_scores"}

    max_score_dah = float(valid["score_dAH"].max())
    mean_score_dah = float(valid["score_dAH"].mean())
    max_ewma = float(valid["ewma_abs"].max())
    mean_ewma = float(valid["ewma_abs"].mean())
    max_cusum = float(valid["cusum_abs"].max())
    mean_cusum = float(valid["cusum_abs"].mean())

    ratio_score = float((valid["score_dAH"] > baseline["thr_score_dAH"]).mean())
    ratio_ewma = float((valid["ewma_abs"] > baseline["thr_ewma_abs"]).mean())
    ratio_cusum = float((valid["cusum_abs"] > baseline["thr_cusum_abs"]).mean())

    cond_persistent = (ratio_cusum > 0.20) or (ratio_ewma > 0.20)
    cond_short = (ratio_score > 0.02) or (max_score_dah > baseline["thr_score_dAH"])
    cond_peak = (max_cusum > baseline["thr_cusum_abs"]) or (max_ewma > baseline["thr_ewma_abs"])

    if cond_persistent and cond_short:
        status = "abnormal"
    elif cond_persistent or cond_peak or cond_short:
        status = "warning"
    else:
        status = "normal"

    return {
        "status": status,
        "max_score_dAH": max_score_dah,
        "mean_score_dAH": mean_score_dah,
        "max_ewma_abs": max_ewma,
        "mean_ewma_abs": mean_ewma,
        "max_cusum_abs": max_cusum,
        "mean_cusum_abs": mean_cusum,
        "ratio_alarm_score_dAH": ratio_score,
        "ratio_alarm_ewma_abs": ratio_ewma,
        "ratio_alarm_cusum_abs": ratio_cusum,
    }


def load_model_bundle(model_dir: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with open(os.path.join(model_dir, "scaler.json"), "r", encoding="utf-8") as f:
        scaler = RobustScaler.from_dict(json.load(f))
    with open(os.path.join(model_dir, "feature_names.json"), "r", encoding="utf-8") as f:
        feature_names = json.load(f)
    with open(os.path.join(model_dir, "window_baseline.json"), "r", encoding="utf-8") as f:
        baseline = json.load(f)
    with open(os.path.join(model_dir, "config.json"), "r", encoding="utf-8") as f:
        config = json.load(f)
    model = GRUForecast(
        d_in=len(feature_names),
        hidden=int(config["hidden"]),
        num_layers=int(config["layers"]),
        H=int(config["H"]),
        dropout=float(config["dropout"]),
    )
    model.load_state_dict(torch.load(os.path.join(model_dir, "best_model.pt"), map_location=device))
    model.to(device).eval()
    return model, scaler, baseline, feature_names, config
