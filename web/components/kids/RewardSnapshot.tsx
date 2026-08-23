"use client";

import type { CSSProperties } from "react";
import type { KidsRewardSnapshot } from "@/lib/kids-api";

const styles: Record<string, CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    minWidth: 0,
  },
  heading: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
  },
  title: {
    fontSize: 17,
    fontWeight: 750,
    color: "#174a5e",
    margin: 0,
    overflowWrap: "anywhere",
  },
  provider: {
    fontSize: 12,
    color: "#64748b",
    whiteSpace: "nowrap",
    maxWidth: "45%",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  message: {
    fontSize: 15,
    color: "#334155",
    margin: 0,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  items: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  item: {
    display: "flex",
    alignItems: "baseline",
    gap: 6,
    maxWidth: "100%",
    padding: "6px 10px",
    borderRadius: 8,
    background: "#eef6f9",
    color: "#174a5e",
  },
  label: {
    fontSize: 12,
    fontWeight: 700,
    overflowWrap: "anywhere",
  },
  value: {
    fontSize: 15,
    fontWeight: 800,
    overflowWrap: "anywhere",
  },
  detail: {
    fontSize: 12,
    color: "#526574",
    overflowWrap: "anywhere",
  },
};

export function RewardSnapshotView({ reward }: { reward: KidsRewardSnapshot | null }) {
  if (!reward) return null;

  return (
    <section style={styles.container} aria-label={reward.title}>
      <div style={styles.heading}>
        <h3 style={styles.title}>{reward.title}</h3>
        <span style={styles.provider}>{reward.provider}</span>
      </div>
      {reward.message && <p style={styles.message}>{reward.message}</p>}
      {reward.items && reward.items.length > 0 && (
        <div style={styles.items}>
          {reward.items.map((item, index) => (
            <div key={`${item.provider_label}-${index}`} style={styles.item}>
              <span style={styles.label}>{item.provider_label}</span>
              {item.value && <span style={styles.value}>{item.value}</span>}
              {item.detail && <span style={styles.detail}>{item.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
