from __future__ import annotations

import argparse
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

import reader_petrochemical as reader


COLUMN_ALIASES = {
    "time": ["time", "时间", "timestamp", "date", "datetime", "采集时间"],
    "project_name": ["project_name", "项目名称"],
    "project_num": ["project_num", "项目编码", "项目编号"],
    "dev_name": ["dev_name", "设备名称", "传感器编号", "sensor_name"],
    "dev_num": ["dev_num", "设备编码", "传感器编码", "sensor_code", "imei"],
    "snr": ["snr", "SNR", "信噪比"],
    "rsrp": ["rsrp", "RSRP", "信号质量"],
    "in_temp": ["in_temp", "内部温度", "内温", "温度_内", "InSideTemp"],
    "in_hum": ["in_hum", "内部湿度", "内湿", "湿度_内", "InSideHumi"],
    "out_temp": ["out_temp", "外部温度", "外温", "温度_外", "OutSideTemp"],
    "out_hum": ["out_hum", "外部湿度", "外湿", "湿度_外", "OutSideHumi"],
    "phase_temp_a": ["phase_temp_a", "A相温度", "PhaseTempA", "Atemp"],
    "phase_temp_b": ["phase_temp_b", "B相温度", "PhaseTempB", "Btemp"],
    "phase_temp_c": ["phase_temp_c", "C相温度", "PhaseTempC", "Ctemp"],
    "mlx_max_temp": ["mlx_max_temp", "红外最高温度", "MlxMaxTemp"],
    "mlx_min_temp": ["mlx_min_temp", "红外最低温度", "MlxMinTemp"],
    "mlx_avg_temp": ["mlx_avg_temp", "红外平均温度", "MlxAvgTemp"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量导入 Excel/CSV 到 device_monitoring_data")
    parser.add_argument("path", help="Excel/CSV 文件或目录")
    parser.add_argument("--sheet", default="", help="指定 Excel sheet；默认优先 Serial Data Log")
    parser.add_argument("--glob", default="*.xlsx", help="目录模式下匹配规则，默认 *.xlsx")
    parser.add_argument(
        "--trigger-mode",
        choices=["none", "latest", "all"],
        default="latest",
        help="导入后触发检测方式：none=不触发，latest=每个设备只触发最新一条，all=每条都触发",
    )
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印统计，不写数据库")
    parser.add_argument("--limit", type=int, default=0, help="每个文件最多导入多少行，0 表示全部")
    parser.add_argument("--default-dev-name", default=os.getenv("SIM_DEV_NAME", "AHCZ-D1S-26801"))
    parser.add_argument("--default-dev-num", default=os.getenv("SIM_DEV_NUM", "848872DC45E1D3F"))
    parser.add_argument("--default-project-name", default=os.getenv("SIM_PROJECT_NAME", "BSTProject"))
    parser.add_argument("--default-project-num", default=os.getenv("SIM_PROJECT_NUM", "001"))
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def resolve_files(path_str: str, glob_expr: str) -> List[Path]:
    path = Path(path_str)
    if path.is_file():
        return [path]
    if path.is_dir():
        files = sorted([p for p in path.glob(glob_expr) if p.is_file()])
        more = sorted([p for p in path.glob("*.csv") if p.is_file()])
        known = {str(p.resolve()) for p in files}
        for item in more:
            if str(item.resolve()) not in known:
                files.append(item)
        return files
    raise FileNotFoundError(f"未找到文件或目录: {path_str}")


def choose_sheet(excel: pd.ExcelFile, requested_sheet: str) -> str:
    if requested_sheet:
        return requested_sheet
    preferred = next((name for name in excel.sheet_names if name.strip().lower() == "serial data log"), None)
    return preferred or excel.sheet_names[0]


def load_dataframe(path: Path, sheet_name: str) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    excel = pd.ExcelFile(path)
    selected_sheet = choose_sheet(excel, sheet_name)
    return excel.parse(sheet_name=selected_sheet)


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    renamed: Dict[str, str] = {}
    lower_map = {str(col).strip().lower(): col for col in df.columns}

    for std_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            original = lower_map.get(str(alias).strip().lower())
            if original is not None:
                renamed[original] = std_name
                break

    out = df.rename(columns=renamed).copy()
    out = out.dropna(how="all").reset_index(drop=True)
    return out


def safe_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def normalize_time_seconds(value) -> int:
    if value is None or value == "":
        return int(pd.Timestamp.now().timestamp())
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return int(ts.timestamp())
    except Exception:
        pass
    try:
        raw = int(float(value))
        if raw > 1_000_000_000_000:
            return raw // 1000
        if raw > 0:
            return raw
    except Exception:
        pass
    return int(pd.Timestamp.now().timestamp())


def build_payload(row: Dict[str, object], args: argparse.Namespace) -> Dict[str, object]:
    dev_name = str(row.get("dev_name") or args.default_dev_name).strip()
    dev_num = str(row.get("dev_num") or args.default_dev_num).strip()
    project_name = str(row.get("project_name") or args.default_project_name).strip()
    project_num = str(row.get("project_num") or args.default_project_num).strip()
    ts_seconds = normalize_time_seconds(row.get("time"))

    datas: Dict[str, str] = {}

    def put(key: str, value):
        numeric = safe_float(value)
        if numeric is None:
            return
        datas[f"{dev_num}_{key}"] = f"{numeric:.2f}"

    put("SNR", row.get("snr"))
    put("RSRP", row.get("rsrp"))
    put("InSideTemp", row.get("in_temp"))
    put("InSideHumi", row.get("in_hum"))
    put("OutSideTemp", row.get("out_temp"))
    put("OutSideHumi", row.get("out_hum"))
    put("PhaseTempA", row.get("phase_temp_a"))
    put("PhaseTempB", row.get("phase_temp_b"))
    put("PhaseTempC", row.get("phase_temp_c"))
    put("MlxMaxTemp", row.get("mlx_max_temp"))
    put("MlxMinTemp", row.get("mlx_min_temp"))
    put("MlxAvgTemp", row.get("mlx_avg_temp"))

    return {
        "date": str(ts_seconds),
        "project_name": project_name,
        "project_num": project_num,
        "dev_name": dev_name,
        "dev_num": dev_num,
        "datas": datas,
    }


def iter_rows(df: pd.DataFrame, limit: int) -> Iterable[Dict[str, object]]:
    if limit > 0:
        df = df.head(limit)
    for row in df.to_dict(orient="records"):
        yield row


def import_file(
    path: Path,
    args: argparse.Namespace,
    db_manager: Optional[reader.MySQLConnectionManager],
    trigger_points: Dict[str, List[int]],
) -> Dict[str, int]:
    df = normalize_dataframe(load_dataframe(path, args.sheet))
    stats = {"rows": 0, "saved": 0, "failed": 0, "skipped": 0}

    logging.info("📄 导入文件: %s", path)
    for row in iter_rows(df, args.limit):
        stats["rows"] += 1
        payload = build_payload(row, args)
        raw_json = json.dumps(payload, ensure_ascii=False)
        db_data = reader.extract_device_data(raw_json)
        if not db_data or not db_data.get("dev_num"):
            stats["skipped"] += 1
            continue

        if args.dry_run:
            stats["saved"] += 1
            trigger_points[db_data["dev_num"]].append(int(db_data["device_timestamp"]))
            continue

        ok = reader.save_to_mysql_with_retry(db_manager, db_data)
        if ok:
            stats["saved"] += 1
            trigger_points[db_data["dev_num"]].append(int(db_data["device_timestamp"]))
        else:
            stats["failed"] += 1

    logging.info(
        "✅ 文件完成: %s rows=%s saved=%s failed=%s skipped=%s",
        path.name,
        stats["rows"],
        stats["saved"],
        stats["failed"],
        stats["skipped"],
    )
    return stats


def trigger_after_import(trigger_mode: str, trigger_points: Dict[str, List[int]], dry_run: bool):
    if dry_run or trigger_mode == "none":
        return

    for dev_num, timestamps in trigger_points.items():
        if not timestamps:
            continue

        if trigger_mode == "latest":
            target_ts_list = [max(timestamps)]
        else:
            target_ts_list = sorted(set(timestamps))

        for ts in target_ts_list:
            ok = reader.trigger_detection(dev_num, ts)
            if ok:
                logging.info("🔁 触发检测成功: %s @ %s", dev_num, ts)
            else:
                logging.warning("⚠️ 触发检测失败: %s @ %s", dev_num, ts)


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    files = resolve_files(args.path, args.glob)
    if not files:
        raise FileNotFoundError("没有匹配到可导入文件")

    logging.info("🚀 批量导入开始 files=%s dry_run=%s trigger_mode=%s", len(files), args.dry_run, args.trigger_mode)
    db_manager = None if args.dry_run else reader.MySQLConnectionManager()

    total = {"files": len(files), "rows": 0, "saved": 0, "failed": 0, "skipped": 0}
    trigger_points: Dict[str, List[int]] = defaultdict(list)

    for path in files:
        stats = import_file(path, args, db_manager, trigger_points)
        total["rows"] += stats["rows"]
        total["saved"] += stats["saved"]
        total["failed"] += stats["failed"]
        total["skipped"] += stats["skipped"]

    trigger_after_import(args.trigger_mode, trigger_points, args.dry_run)

    logging.info(
        "🏁 导入结束 files=%s rows=%s saved=%s failed=%s skipped=%s devices=%s",
        total["files"],
        total["rows"],
        total["saved"],
        total["failed"],
        total["skipped"],
        len(trigger_points),
    )


if __name__ == "__main__":
    main()
