"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  kidsApi,
  type KidsBootstrapProfile,
  type KidsLibraryItem,
} from "@/lib/kids-api";

export default function KidsProfileEntryPage() {
  const router = useRouter();
  const params = useParams();
  const profileId = params.profileId as string;

  const [stage, setStage] = useState<"loading" | "pin" | "shelf" | "not_found">("loading");
  const [profile, setProfile] = useState<KidsBootstrapProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState("");
  const [error, setError] = useState("");
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");

  useEffect(() => {
    let cancelled = false;

    const enterShelf = async (p: KidsBootstrapProfile) => {
      try {
        await kidsApi.selectProfile(p.id);
        if (cancelled) return;
        localStorage.setItem("dt_kids_profile_id", p.id);
        const { library: lib } = await kidsApi.library();
        if (cancelled) return;
        setProfile(p);
        setLibrary(lib || []);
        setStage("shelf");
      } catch {
        if (cancelled) return;
        setError("Cannot load books. Try again!");
        setStage("pin");
      }
    };

    (async () => {
      localStorage.removeItem("dt_kids_token");
      try {
        const { profile: p } = await kidsApi.getProfilePublicInfo(profileId);
        if (cancelled) return;
        if (!p) {
          setStage("not_found");
          return;
        }
        setProfile(p);
        if (p.has_pin) {
          try {
            const session = await kidsApi.library();
            if (cancelled) return;
            if (session.profile?.id === profileId) {
              localStorage.setItem("dt_kids_profile_id", p.id);
              setLibrary(session.library || []);
              setStage("shelf");
            } else {
              setStage("pin");
            }
          } catch {
            if (!cancelled) setStage("pin");
          }
        } else {
          await enterShelf(p);
        }
      } catch {
        if (cancelled) return;
        setError("Cannot connect or profile not found.");
        setStage("not_found");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [profileId]);

  const handlePinSubmit = async () => {
    if (!profile) return;
    try {
      await kidsApi.parentUnlock(profile.id, pinInput);
      localStorage.setItem("dt_kids_profile_id", profile.id);
      const { library: lib } = await kidsApi.library();
      setLibrary(lib || []);
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

  const doExit = async () => {
    await kidsApi.logout().catch(() => {});
    localStorage.removeItem("dt_kids_profile_id");
    router.push("/kids");
  };

  const handleExitPinSubmit = async () => {
    if (!profile) return;
    try {
      await kidsApi.exitVerify(profile.id, exitPin);
      await doExit();
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
          <p style={S.subtitle}>Ask a grown-up to enter the PIN for {profile?.name}</p>
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
        <div style={S.starsBadge}>
          ⭐ {library.reduce((s, b) => s + (b.progress?.total_stars || 0), 0)}
        </div>
      </div>

      {library.length === 0 ? (
        <div style={S.emptyShelf}>
          <div style={{ fontSize: 64, marginBottom: 12 }}>📖</div>
          <h2 style={{ fontSize: 22, color: "#4a3f6b", margin: 0 }}>No books yet!</h2>
          <p style={S.subtitle}>Ask a grown-up to approve and add books from the Parent Center.</p>
        </div>
      ) : (
        <div style={S.bookGrid}>
          {library.map((item) => {
            const doc = item.document as Record<string, string>;
            const coverUrl = kidsApi.getCoverUrl(item.assignment.document_id);
            const completed = (item.progress?.completed_section_ids || []).length;
            return (
              <button
                key={item.assignment.document_id}
                style={S.bookCard}
                onClick={() => router.push(`/kids/${item.assignment.document_id}`)}
              >
                <img src={coverUrl} alt={doc?.title || "Book"} style={S.bookCover}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                <div style={S.bookInfo}>
                  <div style={S.bookTitle}>{doc?.title || "Unknown"}</div>
                  <div style={S.bookStars}>⭐ {item.progress?.total_stars || 0}</div>
                  {(item.progress?.current_section_id || completed > 0) && (
                    <div style={S.bookProgress}>
                      {completed} chapter{completed !== 1 ? "s" : ""} done
                    </div>
                  )}
                  {item.assignment.is_next_read && (
                    <div style={S.nextReadBadge}>Read this next! →</div>
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
    background: "linear-gradient(180deg, #e0f2ff 0%, #fef3e7 50%, #f0fdf4 100%)",
    padding: "24px 16px", display: "flex", flexDirection: "column", alignItems: "center",
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
  starsBadge: {
    background: "#fef3c7", borderRadius: 20, padding: "8px 16px",
    fontSize: 18, fontWeight: 700, color: "#92400e",
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
  bookStars: { fontSize: 14, color: "#d69e2e", marginTop: 4 },
  bookProgress: { fontSize: 12, color: "#718096", marginTop: 2 },
  nextReadBadge: { fontSize: 13, fontWeight: 700, color: "#667eea", marginTop: 6 },
};
