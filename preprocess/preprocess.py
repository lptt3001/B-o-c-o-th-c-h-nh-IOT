"""Tien xu ly: doc iot_raw -> lam sach -> outlier -> resample -> dac trung -> chuan hoa -> ghi iot_clean.

Chay: python preprocess/preprocess.py --hours 6 --window 30s
Ket qua thong ke + hinh anh luu trong thu muc output/ (dung cho bao cao).
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

# Chuan hoa viet tay bang pandas/numpy, khong dung scikit-learn
# (tranh phai bien dich scipy tren may khong co trinh bien dich C/C++,
#  thuong gap voi Python 32-bit hoac ban cu).
def standard_scale(s: pd.Series) -> pd.Series:
    std = s.std()
    return (s - s.mean()) / std if std else s * 0.0

def minmax_scale(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else s * 0.0

BASE = ["temperature", "humidity", "distance_cm"]
# Nguong IQR toi thieu: tranh IQR = 0 khi cam bien gia lap giu gia tri khong doi
MIN_IQR = {"temperature": 0.5, "humidity": 1.0, "distance_cm": 1.0}


def iqr_mask(s: pd.Series, col: str, k: float = 1.5) -> pd.Series:
    q1, q3 = s.quantile([0.25, 0.75])
    iqr = max(q3 - q1, MIN_IQR[col])
    return (s < q1 - k * iqr) | (s > q3 + k * iqr)


def zscore_mask(s: pd.Series, thr: float = 3.0) -> pd.Series:
    std = s.std()
    if not std or np.isnan(std):
        return pd.Series(False, index=s.index)
    return ((s - s.mean()) / std).abs() > thr


def process(df: pd.DataFrame, window: str = "30s", interp_limit: int = 4,
            outlier_method: str = "iqr"):
    """df: index = thoi gian (tz-aware), cot = BASE. Tra ve (ket_qua, bao_cao)."""
    report = {"raw_samples": int(len(df))}
    df = df[~df.index.duplicated(keep="last")].sort_index()  # bo trung lap
    report["after_dedup"] = int(len(df))

    cleaned = df.copy()
    report["outliers_iqr"], report["outliers_zscore"] = {}, {}
    for c in BASE:
        m_iqr, m_z = iqr_mask(df[c], c), zscore_mask(df[c])
        report["outliers_iqr"][c] = int(m_iqr.sum())
        report["outliers_zscore"][c] = int(m_z.sum())
        cleaned.loc[m_iqr if outlier_method == "iqr" else m_z, c] = np.nan

    rs = cleaned.resample(window).mean()
    report["missing_after_resample"] = {c: int(rs[c].isna().sum()) for c in BASE}
    rs = rs.interpolate(method="time", limit=interp_limit, limit_area="inside").dropna()
    report["clean_samples"] = int(len(rs))

    for c in BASE:  # dac trung
        rs[f"{c}_roll5"] = rs[c].rolling(5, min_periods=1).mean()
        rs[f"{c}_delta"] = rs[c].diff().fillna(0)

    for c in BASE:  # chuan hoa
        rs[f"{c}_z"] = standard_scale(rs[c])
        rs[f"{c}_mm"] = minmax_scale(rs[c])
    return rs, report


def load_raw(db: InfluxDBClient, bucket: str, hours: int, device: str) -> pd.DataFrame:
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "environment" and r.device_id == "{device}")
  |> filter(fn: (r) => r._field == "temperature" or r._field == "humidity" or r._field == "distance_cm")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    res = db.query_api().query_data_frame(flux)
    if isinstance(res, list):
        res = pd.concat(res) if res else pd.DataFrame()
    if res.empty:
        raise SystemExit("Khong co du lieu trong khoang thoi gian yeu cau.")
    return res.rename(columns={"_time": "time"}).set_index("time")[BASE]


def save_plots(raw: pd.DataFrame, clean: pd.DataFrame, outdir: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for ax, c in zip(axes, BASE):
        ax.plot(raw.index, raw[c], ".", ms=2, alpha=.5, label="raw")
        ax.plot(clean.index, clean[c], "-", lw=1.2, label="resample 30s")
        ax.plot(clean.index, clean[f"{c}_roll5"], "-", lw=1.5, label="rolling mean(5)")
        ax.set_ylabel(c); ax.legend(loc="upper right", fontsize=8)
    axes[0].set_title("Truoc va sau tien xu ly")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "before_after.png"), dpi=130)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--window", default="30s")
    ap.add_argument("--method", choices=["iqr", "zscore"], default="iqr")
    ap.add_argument("--device", default=os.getenv("DEVICE_ID", "esp32-b23dccn856"))
    ap.add_argument("--location", default="room1")
    a = ap.parse_args()

    db = InfluxDBClient(url=os.getenv("INFLUX_URL", "http://localhost:8086"),
                        token=os.getenv("INFLUX_TOKEN", "my-super-token"),
                        org=os.getenv("INFLUX_ORG", "iot"))
    raw = load_raw(db, os.getenv("RAW_BUCKET", "iot_raw"), a.hours, a.device)
    print("So mau tho:", len(raw))
    clean, report = process(raw.copy(), a.window, outlier_method=a.method)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    os.makedirs("output", exist_ok=True)
    with open("output/preprocess_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    clean.to_csv("output/clean_data.csv")
    save_plots(raw, clean, "output")

    out = clean.copy()
    out["device_id"], out["location"] = a.device, a.location
    db.write_api(write_options=SYNCHRONOUS).write(
        bucket=os.getenv("CLEAN_BUCKET", "iot_clean"), record=out,
        data_frame_measurement_name="environment_clean",
        data_frame_tag_columns=["device_id", "location"])
    print(f"Da ghi {len(out)} diem vao iot_clean/environment_clean")
    db.close()


if __name__ == "__main__":
    main()
