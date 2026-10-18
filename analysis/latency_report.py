"""Thong ke do tre end-to-end, ti le mat goi tu iot_raw. Xuat output/latency_stats.json va latency_hist.png.

Chay: python analysis/latency_report.py --hours 2
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=2)
    a = ap.parse_args()
    db = InfluxDBClient(url=os.getenv("INFLUX_URL", "http://localhost:8086"),
                        token=os.getenv("INFLUX_TOKEN", "my-super-token"),
                        org=os.getenv("INFLUX_ORG", "iot"))
    flux = f'''
from(bucket: "{os.getenv("RAW_BUCKET", "iot_raw")}")
  |> range(start: -{a.hours}h)
  |> filter(fn: (r) => r._measurement == "environment" and (r._field == "latency_ms" or r._field == "seq"))
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    df = db.query_api().query_data_frame(flux)
    if isinstance(df, list):
        df = pd.concat(df)
    df = df.sort_values("_time")
    lat = df["latency_ms"].dropna()
    expected = int(df["seq"].max() - df["seq"].min() + 1)
    received = int(df["seq"].nunique())
    stats = {
        "samples": int(len(lat)),
        "latency_mean_ms": round(lat.mean(), 1), "latency_median_ms": round(lat.median(), 1),
        "latency_p95_ms": round(lat.quantile(.95), 1), "latency_max_ms": round(lat.max(), 1),
        "latency_min_ms": round(lat.min(), 1),
        "expected_msgs": expected, "received_msgs": received,
        "loss_rate_pct": round(100 * (expected - received) / expected, 2) if expected else 0,
    }
    print(json.dumps(stats, indent=2))
    os.makedirs("output", exist_ok=True)
    with open("output/latency_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.figure(figsize=(7, 4))
    plt.hist(lat, bins=40)
    plt.axvline(lat.quantile(.95), color="r", ls="--", label="P95")
    plt.xlabel("Do tre end-to-end (ms)"); plt.ylabel("So ban tin"); plt.legend()
    plt.tight_layout(); plt.savefig("output/latency_hist.png", dpi=130)
    db.close()


if __name__ == "__main__":
    main()
