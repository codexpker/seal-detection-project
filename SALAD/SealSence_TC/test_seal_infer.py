# -*- coding: utf-8 -*-
"""
测试程序：
读取一个24小时窗口CSV，
调用 seal_infer_industrial.py 进行检测，
输出：异常 / 不异常 / 无法判断
"""

import os
import pandas as pd
from seal_infer_industrial import SealInferIndustrial


def read_window_csv(csv_path: str, encoding=None) -> pd.DataFrame:
    """
    读取单个24小时窗口CSV
    要求至少包含：
    time, in_temp, in_hum, out_temp, out_hum
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV文件不存在: {csv_path}")

    df = pd.read_csv(csv_path, encoding=encoding)

    required_cols = ["time", "in_temp", "in_hum", "out_temp", "out_hum"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"CSV缺少必要字段: {missing}")

    return df


def main():
    MODEL_DIR = r"./model"
    CSV_PATH1 = r"./window_24h-unseal.csv"
    CSV_PATH2 = r"./window_24h-seal.csv"
    CSV_ENCODING = None

    try:
        df = read_window_csv(CSV_PATH1, encoding=CSV_ENCODING)

        infer = SealInferIndustrial(model_dir=MODEL_DIR)
        result = infer.predict_one_window_df(df)

        print(result["label"])
        
        df2 = read_window_csv(CSV_PATH2, encoding=CSV_ENCODING)

        result = infer.predict_one_window_df(df2)

        print(result["label"])

        # 若想调试，可打开下面两行
        # print(result["message"])
        # print(result["summary"])

    except Exception as e:
        print("无法判断")
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()