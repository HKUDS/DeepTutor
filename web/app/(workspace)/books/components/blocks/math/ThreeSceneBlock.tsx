"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MathBlockConfig } from "./mathBlockAdapter";

type ThreeModule = typeof import("three");

const DEFAULT_TITLE = "立体几何 · 三维可视化";
const DEFAULT_HINT = "拖动可旋转视角，松开后自动缓慢转动。";

/**
 * YuEdu fork: Three.js 立体几何 block。
 * 在 useEffect 内 `await import("three")` 按需加载（老代码同模式，规避 SSR 下
 * WebGL 不可用）。默认演示正方体（半透明面 + 棱 + 顶点）。初始化失败有降级提示。
 */
export default function ThreeSceneBlock({
  config,
}: {
  config: MathBlockConfig;
}) {
  const { t } = useTranslation();
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let renderer: import("three").WebGLRenderer | null = null;
    let frame = 0;
    let disposed = false;
    const cleanups: Array<() => void> = [];

    (async () => {
      const THREE: ThreeModule = await import("three");
      if (disposed || !mountRef.current) return;
      const mount = mountRef.current;
      const height = 380;
      const width = mount.clientWidth || 640;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf8f9fa);

      const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
      camera.position.set(3.4, 2.8, 3.8);
      camera.lookAt(0, 0, 0);

      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      mount.appendChild(renderer.domElement);

      scene.add(new THREE.AmbientLight(0xffffff, 0.7));
      const dir = new THREE.DirectionalLight(0xffffff, 0.85);
      dir.position.set(4, 6, 5);
      scene.add(dir);

      const group = new THREE.Group();
      const geo = new THREE.BoxGeometry(2, 2, 2);
      group.add(
        new THREE.Mesh(
          geo,
          new THREE.MeshStandardMaterial({
            color: 0x14bf96,
            transparent: true,
            opacity: 0.3,
            metalness: 0.1,
            roughness: 0.6,
          }),
        ),
      );
      group.add(
        new THREE.LineSegments(
          new THREE.EdgesGeometry(geo),
          new THREE.LineBasicMaterial({ color: 0x0b2149 }),
        ),
      );

      const dotGeo = new THREE.SphereGeometry(0.085, 16, 16);
      const dotMat = new THREE.MeshBasicMaterial({ color: 0x0b2149 });
      const corners: Array<[number, number, number]> = [
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
      ];
      corners.forEach((p) => {
        const d = new THREE.Mesh(dotGeo, dotMat);
        d.position.set(p[0], p[1], p[2]);
        group.add(d);
      });
      scene.add(group);

      let isDown = false;
      let lastX = 0;
      let lastY = 0;
      let rotY = 0.6;
      let rotX = 0.4;
      const onDown = (e: PointerEvent) => {
        isDown = true;
        lastX = e.clientX;
        lastY = e.clientY;
      };
      const onUp = () => {
        isDown = false;
      };
      const onMove = (e: PointerEvent) => {
        if (!isDown) return;
        rotY += (e.clientX - lastX) * 0.01;
        rotX += (e.clientY - lastY) * 0.01;
        lastX = e.clientX;
        lastY = e.clientY;
      };
      renderer.domElement.style.touchAction = "none";
      renderer.domElement.addEventListener("pointerdown", onDown);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointermove", onMove);
      cleanups.push(() => {
        renderer?.domElement.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointermove", onMove);
      });

      const onResize = () => {
        if (!mountRef.current || !renderer) return;
        const w = mountRef.current.clientWidth;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
      };
      window.addEventListener("resize", onResize);
      cleanups.push(() => window.removeEventListener("resize", onResize));

      const animate = () => {
        frame = requestAnimationFrame(animate);
        if (!isDown) rotY += 0.004;
        group.rotation.y = rotY;
        group.rotation.x = rotX;
        renderer?.render(scene, camera);
      };
      animate();
    })().catch((e) => {
      console.error("ThreeScene init failed:", e);
      setError(t("3D scene failed to init. Please refresh."));
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      cleanups.forEach((fn) => fn());
      if (renderer) {
        renderer.dispose();
        const el = renderer.domElement;
        if (el.parentNode) el.parentNode.removeChild(el);
      }
    };
  }, []);

  const title = config.title || DEFAULT_TITLE;
  const hint = config.hint || DEFAULT_HINT;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-base font-bold text-[var(--foreground)]">{title}</h3>
        <span className="rounded-full bg-[var(--background)] px-2.5 py-0.5 text-xs font-medium text-[var(--foreground)]">
          {t("3D visualization")}
        </span>
      </div>
      <div className="relative">
        <div ref={mountRef} className="h-[380px] w-full rounded-lg bg-white" />
        {error && (
          <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-white/90 text-center text-sm text-rose-600 dark:bg-black/70 dark:text-rose-200">
            {error}
          </div>
        )}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {hint}
      </p>
    </div>
  );
}
