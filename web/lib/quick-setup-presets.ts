import type { Discovery, ServiceName } from "@/lib/model-catalog-types";

export interface QuickProviderPreset {
  id: string;
  nameKey: string;
  taglineKey: string;
  keyUrl?: string;
  keyPlaceholderKey?: string;
  recommendedModels: string[];
  badgeKey?: string;
  requiresBaseUrl?: boolean;
  requiresManualModel?: boolean;
}

export const FEATURED_DOMESTIC_PROVIDERS: QuickProviderPreset[] = [
  {
    id: "deepseek",
    nameKey: "quickSetup.vendor.deepseek.name",
    taglineKey: "quickSetup.vendor.deepseek.tagline",
    keyUrl: "https://platform.deepseek.com/api_keys",
    recommendedModels: ["deepseek-chat", "deepseek-reasoner"],
    badgeKey: "quickSetup.badge.recommended",
  },
  {
    id: "dashscope",
    nameKey: "quickSetup.vendor.dashscope.name",
    taglineKey: "quickSetup.vendor.dashscope.tagline",
    keyUrl: "https://bailian.console.aliyun.com/?apiKey=1",
    recommendedModels: ["qwen-plus", "qwen-max", "qwen-turbo"],
    badgeKey: "quickSetup.badge.allInOne",
  },
  {
    id: "siliconflow",
    nameKey: "quickSetup.vendor.siliconflow.name",
    taglineKey: "quickSetup.vendor.siliconflow.tagline",
    keyUrl: "https://cloud.siliconflow.cn/account/ak",
    recommendedModels: [
      "deepseek-ai/DeepSeek-V3",
      "deepseek-ai/DeepSeek-R1",
      "Qwen/Qwen2.5-72B-Instruct",
    ],
    badgeKey: "quickSetup.badge.starterCredits",
  },
  {
    id: "zhipu",
    nameKey: "quickSetup.vendor.zhipu.name",
    taglineKey: "quickSetup.vendor.zhipu.tagline",
    keyUrl: "https://open.bigmodel.cn/usercenter/apikeys",
    keyPlaceholderKey: "quickSetup.placeholder.apiKey",
    recommendedModels: ["glm-4-plus", "glm-4-flash", "glm-4-air"],
  },
  {
    id: "moonshot",
    nameKey: "quickSetup.vendor.moonshot.name",
    taglineKey: "quickSetup.vendor.moonshot.tagline",
    keyUrl: "https://platform.moonshot.cn/console/api-keys",
    recommendedModels: ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k"],
  },
  {
    id: "volcengine",
    nameKey: "quickSetup.vendor.volcengine.name",
    taglineKey: "quickSetup.vendor.volcengine.tagline",
    keyUrl: "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    keyPlaceholderKey: "quickSetup.placeholder.apiKey",
    recommendedModels: ["doubao-1-5-pro-32k-250115", "doubao-seed-1-6-250615"],
  },
];

export const MORE_PROVIDERS: QuickProviderPreset[] = [
  {
    id: "minimax",
    nameKey: "quickSetup.vendor.minimax.name",
    taglineKey: "quickSetup.vendor.minimax.tagline",
    keyUrl: "https://platform.minimaxi.com/user-center/basic-information/interface-key",
    keyPlaceholderKey: "quickSetup.placeholder.apiKey",
    recommendedModels: ["MiniMax-M1", "MiniMax-Text-01"],
  },
  {
    id: "qianfan",
    nameKey: "quickSetup.vendor.qianfan.name",
    taglineKey: "quickSetup.vendor.qianfan.tagline",
    keyUrl: "https://console.bce.baidu.com/qianfan/ais/console/apiKey",
    keyPlaceholderKey: "quickSetup.placeholder.apiKey",
    recommendedModels: ["ernie-4.5-turbo-128k", "ernie-4.0-8k"],
  },
  {
    id: "openai",
    nameKey: "quickSetup.vendor.openai.name",
    taglineKey: "quickSetup.vendor.openai.tagline",
    keyUrl: "https://platform.openai.com/api-keys",
    recommendedModels: ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
  },
  {
    id: "anthropic",
    nameKey: "quickSetup.vendor.anthropic.name",
    taglineKey: "quickSetup.vendor.anthropic.tagline",
    keyUrl: "https://console.anthropic.com/settings/keys",
    recommendedModels: ["claude-sonnet-4-20250514", "claude-3-7-sonnet-20250219"],
  },
  {
    id: "gemini",
    nameKey: "quickSetup.vendor.gemini.name",
    taglineKey: "quickSetup.vendor.gemini.tagline",
    keyUrl: "https://aistudio.google.com/apikey",
    recommendedModels: ["gemini-2.5-flash", "gemini-2.5-pro"],
  },
  {
    id: "openrouter",
    nameKey: "quickSetup.vendor.openrouter.name",
    taglineKey: "quickSetup.vendor.openrouter.tagline",
    keyUrl: "https://openrouter.ai/keys",
    recommendedModels: ["openai/gpt-4o-mini", "deepseek/deepseek-chat-v3-0324"],
  },
  {
    id: "custom",
    nameKey: "quickSetup.vendor.custom.name",
    taglineKey: "quickSetup.vendor.custom.tagline",
    recommendedModels: [],
    requiresBaseUrl: true,
    requiresManualModel: true,
  },
];

export const ALL_QUICK_PROVIDERS: QuickProviderPreset[] = [
  ...FEATURED_DOMESTIC_PROVIDERS,
  ...MORE_PROVIDERS,
];

const GLOBAL_FEATURED_IDS = [
  "openai",
  "anthropic",
  "gemini",
  "openrouter",
  "deepseek",
  "custom",
];

/**
 * Return featured + overflow provider lists tailored to the UI locale:
 * Chinese locales prioritize domestic providers; non-Chinese locales
 * prioritize international providers.
 */
export function getQuickProviderGroups(language: string): {
  featured: QuickProviderPreset[];
  more: QuickProviderPreset[];
} {
  const isZh = language.toLowerCase().startsWith("zh");
  if (isZh) {
    return {
      featured: FEATURED_DOMESTIC_PROVIDERS,
      more: MORE_PROVIDERS,
    };
  }
  const byId = new Map(ALL_QUICK_PROVIDERS.map((item) => [item.id, item]));
  const featured = GLOBAL_FEATURED_IDS.map((id) => byId.get(id)).filter(
    (item): item is QuickProviderPreset => Boolean(item),
  );
  const featuredSet = new Set(featured.map((item) => item.id));
  const more = ALL_QUICK_PROVIDERS.filter((item) => !featuredSet.has(item.id));
  return { featured, more };
}

export function findQuickPreset(providerId: string): QuickProviderPreset | undefined {
  return ALL_QUICK_PROVIDERS.find((item) => item.id === providerId);
}

/** Pick the best default model given discovered models and vendor recommendations. */
export function pickRecommendedModel(
  preset: QuickProviderPreset,
  discovered: string[],
): string {
  if (discovered.length > 0) {
    const lowerMap = new Map(discovered.map((id) => [id.toLowerCase(), id]));
    for (const candidate of preset.recommendedModels) {
      const exact = lowerMap.get(candidate.toLowerCase());
      if (exact) return exact;
    }
    for (const candidate of preset.recommendedModels) {
      const prefix = discovered.find((id) =>
        id.toLowerCase().includes(candidate.toLowerCase()),
      );
      if (prefix) return prefix;
    }
    return discovered[0];
  }
  return preset.recommendedModels[0] ?? "";
}

export interface FriendlyErrorResult {
  titleKey: string;
  detailKey: string;
  raw?: string;
}

/** Translate technical HTTP/provider errors into i18n keys for plain, actionable guidance. */
export function formatFriendlySetupError(
  discovery?: Discovery | null,
  rawError?: string,
): FriendlyErrorResult {
  const status = discovery?.status ?? "";
  const raw =
    rawError ||
    discovery?.warning ||
    (discovery?.http_status ? `HTTP ${discovery.http_status}` : "") ||
    status ||
    "";
  const lower = raw.toLowerCase();

  if (
    status === "auth_error" ||
    lower.includes("401") ||
    lower.includes("invalid_api_key") ||
    lower.includes("incorrect api key") ||
    lower.includes("unauthorized") ||
    lower.includes("authentication")
  ) {
    return {
      titleKey: "quickSetup.error.authTitle",
      detailKey: "quickSetup.error.authDetail",
      raw,
    };
  }

  if (
    lower.includes("402") ||
    lower.includes("insufficient") ||
    lower.includes("balance") ||
    lower.includes("quota") ||
    lower.includes("billing") ||
    lower.includes("credit")
  ) {
    return {
      titleKey: "quickSetup.error.quotaTitle",
      detailKey: "quickSetup.error.quotaDetail",
      raw,
    };
  }

  if (
    status === "timeout" ||
    status === "unreachable" ||
    lower.includes("timeout") ||
    lower.includes("connect") ||
    lower.includes("network") ||
    lower.includes("dns")
  ) {
    return {
      titleKey: "quickSetup.error.networkTitle",
      detailKey: "quickSetup.error.networkDetail",
      raw,
    };
  }

  if (lower.includes("403") || lower.includes("404") || lower.includes("permission")) {
    return {
      titleKey: "quickSetup.error.accessTitle",
      detailKey: "quickSetup.error.accessDetail",
      raw,
    };
  }

  return {
    titleKey: "quickSetup.error.genericTitle",
    detailKey: "quickSetup.error.genericDetail",
    raw,
  };
}

export const SYNCABLE_EXTRA_SERVICES: {
  service: ServiceName;
  titleKey: string;
  descKey: string;
}[] = [
  {
    service: "embedding",
    titleKey: "quickSetup.extra.embedding.title",
    descKey: "quickSetup.extra.embedding.desc",
  },
  {
    service: "tts",
    titleKey: "quickSetup.extra.tts.title",
    descKey: "quickSetup.extra.tts.desc",
  },
  {
    service: "stt",
    titleKey: "quickSetup.extra.stt.title",
    descKey: "quickSetup.extra.stt.desc",
  },
];
