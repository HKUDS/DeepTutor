"use client";

import { useState } from "react";
import {
  Plus,
  Check,
  Loader2,
  Eye,
  EyeOff,
  ChevronDown,
  TestTube,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { ConfigItem, ConfigType } from "../types";
import {
  PROVIDER_OPTIONS,
  LOCAL_PROVIDERS,
  LOCAL_PROVIDER_URLS,
  VOICE_OPTIONS,
  getEnvVarForBaseUrl,
  getEnvVarForApiKey,
} from "../constants";

interface ConfigFormProps {
  configType: ConfigType;
  showDimensions: boolean;
  showVoice: boolean;
  isSearchConfig: boolean;
  editConfig?: ConfigItem | null;
  onSuccess: () => void;
  onCancel: () => void;
}

export default function ConfigForm({
  configType,
  showDimensions,
  showVoice,
  isSearchConfig,
  editConfig,
  onSuccess,
  onCancel,
}: ConfigFormProps) {
  const isEditMode = !!editConfig;
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // Helper to check if a value uses env reference format
  const isEnvReference = (value: any): boolean => {
    return !!(value && typeof value === "object" && "use_env" in value);
  };

  // Helper to get display value
  const getDisplayValue = (value: any): string => {
    if (isEnvReference(value)) return "";
    return typeof value === "string" ? value : "";
  };

  // Check initial env reference states
  const initialUseEnvBaseUrl = editConfig
    ? isEnvReference(editConfig.base_url)
    : false;
  const initialUseEnvApiKey = editConfig
    ? isEnvReference(editConfig.api_key)
    : false;

  // Form state
  const [name, setName] = useState(editConfig?.name || "");
  const [provider, setProvider] = useState(
    editConfig?.provider || PROVIDER_OPTIONS[configType][0],
  );
  const [baseUrl, setBaseUrl] = useState(
    editConfig ? getDisplayValue(editConfig.base_url) : "",
  );
  const [useEnvBaseUrl, setUseEnvBaseUrl] =
    useState<boolean>(initialUseEnvBaseUrl);
  const [apiKey, setApiKey] = useState("");
  const [useEnvApiKey, setUseEnvApiKey] =
    useState<boolean>(initialUseEnvApiKey);
  const [showApiKey, setShowApiKey] = useState(false);
  const [model, setModel] = useState(editConfig?.model || "");
  const [dimensions, setDimensions] = useState(editConfig?.dimensions || 3072);
  const [voice, setVoice] = useState(editConfig?.voice || "alloy");

  const isLocalProvider = LOCAL_PROVIDERS.includes(provider);

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider);
    if (
      LOCAL_PROVIDERS.includes(newProvider) &&
      LOCAL_PROVIDER_URLS[newProvider]
    ) {
      setBaseUrl(LOCAL_PROVIDER_URLS[newProvider]);
      setUseEnvBaseUrl(false);
      setUseEnvApiKey(false);
      setApiKey("");
    }
  };

  const handleTestConnection = async () => {
    if (isSearchConfig) return;

    if (!useEnvBaseUrl && !baseUrl) {
      setTestResult({
        success: false,
        message: "Base URL is required for testing",
      });
      return;
    }
    if (!isLocalProvider && !useEnvApiKey && !apiKey) {
      setTestResult({
        success: false,
        message: "API Key is required for cloud providers",
      });
      return;
    }
    if (!model) {
      setTestResult({ success: false, message: "Model name is required" });
      return;
    }
    if (configType === "embedding" && !dimensions) {
      setTestResult({
        success: false,
        message: "Dimensions is required for embedding models",
      });
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const res = await fetch(apiUrl(`/api/v1/config/${configType}/test`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          base_url: useEnvBaseUrl
            ? { use_env: getEnvVarForBaseUrl(configType) }
            : baseUrl,
          api_key: isLocalProvider
            ? ""
            : useEnvApiKey
              ? { use_env: getEnvVarForApiKey(configType) }
              : apiKey,
          model,
          ...(configType === "embedding"
            ? { dimensions: Number(dimensions) }
            : {}),
          ...(configType === "tts" && voice ? { voice } : {}),
        }),
      });
      const data = await res.json();
      setTestResult({
        success: data.success ?? false,
        message:
          data.message ||
          (data.success ? "Connection successful" : "Connection failed"),
      });
    } catch (e: any) {
      setTestResult({
        success: false,
        message: e?.message || "Connection test failed - network error",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const payload: Record<string, any> = {
        name,
        provider,
        api_key: isLocalProvider
          ? apiKey || ""
          : useEnvApiKey
            ? { use_env: getEnvVarForApiKey(configType) }
            : apiKey,
      };

      if (!isSearchConfig) {
        payload.base_url = useEnvBaseUrl
          ? { use_env: getEnvVarForBaseUrl(configType) }
          : baseUrl;
        payload.model = model;
      }

      if (showDimensions) {
        payload.dimensions = dimensions;
      }

      if (showVoice) {
        payload.voice = voice;
      }

      const url = isEditMode
        ? apiUrl(`/api/v1/config/${configType}/${editConfig.id}`)
        : apiUrl(`/api/v1/config/${configType}`);
      const method = isEditMode ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        onSuccess();
      } else {
        const data = await res.json();
        setError(
          data.detail ||
            `Failed to ${isEditMode ? "update" : "add"} configuration`,
        );
      }
    } catch (e) {
      setError(`Failed to ${isEditMode ? "update" : "add"} configuration`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-6 p-4 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20"
    >
      <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-4">
        {isEditMode
          ? `Edit Configuration: ${editConfig.name}`
          : "Add New Configuration"}
      </h3>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm border border-red-200 dark:border-red-800">
          {error}
        </div>
      )}

      {testResult && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            testResult.success
              ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800"
              : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800"
          }`}
        >
          {testResult.message}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="My Configuration"
            className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        {/* Provider */}
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
            Provider
          </label>
          <div className="relative">
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm appearance-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {PROVIDER_OPTIONS[configType].map((p) => (
                <option key={p} value={p}>
                  {p}
                  {LOCAL_PROVIDERS.includes(p) ? " (local)" : ""}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          </div>
        </div>

        {/* Base URL (not for search) */}
        {!isSearchConfig && (
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Base URL
              {useEnvBaseUrl && (
                <span className="ml-2 text-xs font-normal text-blue-500">
                  (using ${getEnvVarForBaseUrl(configType)})
                </span>
              )}
            </label>
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <input
                  type="text"
                  value={useEnvBaseUrl ? "" : baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  disabled={useEnvBaseUrl}
                  placeholder={
                    useEnvBaseUrl
                      ? `Using ${getEnvVarForBaseUrl(configType)} from .env`
                      : "https://api.openai.com/v1"
                  }
                  className={`w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                    useEnvBaseUrl
                      ? "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-600 dark:text-blue-400 italic"
                      : "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600"
                  }`}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={useEnvBaseUrl}
                  onChange={(e) => {
                    setUseEnvBaseUrl(e.target.checked);
                    if (e.target.checked) setBaseUrl("");
                  }}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                Use .env
              </label>
            </div>
          </div>
        )}

        {/* API Key */}
        <div className="md:col-span-2">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
            API Key
            {isLocalProvider ? (
              <span className="ml-2 text-xs font-normal text-slate-400">
                (optional for local providers)
              </span>
            ) : useEnvApiKey ? (
              <span className="ml-2 text-xs font-normal text-blue-500">
                (using ${getEnvVarForApiKey(configType)})
              </span>
            ) : null}
          </label>
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <input
                type={showApiKey ? "text" : "password"}
                value={useEnvApiKey ? "" : apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={useEnvApiKey}
                placeholder={
                  isLocalProvider
                    ? "Not required"
                    : useEnvApiKey
                      ? `Using ${getEnvVarForApiKey(configType)} from .env`
                      : "sk-..."
                }
                className={`w-full px-3 py-2 pr-10 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                  useEnvApiKey
                    ? "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-600 dark:text-blue-400 italic"
                    : "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600"
                }`}
              />
              {!useEnvApiKey && (
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  {showApiKey ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              )}
            </div>
            {!isLocalProvider && (
              <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={useEnvApiKey}
                  onChange={(e) => {
                    setUseEnvApiKey(e.target.checked);
                    if (e.target.checked) setApiKey("");
                  }}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                Use .env
              </label>
            )}
          </div>
        </div>

        {/* Model (not for search) */}
        {!isSearchConfig && (
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Model
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              required
              placeholder="gpt-4o"
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
        )}

        {/* Dimensions (embedding only) */}
        {showDimensions && (
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Dimensions
            </label>
            <input
              type="number"
              value={Number.isNaN(dimensions) ? "" : dimensions}
              onChange={(e) => setDimensions(parseInt(e.target.value, 10))}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
        )}

        {/* Voice (TTS only) */}
        {showVoice && (
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Voice
            </label>
            <div className="relative">
              <select
                value={voice}
                onChange={(e) => setVoice(e.target.value)}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm appearance-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {VOICE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex justify-between items-center mt-4">
        <div>
          {!isSearchConfig && (
            <button
              type="button"
              onClick={handleTestConnection}
              disabled={testing || (!baseUrl && !useEnvBaseUrl)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 rounded-lg transition-colors"
            >
              {testing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <TestTube className="w-4 h-4" />
              )}
              Test Connection
            </button>
          )}
        </div>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isEditMode ? (
              <Check className="w-4 h-4" />
            ) : (
              <Plus className="w-4 h-4" />
            )}
            {isEditMode ? "Save Changes" : "Add Configuration"}
          </button>
        </div>
      </div>
    </form>
  );
}
