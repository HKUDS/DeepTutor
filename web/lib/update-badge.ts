import type { UpdateCheckResponse } from "@/lib/update-api";
import { normalizeVersionTag } from "@/lib/version";

export type UpdateBadgePresentation =
  | {
      kind: "available";
      version: string;
      href: string;
      hostManaged: boolean;
      installMode: UpdateCheckResponse["install_mode"];
      canAutoUpdate: boolean;
    }
  | { kind: "up_to_date"; version: string | null; href: string | null }
  | { kind: "failed" };

export function presentUpdateBadge(
  update: UpdateCheckResponse,
): UpdateBadgePresentation {
  if (
    update.status === "available" &&
    update.latest_version &&
    update.release_url
  ) {
    return {
      kind: "available",
      version:
        normalizeVersionTag(update.latest_version) ?? update.latest_version,
      href: update.release_url,
      hostManaged: update.install_mode === "docker",
      installMode: update.install_mode,
      canAutoUpdate: update.can_auto_update,
    };
  }
  if (update.status === "up_to_date") {
    return {
      kind: "up_to_date",
      version: normalizeVersionTag(update.latest_version ?? ""),
      href: update.release_url,
    };
  }
  return { kind: "failed" };
}
