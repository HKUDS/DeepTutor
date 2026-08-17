"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X, Loader2, RotateCw } from "lucide-react";
import {
  mn4WritebackApi,
  type MN4WritebackItem,
} from "@/lib/immersive-reading-api";

export default function MN4WritebackReview() {
  const { t } = useTranslation();
  const [items, setItems] = useState<MN4WritebackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    let active = true;
    mn4WritebackApi
      .list()
      .then((res) => {
        if (active) {
          setItems(res.writebacks.filter(w => w.status === "pending_confirmation"));
          setLoading(false);
        }
      })
      .catch(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleApprove = async (id: string) => {
    setApproving(true);
    try {
      await mn4WritebackApi.approve([id]);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } finally {
      setApproving(false);
    }
  };

  const handleApproveAll = async () => {
    setApproving(true);
    try {
      const ids = items.map(i => i.id);
      await mn4WritebackApi.approve(ids);
      setItems([]);
    } finally {
      setApproving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center p-4">
        <Loader2 className="animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-[var(--muted-foreground)]">
        {t("No pending MarginNote 4 writebacks.")}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t("MarginNote 4 Sync Review")}</h3>
        <button
          onClick={handleApproveAll}
          disabled={approving}
          className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs text-[var(--primary-foreground)] hover:brightness-110 disabled:opacity-50"
        >
          {t("Approve All")}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between rounded-lg border border-[var(--border)] p-3 shadow-sm"
          >
            <div className="flex flex-col">
              <span className="text-xs font-semibold capitalize text-[var(--primary)]">
                {item.source_type}
              </span>
              <span className="text-xs text-[var(--muted-foreground)]">
                {item.id.slice(0, 8)}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => handleApprove(item.id)}
                disabled={approving}
                className="flex items-center justify-center rounded-md border border-[var(--border)] p-1.5 text-green-600 hover:bg-green-50 disabled:opacity-50"
                title={t("Approve")}
              >
                <Check size={14} />
              </button>
              <button
                disabled={approving}
                className="flex items-center justify-center rounded-md border border-[var(--border)] p-1.5 text-red-600 hover:bg-red-50 disabled:opacity-50"
                title={t("Reject")}
              >
                <X size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
