"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { kidsApi, type KidsProfile, type KidsLibraryItem } from "@/lib/kids-api";

const AVATAR_EMOJIS = ["🦊", "🐼", "🦄", "🐸", "🐱", "🐶", "🦁", "🐰"];

export default function KidsPage() {
  const router = useRouter();
  const [stage, setStage] = useState<"loading" | "picker" | "pin" | "shelf">("loading");
  const [profiles, setProfiles] = useState<KidsProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<KidsProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState("");
 const [error, setError] = useState("");

  const loadProfiles = useCallback(async () => {
    try {
      // Auto-redirect: if we have a stored token for a specific profile,
      // skip the picker and go straight to that profile's dedicated link
      if (typeof window !== "undefined") {
        const storedToken = localStorage.getItem("dt_kids_token");
        const storedPid = localStorage.getItem("dt_kids_profile_id");
        if (storedToken && storedPid) {
          router.push(`/kids/p/${storedPid}`);
          return;
        }
      }
      const { profiles } = await kidsApi.bootstrap();
      setProfiles(profiles);
      if (profiles.length === 0) {
        setError("No profiles yet. Ask a grown-up to set up your account!");
        setStage("picker");
      } else {
        setStage("picker");
      }
    } catch {
      setError("Cannot connect. Ask a grown-up for help.");
      setStage("picker");
    }
  }, []);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  // Exit-protection state
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");

  const handleSelectProfile = async (profile: KidsProfile) => {
    setSelectedProfile(profile);
    if (profile.has_pin) {
      setStage("pin");
      setPinInput("");
      setPinError("");
    } else {
      await enterProfile(profile);
    }
  };

  const enterProfile = async (profile: KidsProfile) => {
    try {
      const { token } = await kidsApi.selectProfile(profile.id);
      localStorage.setItem("dt_kids_token", token);
      const { library: lib } = await kidsApi.library(profile.id);
      setLibrary(lib);
      setStage("shelf");
    } catch {
      setError("Cannot load books. Try again!");
    }
  };

  const handlePinSubmit = async () => {
    if (!selectedProfile) return;
    try {
      const { token } = await kidsApi.parentUnlock(selectedProfile.id, pinInput);
      localStorage.setItem("dt_kids_token", token);
      const { library: lib } = await kidsApi.library(selectedProfile.id);
      setLibrary(lib);
      setStage("shelf");
    } catch {
      setPinError("Wrong PIN. Try again!");
      setPinInput("");
    }
  };

  const handleBackToPicker = () => {
    if (selectedProfile?.has_pin) {
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
    setSelectedProfile(null);
    setStage("picker");
  };

  const handleExitPinSubmit = async () => {
    if (!selectedProfile) return;
    try {
      await kidsApi.exitVerify(selectedProfile.id, exitPin);
      doExit();
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  // ── Loading ────────────────────────────────────────────────────────────
  if (stage === "loading") {
    return (
      <div style={styles.center}>
        <div style={styles.spinner}>📚</div>
      </div>
    );
  }

  // ── Profile Picker ──────────────────────────────────────────────────────
  if (stage === "picker") {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <h1 style={styles.title}>📚 My Reading World</h1>
          <p style={styles.subtitle}>Pick your character to start!</p>
        </div>
        {error && <p style={styles.errorText}>{error}</p>}
        <div style={styles.profileGrid}>
          {profiles.map((p, i) => (
            <button
              key={p.id}
              style={styles.profileCard}
              onClick={() => handleSelectProfile(p)}
            >
              <div style={styles.profileAvatar}>
                {AVATAR_EMOJIS[i % AVATAR_EMOJIS.length]}
              </div>
              <div style={styles.profileName}>{p.name}</div>
              {p.has_pin && <div style={styles.pinBadge}>🔒</div>}
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── PIN Entry ───────────────────────────────────────────────────────────
  if (stage === "pin") {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <h1 style={styles.title}>🔒 Grown-Up PIN</h1>
          <p style={styles.subtitle}>Ask a grown-up to enter the PIN</p>
        </div>
        <div style={styles.pinPad}>
          <input
            type="password"
            value={pinInput}
            onChange={(e) => setPinInput(e.target.value)}
            maxLength={8}
            style={styles.pinInput}
            placeholder="• • • •"
            autoFocus
          />
          {pinError && <p style={styles.errorText}>{pinError}</p>}
          <div style={styles.pinButtons}>
            <button style={{ ...styles.btn, ...styles.btnSecondary }} onClick={() => setStage("picker")}>
              ← Back
            </button>
            <button
              style={{ ...styles.btn, ...styles.btnPrimary }}
              onClick={handlePinSubmit}
              disabled={pinInput.length < 4}
            >
              Enter →
            </button>
          </div>
        </div>
      </div>
    );
  }

 // ── Bookshelf ───────────────────────────────────────────────────────────
 return (
   <div style={styles.container}>
      {/* Exit PIN modal */}
      {showExitPin && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{ ...styles.pinPad, maxWidth: 360 }}>
            <p style={styles.subtitle}>🔒 Enter PIN to exit</p>
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
              <button style={{ ...styles.btn, ...styles.btnSecondary }}
                onClick={() => { setShowExitPin(false); setExitPin(""); setExitPinError(""); }}>
                Cancel
              </button>
              <button style={{ ...styles.btn, ...styles.btnPrimary }}
                onClick={handleExitPinSubmit} disabled={exitPin.length < 4}>
                Exit
              </button>
            </div>
          </div>
        </div>
      )}
     <div style={styles.shelfHeader}>
       <button style={styles.backBtn} onClick={handleBackToPicker}>
         👈
       </button>
        <h1 style={styles.shelfTitle}>
          {AVATAR_EMOJIS[profiles.findIndex((p) => p.id === selectedProfile?.id) % AVATAR_EMOJIS.length]}{" "}
          {selectedProfile?.name}&apos;s Books
        </h1>
        <div style={styles.starsBadge}>
          ⭐ {library.reduce((sum, b) => sum + (b.progress?.total_stars || 0), 0)}
        </div>
      </div>

      {library.length === 0 ? (
        <div style={styles.emptyShelf}>
          <div style={{ fontSize: 64 }}>📖</div>
          <p style={styles.subtitle}>No books yet! Ask a grown-up to add books.</p>
        </div>
      ) : (
        <div style={styles.bookGrid}>
          {library.map((item) => {
            const doc = item.document as Record<string, string>;
            const coverUrl = kidsApi.getCoverUrl(item.assignment.document_id);
            const completed = (item.progress?.completed_section_ids || []).length;
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
                    ⭐ {item.progress?.total_stars || 0}
                  </div>
                  {(item.progress?.current_section_id || completed > 0) && (
                    <div style={styles.bookProgress}>
                      {completed} chapter{completed !== 1 ? "s" : ""} done
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
  spinner: { fontSize: 80, animation: "spin 1s linear infinite" },
  container: {
    minHeight: "100vh",
    background: "linear-gradient(180deg, #e0f2ff 0%, #fef3e7 50%, #f0fdf4 100%)",
    padding: "24px 16px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  header: { textAlign: "center", marginBottom: 32, marginTop: 20 },
  title: { fontSize: 36, fontWeight: 800, color: "#4a3f6b", margin: 0 },
  subtitle: { fontSize: 18, color: "#7c6f9b", marginTop: 8 },
  errorText: { fontSize: 16, color: "#e53e3e", textAlign: "center", marginTop: 12 },
  profileGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
    gap: 20,
    maxWidth: 700,
    width: "100%",
  },
  profileCard: {
    background: "white",
    borderRadius: 24,
    padding: "24px 16px",
    border: "none",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 12,
    boxShadow: "0 4px 14px rgba(0,0,0,0.1)",
    transition: "transform 0.2s",
    position: "relative",
  },
  profileAvatar: { fontSize: 56 },
  profileName: { fontSize: 20, fontWeight: 700, color: "#4a3f6b" },
  pinBadge: { position: "absolute", top: 8, right: 12, fontSize: 20 },
  pinPad: {
    background: "white",
    borderRadius: 24,
    padding: 32,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 16,
    boxShadow: "0 4px 14px rgba(0,0,0,0.1)",
    maxWidth: 360,
    width: "100%",
  },
  pinInput: {
    fontSize: 32,
    textAlign: "center" as const,
    letterSpacing: 12,
    border: "3px solid #667eea",
    borderRadius: 12,
    padding: "12px 16px",
    width: "100%",
    outline: "none",
  },
  pinButtons: { display: "flex", gap: 12, marginTop: 8 },
  btn: {
    padding: "12px 24px",
    borderRadius: 12,
    border: "none",
    fontSize: 16,
    fontWeight: 700,
    cursor: "pointer",
  },
  btnPrimary: { background: "#667eea", color: "white" },
  btnSecondary: { background: "#e2e8f0", color: "#4a5568" },
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
    width: 48,
    height: 48,
    fontSize: 24,
    cursor: "pointer",
    boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
  },
  shelfTitle: { fontSize: 24, fontWeight: 800, color: "#4a3f6b", margin: 0, flex: 1, textAlign: "center" as const },
  starsBadge: {
    background: "#fef3c7",
    borderRadius: 20,
    padding: "8px 16px",
    fontSize: 18,
    fontWeight: 700,
    color: "#92400e",
  },
  emptyShelf: { textAlign: "center", marginTop: 80 },
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
    boxShadow: "0 4px 14px rgba(0,0,0,0.1)",
    transition: "transform 0.2s",
  },
  bookCover: {
    width: "100%",
    height: 200,
    objectFit: "cover",
    background: "#f7fafc",
  },
  bookInfo: { padding: "12px 14px", textAlign: "left" as const },
  bookTitle: { fontSize: 16, fontWeight: 700, color: "#2d3748", lineHeight: 1.3 },
  bookStars: { fontSize: 14, color: "#d69e2e", marginTop: 4 },
  bookProgress: { fontSize: 12, color: "#718096", marginTop: 2 },
  nextReadBadge: {
    fontSize: 13,
    fontWeight: 700,
    color: "#667eea",
    marginTop: 6,
  },
};
