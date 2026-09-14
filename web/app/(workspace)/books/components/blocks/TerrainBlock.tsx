"use client";

import { useEffect, useRef } from "react";
import type { Block } from "@/lib/book-types";

function isFiniteCoordinate(value: unknown): boolean {
  return (
    (typeof value === "number" ||
      (typeof value === "string" && value.trim() !== "")) &&
    Number.isFinite(Number(value))
  );
}

/**
 * YuEdu fork: 地形 block 渲染组件（地理专用）。
 * 用 Leaflet（OpenStreetMap）渲染交互式地图 + 标记点 + 描述。
 * Payload 形如:
 * {
 *   title: "中国三大平原",
 *   description: "东北平原、华北平原、长江中下游平原",
 *   zoom: 4,
 *   markers: [
 *     { name: "东北平原", lat: 44.0, lng: 125.0, event: "中国最大的平原，面积约35万km²" },
 *     { name: "华北平原", lat: 36.0, lng: 115.0, event: "黄河冲积形成，人口稠密" }
 *   ]
 * }
 */
export default function TerrainBlock({ block }: { block: Block }) {
  const params = (block.payload as Record<string, unknown> | undefined) ?? {};
  const title = String(params.title ?? "");
  const description = String(params.description ?? "");
  const markers = Array.isArray(params.markers)
    ? params.markers.filter(
        (marker): marker is Record<string, unknown> =>
          typeof marker === "object" &&
          marker !== null &&
          !Array.isArray(marker) &&
          isFiniteCoordinate((marker as Record<string, unknown>).lat) &&
          isFiniteCoordinate((marker as Record<string, unknown>).lng),
      )
    : [];
  const requestedZoom = Number(params.zoom ?? 4);
  const zoom = Number.isFinite(requestedZoom) ? requestedZoom : 4;
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<unknown>(null);

  useEffect(() => {
    if (!mapRef.current || markers.length === 0) return;

    // 动态加载 Leaflet CSS + JS（CDN，仅首次加载）
    const loadLeaflet = async () => {
      // CSS
      if (!document.querySelector('link[href*="leaflet"]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      const w = window as unknown as Record<string, unknown>;
      // JS
      if (!w.L) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
          script.onload = () => resolve();
          script.onerror = () => reject(new Error("Leaflet failed to load"));
          document.head.appendChild(script);
        });
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const L = w.L as any;

      // 计算中心点
      const lats = markers.map((marker) => Number(marker.lat));
      const lngs = markers.map((marker) => Number(marker.lng));
      const centerLat = lats.length ? lats.reduce((a, b) => a + b, 0) / lats.length : 35.0;
      const centerLng = lngs.length ? lngs.reduce((a, b) => a + b, 0) / lngs.length : 105.0;

      // 清除旧地图
      if (mapInstanceRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mapInstanceRef.current as any)?.remove?.();
      }

      const map = L.map(mapRef.current!).setView([centerLat, centerLng], zoom);
      mapInstanceRef.current = map;

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap",
        maxZoom: 18,
      }).addTo(map);

      markers.forEach((marker) => {
        const lat = Number(marker.lat);
        const lng = Number(marker.lng);
        const m = L.marker([lat, lng]).addTo(map);
        const name = String(marker.name ?? "");
        const event = String(marker.event ?? marker.description ?? "");
        if (name || event) {
          m.bindPopup(`<strong>${name}</strong>${event ? "<br/>" + event : ""}`);
        }
      });
    };

    loadLeaflet().catch(() => {
      if (mapRef.current) {
        mapRef.current.innerHTML =
          '<div class="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">地图加载失败，请检查网络连接</div>';
      }
    });

    return () => {
      if (mapInstanceRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mapInstanceRef.current as any)?.remove?.();
        mapInstanceRef.current = null;
      }
    };
  }, [markers, zoom]);

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      {title && (
        <h3 className="mb-1 text-base font-bold text-[var(--foreground)]">{title}</h3>
      )}
      {description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">{description}</p>
      )}
      {markers.length > 0 ? (
        <div
          ref={mapRef}
          className="h-72 w-full overflow-hidden rounded-xl border border-[var(--border)]"
          style={{ zIndex: 0 }}
        />
      ) : (
        <div className="flex h-40 items-center justify-center text-sm text-[var(--muted-foreground)]">
          暂无地图数据
        </div>
      )}
      {markers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {markers.map((m, i) => (
            <span
              key={i}
              className="rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-xs text-[var(--primary)]"
            >
              📍 {String(m.name ?? "")}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
