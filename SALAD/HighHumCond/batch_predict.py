# -*- coding: utf-8 -*-
"""
Created on Mon Mar 23 23:42:34 2026

@author: wang
"""

import os
from glob import glob
import pandas as pd

from high_hum_seal_model import predict_seal_state


def process_directory(
    input_dir,
    output_csv,
    smooth_win=5,
    downsample_factor=10,
    sub_size=36,
    step=12,
    return_features=True
):
    file_list = sorted(glob(os.path.join(input_dir, "*.csv")))

    if len(file_list) == 0:
        print(f"目录下没有找到 CSV 文件: {input_dir}")
        return

    results = []

    for file_path in file_list:
        try:
            df = pd.read_csv(file_path)

            if return_features:
                label, feats = predict_seal_state(
                    df,
                    smooth_win=smooth_win,
                    downsample_factor=downsample_factor,
                    sub_size=sub_size,
                    step=step,
                    return_features=True
                )
                row = {
                    "file": os.path.basename(file_path),
                    "result": label,
                    **feats
                }
            else:
                label = predict_seal_state(
                    df,
                    smooth_win=smooth_win,
                    downsample_factor=downsample_factor,
                    sub_size=sub_size,
                    step=step,
                    return_features=False
                )
                row = {
                    "file": os.path.basename(file_path),
                    "result": label
                }

        except Exception as e:
            row = {
                "file": os.path.basename(file_path),
                "result": f"error: {str(e)}"
            }

        results.append(row)

    df_res = pd.DataFrame(results)
    df_res.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"处理完成，共 {len(df_res)} 个窗口")
    print(f"结果已保存到: {output_csv}")
    print("\n结果统计：")
    print(df_res["result"].value_counts(dropna=False))


if __name__ == "__main__":
    input_dir = r"./windows"
    output_csv = r"./window_predict_result.csv"

    process_directory(
        input_dir=input_dir,
        output_csv=output_csv,
        smooth_win=5,
        downsample_factor=10,
        sub_size=36,
        step=12,
        return_features=True
    )