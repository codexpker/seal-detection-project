# -*- coding: utf-8 -*-
"""
Created on Wed Mar 25 21:43:59 2026

@author: wang
"""

import os
import glob
import pandas as pd

from moisture_detector import detect_window_state


def process_csv_folder(
    input_dir=None,
    output_csv=None,
    time_col="time",
    hum_col="in_hum",
    hum_threshold=85.0,
    min_duration_hours=2.0
):
    """
    批量处理目录下所有 CSV 文件。

    默认：
    - 输入目录：当前目录/windows
    - 输出文件：当前目录/window_state_results.csv
    """
    current_dir = os.getcwd()

    if input_dir is None:
        input_dir = os.path.join(current_dir, "windows")

    if output_csv is None:
        output_csv = os.path.join(current_dir, "window_state_results.csv")

    csv_files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))

    if not csv_files:
        print(f"未找到CSV文件: {input_dir}")
        return None

    results = []

    for file_path in csv_files:
        file_name = os.path.basename(file_path)
        print(f"处理: {file_name}")

        try:
            df = pd.read_csv(file_path)

            result = detect_window_state(
                window_df=df,
                time_col=time_col,
                hum_col=hum_col,
                hum_threshold=hum_threshold,
                min_duration_hours=min_duration_hours
            )

            results.append({
                "file_name": file_name,
                "state": result["state"],
                "start_time": result["start_time_over_85"],
                "end_time": result["end_time"],
                "duration_hours": result["duration_hours"],
                "slope": result["slope"],
                "reason": result["reason"]
            })

        except Exception as e:
            results.append({
                "file_name": file_name,
                "state": "数据异常",
                "start_time": None,
                "end_time": None,
                "duration_hours": None,
                "slope": None,
                "reason": f"处理失败: {str(e)}"
            })

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("\n=== 检测完成 ===")
    print(result_df)
    print(f"\n结果已保存: {output_csv}")

    return result_df


if __name__ == "__main__":
    process_csv_folder()