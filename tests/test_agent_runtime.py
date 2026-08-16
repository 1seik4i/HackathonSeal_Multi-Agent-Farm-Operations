"""Tests for agent_runtime API key resolution logic."""

from __future__ import annotations

import os
import pytest
from src.agent_runtime import RealAgentGateway, get_env_api_key
from src.models import AgentConfigRequest


class TestAgentApiKeyResolution:
    """Test user API key vs .env default API key resolution."""

    def test_default_env_key_resolution(self):
        gateway = RealAgentGateway()
        configs = gateway.list_configs()
        for config in configs:
            assert config.has_api_key is True
            assert config.connection_status == "READY"

    def test_custom_user_api_key_override_and_reset(self):
        gateway = RealAgentGateway()
        agent_id = "openai_agent"
        
        env_key = gateway._configs[agent_id].get_effective_api_key(agent_id)
        assert env_key != ""

        # Set user custom key
        gateway.configure(agent_id, AgentConfigRequest(provider="openai", model="gpt-4o-mini", api_key="sk-user-provided-key", enabled=True))
        effective_after_custom = gateway._configs[agent_id].get_effective_api_key(agent_id)
        assert effective_after_custom == "sk-user-provided-key"

        # Clear custom key -> fallback to .env default
        gateway.configure(agent_id, AgentConfigRequest(provider="openai", model="gpt-4o-mini", api_key="", enabled=True))
        effective_after_reset = gateway._configs[agent_id].get_effective_api_key(agent_id)
        assert effective_after_reset == env_key
