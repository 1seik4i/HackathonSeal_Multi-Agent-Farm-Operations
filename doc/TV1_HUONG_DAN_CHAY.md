# TV1 — IoT & Data Engineer: Hướng dẫn chạy

## 1. Cài đặt môi trường

```bash
# Clone repo và chuyển sang nhánh TV1
git checkout feature/iot-data

# Cài đặt dependencies
pip install -r requirements.txt
```

---

## 2. Cấu hình `.env`

Tạo file `.env` ở thư mục gốc project (copy từ `.env.example`):

```env
# MQTT Broker (lấy từ BTC)
MQTT_BROKER_HOST=replace-with-broker-host
MQTT_BROKER_PORT=1883
MQTT_USERNAME=TEAM_2
MQTT_PASSWORD=replace-with-full-password
MQTT_TOPIC=hackathon/team_2/test/telemetry
MQTT_TLS=false

# API Server
API_HOST=127.0.0.1
API_PORT=8000

# Data quality
STALE_AFTER_SECONDS=300

# SQLite (TV3)
DATABASE_PATH=farmops.db

# MongoDB Atlas (TV1)
MONGODB_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=farmops
```

> ⚠️ **Lưu ý:** KHÔNG commit file `.env` lên Git. File này đã có trong `.gitignore`.

---

## 3. Chạy API Server

```bash
python -m src.app
```

Server sẽ chạy tại `http://127.0.0.1:8000`. Kiểm tra health:

```bash
curl http://127.0.0.1:8000/api/health
```

---

## 4. Chạy IoT Simulator

Simulator có 5 chế độ để test các kịch bản khác nhau:

### 4.1. Gửi dữ liệu qua HTTP API (không cần MQTT broker)

```bash
python scripts/iot_simulator.py --mode http
```

Dữ liệu sẽ POST trực tiếp vào `http://127.0.0.1:8000/api/telemetry`.

### 4.2. Gửi dữ liệu qua MQTT Broker

> Cần có `MQTT_BROKER_HOST` và `MQTT_PASSWORD` trong `.env`.

```bash
# Dữ liệu bình thường từ 6 sensor (mỗi 5 giây)
python scripts/iot_simulator.py --mode normal

# Dữ liệu cũ 10 phút — test Kịch bản 2 (Stale Data)
python scripts/iot_simulator.py --mode stale

# Tank cạn + Pump hỏng — test Kịch bản 3 (Low Resource)
python scripts/iot_simulator.py --mode low-resource

# Xoay vòng cả 3 kịch bản
python scripts/iot_simulator.py --mode mixed
```

### 4.3. Tuỳ chỉnh Simulator

```bash
# Gửi 10 lần, mỗi 3 giây
python scripts/iot_simulator.py --mode normal --count 10 --interval 3

# Chỉ định broker thủ công (không dùng .env)
python scripts/iot_simulator.py --mode normal --host broker.example.com --password mypass

# Xem tất cả tuỳ chọn
python scripts/iot_simulator.py --help
```

---

## 5. Chạy Unit Tests

```bash
# Chạy tất cả tests của TV1
python -m pytest tests/test_mqtt_parser.py tests/test_data_processor.py -v

# Chạy riêng test MQTT parser
python -m pytest tests/test_mqtt_parser.py -v

# Chạy riêng test Data Processor
python -m pytest tests/test_data_processor.py -v
```

Kết quả mong đợi: **33 passed** ✅

---

## 6. Kiểm tra dữ liệu

### 6.1. Qua API

```bash
# Xem telemetry mới nhất của tất cả sensor
curl http://127.0.0.1:8000/api/telemetry/latest

# Nạp dữ liệu mẫu nhanh (không cần simulator)
curl -X POST http://127.0.0.1:8000/api/demo/seed

# Chạy AI Coordinator (TV2) trên dữ liệu hiện có
curl -X POST http://127.0.0.1:8000/api/coordinate \
  -H "Content-Type: application/json" \
  -d '{"request": "Kiểm tra và đề xuất tưới cho Khu A"}'
```

### 6.2. Qua MongoDB Atlas

1. Vào [MongoDB Atlas](https://cloud.mongodb.com) → Project **smart_iot** → Cluster **farmops-cluster**
2. Bấm **Browse Collections** → Database **farmops** → Collection **telemetry**
3. Xem các document đã được lưu với cấu trúc:

```json
{
  "device_code": "SOIL_01",
  "timestamp": 1723766400.0,
  "metrics": { "soil_moisture": 27.5, "temperature": 31.2 },
  "quality": {
    "freshness": "FRESH",
    "anomalies": [],
    "out_of_range": [],
    "valid": true
  },
  "received_at": 1723766401.0
}
```

---

## 7. Cấu trúc file TV1

```
team-2_su2026/
├── src/
│   ├── data_processor.py    ← Pipeline xử lý raw data (Validate → Range → Freshness → Anomaly)
│   ├── mongo_storage.py     ← Lưu telemetry vào MongoDB Atlas
│   └── mqtt_client.py       ← Nhận MQTT → normalize → pipeline → lưu DB
├── scripts/
│   └── iot_simulator.py     ← Simulator 5 modes cho test
├── tests/
│   ├── test_mqtt_parser.py      ← 10 tests cho parser
│   └── test_data_processor.py   ← 23 tests cho pipeline
└── doc/
    └── payload_samples.json ← Mẫu payload tham khảo cho cả nhóm
```

---

## 8. Troubleshooting

| Lỗi | Nguyên nhân | Cách sửa |
|---|---|---|
| `ModuleNotFoundError: paho` | Chưa cài dependencies | `pip install -r requirements.txt` |
| `MQTT is not configured` | Thiếu `MQTT_BROKER_HOST` trong `.env` | Điền broker host hoặc dùng `--mode http` |
| `MongoDB connection failed` | Sai `MONGODB_URI` hoặc chưa whitelist IP | Kiểm tra Atlas → Network Access → Allow `0.0.0.0/0` |
| `Unknown device_code` | Payload có device không hợp lệ | Chỉ chấp nhận: `SOIL_01`, `WEATHER_01`, `PUMP_01`, `PH_01`, `TANK_01`, `SUN_01` |
| Timestamp bị `STALE` | `timestamp` cách hiện tại > 300 giây | Điều chỉnh `STALE_AFTER_SECONDS` trong `.env` |
