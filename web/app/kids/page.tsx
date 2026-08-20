"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { kidsApi, type KidsProfile, type KidsLibraryItem } from "@/lib/kids-api";

export default function KidsPage() {
  const router = useRouter();
  const [stage, setStage] = useState<"loading" | "pairing" | "shelf">("loading");
  const [currentProfile, setCurrentProfile] = useState<KidsProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [pairCode, setPairCode] = useState("");
  const [pairingLoading, setPairingLoading] = useState(false);
  const [error, setError] = useState("");

  // Exit PIN state
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");

  const loadShelf = async () => {
    try {
      const { library: lib, profile: prof } = await kidsApi.library();
      setLibrary(lib || []);
      setCurrentProfile(prof || null);
      if (prof?.id) {
        localStorage.setItem("dt_kids_profile_id", prof.id);
      }
      setStage("shelf");
    } catch {
      setStage("pairing");
    }
  };

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        localStorage.removeItem("dt_kids_token");
        const boot = await kidsApi.bootstrap();
        if (cancelled) return;

        if (boot.authenticated && boot.profile) {
          setCurrentProfile(boot.profile);
          await loadShelf();
        } else {
          try {
            await loadShelf();
          } catch {
            const storedPid = localStorage.getItem("dt_kids_profile_id");
            if (storedPid) {
              router.push(`/kids/p/${storedPid}`);
              return;
            }
            setStage("pairing");
          }
        }
      } catch {
        if (!cancelled) {
          setStage("pairing");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  const handlePairSubmit = async () => {
    const cleanCode = pairCode.trim();
    if (cleanCode.length < 6) return;
    setPairingLoading(true);
    setError("");
    try {
      const { profile } = await kidsApi.pairDevice(cleanCode, "Child Device");
      setCurrentProfile(profile);
      localStorage.setItem("dt_kids_profile_id", profile.id);
      await loadShelf();
    } catch (err: any) {
      setError(err?.detail || "Invalid or expired 6-digit code. Please ask a grown-up for a new code.");
      setPairCode("");
    } finally {
      setPairingLoading(false);
    }
  };

  const handleExitClick = () => {
    if (currentProfile?.has_pin) {
      setShowExitPin(true);
      setExitPin("");
      setExitPinError("");
    } else {
      doLogout();
    }
  };

  const doLogout = async () => {
    await kidsApi.logout().catch(() => {});
    localStorage.removeItem("dt_kids_profile_id");
    setCurrentProfile(null);
    setLibrary([]);
    setStage("pairing");
  };

  const handleExitPinSubmit = async () => {
    if (!currentProfile) return;
    try {
      await kidsApi.exitVerify(currentProfile.id, exitPin);
      setShowExitPin(false);
      await doLogout();
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  if (stage === "loading") {
    return (
      <div style={styles.center}>
        <div style={styles.spinner}>📚</div>
      </div>
    );
  }

  // Pairing View
  if (stage === "pairing") {
    return (
      <div style={styles.container}>
        <div style={{ ...styles.header, marginTop: 40 }}>
          <div style={{ fontSize: 64, marginBottom: 12 }}>🚀</div>
          <h1 style={styles.title}>My Reading World</h1>
          <p style={styles.subtitle}>Enter the 6-digit code from the Parent Center to pair this device</p>
        </div>

        <div style={styles.pinPad}>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={pairCode}
            onChange={(e) => setPairCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            onKeyDown={(e) => e.key === "Enter" && pairCode.length === 6 && handlePairSubmit()}
            maxLength={6}
            style={styles.pairingInput}
            placeholder="0 0 0 0 0 0"
            autoFocus
          />

          {error && <p style={styles.errorText}>{error}</p>}

          <button
            style={{
              ...styles.btn,
              ...styles.btnPrimary,
              width: "100%",
              marginTop: 10,
              opacity: pairCode.length < 6 || pairingLoading ? 0.6 : 1,
            }}
            onClick={handlePairSubmit}
            disabled={pairCode.length < 6 || pairingLoading}
          >
            {pairingLoading ? "Connecting..." : "Start Reading →"}
          </button>
        </div>

        <div style={{ marginTop: 24, textAlign: "center" }}>
          <a href="/kids/manage" target="_blank" style={{ color: "#6366f1", fontSize: 14, textDecoration: "none" }}>
            Parent Center (Generate Code) →
          </a>
        </div>
      </div>
    );
  }

  // Bookshelf View
  return (
    <div style={styles.container}>
      {showExitPin && (
        <div style={styles.overlay}>
          <div style={{ ...styles.pinPad, maxWidth: 360 }}>
            <p style={styles.subtitle}>🔒 Enter Grown-up PIN to Exit</p>
            <input
              type="password"
              value={exitPin}
              onChange={(e) => setExitPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && exitPin.length >= 4 && handleExitPinSubmit()}
              maxLength={8}
              style={styles.pinInput}
              placeholder="• • • •"
              autoFocus
            />
            {exitPinError && <p style={styles.errorText}>{exitPinError}</p>}
            <div style={styles.pinButtons}>
              <button
                style={{ ...styles.btn, ...styles.btnSecondary }}
                onClick={() => { setShowExitPin(false); setExitPin(""); setExitPinError(""); }}
              >
                Cancel
              </button>
              <button
                style={{ ...styles.btn, ...styles.btnPrimary }}
                onClick={handleExitPinSubmit}
                disabled={exitPin.length < 4}
              >
                Exit
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={styles.shelfHeader}>
        <button style={styles.backBtn} onClick={handleExitClick} title="Exit Kids Mode">
          🚪
        </button>
        <h1 style={styles.shelfTitle}>
          {currentProfile?.name}&apos;s Books
        </h1>
        <div style={styles.starsBadge}>
          ⭐ {library.reduce((sum, b) => sum + (b.progress?.total_stars || 0), 0)}
        </div>
      </div>

      {library.length === 0 ? (
        <div style={styles.emptyShelf}>
          <div style={{ fontSize: 64, marginBottom: 12 }}>📖</div>
          <h2 style={{ fontSize: 22, color: "#4a3f6b", margin: 0 }}>No books yet!</h2>
          <p style={styles.subtitle}>Ask a grown-up to approve and assign books from the Parent Center.</p>
        </div>
      ) : (
        <div style={styles.bookGrid}>
          {library.map((item) => {
            const doc = item.document as Record<string, any>;
            const coverUrl = kidsApi.getCoverUrl(item.assignment.document_id);
            const completed = (item.progress?.completed_section_ids || []).length;
            const totalCh = Array.isArray(doc.sections) ? doc.sections.length : 0;
            return (
              <button
                key={item.assignment.document_id}
                style={styles.bookCard}
                onClick={() => router.push(`/kids/${item.assignment.document_id}`)}
              >
                <img
                  src={coverUrl}
                  alt={doc?.title || "Book"}
                  style={styles.bookCover}
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
                <div style={styles.bookInfo}>
                  <div style={styles.bookTitle}>{doc?.title || "Unknown"}</div>
                  <div style={styles.bookStars}>
                    ⭐ {item.progress?.total_stars || 0} stars
                  </div>
                  {totalCh > 0 && (
                    <div style={styles.bookProgress}>
                      {completed}/{totalCh} chapters completed
                    </div>
                  )}
                  {item.assignment.is_next_read && (
                    <div style={styles.nextReadBadge}>Read this next! →</div>
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

const styles: Record<string, React.CSSProperties> = {
  center: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "100vh",
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
  },
  spinner: { fontSize: 80 },
  container: {
    minHeight: "100vh",
    background: "linear-gradient(180deg, #e0f2ff 0%, #fef3e7 50%, #f0fdf4 100%)",
    padding: "24px 16px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  header: { textAlign: "center", marginBottom: 28 },
  title: { fontSize: 32, fontWeight: 800, color: "#312e81", margin: 0 },
  subtitle: { fontSize: 16, color: "#475569", marginTop: 8, maxWidth: 460 },
  errorText: { fontSize: 14, color: "#e11d48", textAlign: "center", marginTop: 8 },
  pinPad: {
    background: "white",
    borderRadius: 24,
    padding: 28,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 14,
    boxShadow: "0 8px 30px rgba(0,0,0,0.08)",
    maxWidth: 380,
    width: "100%",
  },
  pairingInput: {
    fontSize: 32,
    textAlign: "center",
    letterSpacing: 8,
    border: "3px solid #6366f1",
    borderRadius: 14,
    padding: "12px 16px",
    width: "100%",
    outline: "none",
    fontWeight: 700,
    color: "#1e1b4b",
  },
  pinInput: {
    fontSize: 28,
    textAlign: "center",
    letterSpacing: 8,
    border: "2px solid #cbd5e1",
    borderRadius: 12,
    padding: "10px 14px",
    width: "100%",
    outline: "none",
  },
  pinButtons: { display: "flex", gap: 10, marginTop: 8 },
  btn: {
    padding: "12px 20px",
    borderRadius: 12,
    border: "none",
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer",
  },
  btnPrimary: { background: "#6366f1", color: "white" },
  btnSecondary: { background: "#f1f5f9", color: "#475569" },
  shelfHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    width: "100%",
    maxWidth: 900,
    marginBottom: 24,
  },
  backBtn: {
    background: "white",
    border: "none",
    borderRadius: "50%",
    width: 44,
    height: 44,
    fontSize: 20,
    cursor: "pointer",
    boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
  },
  shelfTitle: {
    fontSize: 24,
    fontWeight: 800,
    color: "#1e1b4b",
    margin: 0,
    flex: 1,
    textAlign: "center",
  },
  starsBadge: {
    background: "#fef3c7",
    borderRadius: 20,
    padding: "6px 14px",
    fontSize: 16,
    fontWeight: 700,
    color: "#92400e",
  },
  emptyShelf: { textAlign: "center", marginTop: 60 },
  bookGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
    gap: 20,
    maxWidth: 900,
    width: "100%",
  },
  bookCard: {
    background: "white",
    borderRadius: 16,
    overflow: "hidden",
    border: "none",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    boxShadow: "0 4px 14px rgba(0,0,0,0.08)",
    transition: "transform 0.15s",
  },
  bookCover: {
    width: "100%",
    height: 200,
    objectFit: "cover",
    background: "#f8fafc",
  },
  bookInfo: { padding: "12px 14px", textAlign: "left" },
  bookTitle: { fontSize: 15, fontWeight: 700, color: "#1e293b", lineHeight: 1.3 },
  bookStars: { fontSize: 13, color: "#d97706", marginTop: 4 },
  bookProgress: { fontSize: 12, color: "#64748b", marginTop: 2 },
  nextReadBadge: {
    fontSize: 12,
    fontWeight: 700,
    color: "#6366f1",
    marginTop: 6,
  },
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.5)",
    backdropFilter: "blur(4px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
    padding: 16,
  },
};
