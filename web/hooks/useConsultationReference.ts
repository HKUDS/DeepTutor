"use client";

import { useEffect, useState } from "react";
import { getPartner } from "@/lib/partners-api";
import { getPartnerGroup } from "@/lib/partner-groups-api";

/** Read the same per-turn snapshot used for retry, including restored history. */
export function useConsultationReference(config?: Record<string, unknown>) {
  const groupId = config?.partner_discussion_group_id;
  const partnerId = config?.consult_partner_id;
  const kind = typeof groupId === "string" && groupId ? "partner_group" : "partner";
  const value = kind === "partner_group" ? groupId : partnerId;
  const id = typeof value === "string" ? value : "";
  const key = `${kind}:${id}`;
  const [resolved, setResolved] = useState({ key: "", name: "" });

  useEffect(() => {
    if (!id) return;
    let active = true;
    const request = kind === "partner_group" ? getPartnerGroup(id) : getPartner(id);
    void request.then(entity => {
      if (active) setResolved({ key, name: entity.name });
    }).catch(() => {
      // Deleted or unavailable resources still appear by their stored identity.
    });
    return () => { active = false; };
  }, [id, key, kind]);

  return id ? { id, kind, name: resolved.key === key ? resolved.name : id } : null;
}
