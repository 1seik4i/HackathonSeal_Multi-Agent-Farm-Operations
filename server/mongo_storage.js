import { MongoClient } from "mongodb";

export class MongoTelemetryStore {
  constructor(uri, dbName = "farmops") {
    this.client = new MongoClient(uri, { serverSelectionTimeoutMS: 5000 });
    this.dbName = dbName;
    this.connected = false;
    this._connect();
  }

  async _connect() {
    try {
      await this.client.connect();
      this.db = this.client.db(this.dbName);
      this.telemetry = this.db.collection("telemetry");
      this.connected = true;
      console.log(`[MongoDB] Connected successfully to database '${this.dbName}'`);
      await this._ensureIndexes();
    } catch (err) {
      console.warn("[MongoDB] Connection warning:", err.message);
      this.connected = false;
    }
  }

  async _ensureIndexes() {
    if (!this.telemetry) return;
    try {
      await this.telemetry.createIndex({ device_code: 1, timestamp: -1 }, { name: "device_time_idx" });
      await this.telemetry.createIndex({ received_at: -1 }, { name: "received_idx" });
    } catch (err) {
      console.warn("[MongoDB] Index creation warning:", err.message);
    }
  }

  async ingest(processedData) {
    if (!this.connected || !this.telemetry) return null;
    try {
      const res = await this.telemetry.insertOne(processedData);
      return res.insertedId.toString();
    } catch (err) {
      console.warn("[MongoDB] Ingest error:", err.message);
      return null;
    }
  }

  async latestByDevice() {
    if (!this.connected || !this.telemetry) return {};
    try {
      const pipeline = [
        { $sort: { timestamp: -1 } },
        {
          $group: {
            _id: "$device_code",
            timestamp: { $first: "$timestamp" },
            metrics: { $first: "$metrics" },
            quality: { $first: "$quality" },
          },
        },
      ];
      const docs = await this.telemetry.aggregate(pipeline).toArray();
      const result = {};
      for (const doc of docs) {
        result[doc._id] = {
          timestamp: doc.timestamp,
          metrics: doc.metrics,
          quality: doc.quality,
        };
      }
      return result;
    } catch (err) {
      console.warn("[MongoDB] latestByDevice error:", err.message);
      return {};
    }
  }

  async healthCheck() {
    if (!this.connected || !this.db) {
      return { status: "error", error: "Not connected to MongoDB" };
    }
    try {
      await this.db.command({ ping: 1 });
      const count = await this.telemetry.estimatedDocumentCount();
      return { status: "ok", documents: count };
    } catch (err) {
      return { status: "error", error: err.message };
    }
  }
}
