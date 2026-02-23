"use client";

import { useState, useEffect } from "react";
import {
  Wifi,
  WifiOff,
  Brain,
  Database,
  Volume2,
  Loader2,
  CheckCircle2,
  XCircle,
  RefreshCw,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

interface SystemStatusData {
  backend: {
    status: string;
    timestamp: string;
  };
  llm: {
    status: string;
    model: string | null;
    testable: boolean;
    error?: string;
  };
  embeddings: {
    status: string;
    model: string | null;
    testable: boolean;
    error?: string;
  };
  tts: {
    status: string;
    model: string | null;
    testable: boolean;
    error?: string;
    base_url?: string;
    provider?: string;
  };
}

interface TestResult {
  success: boolean;
  message: string;
  model?: string;
  response_time_ms?: number;
  error?: string;
}

type ModelType = "llm" | "embeddings" | "tts";

export default function SystemStatus() {
  const { uiSettings } = useGlobal();
  const t = (key: string) => getTranslation(uiSettings.language, key);
  const [statusData, setStatusData] = useState<SystemStatusData | null>(null);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(
    null,
  );
  const [testing, setTesting] = useState<Record<ModelType, boolean>>({
    llm: false,
    embeddings: false,
    tts: false,
  });
  const [testResults, setTestResults] = useState<
    Record<ModelType, TestResult | null>
  >({
    llm: null,
    embeddings: null,
    tts: null,
  });

  // Check backend connection status (auto-update every 30 seconds)
  useEffect(() => {
    const checkBackendConnection = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);

        const response = await fetch(apiUrl("/api/v1/knowledge/health"), {
          method: "GET",
          signal: controller.signal,
        });

        clearTimeout(timeoutId);
        setBackendConnected(response.ok);

        // If backend is connected, fetch system status
        if (response.ok) {
          fetchSystemStatus();
        }
      } catch {
        setBackendConnected(false);
      }
    };

    // Initial check
    checkBackendConnection();

    // Check every 30 seconds
    const interval = setInterval(checkBackendConnection, 30000);

    return () => clearInterval(interval);
  }, []);

  const fetchSystemStatus = async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/system/status"));
      if (response.ok) {
        const data = await response.json();
        setStatusData(data);
      }
    } catch {
      // Silently fail - backend connection check will handle this
    }
  };

  const testModelConnection = async (modelType: ModelType) => {
    setTesting((prev) => ({ ...prev, [modelType]: true }));
    setTestResults((prev) => ({ ...prev, [modelType]: null }));

    try {
      const response = await fetch(apiUrl(`/api/v1/system/test/${modelType}`), {
        method: "POST",
      });

      const result: TestResult = await response.json();
      setTestResults((prev) => ({ ...prev, [modelType]: result }));

      // Refresh system status after test
      if (result.success) {
        fetchSystemStatus();
      }
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [modelType]: {
          success: false,
          message: t("Test Failed"),
          error: error instanceof Error ? error.message : t("Unknown Error"),
        },
      }));
    } finally {
      setTesting((prev) => ({ ...prev, [modelType]: false }));
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "online":
      case "configured":
        return "text-green-600 dark:text-green-400";
      case "offline":
      case "not_configured":
      case "error":
        return "text-red-600 dark:text-red-400";
      default:
        return "text-slate-500 dark:text-slate-400";
    }
  };

  const getStatusIcon = (status: string, isBackend: boolean = false) => {
    if (isBackend) {
      return backendConnected ? (
        <Wifi className="w-3 h-3" />
      ) : (
        <WifiOff className="w-3 h-3" />
      );
    }

    switch (status) {
      case "online":
      case "configured":
        return <CheckCircle2 className="w-3 h-3" />;
      case "offline":
      case "not_configured":
      case "error":
        return <XCircle className="w-3 h-3" />;
      default:
        return <div className="w-3 h-3 rounded-full bg-slate-400" />;
    }
  };

  const getStatusText = (status: string, isBackend: boolean = false) => {
    if (isBackend) {
      if (backendConnected === null) return t("Checking...");
      return backendConnected ? t("Online") : t("Offline");
    }

    switch (status) {
      case "online":
        return t("Online");
      case "configured":
        return t("Configured");
      case "offline":
        return t("Offline");
      case "not_configured":
        return t("Not Configured");
      case "error":
        return t("Error");
      default:
        return t("Unknown");
    }
  };

  return (
    <div className="space-y-3">
      {/* Backend Status */}
      <div
        className={`px-3 py-2 rounded-lg flex items-center justify-between text-sm transition-colors border ${
          backendConnected === null
            ? "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-700"
            : backendConnected
              ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 border-green-100 dark:border-green-800"
              : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-100 dark:border-red-800"
        }`}
      >
        <div className="flex items-center gap-2">
          {getStatusIcon("", true)}
          <span className="font-medium">{t("Backend Service")}</span>
        </div>
        <span>{getStatusText("", true)}</span>
      </div>

      {/* Model Statuses */}
      {statusData && (
        <>
          {/* LLM Status */}
          <div
            className={`px-3 py-2.5 rounded-lg border text-sm transition-colors bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <Brain className="w-4 h-4 text-blue-500 dark:text-blue-400" />
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  {t("LLM Model")}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {statusData.llm.status === "configured" && testResults.llm && (
                  <span
                    className={`text-xs ${testResults.llm.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                  >
                    {testResults.llm.success ? "✓" : "✗"}
                  </span>
                )}
                {getStatusIcon(statusData.llm.status)}
                <span
                  className={`text-xs ${getStatusColor(statusData.llm.status)}`}
                >
                  {getStatusText(statusData.llm.status)}
                </span>
              </div>
            </div>
            {statusData.llm.model && (
              <div className="text-xs text-slate-500 dark:text-slate-400 truncate mb-1.5">
                {statusData.llm.model}
              </div>
            )}
            {statusData.llm.testable && (
              <button
                onClick={() => testModelConnection("llm")}
                disabled={testing.llm || !backendConnected}
                className="w-full mt-1.5 px-3 py-1.5 text-xs bg-white dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
              >
                {testing.llm ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>{t("Testing...")}</span>
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>{t("Test Connection")}</span>
                  </>
                )}
              </button>
            )}
            {testResults.llm && (
              <div
                className={`mt-1.5 text-xs ${testResults.llm.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
              >
                {testResults.llm.message}
                {testResults.llm.response_time_ms && (
                  <span className="text-slate-500 dark:text-slate-400 ml-1">
                    ({testResults.llm.response_time_ms}ms)
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Embeddings Status */}
          <div
            className={`px-3 py-2.5 rounded-lg border text-sm transition-colors bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-purple-500 dark:text-purple-400" />
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  向量模型
                </span>
              </div>
              <div className="flex items-center gap-2">
                {statusData.embeddings.status === "configured" &&
                  testResults.embeddings && (
                    <span
                      className={`text-xs ${testResults.embeddings.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                    >
                      {testResults.embeddings.success ? "✓" : "✗"}
                    </span>
                  )}
                {getStatusIcon(statusData.embeddings.status)}
                <span
                  className={`text-xs ${getStatusColor(statusData.embeddings.status)}`}
                >
                  {getStatusText(statusData.embeddings.status)}
                </span>
              </div>
            </div>
            {statusData.embeddings.model && (
              <div className="text-xs text-slate-500 dark:text-slate-400 truncate mb-1.5">
                {statusData.embeddings.model}
              </div>
            )}
            {statusData.embeddings.testable && (
              <button
                onClick={() => testModelConnection("embeddings")}
                disabled={testing.embeddings || !backendConnected}
                className="w-full mt-1.5 px-3 py-1.5 text-xs bg-white dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
              >
                {testing.embeddings ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>测试中...</span>
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>测试连接</span>
                  </>
                )}
              </button>
            )}
            {testResults.embeddings && (
              <div
                className={`mt-1.5 text-xs ${testResults.embeddings.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
              >
                {testResults.embeddings.message}
                {testResults.embeddings.response_time_ms && (
                  <span className="text-slate-500 dark:text-slate-400 ml-1">
                    ({testResults.embeddings.response_time_ms}ms)
                  </span>
                )}
              </div>
            )}
          </div>

          {/* TTS Status */}
          <div
            className={`px-3 py-2.5 rounded-lg border text-sm transition-colors bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700`}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <Volume2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                <span className="font-medium text-slate-700 dark:text-slate-200">
                  TTS 模型
                </span>
              </div>
              <div className="flex items-center gap-2">
                {statusData.tts.status === "configured" && testResults.tts && (
                  <span
                    className={`text-xs ${testResults.tts.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                  >
                    {testResults.tts.success ? "✓" : "✗"}
                  </span>
                )}
                {getStatusIcon(statusData.tts.status)}
                <span
                  className={`text-xs ${getStatusColor(statusData.tts.status)}`}
                >
                  {getStatusText(statusData.tts.status)}
                </span>
              </div>
            </div>
            {statusData.tts.model && (
              <div className="text-xs text-slate-500 dark:text-slate-400 truncate mb-0.5">
                {statusData.tts.model}
              </div>
            )}
            <div className="text-[10px] text-slate-400 dark:text-slate-500 truncate mb-1.5">
              {statusData.tts.base_url || "No endpoint"}
            </div>
            {statusData.tts.testable && (
              <button
                onClick={() => testModelConnection("tts")}
                disabled={testing.tts || !backendConnected}
                className="w-full mt-1.5 px-3 py-1.5 text-xs bg-white dark:bg-slate-700 hover:bg-slate-100 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
              >
                {testing.tts ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>测试中...</span>
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>测试连接</span>
                  </>
                )}
              </button>
            )}
            {testResults.tts && (
              <div
                className={`mt-1.5 text-xs ${testResults.tts.success ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
              >
                {testResults.tts.message}
                {testResults.tts.response_time_ms && (
                  <span className="text-slate-500 dark:text-slate-400 ml-1">
                    ({testResults.tts.response_time_ms}ms)
                  </span>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
