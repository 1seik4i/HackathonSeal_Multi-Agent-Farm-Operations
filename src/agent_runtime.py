from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from src.models import AgentConfigRequest, AgentConfigView

load_dotenv()
load_dotenv("api_keys.env")

AGENT_CATALOG = {
    "openai_agent": ("ChatGPT (OpenAI)", "GPT phân tích evidence và đưa ra nhận định có dẫn chứng."),
    "gemini_agent": ("Google Gemini", "Gemini phân tích vận hành dựa trên telemetry đã xác thực."),
    "claude_agent": ("Claude (Anthropic)", "Claude rà soát rủi ro và nêu rõ dữ liệu còn thiếu."),
    "deepseek_agent": ("DeepSeek", "DeepSeek tạo nhận định ngắn gọn từ dữ liệu được cấp."),
}


def get_default_env_key(agent_id: str, provider: str = "") -> str:
    prefix = f"AGENT_{agent_id.upper()}"
    custom_prefix_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    if custom_prefix_key:
        return custom_prefix_key

    if agent_id == "openai_agent":
        key = os.getenv("OPENAI_API_KEY", os.getenv("GPT_OSS_API_KEY", os.getenv("GPT_OSS_2_API_KEY", os.getenv("LLM_API_KEY", "")))).strip()
    elif agent_id == "gemini_agent":
        key = os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_2_API_KEY", "")).strip()
    elif agent_id == "claude_agent":
        key = os.getenv("ANTHROPIC_API_KEY", os.getenv("CLAUDE_API_KEY", os.getenv("GPT_OSS_2_API_KEY", os.getenv("GEMINI_2_API_KEY", "")))).strip()
    elif agent_id == "deepseek_agent":
        key = os.getenv("DEEPSEEK_API_KEY", os.getenv("GPT_OSS_2_API_KEY", os.getenv("GEMINI_2_API_KEY", ""))).strip()
    else:
        key = ""

    if key:
        return key

    prov = (provider or "").lower()
    if prov == "openai":
        return os.getenv("OPENAI_API_KEY", os.getenv("GPT_OSS_API_KEY", os.getenv("GPT_OSS_2_API_KEY", os.getenv("LLM_API_KEY", "")))).strip()
    elif prov == "gemini":
        return os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_2_API_KEY", "")).strip()
    elif prov == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY", os.getenv("CLAUDE_API_KEY", "")).strip()
    elif prov == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "").strip()

    return os.getenv("GPT_OSS_API_KEY", os.getenv("GEMINI_API_KEY", os.getenv("GPT_OSS_2_API_KEY", os.getenv("GEMINI_2_API_KEY", "")))).strip()


@dataclass
class RuntimeConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    enabled: bool = True
    user_api_key: str = ""
    connection_status: str = "NOT_CONFIGURED"
    last_tested_at: float | None = None
    last_error: str | None = None

    def get_effective_key(self, agent_id: str) -> str:
        if self.user_api_key and self.user_api_key.strip():
            return self.user_api_key.strip()
        return get_default_env_key(agent_id, self.provider)


class RealAgentGateway:
    """Runtime-only secret store. Keys are never written to SQLite or API responses."""

    def __init__(self) -> None:
        self._configs: dict[str, RuntimeConfig] = {}
        default_gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        for agent_id in AGENT_CATALOG:
            prefix = f"AGENT_{agent_id.upper()}"
            prov = os.getenv(f"{prefix}_PROVIDER", "openai" if agent_id == "openai_agent" else "gemini" if agent_id == "gemini_agent" else "anthropic" if agent_id == "claude_agent" else "deepseek")
            mod = os.getenv(f"{prefix}_MODEL", "gpt-4o-mini" if agent_id == "openai_agent" else default_gemini_model if agent_id == "gemini_agent" else "claude-3-5-haiku-latest" if agent_id == "claude_agent" else "deepseek-chat")
            user_key = os.getenv(f"{prefix}_API_KEY", "").strip()
            config = RuntimeConfig(
                provider=prov,
                model=mod,
                enabled=True,
                user_api_key=user_key,
                connection_status="NOT_CONFIGURED",
            )
            eff_key = config.get_effective_key(agent_id)
            if eff_key:
                config.connection_status = "READY"
            self._configs[agent_id] = config

    def _view(self, agent_id: str) -> AgentConfigView:
        name, role = AGENT_CATALOG[agent_id]
        config = self._configs[agent_id]
        eff_key = config.get_effective_key(agent_id)
        has_key = bool(eff_key)
        has_custom = bool(config.user_api_key and config.user_api_key.strip())
        status = config.connection_status
        if status == "NOT_CONFIGURED" and has_key:
            status = "READY"
        return AgentConfigView(
            agent_id=agent_id,
            display_name=name,
            role=role,
            provider=config.provider,
            model=config.model,
            enabled=config.enabled and has_key,
            has_api_key=has_key,
            has_custom_key=has_custom,
            connection_status=status,
            last_tested_at=config.last_tested_at,
            last_error=config.last_error,
        )

    def list_configs(self) -> list[AgentConfigView]:
        return [self._view(agent_id) for agent_id in AGENT_CATALOG]

    def configure(self, agent_id: str, update: AgentConfigRequest) -> AgentConfigView:
        self._require_known(agent_id)
        current = self._configs[agent_id]
        current.provider = update.provider
        current.model = update.model
        current.enabled = update.enabled
        current.user_api_key = update.api_key.strip()
        
        eff_key = current.get_effective_key(agent_id)
        if eff_key:
            current.connection_status = "READY"
            current.last_error = None
        else:
            current.connection_status = "NOT_CONFIGURED"
            current.last_error = "API key chưa được cấu hình."
        return self._view(agent_id)

    def test_connection(self, agent_id: str) -> AgentConfigView:
        self._require_known(agent_id)
        config = self._configs[agent_id]
        eff_key = config.get_effective_key(agent_id)
        if not config.enabled or not eff_key:
            config.connection_status = "NOT_CONFIGURED"
            config.last_error = "API key chưa được cấu hình hoặc provider chưa được bật."
            return self._view(agent_id)
        config.connection_status = "TESTING"
        config.last_tested_at = time.time()
        try:
            self._request(config, "Trả lời đúng một từ: READY.", override_key=eff_key)
            config.connection_status = "READY"
            config.last_error = None
        except RuntimeError as error:
            config.connection_status = "FAILED"
            config.last_error = str(error)[:240]
        return self._view(agent_id)

    def analyze(self, agent_id: str, facts: dict[str, Any], scenario: str) -> dict[str, Any]:
        self._require_known(agent_id)
        config = self._configs[agent_id]
        eff_key = config.get_effective_key(agent_id)
        if not config.enabled or not eff_key:
            raise RuntimeError("AGENT_NOT_READY")
        prompt = (
            f"Bạn là một chuyên gia nông nghiệp AI ({config.provider}). "
            f"Người dùng vừa gửi yêu cầu: \"{scenario}\".\n"
            f"Dữ liệu cảm biến thời gian thực tại hiện trường: {json.dumps(facts, ensure_ascii=False)}.\n"
            "Hãy đối thoại tự nhiên như một con người chuyên gia nông nghiệp với người dùng. "
            "Phân tích ngắn gọn (2-3 câu), giải đáp trực tiếp yêu cầu người dùng dựa trên dữ liệu cảm biến thực tế trên. Không sử dụng câu văn mẫu."
        )
        analysis_res = self._request(config, prompt, override_key=eff_key)
        return {"agent_id": agent_id, "provider": config.provider, "model": config.model, "analysis": analysis_res}

    def _request(self, config: RuntimeConfig, prompt: str, override_key: str = "") -> str:
        api_key = override_key or config.get_effective_key("")
        if not api_key:
            raise RuntimeError("Thiếu API key cho agent.")
            
        try:
            if api_key.startswith("gsk_") or "/" in config.model:
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                model_name = config.model
                if "/" not in model_name:
                    model_name = f"openai/{config.model}" if config.provider == "openai" else f"google/{config.model}" if config.provider == "gemini" else f"anthropic/{config.model}" if config.provider == "anthropic" else f"deepseek/{config.model}"
                payload = {"model": model_name, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}
                request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            elif config.provider == "gemini" or api_key.startswith("AIzaSy"):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.model}:generateContent?key={api_key}"
                payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 300}}
                request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            elif config.provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                payload = {"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}
                request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            elif config.provider == "anthropic":
                request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps({"model": config.model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"), headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("content", [{}])[0].get("text", "").strip()
            elif config.provider == "deepseek":
                request = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps({"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            else:
                raise RuntimeError("Provider không được hỗ trợ.")
        except urllib.error.HTTPError as error:
            err_msg = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {error.code}: {err_msg[:120]}") from error
        except urllib.error.URLError as url_err:
            raise RuntimeError(f"Không thể kết nối API provider ({url_err.reason}).") from url_err

        if not text:
            raise RuntimeError("API Provider không trả về câu trả lời.")
        return text

    @staticmethod
    def _require_known(agent_id: str) -> None:
        if agent_id not in AGENT_CATALOG:
            raise KeyError(agent_id)
