"""App giam sat IoT bang Streamlit (doc truc tiep tu InfluxDB).

Chay: streamlit run app/app.py
"""
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()
URL = os.getenv("INFLUX_URL", "http://localhost:8086")
TOKEN = os.getenv("INFLUX_TOKEN", "my-super-token")
ORG = os.getenv("INFLUX_ORG", "iot")
RAW = os.getenv("RAW_BUCKET", "iot_raw")
CLEAN = os.getenv("CLEAN_BUCKET", "iot_clean")

st.set_page_config(page_title="IoT Monitor", page_icon="🌡️", layout="wide")


@st.cache_resource
def client():
    return InfluxDBClient(url=URL, token=TOKEN, org=ORG)


def query(bucket, measurement, fields, minutes):
    cond = " or ".join(f'r._field == "{f}"' for f in fields)
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "{measurement}" and ({cond}))
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    try:
        res = client().query_api().query_data_frame(flux)
    except Exception as exc:
        st.error(f"Loi truy van InfluxDB: {exc}")
        return pd.DataFrame()
    if isinstance(res, list):
        res = pd.concat(res) if res else pd.DataFrame()
    if res.empty:
        return res
    return res.rename(columns={"_time": "time"}).set_index("time").sort_index()


st.title("🌡️ Giám sát IoT: ESP32 → MQTT → InfluxDB")
minutes = st.sidebar.slider("Khoảng thời gian (phút)", 5, 360, 60)
refresh = st.sidebar.selectbox("Tự làm mới (giây)", [5, 10, 30], index=0)


@st.fragment(run_every=refresh)
def live():
    raw = query(RAW, "environment",
                ["temperature", "humidity", "distance_cm", "latency_ms", "rssi", "seq"], minutes)
    if raw.empty:
        st.warning("Chưa có dữ liệu. Hãy chạy collector và simulation trên Wokwi.")
        return
    last = raw.iloc[-1]
    c = st.columns(5)
    c[0].metric("Nhiệt độ (°C)", f"{last.temperature:.1f}")
    c[1].metric("Độ ẩm (%)", f"{last.humidity:.1f}")
    c[2].metric("Khoảng cách (cm)", f"{last.distance_cm:.0f}")
    c[3].metric("Độ trễ gần nhất (ms)", f"{last.latency_ms:.0f}")
    c[4].metric("RSSI (dBm)", f"{last.rssi:.0f}")

    expected = int(raw.seq.max() - raw.seq.min() + 1)
    loss = 100 * (expected - raw.seq.nunique()) / expected if expected else 0
    s = st.columns(4)
    s[0].metric("Số mẫu", len(raw))
    s[1].metric("Độ trễ TB (ms)", f"{raw.latency_ms.mean():.0f}")
    s[2].metric("Độ trễ P95 (ms)", f"{raw.latency_ms.quantile(.95):.0f}")
    s[3].metric("Tỉ lệ mất gói (%)", f"{loss:.2f}")

    st.subheader("Dữ liệu thô (real-time)")
    a, b, d = st.columns(3)
    a.line_chart(raw[["temperature"]])
    b.line_chart(raw[["humidity"]])
    d.line_chart(raw[["distance_cm"]])
    st.subheader("Độ trễ end-to-end (ms)")
    st.line_chart(raw[["latency_ms"]])

    clean = query(CLEAN, "environment_clean",
                  ["temperature", "temperature_roll5", "humidity", "humidity_roll5"], minutes)
    st.subheader("Dữ liệu đã tiền xử lý")
    if clean.empty:
        st.info("Chưa có dữ liệu trong iot_clean. Chạy preprocess/preprocess.py trước.")
    else:
        st.line_chart(clean[["temperature", "temperature_roll5"]])
        st.line_chart(clean[["humidity", "humidity_roll5"]])


live()
