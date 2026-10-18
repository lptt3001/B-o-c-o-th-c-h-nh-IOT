"""Subscribe MQTT -> validate -> ghi InfluxDB (bucket iot_raw).

Chay: python collector/collector.py
"""
import json
import logging
import os
import time

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()
BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = os.getenv("MQTT_TOPIC", "iot/b23dccn856/lab2/+/telemetry")
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
TOKEN = os.getenv("INFLUX_TOKEN", "my-super-token")
ORG = os.getenv("INFLUX_ORG", "iot")
BUCKET = os.getenv("RAW_BUCKET", "iot_raw")

# Khoang gia tri hop le cua cam bien (theo datasheet DHT22 / HC-SR04)
LIMITS = {"temperature": (-40, 80), "humidity": (0, 100), "distance_cm": (2, 400)}
REQUIRED = ["device_id", "ts", "temperature", "humidity", "distance_cm", "seq"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
db = InfluxDBClient(url=INFLUX_URL, token=TOKEN, org=ORG)
write_api = db.write_api(write_options=SYNCHRONOUS)

last_seq = {}
stats = {"ok": 0, "invalid": 0, "lost": 0, "duplicate": 0, "db_error": 0}
write_ms_samples = []


def validate(d):
    """Tra ve (hop_le, ly_do)."""
    if not isinstance(d, dict):
        return False, "payload khong phai object"
    missing = [k for k in REQUIRED if k not in d]
    if missing:
        return False, f"thieu truong {missing}"
    if not isinstance(d["ts"], (int, float)) or d["ts"] < 1_700_000_000_000:
        return False, "ts khong hop le (can epoch ms)"
    for k, (lo, hi) in LIMITS.items():
        v = d[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False, f"{k} khong phai so"
        if not lo <= v <= hi:
            return False, f"{k}={v} ngoai khoang [{lo},{hi}]"
    return True, ""


def on_connect(client, userdata, flags, reason_code, properties=None):
    logging.info("MQTT connected: %s", reason_code)
    client.subscribe(TOPIC, qos=1)  # subscribe lai moi lan (re)connect


def on_message(client, userdata, msg):
    recv_ms = int(time.time() * 1000)
    try:
        d = json.loads(msg.payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        stats["invalid"] += 1
        logging.warning("JSON loi: %r", msg.payload[:80])
        return

    ok, why = validate(d)
    if not ok:
        stats["invalid"] += 1
        logging.warning("Bo ban tin: %s", why)
        return

    # Phat hien mat goi / trung lap / thiet bi khoi dong lai qua 'seq'
    dev, seq = d["device_id"], int(d["seq"])
    prev = last_seq.get(dev)
    if prev is not None:
        if seq == prev:
            stats["duplicate"] += 1
        elif seq > prev + 1:
            stats["lost"] += seq - prev - 1
        # seq < prev: thiet bi reset -> khong tinh la mat goi
    last_seq[dev] = seq

    location = msg.topic.split("/")[3] if msg.topic.count("/") >= 4 else "unknown"
    latency_ms = recv_ms - int(d["ts"])
    point = (
        Point("environment")
        .tag("device_id", dev)
        .tag("location", location)
        .field("temperature", float(d["temperature"]))
        .field("humidity", float(d["humidity"]))
        .field("distance_cm", float(d["distance_cm"]))
        .field("rssi", int(d.get("rssi", 0)))
        .field("seq", seq)
        .field("latency_ms", float(latency_ms))
        # Dung ts cua thiet bi: cung (measurement, tags, ts) se ghi de -> khong bi nhan doi
        .time(int(d["ts"]), WritePrecision.MS)
    )
    t0 = time.perf_counter()
    try:
        write_api.write(bucket=BUCKET, record=point)
    except Exception as exc:  # loi mang/DB khong lam chet collector
        stats["db_error"] += 1
        logging.error("Ghi DB that bai: %s", exc)
        return
    write_ms = (time.perf_counter() - t0) * 1000
    write_ms_samples.append(write_ms)
    stats["ok"] += 1
    logging.info("seq=%s latency=%dms db_write=%.1fms | %s", seq, latency_ms, write_ms, stats)


def main():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"collector-{os.getpid()}",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect(BROKER, PORT, keepalive=60)
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        total = stats["ok"] + stats["lost"]
        logging.info("Dung. Tong ket: %s | ti le mat goi=%.2f%%", stats,
                     100 * stats["lost"] / total if total else 0)
        if write_ms_samples:
            logging.info("Ghi DB trung binh %.1f ms", sum(write_ms_samples) / len(write_ms_samples))
        db.close()


if __name__ == "__main__":
    main()
