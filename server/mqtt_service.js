import mqtt from "mqtt";
import { IoTDataProcessor } from "./data_processor.js";

export class MQTTIngestionClient {
  constructor(store, mongoStore = null) {
    this.store = store;
    this.mongoStore = mongoStore;
    this.processor = new IoTDataProcessor(parseInt(process.env.STALE_AFTER_SECONDS || "300", 10));
    this.connected = false;
    this.subscribed = false;
    this.lastError = null;
    this.lastMessageAt = null;
    this.client = null;
  }

  start() {
    const host = process.env.MQTT_BROKER_HOST || process.env.MQTT_ENDPOINT_HOST;
    if (!host) {
      console.log("[MQTT] MQTT Broker host not configured. Running in REST API ingestion mode.");
      return;
    }

    const port = parseInt(process.env.MQTT_BROKER_PORT || "1883", 10);
    const transport = process.env.MQTT_TRANSPORT || "tcp";
    const useTls = process.env.MQTT_TLS === "true";
    const protocol = transport === "websockets" ? (useTls ? "wss" : "ws") : useTls ? "mqtts" : "mqtt";

    const topic = process.env.MQTT_TOPIC || "hackathon/team_2/test/telemetry";
    const url = `${protocol}://${host}:${port}${transport === "websockets" ? process.env.MQTT_WEBSOCKET_PATH || "/mqtt" : ""}`;

    const options = {
      clientId: `farmops-node-${Math.random().toString(16).substring(2, 10)}`,
      username: process.env.MQTT_USERNAME || "TEAM_2",
      password: process.env.MQTT_PASSWORD || "",
      clean: true,
      connectTimeout: 10000,
    };

    console.log(`[MQTT] Connecting to ${url}...`);
    try {
      this.client = mqtt.connect(url, options);

      this.client.on("connect", () => {
        this.connected = true;
        this.lastError = null;
        console.log(`[MQTT] Connected to ${host}`);

        this.client.subscribe(topic, (err) => {
          if (!err) {
            this.subscribed = true;
            console.log(`[MQTT] Subscribed to topic '${topic}'`);
          } else {
            this.lastError = err.message;
          }
        });
      });

      this.client.on("message", async (topicName, messageBuffer) => {
        this.lastMessageAt = Date.now() / 1000;
        try {
          const rawPayload = JSON.parse(messageBuffer.toString("utf-8"));
          const processed = this.processor.process(rawPayload);
          await this.store.ingest({ device_code: processed.device_code, timestamp: processed.timestamp, metrics: processed.metrics }, "MQTT", processed.quality);
          if (this.mongoStore && this.mongoStore.connected) {
            await this.mongoStore.ingest(processed);
          }
        } catch (err) {
          console.warn("[MQTT Message Error]:", err.message);
        }
      });

      this.client.on("error", (err) => {
        this.connected = false;
        this.lastError = err.message;
        console.warn("[MQTT Error]:", err.message);
      });
    } catch (err) {
      this.lastError = err.message;
    }
  }

  stop() {
    if (this.client) {
      this.client.end();
      this.connected = false;
      this.subscribed = false;
    }
  }

  status() {
    return {
      configured: Boolean(process.env.MQTT_BROKER_HOST),
      connected: this.connected,
      subscribed: this.subscribed,
      last_error: this.lastError,
      last_message_at: this.lastMessageAt,
    };
  }
}
