"use client";

import { useState, useEffect } from "react";
import {
  Settings as SettingsIcon,
  Brain,
  Database,
  Volume2,
  Search,
  Loader2,
  Sun,
  Moon,
  Globe,
  Trash2,
  AlertTriangle,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { useGlobal } from "@/context/GlobalContext";
import { OverviewTab, ConfigTab } from "./components";
import { FullStatus, PortsInfo, TabType } from "./types";
import { LANGUAGE_OPTIONS } from "./constants";
import { getStorageStats } from "@/lib/persistence";

export default function SettingsPage() {
  const { uiSettings, updateTheme, updateLanguage, clearAllPersistence } = useGlobal();
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [storageStats, setStorageStats] = useState<{ totalSize: number; items: { key: string; size: number }[] } | null>(null);

  // Load storage stats
  useEffect(() => {
    setStorageStats(getStorageStats());
  }, []);

  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [status, setStatus] = useState<FullStatus | null>(null);
  const [ports, setPorts] = useState<PortsInfo | null>(null);
  const [loading, setLoading] = useState(true);

  // Load initial data
  useEffect(() => {
    loadStatus();
    loadPorts();
  }, []);

  const loadStatus = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/config/status"));
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (e) {
      console.error("Failed to load config status:", e);
    } finally {
      setLoading(false);
    }
  };

  const loadPorts = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/config/ports"));
      if (res.ok) {
        const data = await res.json();
        setPorts(data);
      }
    } catch (e) {
      console.error("Failed to load ports:", e);
    }
  };

  const tabs: { id: TabType; label: string; icon: React.ReactNode }[] = [
    {
      id: "overview",
      label: "Overview",
      icon: <SettingsIcon className="w-4 h-4" />,
    },
    { id: "llm", label: "LLM", icon: <Brain className="w-4 h-4" /> },
    {
      id: "embedding",
      label: "Embedding",
      icon: <Database className="w-4 h-4" />,
    },
    { id: "tts", label: "TTS", icon: <Volume2 className="w-4 h-4" /> },
    { id: "search", label: "Search", icon: <Search className="w-4 h-4" /> },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-900 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-xl">
            <SettingsIcon className="w-6 h-6 text-blue-600 dark:text-blue-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {uiSettings.language === "zh" ? "设置" : "Settings"}
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {uiSettings.language === "zh"
                ? "配置 AI 服务和界面偏好"
                : "Configure your AI services and preferences"}
            </p>
          </div>
        </div>

        {/* General Settings - Theme & Language */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-4 mb-6">
          <div className="flex flex-wrap items-center gap-6">
            {/* Theme Toggle */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                {uiSettings.theme === "dark" ? (
                  <Moon className="w-4 h-4" />
                ) : (
                  <Sun className="w-4 h-4" />
                )}
                <span>{uiSettings.language === "zh" ? "主题" : "Theme"}</span>
              </div>
              <div className="flex p-1 bg-slate-100 dark:bg-slate-700 rounded-lg">
                <button
                  onClick={() => updateTheme("light")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-all ${
                    uiSettings.theme === "light"
                      ? "bg-white dark:bg-slate-600 text-slate-900 dark:text-slate-100 shadow-sm"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                  }`}
                >
                  <Sun className="w-3.5 h-3.5" />
                  {uiSettings.language === "zh" ? "浅色" : "Light"}
                </button>
                <button
                  onClick={() => updateTheme("dark")}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-all ${
                    uiSettings.theme === "dark"
                      ? "bg-white dark:bg-slate-600 text-slate-900 dark:text-slate-100 shadow-sm"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                  }`}
                >
                  <Moon className="w-3.5 h-3.5" />
                  {uiSettings.language === "zh" ? "深色" : "Dark"}
                </button>
              </div>
            </div>

            {/* Separator */}
            <div className="h-8 w-px bg-slate-200 dark:bg-slate-700 hidden sm:block" />

            {/* Language Selector */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                <Globe className="w-4 h-4" />
                <span>
                  {uiSettings.language === "zh" ? "语言" : "Language"}
                </span>
              </div>
              <div className="flex p-1 bg-slate-100 dark:bg-slate-700 rounded-lg">
                {LANGUAGE_OPTIONS.map((lang) => (
                  <button
                    key={lang.value}
                    onClick={() => updateLanguage(lang.value)}
                    className={`px-3 py-1.5 rounded-md text-sm transition-all ${
                      uiSettings.language === lang.value
                        ? "bg-white dark:bg-slate-600 text-slate-900 dark:text-slate-100 shadow-sm"
                        : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                    }`}
                  >
                    {lang.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Separator */}
            <div className="h-8 w-px bg-slate-200 dark:bg-slate-700 hidden sm:block" />

            {/* Clear Data */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                <Trash2 className="w-4 h-4" />
                <span>
                  {uiSettings.language === "zh" ? "本地数据" : "Local Data"}
                </span>
                {storageStats && (
                  <span className="text-xs text-slate-400 dark:text-slate-500">
                    ({(storageStats.totalSize / 1024).toFixed(1)} KB)
                  </span>
                )}
              </div>
              <button
                onClick={() => setShowClearConfirm(true)}
                className="px-3 py-1.5 rounded-md text-sm bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-all"
              >
                {uiSettings.language === "zh" ? "清除缓存" : "Clear Cache"}
              </button>
            </div>
          </div>
        </div>

        {/* Clear Confirmation Modal */}
        {showClearConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 max-w-md mx-4 shadow-2xl">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-3 bg-red-100 dark:bg-red-900/30 rounded-xl">
                  <AlertTriangle className="w-6 h-6 text-red-600 dark:text-red-400" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    {uiSettings.language === "zh" ? "确认清除" : "Confirm Clear"}
                  </h3>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {uiSettings.language === "zh"
                      ? "此操作将清除所有本地缓存数据"
                      : "This will clear all locally cached data"}
                  </p>
                </div>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-300 mb-6">
                {uiSettings.language === "zh"
                  ? "包括：聊天记录、解题历史、题目生成结果、研究报告、创意生成、引导学习进度、Co-Writer 内容等。此操作不可撤销。"
                  : "Including: chat history, solver history, question results, research reports, idea generation, guided learning progress, Co-Writer content, etc. This action cannot be undone."}
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowClearConfirm(false)}
                  className="px-4 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-all"
                >
                  {uiSettings.language === "zh" ? "取消" : "Cancel"}
                </button>
                <button
                  onClick={() => {
                    clearAllPersistence();
                    setShowClearConfirm(false);
                    setStorageStats(getStorageStats());
                  }}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-all"
                >
                  {uiSettings.language === "zh" ? "确认清除" : "Clear All"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-xl mb-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab.id
                  ? "bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm"
                  : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          {activeTab === "overview" && (
            <OverviewTab status={status} ports={ports} onRefresh={loadStatus} />
          )}
          {activeTab === "llm" && (
            <ConfigTab
              configType="llm"
              title="LLM Configuration"
              description="Configure language model providers"
              onUpdate={loadStatus}
            />
          )}
          {activeTab === "embedding" && (
            <ConfigTab
              configType="embedding"
              title="Embedding Configuration"
              description="Configure embedding model providers"
              onUpdate={loadStatus}
              showDimensions
            />
          )}
          {activeTab === "tts" && (
            <ConfigTab
              configType="tts"
              title="TTS Configuration"
              description="Configure text-to-speech providers"
              onUpdate={loadStatus}
              showVoice
            />
          )}
          {activeTab === "search" && (
            <ConfigTab
              configType="search"
              title="Search Configuration"
              description="Configure web search providers"
              onUpdate={loadStatus}
              isSearchConfig
            />
          )}
        </div>
      </div>
    </div>
  );
}
