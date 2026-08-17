import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SETTINGS_PATH = path.join(__dirname, "../.runtime-settings.json");
const SECRETS_PATH = path.join(__dirname, "../.runtime-secrets.json");

export const GEMINI_MODELS = [
  "gemini-3.5-flash-lite",
  "gemini-3.5-flash",
  "gemini-2.5-flash",
  "gemini-2.0-flash",
  "gemini-2.0-flash-lite",
];

export const GPT_OSS_MODELS = [
  "openai/gpt-oss-120b",
  "openai/gpt-oss-20b",
  "openai/gpt-4o-mini",
];

const DEFAULT_SETTINGS = {
  manager_name: "Quản lý Nông trại",
  default_prompt: "Hãy kiểm tra nông trại và lập kế hoạch tưới hôm nay",
  target_zone: "Khu A",
  stale_after_seconds: parseInt(process.env.STALE_AFTER_SECONDS || "300", 10),
  enabled_agents: {
    field_iot: true,
    irrigation: true,
    resource: true,
    action: true,
  },
  models: {
    field_iot: process.env.GPT_OSS_2_MODEL || process.env.GPT_OSS_MODEL || "openai/gpt-oss-120b",
    irrigation: process.env.GEMINI_MODEL || "gemini-3.5-flash-lite",
    resource: process.env.GPT_OSS_MODEL || "openai/gpt-oss-120b",
    coordinator: process.env.GEMINI_2_MODEL || "gemini-3.5-flash",
  },
  gpt_oss_base_url: process.env.GPT_OSS_BASE_URL || "https://openrouter.ai/api/v1",
};

const DEFAULT_SECRETS = {
  gemini_api_key: "",
  gemini_2_api_key: "",
  gpt_oss_api_key: "",
  gpt_oss_2_api_key: "",
};

function readJson(filePath, fallback) {
  try {
    if (fs.existsSync(filePath)) {
      return { ...fallback, ...JSON.parse(fs.readFileSync(filePath, "utf8")) };
    }
  } catch {
    /* keep fallback */
  }
  return structuredClone(fallback);
}

function writeJson(filePath, data) {
  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
  } catch (err) {
    console.warn("[Settings] Persist failed:", err.message);
  }
}

let settingsState = (() => {
  const loaded = readJson(SETTINGS_PATH, DEFAULT_SETTINGS);
  return {
    ...DEFAULT_SETTINGS,
    ...loaded,
    enabled_agents: { ...DEFAULT_SETTINGS.enabled_agents, ...(loaded.enabled_agents || {}) },
    models: { ...DEFAULT_SETTINGS.models, ...(loaded.models || {}) },
  };
})();

let secretsState = readJson(SECRETS_PATH, DEFAULT_SECRETS);

export function getSettings() {
  return structuredClone(settingsState);
}

export function updateSettings(patch = {}) {
  const next = {
    ...settingsState,
    ...patch,
    enabled_agents: {
      ...settingsState.enabled_agents,
      ...(patch.enabled_agents || {}),
    },
    models: {
      ...settingsState.models,
      ...(patch.models || {}),
    },
  };

  if (typeof next.stale_after_seconds === "number" || typeof next.stale_after_seconds === "string") {
    next.stale_after_seconds = Math.max(30, Math.min(3600, Number(next.stale_after_seconds) || 300));
  }
  if (typeof next.manager_name === "string") {
    next.manager_name = next.manager_name.trim().slice(0, 80) || DEFAULT_SETTINGS.manager_name;
  }
  if (typeof next.default_prompt === "string") {
    next.default_prompt = next.default_prompt.trim().slice(0, 500) || DEFAULT_SETTINGS.default_prompt;
  }
  if (typeof next.target_zone === "string") {
    next.target_zone = next.target_zone.trim().slice(0, 40) || DEFAULT_SETTINGS.target_zone;
  }
  if (typeof next.gpt_oss_base_url === "string" && next.gpt_oss_base_url.trim()) {
    next.gpt_oss_base_url = next.gpt_oss_base_url.trim().replace(/\/+$/, "");
  }

  settingsState = next;
  writeJson(SETTINGS_PATH, settingsState);
  return getSettings();
}

export function updateSecrets(patch = {}) {
  const next = { ...secretsState };
  for (const key of Object.keys(DEFAULT_SECRETS)) {
    if (typeof patch[key] === "string") {
      const value = patch[key].trim();
      // Empty string means "keep existing" when UI sends blank password fields
      if (value) next[key] = value;
    }
  }
  secretsState = next;
  writeJson(SECRETS_PATH, secretsState);
  return getLlmSlots();
}

export function maskKey(value) {
  if (!value) return { configured: false, hint: null };
  const tip = value.length <= 8 ? "****" : `${value.slice(0, 4)}…${value.slice(-4)}`;
  return { configured: true, hint: tip };
}

function pickKey(...candidates) {
  for (const value of candidates) {
    if (value && String(value).trim()) return String(value).trim();
  }
  return "";
}

/** Effective keys/models used by agents (secrets file overrides .env). */
export function resolveLlm() {
  const models = settingsState.models || DEFAULT_SETTINGS.models;
  return {
    gemini_api_key: pickKey(secretsState.gemini_api_key, process.env.GEMINI_API_KEY),
    gemini_2_api_key: pickKey(secretsState.gemini_2_api_key, process.env.GEMINI_2_API_KEY, secretsState.gemini_api_key, process.env.GEMINI_API_KEY),
    gpt_oss_api_key: pickKey(secretsState.gpt_oss_api_key, process.env.GPT_OSS_API_KEY, process.env.LLM_API_KEY),
    gpt_oss_2_api_key: pickKey(secretsState.gpt_oss_2_api_key, process.env.GPT_OSS_2_API_KEY, secretsState.gpt_oss_api_key, process.env.GPT_OSS_API_KEY, process.env.LLM_API_KEY),
    gemini_model: models.irrigation || process.env.GEMINI_MODEL || "gemini-3.5-flash-lite",
    gemini_2_model: models.coordinator || process.env.GEMINI_2_MODEL || "gemini-3.5-flash",
    gpt_oss_model: models.resource || process.env.GPT_OSS_MODEL || "openai/gpt-oss-120b",
    gpt_oss_2_model: models.field_iot || process.env.GPT_OSS_2_MODEL || process.env.GPT_OSS_MODEL || "openai/gpt-oss-120b",
    gpt_oss_base_url: settingsState.gpt_oss_base_url || process.env.GPT_OSS_BASE_URL || "https://openrouter.ai/api/v1",
  };
}

export function getLlmSlots() {
  const llm = resolveLlm();
  return [
    {
      id: "field_iot",
      agent: "Field IoT Agent",
      role: "Giám sát cảm biến & freshness",
      provider: "GPT-OSS",
      model: llm.gpt_oss_2_model,
      model_options: GPT_OSS_MODELS,
      key_field: "gpt_oss_2_api_key",
      ...maskKey(llm.gpt_oss_2_api_key),
    },
    {
      id: "irrigation",
      agent: "Irrigation Planning Agent",
      role: "Lập kế hoạch tưới động",
      provider: "Gemini",
      model: llm.gemini_model,
      model_options: GEMINI_MODELS,
      key_field: "gemini_api_key",
      ...maskKey(llm.gemini_api_key),
    },
    {
      id: "resource",
      agent: "Resource Agent",
      role: "Thẩm định bơm / nước / pH",
      provider: "GPT-OSS",
      model: llm.gpt_oss_model,
      model_options: GPT_OSS_MODELS,
      key_field: "gpt_oss_api_key",
      ...maskKey(llm.gpt_oss_api_key),
    },
    {
      id: "coordinator",
      agent: "Farm Coordinator Agent",
      role: "Tóm tắt điều hành",
      provider: "Gemini",
      model: llm.gemini_2_model,
      model_options: GEMINI_MODELS,
      key_field: "gemini_2_api_key",
      ...maskKey(llm.gemini_2_api_key),
    },
  ];
}

export function getModelCatalog() {
  return { gemini: GEMINI_MODELS, gpt_oss: GPT_OSS_MODELS };
}
