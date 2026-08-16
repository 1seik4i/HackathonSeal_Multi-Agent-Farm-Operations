# TV1 — Giải thích chi tiết luồng xử lý dữ liệu IoT

## Mục đích

Tài liệu này giải thích **chính xác** dữ liệu IoT đi qua những đâu, mỗi bước làm gì,
input là gì, output là gì, và các công cụ TV1 đã tạo ra hoạt động như thế nào.

---

## Tổng quan luồng dữ liệu

```
┌─────────────────┐
│  IoT Sensor     │  Cảm biến thật hoặc Simulator
│  (6 thiết bị)   │  gửi raw JSON qua MQTT hoặc HTTP
└───────┬─────────┘
        │
        │  Raw JSON payload
        │  VD: {"device_id":"SOIL_01","timestamp":"2026-08-16T09:00:00Z","metrics":{"soil_moisture":27.5}}
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BƯỚC 1: mqtt_client.py → _normalize()                            │
│  ─────────────────────────────────────────                         │
│  INPUT:  Raw JSON (nhiều format khác nhau)                        │
│  CÔNG VIỆC:                                                        │
│    • device_id / device / device_code  →  device_code              │
│    • "2026-08-16T09:00:00Z" (string)   →  1786845600.0 (float)    │
│    • Flat payload (không có key metrics) →  metrics dict           │
│  OUTPUT: TelemetryMessage (Pydantic model chuẩn)                   │
└───────┬─────────────────────────────────────────────────────────────┘
        │
        │  TelemetryMessage
        │  {"device_code":"SOIL_01","timestamp":1786845600.0,"metrics":{"soil_moisture":27.5}}
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BƯỚC 2: data_processor.py → process()                             │
│  ─────────────────────────────────────────                         │
│  INPUT:  TelemetryMessage dict                                     │
│                                                                     │
│  2a. VALIDATE                                                       │
│      Kiểm tra: device_code hợp lệ? metrics không rỗng? timestamp? │
│                                                                     │
│  2b. RANGE CHECK                                                    │
│      soil_moisture: 27.5 → trong ngưỡng 0-100%? ✅                 │
│      Nếu ngoài → clamp về biên (VD: 120 → 100)                    │
│                                                                     │
│  2c. FRESHNESS                                                      │
│      now - timestamp <= 300s? → FRESH                               │
│      now - timestamp > 300s?  → STALE                               │
│      timestamp = null?        → MISSING                             │
│                                                                     │
│  2d. ANOMALY DETECTION                                              │
│      Ngưỡng cảnh báo hẹp hơn (VD: soil_moisture < 10 hoặc > 90)  │
│      Pump flow_rate = 0? → WARNING                                  │
│                                                                     │
│  OUTPUT: ProcessedTelemetry dict                                    │
└───────┬─────────────────────────────────────────────────────────────┘
        │
        │  ProcessedTelemetry
        │  {"device_code":"SOIL_01","timestamp":1786845600.0,
        │   "metrics":{"soil_moisture":27.5,"temperature":31.2},
        │   "quality":{"freshness":"FRESH","anomalies":[],"valid":true},
        │   "received_at":1786845601.0}
        │
        ├────────────────────┐
        ▼                    ▼
┌───────────────┐    ┌───────────────┐
│ SQLite (TV3)  │    │ MongoDB (TV1) │
│ storage.py    │    │ mongo_storage │
│ farmops.db    │    │ Atlas cloud   │
└───────┬───────┘    └───────┬───────┘
        │                    │
        └────────┬───────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  TV2: AI Agents │
        │  agents.py      │
        │  Quyết định:    │
        │  IRRIGATE hoặc  │
        │  FIELD_TASK      │
        └─────────────────┘
```

---

## Chi tiết từng file và chức năng

### 1. `mqtt_client.py` — Nhận và chuẩn hoá dữ liệu

**Vị trí:** `src/mqtt_client.py`

**Chức năng:** Nhận raw JSON từ MQTT broker, chuẩn hoá về format chung.

**INPUT (3 dạng raw payload mà BTC có thể gửi):**

```json
// Dạng 1: device_id + ISO-8601 timestamp
{"device_id": "SOIL_01", "timestamp": "2026-08-16T09:00:00Z", "metrics": {"soil_moisture": 27.5}}

// Dạng 2: device_code + float timestamp
{"device_code": "SOIL_01", "timestamp": 1786845600.0, "metrics": {"soil_moisture": 27.5}}

// Dạng 3: Flat payload (không có key "metrics")
{"device_code": "SOIL_01", "soil_moisture": 27.5, "temperature": 31.2}
```

**OUTPUT (luôn giống nhau — TelemetryMessage):**

```json
{
    "device_code": "SOIL_01",
    "timestamp": 1786845600.0,
    "metrics": {"soil_moisture": 27.5, "temperature": 31.2}
}
```

---

### 2. `data_processor.py` — Pipeline xử lý dữ liệu

**Vị trí:** `src/data_processor.py`

**Chức năng:** Validate, kiểm tra ngưỡng, tính freshness, phát hiện anomaly.

**INPUT:** TelemetryMessage dict (output của bước 1)

**OUTPUT (ProcessedTelemetry):**

```json
{
    "device_code": "SOIL_01",
    "timestamp": 1786845600.0,
    "metrics": {
        "soil_moisture": 27.5,
        "temperature": 31.2
    },
    "quality": {
        "freshness": "FRESH",
        "anomalies": [],
        "out_of_range": [],
        "valid": true
    },
    "received_at": 1786845601.0,
    "raw_payload": { ... }
}
```

**Bảng ngưỡng sensor (Range Check):**

| Device | Metric | Min | Max | Đơn vị | Cảnh báo khi |
|---|---|---|---|---|---|
| SOIL_01 | soil_moisture | 0 | 100 | % | < 10 hoặc > 90 |
| SOIL_01 | temperature | -10 | 60 | °C | < 0 hoặc > 50 |
| WEATHER_01 | temperature | -20 | 55 | °C | < -10 hoặc > 50 |
| WEATHER_01 | humidity | 0 | 100 | % | < 10 hoặc > 95 |
| PUMP_01 | flow_rate | 0 | 200 | L/min | < 1 hoặc > 150 |
| PUMP_01 | power | 0 | 5000 | W | < 50 hoặc > 4000 |
| PH_01 | ph | 0 | 14 | - | < 4 hoặc > 10 |
| TANK_01 | level | 0 | 100 | % | < 5 hoặc > 95 |
| SUN_01 | lux | 0 | 150000 | lx | > 120000 |

---

### 3. `mongo_storage.py` — Lưu trữ MongoDB Atlas

**Vị trí:** `src/mongo_storage.py`

**Chức năng:** Lưu ProcessedTelemetry vào MongoDB cloud, cung cấp API đọc cho TV2.

**Các method:**

| Method | INPUT | OUTPUT | Mô tả |
|---|---|---|---|
| `ingest(data)` | ProcessedTelemetry dict | `_id` string | Lưu 1 document vào MongoDB |
| `latest_by_device()` | (không có) | `{device: {timestamp, metrics, quality}}` | Bản ghi mới nhất mỗi device |
| `get_history(device, limit)` | device_code, số lượng | List[dict] | N bản ghi gần nhất |
| `health_check()` | (không có) | `{status, documents}` | Kiểm tra kết nối |

---

### 4. `scripts/iot_simulator.py` — Công cụ tạo dữ liệu test

**Chức năng:** Giả lập sensor gửi dữ liệu để test hệ thống.

**5 chế độ chạy:**

| Mode | Lệnh chạy | Dữ liệu gửi | Test kịch bản |
|---|---|---|---|
| `http` | `python scripts/iot_simulator.py --mode http` | 6 sensor bình thường qua HTTP API | Không cần MQTT broker |
| `normal` | `python scripts/iot_simulator.py --mode normal` | 6 sensor bình thường qua MQTT | Kịch bản 1 (Tưới OK) |
| `stale` | `python scripts/iot_simulator.py --mode stale` | Timestamp cũ 10 phút | Kịch bản 2 (Stale) |
| `low-resource` | `python scripts/iot_simulator.py --mode low-resource` | Tank cạn + Pump hỏng | Kịch bản 3 (Thiếu tài nguyên) |
| `mixed` | `python scripts/iot_simulator.py --mode mixed` | Xoay vòng cả 3 | Test tổng hợp |

---

## So sánh INPUT vs OUTPUT qua 3 kịch bản demo

### Kịch bản 1: Tưới thành công

```
INPUT sensor:  soil_moisture = 27.5%, tank = 62%, pump = flow 18 L/min
                                    ▼
OUTPUT pipeline: freshness = FRESH, anomalies = [], valid = true
                                    ▼
TV2 quyết định: IRRIGATE → tạo IRRIGATION_PLAN → operator duyệt
```

### Kịch bản 2: Dữ liệu cũ

```
INPUT sensor:  soil_moisture = 22% nhưng timestamp cách đây 10 phút
                                    ▼
OUTPUT pipeline: freshness = STALE, valid = true
                                    ▼
TV2 quyết định: NEEDS_FIELD_CHECK → tạo FIELD_TASK kiểm tra sensor
```

### Kịch bản 3: Thiếu tài nguyên

```
INPUT sensor:  tank = 3% (cạn), pump flow_rate = 0, power = 0 (hỏng)
                                    ▼
OUTPUT pipeline: freshness = FRESH, anomalies = [tank, pump], valid = true
                                    ▼
TV2 quyết định: ResourceAgent CHẶN tưới → tạo FIELD_TASK + alert
```

---

## Cách chạy demo trực quan

Chạy lệnh sau để xem từng bước pipeline với input/output chi tiết:

```bash
python scripts/tv1_demo.py
```

Script sẽ hiển thị 5 demo:
1. Dữ liệu bình thường → FRESH
2. Dữ liệu cũ → STALE
3. Tank cạn + Pump hỏng → ANOMALY
4. Giá trị phi lý → CLAMP
5. Kiểm tra MongoDB Atlas

Mỗi demo in ra INPUT và OUTPUT chi tiết tại từng bước xử lý.
