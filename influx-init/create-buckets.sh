#!/bin/bash
# Chay tu dong sau khi InfluxDB khoi tao lan dau: bucket du lieu da xu ly, giu 30 ngay
influx bucket create --name iot_clean --org iot --retention 30d \
  --host http://localhost:8086 --token "${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN}"
