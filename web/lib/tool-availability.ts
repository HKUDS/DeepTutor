export type ToolAvailabilityLanguage = "en" | "zh";

export type ToolAvailabilityCopy = {
  badge: string;
  detail: string;
  href?: string;
};

export function toolEffectiveEnabled(
  savedEnabled: boolean,
  available: boolean,
  comingSoon: boolean,
): boolean {
  return savedEnabled && available && !comingSoon;
}

export function toolAvailabilityCopy(
  reason: string | null | undefined,
  language: ToolAvailabilityLanguage,
): ToolAvailabilityCopy {
  if (reason === "search_provider_not_configured") {
    return language === "zh"
      ? {
          badge: "未配置",
          detail: "请先在搜索设置中选择提供商。DuckDuckGo 无需 API 密钥。",
          href: "/settings#search",
        }
      : {
          badge: "Not configured",
          detail:
            "Choose a provider in Search settings first. DuckDuckGo needs no API key.",
          href: "/settings#search",
        };
  }
  if (reason === "search_credentials_missing") {
    return language === "zh"
      ? {
          badge: "缺少凭证",
          detail: "当前搜索提供商缺少所需凭证，请检查搜索设置。",
          href: "/settings#search",
        }
      : {
          badge: "Credentials missing",
          detail:
            "The selected search provider needs credentials. Check Search settings.",
          href: "/settings#search",
        };
  }
  return language === "zh"
    ? { badge: "暂不可用", detail: "该工具的运行服务当前不可用。" }
    : {
        badge: "Unavailable",
        detail: "This tool's runtime service is unavailable.",
      };
}
