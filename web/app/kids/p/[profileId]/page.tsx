"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { RewardSnapshotView } from "@/components/kids/RewardSnapshot";
import {
  kidsApi,
  type KidsProfile,
  type KidsLibraryItem,
  type KidsRewardSnapshot,
} from "@/lib/kids-api";

/**
 * Dedicated child entry point.
 *
 * URL pattern: /kids/p/{profile_id}
 *
 * The parent bookmarks this on the child's device. On first visit:
 *   - If the profile has no PIN → auto-select and enter the shelf.
 *   - If the profile has a PIN → show a PIN pad; on success store the device
 *     token in localStorage and enter the shelf.
 *
 * On subsequent visits the stored token is reused (no PIN prompt).
 *
 * The shelf's "Exit" button triggers PIN verification before clearing the
 * token, so the child can't accidentally wander out of Kids mode.
 */
export default function KidsProfileEntryPage() {
  const router = useRouter();
  const params = useParams();
  const profileId = params.profileId as string;

  const [stage, setStage] = useState<
    "loading" | "pin" | "shelf" | "not_found"
  >("loading");
  const [profile, setProfile] = useState<KidsProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [reward, setReward] = useState<KidsRewardSnapshot | null>(null);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState("");
  const [error, setError] = useState("");
  // Exit-protection state
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");

  const enterShelf = async (p: KidsProfile) => {
    try {
      const { token } = await kidsApi.selectProfile(p.id);
      localStorage.setItem("dt_kids_token", token);
      localStorage.setItem("dt_kids_profile_id", p.id);
      const { library: lib } = await kidsApi.library();
      const { reward: nextReward } = await kidsApi.getRewards();
      setProfile(p);
      setLibrary(lib);
      setReward(nextReward);
      setStage("shelf");
    } catch {
      setError("Cannot load books. Try again!");
      setStage("pin");
    }
  };

  // ── On mount: check for existing token or fetch profile info ──────────
  const bootstrap = useCallback(async () => {
    const storedToken =
      typeof window !== "undefined"
        ? localStorage.getItem("dt_kids_token")
        : null;
    const storedPid =
      typeof window !== "undefined"
        ? localStorage.getItem("dt_kids_profile_id")
        : null;

    if (storedToken && storedPid === profileId) {
      try {
        const { library: lib } = await kidsApi.library();
        try {
          const { profiles } = await kidsApi.bootstrap();
          const p = profiles.find((x) => x.id === profileId);
          if (p) setProfile(p);
        } catch {}
        setLibrary(lib);
        try {
          const { reward: nextReward } = await kidsApi.getRewards();
          setReward(nextReward);
        } catch {}
        setStage("shelf");
        return;
      } catch {
        localStorage.removeItem("dt_kids_token");
        localStorage.removeItem("dt_kids_profile_id");
      }
    }

    try {
      const { profiles } = await kidsApi.bootstrap();
      const p = profiles.find((x) => x.id === profileId);
      if (!p) {
        setStage("not_found");
        return;
      }
      setProfile(p);
      if (p.has_pin) {
        setStage("pin");
      } else {
        await enterShelf(p);
      }
    } catch {
      setError("Cannot connect. Ask a grown-up for help.");
      setStage("not_found");
    }
  }, [profileId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!cancelled) {
        await bootstrap();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bootstrap]);

  const handlePinSubmit = async () => {
    if (!profile) return;
    try {
      const { token } = await kidsApi.parentUnlock(profile.id, pinInput);
      localStorage.setItem("dt_kids_token", token);
      localStorage.setItem("dt_kids_profile_id", profile.id);
      const { library: lib } = await kidsApi.library();
      const { reward: nextReward } = await kidsApi.getRewards();
      setLibrary(lib);
      setReward(nextReward);
      setStage("shelf");
    } catch {
      setPinError("Wrong PIN. Try again!");
      setPinInput("");
    }
  };

  const handleExitClick = () => {
    if (profile?.has_pin) {
      setShowExitPin(true);
      setExitPin("");
      setExitPinError("");
    } else {
      doExit();
    }
  };

  const doExit = () => {
    localStorage.removeItem("dt_kids_token");
    localStorage.removeItem("dt_kids_profile_id");
    setReward(null);
    router.push("/kids");
  };

  const handleExitPinSubmit = async () => {
    if (!profile) return;
    try {
      await kidsApi.exitVerify(profile.id, exitPin);
      doExit();
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  if (stage === "loading") {
    return (
      <div style={S.center}>
        <div style={S.spinner}>📚</div>
      </div>
    );
  }

  if (stage === "not_found") {
    return (
      <div style={S.container}>
        <h1 style={S.title}>Oops!</h1>
        <p style={S.subtitle}>{error || "Profile not found."}</p>
        <a href="/kids/manage" style={S.link}>
          Go to Parent Settings
        </a>
      </div>
    );
  }

  if (stage === "pin") {
    return (
      <div style={S.container}>
        <div style={S.header}>
          <h1 style={S.title}>🔒 Grown-Up PIN</h1>
          <p style={S.subtitle}>Ask a grown-up to enter the PIN</p>
        </div>
        <div style={S.pinPad}>
          <input
            type="password"
            value={pinInput}
            onChange={(e) => setPinInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && pinInput.length >= 4 && handlePinSubmit()}
            maxLength={8}
            style={S.pinInput}
            placeholder="• • • •"
            autoFocus
          />
          {pinError && <p style={S.errorText}>{pinError}</p>}
          {error && <p style={S.errorText}>{error}</p>}
          <button
            style={{ ...S.btn, ...S.btnPrimary, opacity: pinInput.length < 4 ? 0.5 : 1 }}
            onClick={handlePinSubmit}
            disabled={pinInput.length < 4}
          >
            Enter →
          </button>
        </div>
      </div>
    );
  }

  // Bookshelf
  return (
    <div style={S.container}>
      {showExitPin && (
        <div style={S.overlay}>
          <div style={S.pinPad}>
            <p style={S.subtitle}>🔒 Enter PIN to exit</p>
            <input
              type="password"
              value={exitPin}
              onChange={(e) => setExitPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && exitPin.length >= 4 && handleExitPinSubmit()}
              maxLength={8}
              style={S.pinInput}
              placeholder="• • • •"
              autoFocus
            />
            {exitPinError && <p style={S.errorText}>{exitPinError}</p>}
            <div style={{ display: "flex", gap: 12 }}>
              <button
                style={{ ...S.btn, ...S.btnSecondary }}
                onClick={() => { setShowExitPin(false); setExitPin(""); setExitPinError(""); }}
              >
                Cancel
              </button>
              <button
                style={{ ...S.btn, ...S.btnPrimary, opacity: exitPin.length < 4 ? 0.5 : 1 }}
                onClick={handleExitPinSubmit}
                disabled={exitPin.length < 4}
              >
                Exit
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={S.shelfHeader}>
        <button style={S.backBtn} onClick={handleExitClick}>👈</button>
        <h1 style={S.shelfTitle}>{profile?.name}&apos;s Books</h1>
      </div>
      <RewardSnapshotView reward={reward} />

      {library.length === 0 ? (
        <div style={S.emptyShelf}>
          <div style={{ fontSize: 64 }}>📖</div>
          <p style={S.subtitle}>No books yet! Ask a grown-up to add books.</p>
        </div>
      ) : (
        <div style={S.bookGrid}>
          {library.map((item) => {
            const isInteractive = item.content_type === "interactive_book" || Boolean(item.book);
            const title = (isInteractive ? item.book?.title : (item.document as Record<string, string>)?.title) || item.assignment.document_title || "Unknown";
            const targetBookId = item.assignment.book_id || item.book?.id || item.assignment.document_id || "";
            const targetUrl = isInteractive
              ? `/kids/p/${profileId}/book/${targetBookId}`
              : `/kids/${item.assignment.document_id || targetBookId}`;
            const coverUrl = isInteractive
              ? kidsApi.getInteractiveCoverUrl(targetBookId)
              : kidsApi.getCoverUrl(item.assignment.document_id || targetBookId);
            const completed = isInteractive
              ? (item.progress as any)?.completed_page_ids?.length || 0
              : (item.progress as any)?.completed_section_ids?.length || 0;

            return (
              <button
                key={item.assignment.id || targetBookId}
                style={S.bookCard}
                onClick={() => router.push(targetUrl)}
              >
                <img src={coverUrl} alt={title} style={S.bookCover}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                <div style={S.bookInfo}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 700,
                      padding: "2px 8px",
                      borderRadius: 10,
                      background: isInteractive ? "#f3e8ff" : "#e0f2fe",
                      color: isInteractive ? "#6b21a8" : "#0369a1",
                    }}>
                      {isInteractive ? "🔢 互动书" : "📖 故事绘本"}
                    </span>
                  </div>
                  <div style={S.bookTitle}>{title}</div>
                  {completed > 0 && (
                    <div style={S.bookProgress}>
                      已学完 {completed} 节
                    </div>
                  )}
                  {item.assignment.is_next_read && (
                    <div style={S.nextReadBadge}>接着学这个！→</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

const S: Record<string, React.CSSProperties> = {
  center: {
    display: "flex", alignItems: "center", justifyContent: "center",
    minHeight: "100vh", background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
  },
  spinner: { fontSize: 80 },
  container: {
    minHeight: "100vh",
    height: "100vh",
    overflowY: "auto",
    background: "linear-gradient(180deg, #e0f2ff 0%, #fef3e7 50%, #f0fdf4 100%)",
    padding: "24px 16px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    WebkitOverflowScrolling: "touch",
  },
  header: { textAlign: "center", marginBottom: 32, marginTop: 20 },
  title: { fontSize: 36, fontWeight: 800, color: "#4a3f6b", margin: 0 },
  subtitle: { fontSize: 18, color: "#7c6f9b", marginTop: 8 },
  errorText: { fontSize: 16, color: "#e53e3e", textAlign: "center", marginTop: 12 },
  link: { fontSize: 16, color: "#667eea", marginTop: 16, display: "inline-block" },
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
  },
  pinPad: {
    background: "white", borderRadius: 24, padding: 32,
    display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
    boxShadow: "0 4px 14px rgba(0,0,0,0.1)", maxWidth: 360, width: "90%",
  },
  pinInput: {
    fontSize: 32, textAlign: "center", letterSpacing: 12,
    border: "3px solid #667eea", borderRadius: 12, padding: "12px 16px",
    width: "100%", outline: "none",
  },
  btn: { padding: "12px 24px", borderRadius: 12, border: "none", fontSize: 16, fontWeight: 700, cursor: "pointer" },
  btnPrimary: { background: "#667eea", color: "white" },
  btnSecondary: { background: "#e2e8f0", color: "#4a5568" },
  shelfHeader: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    width: "100%", maxWidth: 900, marginBottom: 24,
  },
  backBtn: {
    background: "white", border: "none", borderRadius: "50%",
    width: 48, height: 48, fontSize: 24, cursor: "pointer",
    boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
  },
  shelfTitle: {
    fontSize: 24, fontWeight: 800, color: "#4a3f6b",
    margin: 0, flex: 1, textAlign: "center",
  },
  emptyShelf: { textAlign: "center", marginTop: 80 },
  bookGrid: {
    display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
    gap: 20, maxWidth: 900, width: "100%",
  },
  bookCard: {
    background: "white", borderRadius: 16, overflow: "hidden", border: "none",
    cursor: "pointer", display: "flex", flexDirection: "column",
    boxShadow: "0 4px 14px rgba(0,0,0,0.1)",
  },
  bookCover: { width: "100%", height: 200, objectFit: "cover", background: "#f7fafc" },
  bookInfo: { padding: "12px 14px", textAlign: "left" },
  bookTitle: { fontSize: 16, fontWeight: 700, color: "#2d3748", lineHeight: 1.3 },
  bookProgress: { fontSize: 12, color: "#718096", marginTop: 2 },
  nextReadBadge: { fontSize: 13, fontWeight: 700, color: "#667eea", marginTop: 6 },
};
