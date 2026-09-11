"use client";

/**
 * Clearing a knowledge point's gate is the one real payoff Mastery Path
 * offers. This is that payoff made visible: three confetti cannons fired
 * from the bottom edge, portalled straight to ``document.body``.
 *
 * Portalled rather than rendered in place: this screen's shell uses
 * ``overflow-hidden`` and the outline column has its own stacking context,
 * so a plain ``position: fixed`` div nested under either would still be a
 * citizen of that box. Escaping to `document.body` is what lets the burst
 * spray across the whole viewport — outline, header, and the conversation
 * all sit under it as one surface, not three.
 *
 * Physics run on a plain 2D canvas; no particle dependency pulled in for a
 * three-second effect. What sells it as paper rather than coloured dots is
 * three things beyond simple ballistics:
 *
 *  - **Tumbling.** Each piece spins about its own horizontal axis, drawn as
 *    a vertical squash (`scale(1, cos φ)`). Edge-on frames read as real
 *    thickness, which a flat rotating rectangle never does.
 *  - **Flutter.** Air does not let paper fall straight. Every piece carries
 *    a sine phase that pushes it sideways as it descends, so the fall is a
 *    sway rather than a drop.
 *  - **Split drag.** Horizontal velocity bleeds off fast while vertical
 *    barely does — that asymmetry is what turns a ballistic arc into the
 *    "shoots out, then hangs and drifts down" shape confetti actually has.
 */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/** Saturated but not neon — these read as paper under both themes. */
const COLORS = [
  "#FF4D6D",
  "#FF8A3D",
  "#FFC53D",
  "#3DD68C",
  "#38BDF8",
  "#7C7CFF",
  "#F472B6",
];

/** Total run, ms. */
const DURATION = 3200;

/** Trailing window over which whatever is still airborne is faded out, so the
 *  effect ends on a dissolve rather than a cut. */
const TAIL_FADE = 550;

/** The physics are authored at 60fps and scaled by real elapsed time, so a
 *  120Hz display runs the same animation rather than a double-speed one. */
const BASE_FRAME_MS = 1000 / 60;

type Shape = "paper" | "sequin" | "streamer";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  w: number;
  h: number;
  color: string;
  shape: Shape;
  /** Rotation in the screen plane. */
  tilt: number;
  tiltSpin: number;
  /** Phase of the tumble about the piece's own horizontal axis. */
  flip: number;
  flipSpeed: number;
  /** Phase + strength of the sideways sway while falling. */
  wobble: number;
  wobbleSpeed: number;
  wobbleStrength: number;
  /** 1 → 0. Drives the per-piece fade so they do not all vanish together. */
  life: number;
  decay: number;
}

interface Cannon {
  x: number;
  y: number;
  /** Radians, measured from straight up; negative leans left. */
  aim: number;
  spread: number;
  count: number;
  /** ms after the first cannon. */
  delay: number;
}

function makeParticle(cannon: Cannon): Particle {
  // Two populations. Most pieces are launched hard — sqrt-distributed so the
  // speeds bunch at the fast end, which is what makes the first 200ms read
  // as a detonation rather than a cloud drifting outward. A minority barely
  // clear the muzzle and flutter down near it, which keeps the lower third
  // of the screen alive after the main wave has passed overhead. Without
  // them the effect empties from the bottom up and looks like it ended
  // early.
  const nearField = Math.random() < 0.18;
  const speed = nearField
    ? 6 + Math.random() * 7
    : 17 + Math.sqrt(Math.random()) * 17;
  const angle =
    -Math.PI / 2 + cannon.aim + (Math.random() - 0.5) * cannon.spread;
  const shapeRoll = Math.random();
  const shape: Shape =
    shapeRoll < 0.66 ? "paper" : shapeRoll < 0.88 ? "sequin" : "streamer";

  const w =
    shape === "streamer" ? 3 + Math.random() * 2 : 7 + Math.random() * 5;
  const h =
    shape === "streamer"
      ? 14 + Math.random() * 10
      : shape === "sequin"
        ? w
        : w * (0.5 + Math.random() * 0.35);

  return {
    x: cannon.x + (Math.random() - 0.5) * 26,
    y: cannon.y + (Math.random() - 0.5) * 14,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    w,
    h,
    color: COLORS[Math.floor(Math.random() * COLORS.length)],
    shape,
    tilt: Math.random() * Math.PI * 2,
    tiltSpin: (Math.random() - 0.5) * 0.24,
    flip: Math.random() * Math.PI * 2,
    // Sequins spin fast enough to glint; paper tumbles lazily.
    flipSpeed: (shape === "sequin" ? 0.18 : 0.09) * (0.6 + Math.random() * 0.9),
    wobble: Math.random() * Math.PI * 2,
    wobbleSpeed: 0.04 + Math.random() * 0.05,
    wobbleStrength: 0.35 + Math.random() * 0.9,
    life: 1,
    // Tuned so the spread of lifetimes straddles DURATION: some pieces are
    // gone well before the end, others are still falling when the tail fade
    // takes them. A shorter decay emptied the screen a full second early and
    // left the effect visibly waiting to finish.
    decay: (nearField ? 0.0026 : 0.0034) + Math.random() * 0.0028,
  };
}

export function LevelUpCelebration({ onDone }: { onDone: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Read once, before the effect: a reduced-motion visitor gets no canvas at
  // all rather than a canvas that quietly renders nothing.
  const reducedMotionRef = useRef(
    typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    if (reducedMotionRef.current) {
      const t = setTimeout(onDone, 400);
      return () => clearTimeout(t);
    }

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) {
      const t = setTimeout(onDone, 0);
      return () => clearTimeout(t);
    }

    let width = window.innerWidth;
    let height = window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    // Two angled cannons at the lower corners crossing in the middle, and a
    // straight-up one a beat later. The stagger is what makes it read as one
    // eruption with depth instead of a single symmetrical pop.
    const cannons: Cannon[] = [
      {
        x: width * 0.14,
        y: height * 0.88,
        aim: 0.42,
        spread: 0.72,
        count: 62,
        delay: 0,
      },
      {
        x: width * 0.86,
        y: height * 0.88,
        aim: -0.42,
        spread: 0.72,
        count: 62,
        delay: 110,
      },
      {
        x: width * 0.5,
        y: height * 0.94,
        aim: 0,
        spread: 1.0,
        count: 56,
        delay: 260,
      },
    ];

    const particles: Particle[] = [];
    const fired = cannons.map(() => false);

    const GRAVITY = 0.42;
    const DRAG_X = 0.968; // sideways speed bleeds off fast…
    const DRAG_Y = 0.995; // …while the fall barely slows: that's the shape.
    const TERMINAL_VY = 9;

    let raf = 0;
    let last = performance.now();
    const start = last;

    const tick = (now: number) => {
      const elapsed = now - start;
      // Clamp so a backgrounded tab that resumes does not teleport every
      // piece off-screen in one enormous step.
      const step = Math.min((now - last) / BASE_FRAME_MS, 3);
      last = now;

      cannons.forEach((cannon, i) => {
        if (!fired[i] && elapsed >= cannon.delay) {
          fired[i] = true;
          for (let n = 0; n < cannon.count; n++) {
            particles.push(makeParticle(cannon));
          }
        }
      });

      ctx.clearRect(0, 0, width, height);

      const tailStart = DURATION - TAIL_FADE;
      const tailFade =
        elapsed > tailStart
          ? Math.max(0, 1 - (elapsed - tailStart) / TAIL_FADE)
          : 1;

      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];

        p.vx *= Math.pow(DRAG_X, step);
        p.vy *= Math.pow(DRAG_Y, step);
        p.vy += GRAVITY * step;
        if (p.vy > TERMINAL_VY) p.vy = TERMINAL_VY;

        p.wobble += p.wobbleSpeed * step;
        // Flutter only matters once the piece has stopped shooting; while it
        // is still fast the ballistic path should dominate.
        const settled = Math.max(0, 1 - Math.abs(p.vx) / 6);
        p.x += (p.vx + Math.cos(p.wobble) * p.wobbleStrength * settled) * step;
        p.y += p.vy * step;

        p.tilt += p.tiltSpin * step;
        p.flip += p.flipSpeed * step;
        p.life -= p.decay * step;

        if (p.life <= 0 || p.y - 40 > height) {
          particles.splice(i, 1);
          continue;
        }
        if (p.x < -60 || p.x > width + 60) continue;

        // Ease the fade so pieces hold full colour most of their life and
        // then go quickly, rather than being half-transparent throughout.
        const alpha = Math.min(1, p.life * 2.2);
        const squash = Math.cos(p.flip);
        // Backs of the pieces read slightly duller than their fronts. It is
        // one multiply, and it is most of what stops a field of tumbling
        // rectangles from looking like flat stickers.
        const facing = squash < 0 ? 0.76 : 1;

        ctx.save();
        ctx.globalAlpha = alpha * facing * tailFade;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.tilt);
        ctx.scale(1, squash);
        ctx.fillStyle = p.color;

        if (p.shape === "sequin") {
          ctx.beginPath();
          ctx.arc(0, 0, p.w / 2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        }
        ctx.restore();
      }

      if (elapsed < DURATION && (particles.length > 0 || elapsed < 400)) {
        raf = requestAnimationFrame(tick);
      } else {
        ctx.clearRect(0, 0, width, height);
        onDone();
      }
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
    // Runs exactly once per mount — the parent forces a remount (a fresh
    // `key`) for every new celebration rather than letting this effect
    // re-fire, so mid-flight particles from the last gate never restart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (typeof document === "undefined" || reducedMotionRef.current) return null;

  return createPortal(
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[999]"
    />,
    document.body,
  );
}
