from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.models import AgentConfigRequest, AgentConfigView


from dotenv import load_dotenv

load_dotenv()
load_dotenv("api_keys.env")


AGENT_CATALOG = {
    "openai_agent": ("ChatGPT (OpenAI)", "GPT phân tích evidence và đưa ra nhận định có dẫn chứng."),
    "gemini_agent": ("Google Gemini", "Gemini phân tích vận hành dựa trên telemetry đã xác thực."),
    "claude_agent": ("Claude (Anthropic)", "Claude rà soát rủi ro và nêu rõ dữ liệu còn thiếu."),
    "deepseek_agent": ("DeepSeek", "DeepSeek tạo nhận định ngắn gọn từ dữ liệu được cấp."),
}


def get_env_api_key(agent_id: str) -> str:
    load_dotenv()
    load_dotenv("api_keys.env")
    prefix = f"AGENT_{agent_id.upper()}"
    direct_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    if direct_key:
        return direct_key

    if agent_id == "openai_agent":
        return (
            os.getenv("OPENAI_API_KEY", "")
            or os.getenv("GPT_OSS_API_KEY", "")
            or os.getenv("LLM_API_KEY", "")
        ).strip()
    elif agent_id == "gemini_agent":
        return (
            os.getenv("GEMINI_API_KEY", "")
            or os.getenv("GEMINI_2_API_KEY", "")
            or os.getenv("GOOGLE_API_KEY", "")
        ).strip()
    elif agent_id == "claude_agent":
        return (
            os.getenv("CLAUDE_API_KEY", "")
            or os.getenv("ANTHROPIC_API_KEY", "")
            or os.getenv("GEMINI_2_API_KEY", "")
            or os.getenv("GEMINI_API_KEY", "")
        ).strip()
    elif agent_id == "deepseek_agent":
        return (
            os.getenv("DEEPSEEK_API_KEY", "")
            or os.getenv("GPT_OSS_2_API_KEY", "")
            or os.getenv("GPT_OSS_API_KEY", "")
        ).strip()
    return ""


@dataclass
class RuntimeConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    enabled: bool = False
    custom_api_key: str = ""
    connection_status: str = "NOT_CONFIGURED"
    last_tested_at: float | None = None
    last_error: str | None = None

    def get_effective_api_key(self, agent_id: str) -> str:
        if self.custom_api_key.strip():
            return self.custom_api_key.strip()
        return get_env_api_key(agent_id)


class RealAgentGateway:
    """Runtime-only secret store. Keys are never written to SQLite or API responses."""

    def __init__(self) -> None:
        self._configs: dict[str, RuntimeConfig] = {}
        for agent_id in AGENT_CATALOG:
            prefix = f"AGENT_{agent_id.upper()}"
            env_key = get_env_api_key(agent_id)
            has_key = bool(env_key)
            self._configs[agent_id] = RuntimeConfig(
                provider=os.getenv(f"{prefix}_PROVIDER", "openai" if agent_id == "openai_agent" else "gemini" if agent_id == "gemini_agent" else "anthropic" if agent_id == "claude_agent" else "deepseek"),
                model=os.getenv(f"{prefix}_MODEL", "gpt-4o-mini" if agent_id == "openai_agent" else "gemini-2.0-flash" if agent_id == "gemini_agent" else "claude-3-5-haiku-latest" if agent_id == "claude_agent" else "deepseek-chat"),
                enabled=has_key,
                custom_api_key="",
                connection_status="READY" if has_key else "NOT_CONFIGURED",
            )

    def _view(self, agent_id: str) -> AgentConfigView:
        name, role = AGENT_CATALOG[agent_id]
        config = self._configs[agent_id]
        eff_key = config.get_effective_api_key(agent_id)
        has_key = bool(eff_key)
        return AgentConfigView(
            agent_id=agent_id,
            display_name=name,
            role=role,
            provider=config.provider,
            model=config.model,
            enabled=config.enabled,
            has_api_key=has_key,
            connection_status=config.connection_status if has_key else "NOT_CONFIGURED",
            last_tested_at=config.last_tested_at,
            last_error=config.last_error if has_key else ("API key chưa được cấu hình." if not has_key else None),
        )

    def list_configs(self) -> list[AgentConfigView]:
        return [self._view(agent_id) for agent_id in AGENT_CATALOG]

    def configure(self, agent_id: str, update: AgentConfigRequest) -> AgentConfigView:
        self._require_known(agent_id)
        config = self._configs[agent_id]
        config.provider = update.provider
        config.model = update.model
        config.enabled = update.enabled
        config.custom_api_key = update.api_key.strip()
        config.last_tested_at = None
        
        eff_key = config.get_effective_api_key(agent_id)
        if eff_key:
            config.connection_status = "READY"
            config.last_error = None
        else:
            config.connection_status = "NOT_CONFIGURED"
            config.last_error = "API key chưa được cấu hình."
        return self._view(agent_id)

    def test_connection(self, agent_id: str) -> AgentConfigView:
        self._require_known(agent_id)
        config = self._configs[agent_id]
        eff_key = config.get_effective_api_key(agent_id)
        if not config.enabled or not eff_key:
            config.connection_status = "NOT_CONFIGURED"
            config.last_error = "API key chưa được cấu hình hoặc provider chưa được bật."
            return self._view(agent_id)
        config.connection_status = "TESTING"
        config.last_tested_at = time.time()
        try:
            self._request(config, eff_key, "Trả lời đúng một từ: READY.")
            config.connection_status = "READY"
            config.last_error = None
        except RuntimeError as error:
            config.connection_status = "FAILED"
            config.last_error = str(error)[:240]
        return self._view(agent_id)

    def analyze(self, agent_id: str, facts: dict[str, Any], scenario: str) -> dict[str, Any]:
        self._require_known(agent_id)
        config = self._configs[agent_id]
        eff_key = config.get_effective_api_key(agent_id)
        if not config.enabled or not eff_key or config.connection_status != "READY":
            raise RuntimeError("AGENT_NOT_READY")
        prompt = (
            "Bạn là một agent vận hành nông nghiệp. Chỉ phân tích facts bên dưới; không suy đoán số liệu, "
            "không khẳng định đã thực hiện hành động, và nêu rõ thiếu dữ liệu nếu có. Scenario là ràng buộc, "
            "không phải dữ liệu cảm biến. Trả lời tiếng Việt tối đa 120 từ.\n"
            f"AGENT={agent_id}\nSCENARIO={scenario}\nFACTS_JSON={json.dumps(facts, ensure_ascii=False)}"
        )
        return {"agent_id": agent_id, "provider": config.provider, "model": config.model, "analysis": self._request(config, eff_key, prompt)}

    def _request(self, config: RuntimeConfig, api_key: str, prompt: str) -> str:
        try:
            if config.provider == "openai":
                request = urllib.request.Request(
                    "https://api.openai.com/v1/responses",
                    data=json.dumps({"model": config.model, "input": prompt, "max_output_tokens": 180}).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("output_text", "").strip()
            elif config.provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.model}:generateContent?key={api_key}"
                request = urllib.request.Request(url, data=json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 180}}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            elif config.provider == "anthropic":
                request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps({"model": config.model, "max_tokens": 180, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8"), headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("content", [{}])[0].get("text", "").strip()
            elif config.provider == "deepseek":
                request = urllib.request.Request("https://api.deepseek.com/chat/completions", data=json.dumps({"model": config.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 180}).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            else:
                raise RuntimeError("Provider không được hỗ trợ.")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Provider trả về HTTP {error.code}.") from error
        except urllib.error.URLError:
            raise RuntimeError("Không thể kết nối provider.")
        if not text:
            raise RuntimeError("Provider không trả nội dung có thể sử dụng.")
        return text

    @staticmethod
    def _require_known(agent_id: str) -> None:
        if agent_id not in AGENT_CATALOG:
            raise KeyError(agent_id)
