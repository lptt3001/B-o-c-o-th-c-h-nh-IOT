# Bài thực hành 2: Thu thập, lưu trữ và tiền xử lý dữ liệu IoT

Sinh viên: Lê Phạm Thành Trung - B23DCCN856 | Học phần: IoT và Ứng dụng (INT14149)

Pipeline: **ESP32 (Wokwi) → MQTT (broker.hivemq.com) → collector.py → InfluxDB (`iot_raw`) → preprocess.py → InfluxDB (`iot_clean`) → Grafana / Streamlit**

## Cấu trúc
```
firmware/      sketch.ino, diagram.json, libraries.txt (dán vào Wokwi)
collector/     collector.py   subscribe + validate + ghi InfluxDB
preprocess/    preprocess.py  làm sạch, outlier, resample, đặc trưng, chuẩn hóa
analysis/      latency_report.py  thống kê độ trễ, tỉ lệ mất gói
app/           app.py         ứng dụng Streamlit
grafana/       provisioning + dashboard tự nạp
influx-init/   script tạo bucket iot_clean
docker-compose.yml, requirements.txt, .env.example
```

## Yêu cầu
Docker Desktop, Python 3.10+, tài khoản Wokwi (miễn phí).

## Chạy
1. **Cấu hình**: `cp .env.example .env` (Windows: `copy .env.example .env`). Nên đổi `MQTT_TOPIC` và topic trong `sketch.ino` thành chuỗi riêng của bạn (broker công cộng ai cũng đọc được).
2. **Hạ tầng**: `docker compose up -d`. InfluxDB: http://localhost:8086 (admin / admin12345), Grafana: http://localhost:3000 (admin / admin). Bucket `iot_raw` (retention 7 ngày) và `iot_clean` (30 ngày) được tạo tự động. Nếu `iot_clean` chưa có, chạy:
   `docker exec iot-influxdb influx bucket create -n iot_clean -o iot -r 30d -t my-super-token`
3. **Thư viện**: `pip install -r requirements.txt`
4. **Collector**: `python collector/collector.py` (để chạy nền).
5. **Thiết bị**: tạo project ESP32 trên Wokwi, dán `firmware/sketch.ino`, `diagram.json`, `libraries.txt`, bấm Start. Collector sẽ in log `seq=... latency=...`.
6. **Chạy 30–60 phút** để có đủ dữ liệu. Tạo tình huống thử: trên Wokwi kéo nhiệt độ DHT22 đột ngột (outlier); dừng simulation vài phút (missing data).
7. **Tiền xử lý**: `python preprocess/preprocess.py --hours 2 --window 30s` (thêm `--method zscore` để so sánh). Kết quả ở `output/`.
8. **Độ trễ**: `python analysis/latency_report.py --hours 2`
9. **Dashboard**: Grafana → Dashboards → "IoT Lab 2 - Monitoring". **App**: `streamlit run app/app.py` (http://localhost:8501).

## Schema InfluxDB
| Bucket | Measurement | Tags | Fields |
|---|---|---|---|
| iot_raw | environment | device_id, location | temperature, humidity, distance_cm, rssi, seq, latency_ms |
| iot_clean | environment_clean | device_id, location | temperature, humidity, distance_cm, *_roll5, *_delta, *_z, *_mm |

Timestamp lấy từ `ts` của thiết bị (epoch ms, NTP) nên bản tin gửi lặp (QoS 1) ghi đè đúng điểm cũ, không bị nhân đôi.

## Định dạng bản tin
Topic: `iot/b23dccn856/lab2/<location>/telemetry`
```json
{"device_id":"esp32-b23dccn856","ts":1760770000000,"temperature":18.2,"humidity":34.5,"distance_cm":201.0,"rssi":-60,"seq":42,"uptime_s":210}
```

## Lưu ý
- Độ trễ = thời điểm collector nhận − `ts` của ESP32; phụ thuộc độ lệch đồng hồ giữa hai bên.
- Không commit `.env`.
