import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

const DEVICES = ["SOIL_01", "WEATHER_01", "SUN_01", "PUMP_01", "PH_01", "TANK_01"];

const FarmDataContext = createContext(null);

function deriveVerdict(telemetry, staleAfter = 300) {
  const now = Date.now() / 1000;
  const soil = telemetry?.SOIL_01?.metrics?.soil_moisture;
  const tank = telemetry?.TANK_01?.metrics?.level;
  const soilTs = telemetry?.SOIL_01?.timestamp;

  if (soil === undefined || !soilTs || now - soilTs > staleAfter) {
    return {
      code: "THIẾU DỮ LIỆU",
      tone: "warn",
      detail: "Chưa có dữ liệu đất mới. Kiểm tra MQTT hoặc nạp kịch bản demo.",
    };
  }
  if (soil < 35) {
    return {
      code: "CẦN TƯỚI",
      tone: "danger",
      detail: `Độ ẩm đất ${soil}% — dưới ngưỡng tham chiếu 35%.`,
    };
  }
  if (tank !== undefined && tank < 30) {
    return {
      code: "THIẾU NƯỚC",
      tone: "warn",
      detail: `Bồn nước còn ${tank}% — dưới mức tối thiểu 30%.`,
    };
  }
  return {
    code: "ỔN ĐỊNH",
    tone: "ok",
    detail: "Các chỉ số chính đang trong ngưỡng vận hành.",
  };
}

export function FarmDataProvider({ children }) {
  const [systemStatus, setSystemStatus] = useState(null);
  const [telemetry, setTelemetry] = useState({});
  const [historyMap, setHistoryMap] = useState({});
  const [actions, setActions] = useState([]);
  const [settingsBundle, setSettingsBundle] = useState(null);
  const [loadingAgent, setLoadingAgent] = useState(false);
  const [agentResult, setAgentResult] = useState(null);
  const [agentHealth, setAgentHealth] = useState(null);
  const [seeding, setSeeding] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const wsRef = useRef(null);

  const staleAfter = settingsBundle?.settings?.stale_after_seconds || 300;
  const verdict = useMemo(() => deriveVerdict(telemetry, staleAfter), [telemetry, staleAfter]);

  const fetchAgentHealth = useCallback(async () => {
    try {
      const resp = await fetch("/api/agents/status");
      if (resp.ok) {
        const data = await resp.json();
        if (data.agent_health) setAgentHealth(data.agent_health);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const fetchAllHistory = useCallback(async () => {
    const next = {};
    await Promise.all(
      DEVICES.map(async (dev) => {
        try {
          const resp = await fetch(`/api/telemetry/history?device_id=${dev}&limit=25`);
          if (resp.ok) next[dev] = await resp.json();
        } catch {
          /* ignore */
        }
      })
    );
    setHistoryMap(next);
  }, []);

  const fetchLatest = useCallback(async () => {
    try {
      const resp = await fetch("/api/telemetry/latest");
      if (resp.ok) setTelemetry(await resp.json());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchActions = useCallback(async () => {
    try {
      const resp = await fetch("/api/actions?limit=20");
      if (resp.ok) setActions(await resp.json());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const resp = await fetch("/api/health");
      if (resp.ok) setSystemStatus(await resp.json());
    } catch {
      /* ignore */
    }
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const resp = await fetch("/api/settings");
      if (resp.ok) setSettingsBundle(await resp.json());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    fetchLatest();
    fetchActions();
    fetchAllHistory();
    fetchSettings();
    fetchAgentHealth();

    const poll = setInterval(() => {
      fetchLatest();
      fetchActions();
      fetchAllHistory();
      fetchHealth();
      fetchAgentHealth();
    }, 5000);

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsHost = window.location.host || "127.0.0.1:8000";
    try {
      const ws = new WebSocket(`${wsProtocol}//${wsHost}/ws/telemetry`);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "STATE_UPDATE") {
            if (message.telemetry) setTelemetry(message.telemetry);
            if (message.recent_actions) setActions(message.recent_actions);
            if (message.system_status) {
              setSystemStatus((prev) => ({ ...prev, ...message.system_status }));
            }
          }
        } catch {
          /* ignore */
        }
      };
    } catch {
      /* ignore */
    }

    return () => {
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, [fetchAllHistory, fetchActions, fetchHealth, fetchLatest, fetchSettings, fetchAgentHealth]);

  const handleSeedDemo = async (scenario = "dry") => {
    setSeeding(true);
    try {
      const resp = await fetch("/api/demo/seed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario }),
      });
      if (resp.ok) {
        await fetchLatest();
        await fetchAllHistory();
      }
    } finally {
      setSeeding(false);
    }
  };

  const handleCoordinate = async (requestText, managerName) => {
    setLoadingAgent(true);
    try {
      const resp = await fetch("/api/dialogue/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: requestText,
          manager_name: managerName || settingsBundle?.settings?.manager_name,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setAgentResult(data);
        if (data.agent_health) setAgentHealth(data.agent_health);
        await fetchActions();
      }
    } finally {
      setLoadingAgent(false);
    }
  };

  const handleApproveAction = async (actionId, decision) => {
    const resp = await fetch(`/api/actions/${actionId}/approval`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, operator_note: "Phê duyệt từ dashboard React" }),
    });
    if (resp.ok) await fetchActions();
  };

  const handleVerifyAction = async (actionId) => {
    const resp = await fetch(`/api/actions/${actionId}/verify`, { method: "POST" });
    if (resp.ok) await fetchActions();
  };

  const handleClearActions = async () => {
    const resp = await fetch("/api/actions", { method: "DELETE" });
    if (resp.ok) {
      setActions([]);
      setAgentResult(null);
    }
  };

  const handleSaveSettings = async (patch) => {
    setSavingSettings(true);
    try {
      const resp = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (resp.ok) setSettingsBundle(await resp.json());
    } finally {
      setSavingSettings(false);
    }
  };

  const handleSaveLlmConfig = async (payload) => {
    setSavingSettings(true);
    try {
      const resp = await fetch("/api/settings/llm", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.ok) setSettingsBundle(await resp.json());
    } finally {
      setSavingSettings(false);
    }
  };

  const value = {
    DEVICES,
    systemStatus,
    telemetry,
    historyMap,
    actions,
    settingsBundle,
    loadingAgent,
    agentResult,
    agentHealth,
    seeding,
    savingSettings,
    verdict,
    pendingApprovals: actions.filter((a) => a.status === "PENDING_APPROVAL").length,
    handleSeedDemo,
    handleCoordinate,
    handleApproveAction,
    handleVerifyAction,
    handleClearActions,
    handleSaveSettings,
    handleSaveLlmConfig,
    fetchSettings,
    fetchAgentHealth,
  };

  return <FarmDataContext.Provider value={value}>{children}</FarmDataContext.Provider>;
}

export function useFarmData() {
  const ctx = useContext(FarmDataContext);
  if (!ctx) throw new Error("useFarmData must be used within FarmDataProvider");
  return ctx;
}
