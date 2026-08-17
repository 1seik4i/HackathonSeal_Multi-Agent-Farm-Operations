import { useEffect, useState } from "react";
import { useFarmData } from "../context/FarmDataContext";

const AGENT_LABELS = {
  field_iot: "Field IoT Agent",
  irrigation: "Irrigation Planning Agent",
  resource: "Resource Agent",
  action: "Farm Action Agent",
};

const KEY_LABELS = {
  gemini_api_key: "Gemini API key (Irrigation)",
  gemini_2_api_key: "Gemini API key (Coordinator)",
  gpt_oss_api_key: "GPT-OSS API key (Resource)",
  gpt_oss_2_api_key: "GPT-OSS API key (Field IoT)",
};

export function SettingsPage() {
  const { settingsBundle, seeding, savingSettings, handleSeedDemo, handleSaveSettings, handleSaveLlmConfig } =
    useFarmData();

  const settings = settingsBundle?.settings;
  const llmSlots = settingsBundle?.llm_slots || [];

  const [baseUrl, setBaseUrl] = useState("https://openrouter.ai/api/v1");
  const [enabledAgents, setEnabledAgents] = useState({
    field_iot: true,
    irrigation: true,
    resource: true,
    action: true,
  });
  const [models, setModels] = useState({
    field_iot: "openai/gpt-oss-120b",
    irrigation: "gemini-3.5-flash-lite",
    resource: "openai/gpt-oss-120b",
    coordinator: "gemini-3.5-flash",
  });
  const [keys, setKeys] = useState({
    gemini_api_key: "",
    gemini_2_api_key: "",
    gpt_oss_api_key: "",
    gpt_oss_2_api_key: "",
  });
  const [llmMessage, setLlmMessage] = useState("");
  const [opsMessage, setOpsMessage] = useState("");

  useEffect(() => {
    if (!settings) return;
    setBaseUrl(settings.gpt_oss_base_url || "https://openrouter.ai/api/v1");
    setEnabledAgents(settings.enabled_agents || enabledAgents);
    setModels({
      field_iot: settings.models?.field_iot || "openai/gpt-oss-120b",
      irrigation: settings.models?.irrigation || "gemini-3.5-flash-lite",
      resource: settings.models?.resource || "openai/gpt-oss-120b",
      coordinator: settings.models?.coordinator || "gemini-3.5-flash",
    });
  }, [settings]);

  const saveOps = async () => {
    setOpsMessage("");
    await handleSaveSettings({ enabled_agents: enabledAgents });
    setOpsMessage("Đã lưu phân công agent.");
  };

  const saveLlm = async () => {
    setLlmMessage("");
    await handleSaveLlmConfig({
      models,
      gpt_oss_base_url: baseUrl,
      keys,
    });
    setKeys({
      gemini_api_key: "",
      gemini_2_api_key: "",
      gpt_oss_api_key: "",
      gpt_oss_2_api_key: "",
    });
    setLlmMessage("Đã lưu API key và model. Key không hiển thị lại toàn bộ vì lý do bảo mật.");
  };

  return (
    <main className="panel-stack">
      <section>
        <h1 className="section-title" style={{ fontSize: "1.55rem" }}>
          Cài đặt
        </h1>
        <p className="section-sub">Phân công agent, dữ liệu demo và Configure AI.</p>

        <div className="chip-row">
          <button type="button" className="chip" disabled={seeding} onClick={() => handleSeedDemo("normal")}>
            Demo: Bình thường
          </button>
          <button type="button" className="chip" disabled={seeding} onClick={() => handleSeedDemo("dry")}>
            Demo: Đất khô
          </button>
          <button type="button" className="chip" disabled={seeding} onClick={() => handleSeedDemo("stale")}>
            Demo: Dữ liệu cũ
          </button>
          <button type="button" className="chip" disabled={seeding} onClick={() => handleSeedDemo("pump_failure")}>
            Demo: Bơm lỗi
          </button>
        </div>

        <h2 className="section-title" style={{ marginTop: "0.5rem" }}>
          Phân công agent
        </h2>
        <div className="toggle-list">
          {Object.keys(AGENT_LABELS).map((key) => (
            <div className="toggle-row" key={key}>
              <div>
                <div style={{ fontWeight: 700 }}>{AGENT_LABELS[key]}</div>
                <div style={{ fontSize: "0.9rem", color: "var(--muted)" }}>{key}</div>
              </div>
              <button
                type="button"
                className={`switch ${enabledAgents[key] ? "on" : ""}`}
                aria-pressed={Boolean(enabledAgents[key])}
                onClick={() => setEnabledAgents((s) => ({ ...s, [key]: !s[key] }))}
              >
                <span />
              </button>
            </div>
          ))}
        </div>

        <div style={{ marginTop: "1rem", display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-primary" disabled={savingSettings} onClick={saveOps}>
            {savingSettings ? "Đang lưu..." : "Lưu phân công agent"}
          </button>
          {opsMessage && <span style={{ color: "var(--leaf)", fontSize: "0.95rem" }}>{opsMessage}</span>}
        </div>
      </section>

      <section>
        <h2 className="section-title">Configure AI</h2>
        <p className="section-sub">
          Nhập API key, chọn model cho từng agent rồi lưu. Key lưu trên server (không commit).
        </p>

        <div className="field">
          <label htmlFor="base-url">GPT-OSS / OpenRouter Base URL</label>
          <input id="base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </div>

        {llmSlots.map((slot) => (
          <div key={slot.id} style={{ padding: "1rem 0", borderBottom: "1px solid var(--line)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", marginBottom: "0.65rem" }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: "1.02rem" }}>{slot.agent}</div>
                <div style={{ fontSize: "0.9rem", color: "var(--muted)" }}>
                  {slot.provider} · {slot.configured ? `key ${slot.hint}` : "chưa có key"}
                </div>
              </div>
              <span style={{ fontWeight: 700, color: slot.configured ? "var(--leaf)" : "var(--warn)" }}>
                {slot.configured ? "OK" : "MISSING"}
              </span>
            </div>

            <div className="field">
              <label htmlFor={`model-${slot.id}`}>Chọn model</label>
              <select
                id={`model-${slot.id}`}
                value={models[slot.id] || slot.model}
                onChange={(e) => setModels((m) => ({ ...m, [slot.id]: e.target.value }))}
              >
                {(slot.model_options || [slot.model]).map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>

            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor={`key-${slot.id}`}>{KEY_LABELS[slot.key_field] || "API key"}</label>
              <input
                id={`key-${slot.id}`}
                type="password"
                autoComplete="off"
                placeholder={slot.configured ? "Để trống nếu giữ key hiện tại" : "Dán API key mới"}
                value={keys[slot.key_field] || ""}
                onChange={(e) => setKeys((k) => ({ ...k, [slot.key_field]: e.target.value }))}
              />
            </div>
          </div>
        ))}

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "1.1rem", alignItems: "center" }}>
          <button type="button" className="btn btn-primary" disabled={savingSettings} onClick={saveLlm}>
            {savingSettings ? "Đang lưu..." : "Lưu API key & model"}
          </button>
          {llmMessage && <span style={{ color: "var(--leaf)", fontSize: "0.95rem" }}>{llmMessage}</span>}
        </div>
      </section>
    </main>
  );
}
