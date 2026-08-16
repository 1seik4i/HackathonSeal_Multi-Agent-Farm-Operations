# FarmOps AI — Team 2

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
