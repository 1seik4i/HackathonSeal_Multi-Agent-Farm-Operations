# FarmOps AI — Team 2

## Production MQTT backend

The live broker was verified as MQTT over secure WebSocket. The backend connects to `mqtt-hackathon.lexatek.vn:443`, subscribes to `hackathon/team_2/test/telemetry`, and automatically reconnects with exponential backoff.

The contest payload contains a six-device batch:

```json
{
  "epoch": 1786840000,
  "devices": [
    {"deviceCode": "SOIL_01", "status": "ok", "metrics": {"soil_moisture": 32}}
  ]
}
```

Each batch is validated, split into device readings, enriched with freshness/range/anomaly quality metadata, and persisted with MQTT topic and payload provenance. Invalid device records are rejected independently without discarding valid records from the same batch.

Operational endpoints:

- `GET /api/health`: compact API and MQTT readiness.
- `GET /api/mqtt/status`: connection, subscription, counters and last-message diagnostics; credentials are never returned.
- `POST /api/mqtt/reconnect`: safely rebuild and restart the MQTT client.
- `GET /api/telemetry/status`: coverage, freshness, MQTT source count and per-device quality.
- `GET /api/telemetry/latest`: latest reading and provenance for all devices.
- `GET /api/telemetry/history?device_id=SOIL_01&limit=30`: retained device history.

Copy `.env.example` to `.env`, keep the provided username/password locally, and use the verified `MQTT_ENDPOINT_*`, `MQTT_TRANSPORT`, WebSocket path and TLS settings from the example.

Multi-Agent Smart Agriculture cho đề thi: MQTT → Agent coordination → Tool/API → Verification.

## Bảo mật MQTT

Ảnh credential chỉ cung cấp topic và username; **không commit key/password**. Tạo `.env` từ `.env.example`, rồi dán đầy đủ broker host, password và test key nếu cổng thông tin cung cấp key riêng. `.env` đã nằm trong `.gitignore`.

```powershell
Copy-Item .env.example .env
```

Giữ topic đúng theo portal của BTC. Trong code, MQTT chỉ subscribe telemetry; không publish ngược lên topic thi khi chưa có yêu cầu rõ ràng.

## Chạy local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn src.app:app --reload
```

Mở <http://127.0.0.1:8000>. Nếu chưa có credential đầy đủ, API vẫn chạy; hãy gửi telemetry demo qua `POST /api/telemetry`.

## Chạy bằng Docker

Docker image không chứa `.env`, database local hay virtual environment. Tạo file cấu hình cục bộ trước:

```powershell
Copy-Item .env.example .env
# Điền MQTT_BROKER_HOST, MQTT_PASSWORD và các giá trị do BTC cung cấp.
docker-compose up --build -d
```

Mở <http://127.0.0.1:8000>. SQLite được lưu trong Docker volume `farmops-data`, nên dữ liệu không mất khi container được tạo lại.

```powershell
docker-compose ps
docker-compose logs -f farmops-ai
docker-compose down
```

## MQTT payload mong đợi

```json
{
  "device_code": "SOIL_01",
  "timestamp": 1760000000,
  "metrics": {"soil_moisture": 27, "temperature": 31.2}
}
```

Thiết bị hợp lệ: `SOIL_01`, `WEATHER_01`, `PUMP_01`, `PH_01`, `TANK_01`, `SUN_01`.

## API/Tool

- `POST /api/telemetry`: nạp telemetry demo.
- `GET /api/telemetry/latest`: xem bằng chứng IoT theo thiết bị.
- `POST /api/coordinate`: Coordinator chạy Field IoT → Irrigation → Resource → Action Agent.
- `GET /api/actions/{id}`: truy xuất action; Action Agent gọi lại để verification.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

## Agent Settings và AI Operations

- Mở `Agent Settings`, chọn provider/model, nhập key cho từng agent và bấm **Test connection**. Key chỉ tồn tại ở backend runtime hoặc biến môi trường; API không trả key lại và giao diện không dùng localStorage.
- `AI Operations` chỉ chạy khi có ít nhất 3 agent `READY` và đủ telemetry **MQTT LIVE** mới từ SOIL_01, WEATHER_01, PUMP_01, PH_01, TANK_01.
- Scenario là ràng buộc vận hành, không phải số liệu cảm biến. Hệ thống lưu evidence/provenance của snapshot; nếu dữ liệu stale, missing, DEMO/API hoặc agent chưa sẵn sàng, backend trả lỗi rõ ràng thay vì tạo kết quả AI giả.
- Action tưới tạo ở trạng thái `PENDING_APPROVAL`. `VERIFIED` chỉ được gán khi sau khi duyệt có MQTT telemetry mới từ PUMP_01 với `flow_rate > 0`.
