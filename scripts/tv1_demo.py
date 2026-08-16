#!/usr/bin/env python
"""TV1 Pipeline Demo — Trực quan hoá từng bước xử lý dữ liệu IoT.

Chạy: python scripts/tv1_demo.py

Script này mô phỏng toàn bộ luồng xử lý của TV1, in ra INPUT và OUTPUT
chi tiết tại MỖI BƯỚC để bạn hiểu chính xác dữ liệu đi qua đâu và
biến đổi như thế nào.
"""

from __future__ import annotations

import json
import sys
import time
import os

# Fix encoding for Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.data_processor import IoTDataProcessor
from src.mqtt_client import MQTTIngestionClient
from src.settings import settings
import paho.mqtt.client as mqtt
import uuid


# ─── Helpers ──────────────────────────────────────────────────────────
COLORS = {
    "HEADER": "\033[95m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "RED": "\033[91m",
    "BOLD": "\033[1m",
    "DIM": "\033[2m",
    "END": "\033[0m",
}

def c(text, color):
    return f"{COLORS[color]}{text}{COLORS['END']}"

def banner(title, char="═"):
    width = 70
    print(f"\n{c(char * width, 'CYAN')}")
    print(c(f"  {title}", "BOLD"))
    print(c(char * width, "CYAN"))

def step_header(step_num, title):
    print(f"\n{c(f'  ▶ BƯỚC {step_num}: {title}', 'YELLOW')}")
    print(c("  " + "─" * 60, "DIM"))

def show_json(label, data, color="GREEN"):
    print(f"  {c(label, color)}")
    formatted = json.dumps(data, indent=4, ensure_ascii=False, default=str)
    for line in formatted.split("\n"):
        print(f"    {c(line, 'DIM')}")

def show_result(label, value, color="GREEN"):
    print(f"  {c(label, 'BOLD')} {c(str(value), color)}")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 1: Dữ liệu bình thường (FRESH + trong ngưỡng)
# ═══════════════════════════════════════════════════════════════════════
def demo_normal():
    banner("DEMO 1: DỮ LIỆU BÌNH THƯỜNG (Kịch bản 1 — Tưới thành công)")
    
    # --- Raw MQTT payload (đây là dữ liệu thô từ sensor) ---
    raw_mqtt = {
        "device_id": "SOIL_01",
        "timestamp": "2026-08-16T09:00:00+07:00",
        "metrics": {
            "soil_moisture": 27.5,
            "temperature": 31.2
        }
    }
    
    step_header(1, "RAW MQTT PAYLOAD (Input gốc từ sensor)")
    print(f"  {c('Nguồn:', 'BOLD')} Sensor SOIL_01 gửi qua MQTT broker")
    print(f"  {c('Topic:', 'BOLD')} {settings.mqtt_topic}")
    show_json("📥 INPUT (raw JSON từ MQTT):", raw_mqtt, "RED")
    
    # --- Normalize ---
    step_header(2, "NORMALIZE (_normalize trong mqtt_client.py)")
    print(f"  {c('Chức năng:', 'BOLD')} Chuyển đổi các định dạng khác nhau về chuẩn chung")
    print(f"  • device_id → device_code")
    print(f"  • ISO-8601 string → float timestamp")
    print(f"  • Flat payload → metrics dict")
    
    normalized_list = MQTTIngestionClient._normalize(raw_mqtt)
    normalized = normalized_list[0]
    normalized_dict = normalized.model_dump()
    show_json("📤 OUTPUT (TelemetryMessage chuẩn):", normalized_dict, "GREEN")
    
    show_result("✓ device_id → device_code:", normalized.device_code)
    show_result("✓ ISO-8601 → float:", f"{raw_mqtt['timestamp']} → {normalized.timestamp}")
    
    # --- Data Processing Pipeline ---
    step_header(3, "DATA PROCESSING PIPELINE (data_processor.py)")
    processor = IoTDataProcessor(stale_after_seconds=300)
    
    print(f"\n  {c('3a. VALIDATE — Kiểm tra payload hợp lệ', 'CYAN')}")
    errors = processor.validate_payload(normalized_dict)
    show_result("  Kết quả:", "✅ VALID (không có lỗi)" if not errors else f"❌ {errors}",
                "GREEN" if not errors else "RED")
    
    print(f"\n  {c('3b. RANGE CHECK — Kiểm tra giá trị trong ngưỡng vật lý', 'CYAN')}")
    range_result = processor.check_ranges(normalized.device_code, normalized.metrics)
    show_json("  Ngưỡng cho SOIL_01:", {
        "soil_moisture": "0 – 100 %",
        "temperature": "-10 – 60 °C"
    }, "BLUE")
    show_result("  Trong ngưỡng:", [f"{v['metric']}={v['value']}" for v in range_result["valid"]])
    show_result("  Ngoài ngưỡng:", range_result["out_of_range"] or "Không có ✅")
    
    print(f"\n  {c('3c. FRESHNESS — Kiểm tra độ mới dữ liệu', 'CYAN')}")
    freshness = processor.compute_freshness(normalized.timestamp)
    age = time.time() - normalized.timestamp
    show_result("  Tuổi dữ liệu:", f"{age:.0f} giây")
    show_result("  Ngưỡng stale:", f"{processor.stale_after_seconds} giây")
    show_result("  Kết quả:", freshness, "GREEN" if freshness == "FRESH" else "RED")
    
    print(f"\n  {c('3d. ANOMALY DETECTION — Phát hiện bất thường', 'CYAN')}")
    anomalies = processor.detect_anomalies(normalized.device_code, normalized.metrics)
    show_result("  Kết quả:", "Không có anomaly ✅" if not anomalies else anomalies,
                "GREEN" if not anomalies else "YELLOW")
    
    print(f"\n  {c('3e. OUTPUT — Kết quả cuối cùng (ProcessedTelemetry)', 'CYAN')}")
    processed = processor.process(normalized_dict)
    show_json("📤 FINAL OUTPUT cho TV2 + MongoDB:", processed, "GREEN")
    
    # --- Summary ---
    print(f"\n  {c('TÓM TẮT LUỒNG:', 'BOLD')}")
    print(f"  Raw MQTT → Normalize → Validate ✅ → Range Check ✅ → Freshness: {freshness} → Anomaly: None")
    print(f"  → {c('Lưu SQLite (TV3)', 'BLUE')} + {c('Lưu MongoDB (TV1)', 'GREEN')}")
    print(f"  → {c('Sẵn sàng cho TV2 (AI Agents)', 'YELLOW')}")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 2: Dữ liệu cũ (STALE)
# ═══════════════════════════════════════════════════════════════════════
def demo_stale():
    banner("DEMO 2: DỮ LIỆU CŨ (Kịch bản 2 — Stale Data)")
    
    stale_ts = time.time() - 600  # 10 phút trước
    raw = {
        "device_code": "SOIL_01",
        "timestamp": stale_ts,
        "metrics": {"soil_moisture": 22.0, "temperature": 33.0}
    }
    
    step_header(1, "INPUT — Dữ liệu có timestamp 10 phút trước")
    show_json("📥 Payload:", raw, "RED")
    
    processor = IoTDataProcessor(stale_after_seconds=300)
    
    step_header(2, "FRESHNESS CHECK")
    freshness = processor.compute_freshness(raw["timestamp"])
    age = time.time() - raw["timestamp"]
    show_result("Tuổi dữ liệu:", f"{age:.0f} giây (~{age/60:.0f} phút)")
    show_result("Ngưỡng stale:", f"{processor.stale_after_seconds} giây (5 phút)")
    show_result("Kết quả:", f"⚠️ {freshness} — Dữ liệu đã cũ!", "RED")
    
    step_header(3, "OUTPUT")
    processed = processor.process(raw)
    show_json("📤 ProcessedTelemetry:", processed, "YELLOW")
    
    print(f"\n  {c('HỆ QUẢ:', 'BOLD')}")
    print(f"  → TV2 nhận freshness = {c('STALE', 'RED')}")
    print(f"  → IrrigationPlanningAgent sẽ {c('KHÔNG tạo kế hoạch tưới', 'RED')}")
    print(f"  → Thay vào đó tạo {c('FIELD_TASK', 'YELLOW')} yêu cầu kiểm tra sensor ngoài hiện trường")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 3: Dữ liệu ngoài ngưỡng + anomaly
# ═══════════════════════════════════════════════════════════════════════
def demo_anomaly():
    banner("DEMO 3: DỮ LIỆU BẤT THƯỜNG (Kịch bản 3 — Tank cạn + Pump hỏng)")
    
    processor = IoTDataProcessor(stale_after_seconds=300)
    
    # --- Tank cạn ---
    print(f"\n{c('  ── Sensor TANK_01: Bồn nước gần cạn ──', 'RED')}")
    tank_raw = {
        "device_code": "TANK_01",
        "timestamp": time.time(),
        "metrics": {"level": 3.0}
    }
    show_json("📥 INPUT:", tank_raw, "RED")
    
    anomalies = processor.detect_anomalies("TANK_01", {"level": 3.0})
    show_json("⚠️ ANOMALY DETECTED:", anomalies, "YELLOW")
    
    tank_processed = processor.process(tank_raw)
    show_result("Quality:", tank_processed["quality"])
    
    # --- Pump hỏng ---
    print(f"\n{c('  ── Sensor PUMP_01: Bơm không hoạt động ──', 'RED')}")
    pump_raw = {
        "device_code": "PUMP_01",
        "timestamp": time.time(),
        "metrics": {"flow_rate": 0, "power": 0}
    }
    show_json("📥 INPUT:", pump_raw, "RED")
    
    anomalies = processor.detect_anomalies("PUMP_01", {"flow_rate": 0, "power": 0})
    show_json("⚠️ ANOMALY DETECTED:", anomalies, "YELLOW")
    
    pump_processed = processor.process(pump_raw)
    show_result("Quality:", pump_processed["quality"])
    
    print(f"\n  {c('HỆ QUẢ:', 'BOLD')}")
    print(f"  → TV2 nhận anomalies cho cả TANK_01 và PUMP_01")
    print(f"  → ResourceAgent sẽ {c('CHẶN tưới', 'RED')} vì tank < 25% và pump flow_rate = 0")
    print(f"  → FarmActionAgent tạo {c('FIELD_TASK', 'YELLOW')} kiểm tra + alert")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 4: Dữ liệu ngoài ngưỡng vật lý (bị clamp)
# ═══════════════════════════════════════════════════════════════════════
def demo_out_of_range():
    banner("DEMO 4: DỮ LIỆU NGOÀI NGƯỠNG VẬT LÝ (Bị Clamp)")
    
    raw = {
        "device_code": "SOIL_01",
        "timestamp": time.time(),
        "metrics": {"soil_moisture": 120.0, "temperature": -15.0}
    }
    
    step_header(1, "INPUT — Giá trị phi lý")
    show_json("📥 Payload:", raw, "RED")
    print(f"  {c('soil_moisture = 120% → vượt max 100%', 'RED')}")
    print(f"  {c('temperature = -15°C → dưới min -10°C', 'RED')}")
    
    processor = IoTDataProcessor(stale_after_seconds=300)
    
    step_header(2, "RANGE CHECK + CLAMP")
    range_result = processor.check_ranges("SOIL_01", raw["metrics"])
    show_json("Ngoài ngưỡng:", range_result["out_of_range"], "RED")
    
    step_header(3, "OUTPUT — Metrics đã được clamp về giá trị hợp lệ")
    processed = processor.process(raw)
    show_json("📤 ProcessedTelemetry:", {
        "metrics_TRƯỚC": raw["metrics"],
        "metrics_SAU": processed["metrics"],
        "quality": processed["quality"]
    }, "GREEN")
    print(f"  {c('soil_moisture: 120 → 100 (clamp về max)', 'YELLOW')}")
    print(f"  {c('temperature: -15 → -10 (clamp về min)', 'YELLOW')}")
    print(f"  {c('quality.valid = False (có dữ liệu bị clamp)', 'RED')}")


# ═══════════════════════════════════════════════════════════════════════
# DEMO 5: MongoDB storage check
# ═══════════════════════════════════════════════════════════════════════
def demo_mongodb():
    banner("DEMO 5: KIỂM TRA MONGODB ATLAS")
    
    if not settings.mongodb_uri:
        print(f"  {c('⚠️ MONGODB_URI chưa cấu hình trong .env → bỏ qua', 'YELLOW')}")
        return
    
    try:
        from src.mongo_storage import MongoTelemetryStore
        store = MongoTelemetryStore(settings.mongodb_uri, settings.mongodb_db_name)
        
        step_header(1, "HEALTH CHECK")
        health = store.health_check()
        show_json("📊 MongoDB status:", health, "GREEN" if health["status"] == "ok" else "RED")
        
        step_header(2, "GHI DỮ LIỆU TEST (Giả lập cả 6 sensors)")
        processor = IoTDataProcessor(stale_after_seconds=300)
        
        sensors = [
            ("SOIL_01", {"soil_moisture": 35.0, "temperature": 29.5}),
            ("WEATHER_01", {"temperature": 32.0, "humidity": 60.0}),
            ("PUMP_01", {"flow_rate": 120.0, "power": 1500.0}),
            ("PH_01", {"ph": 6.5}),
            ("TANK_01", {"level": 80.0}),
            ("SUN_01", {"lux": 50000.0})
        ]
        
        for device_code, metrics in sensors:
            test_data = processor.process({
                "device_code": device_code,
                "timestamp": time.time(),
                "metrics": metrics
            })
            store.ingest(test_data)
        
        print(f"  {c(f'✓ Đã ghi giả lập {len(sensors)} sensors vào MongoDB', 'GREEN')}")
        
        step_header(3, "ĐỌC LẠI — latest_by_device()")
        latest = store.latest_by_device()
        show_json("📤 Output (format cho TV2):", latest, "GREEN")
        
        step_header(4, "LỊCH SỬ — get_history('SOIL_01', limit=3)")
        history = store.get_history("SOIL_01", limit=3)
        show_json(f"📤 {len(history)} bản ghi gần nhất:", history, "BLUE")
        
        print(f"\n  {c('✅ MongoDB Atlas hoạt động tốt!', 'GREEN')}")
        
    except Exception as err:
        print(f"  {c(f'❌ Lỗi kết nối MongoDB: {err}', 'RED')}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN & LIVE MODE
# ═══════════════════════════════════════════════════════════════════════

def demo_live():
    step_header(1, "CHẾ ĐỘ LIVE DATA (HỨNG DỮ LIỆU TỪ MQTT THẬT)")
    print(f"  {c('Đang kết nối tới Broker:', 'CYAN')} {settings.mqtt_host}:{settings.mqtt_port}")
    
    if not settings.mqtt_host:
        print(f"  {c('❌ Lỗi: Chưa cấu hình MQTT_BROKER_HOST trong file .env', 'RED')}")
        return

    # Use a random client_id so we don't kick the main app off the broker
    client_id = f"tv1-demo-live-{uuid.uuid4().hex[:8]}"
    transport_protocol = "websockets" if settings.mqtt_port == 443 else "tcp"
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, transport=transport_protocol)
    
    if transport_protocol == "websockets":
        client.ws_set_options(path="/mqtt")
        
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_tls:
        client.tls_set()

    processor = IoTDataProcessor(stale_after_seconds=settings.stale_after_seconds)
    
    def on_connect(client_obj, userdata, flags, rc, properties):
        if rc.is_failure:
            print(f"  {c('❌ Kết nối MQTT thất bại:', 'RED')} {rc}")
        else:
            print(f"  {c('✅ Kết nối MQTT THÀNH CÔNG!', 'GREEN')}")
            client_obj.subscribe(settings.mqtt_topic)
            print(f"  {c('📡 Đang lắng nghe topic:', 'CYAN')} {settings.mqtt_topic}")
            print(f"  {c('(Hãy chờ thiết bị thật bắn dữ liệu lên...)', 'DIM')}")
            print("  " + "─"*60)

    def on_message(client_obj, userdata, msg):
        try:
            payload_str = msg.payload.decode()
            payload = json.loads(payload_str)
            
            print("\n" + "═"*70)
            print(f"  {c('📥 CÓ TIN NHẮN MỚI TỪ MQTT', 'BOLD', 'GREEN')}")
            print("═"*70)
            
            show_json("1. INPUT GỐC (Raw Payload):", payload, "YELLOW")
            
            # Normalize
            normalized_list = MQTTIngestionClient._normalize(payload)
            
            for normalized in normalized_list:
                # Process
                processed = processor.process(normalized.model_dump())
                
                # Khúc này không gọi store.ingest để tránh bị ghi đúp (vì app.py đang chạy và ghi rồi)
                # Chúng ta chỉ trực quan hoá ra màn hình thôi
                
                show_json(f"2. OUTPUT SAU KHI ĐI QUA PIPELINE ({normalized.device_code}):", processed, "GREEN")
                
                if not processed["quality"]["valid"]:
                    print(f"  {c('⚠️ DỮ LIỆU CÓ LỖI HOẶC BỊ CLAMP (Chặn rác thành công!)', 'RED')}")
                elif processed["quality"]["freshness"] != "FRESH":
                    print(f"  {c('⏳ DỮ LIỆU CŨ (STALE)', 'YELLOW')}")
                elif processed["quality"]["anomalies"]:
                    print(f"  {c('🚨 PHÁT HIỆN BẤT THƯỜNG (ANOMALY)', 'RED')}")
                else:
                    print(f"  {c('✅ DỮ LIỆU ĐẸP, HOÀN HẢO!', 'CYAN')}")
                    
                print("  " + "─"*60)
            
        except Exception as e:
            print(f"  {c('❌ Lỗi xử lý tin nhắn:', 'RED')} {e}")

    client.on_connect = on_connect
    client.on_message = on_message
    
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n  {c('Đã dừng Live Mode.', 'YELLOW')}")


def main():
    print(c("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║          FARMOPS AI — TV1 PIPELINE DEMO                     ║
    ║          Trực quan hoá Input → Output từng bước             ║
    ╚═══════════════════════════════════════════════════════════════╝
    """, "BOLD"))
    
    print("  Chọn chế độ chạy:")
    print("  1. Chạy MOCK DATA (để thuyết trình các case lỗi: Stale, Anomaly, Clamp)")
    print("  2. Chạy LIVE DATA (Hứng trực tiếp dữ liệu thật từ MQTT)")
    print("")
    
    choice = input("  Nhập số (1 hoặc 2): ").strip()
    
    if choice == "2":
        demo_live()
    else:
        demo_normal()
        input(f"\n  {c('Nhấn Enter để tiếp tục...', 'DIM')}")
        
        demo_stale()
        input(f"\n  {c('Nhấn Enter để tiếp tục...', 'DIM')}")
        
        demo_anomaly()
        input(f"\n  {c('Nhấn Enter để tiếp tục...', 'DIM')}")
        
        demo_out_of_range()
        input(f"\n  {c('Nhấn Enter để tiếp tục...', 'DIM')}")
        
        demo_mongodb()
        
        banner("KẾT THÚC DEMO", "═")
        print(f"""
      {c('Tổng kết luồng TV1:', 'BOLD')}
      
      1. Sensor gửi raw JSON → MQTT broker / HTTP API
      2. mqtt_client.py: _normalize() → TelemetryMessage (chuẩn hoá)
      3. data_processor.py: process() → ProcessedTelemetry (validate + enrich)
         ├── Validate: device_code, metrics, timestamp
         ├── Range Check: giá trị trong ngưỡng vật lý
         ├── Freshness: FRESH / STALE / MISSING  
         ├── Anomaly: phát hiện bất thường
         └── Clamp: sửa giá trị phi lý
      4. Lưu SQLite (cho TV2/TV3) + MongoDB Atlas (cho TV1)
      5. TV2 nhận ProcessedTelemetry → AI Agents quyết định
    """)

if __name__ == "__main__":
    main()
