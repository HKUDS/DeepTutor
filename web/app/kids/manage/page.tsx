"use client";

import { useCallback, useEffect, useState } from "react";
import { kidsAdminApi, type KidsProfile, type KidsLibraryItem } from "@/lib/kids-api";

const AVATARS = ["🦊", "🐼", "🦄", "🐸", "🐱", "🐶", "🦁", "🐰"];

export default function KidsManagePage() {
  const [profiles, setProfiles] = useState<KidsProfile[]>([]);
  const [selected, setSelected] = useState<KidsProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [allDocs, setAllDocs] = useState<Record<string, any>[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);

  const [copiedId, setCopiedId] = useState("");

  // Create form state
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [pin, setPin] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const loadProfiles = useCallback(async () => {
    try {
      const { profiles } = await kidsAdminApi.listProfiles();
      setProfiles(profiles);
    } catch (e) {
      setError("Failed to load profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLibrary = useCallback(async (profileId: string) => {
    try {
      const [lib, docs] = await Promise.all([
        kidsAdminApi.listAssignedBooks(profileId),
        kidsAdminApi.adultLibrary(),
      ]);
      setLibrary(lib.library);
      setAllDocs(docs.documents);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  const copyDeviceUrl = (profile: KidsProfile) => {
    const url = typeof window !== "undefined"
      ? `${window.location.origin}/kids/p/${profile.id}`
      : `/kids/p/${profile.id}`;
    navigator.clipboard?.writeText(url).then(() => {
      setCopiedId(profile.id);
      setTimeout(() => setCopiedId(""), 2000);
    });
  };

  useEffect(() => {
    if (selected) {
      loadLibrary(selected.id);
    }
  }, [selected, loadLibrary]);

  const handleCreate = async () => {
    if (!name.trim() || !birthDate) return;
    setCreating(true);
    setError("");
    try {
      const { profile } = await kidsAdminApi.createProfile({
        name: name.trim(),
        birth_date: birthDate,
        parent_pin: pin || undefined,
      });
      setName(""); setBirthDate(""); setPin("");
      setShowCreate(false);
      await loadProfiles();
      setSelected(profile as KidsProfile);
    } catch {
      setError("Failed to create profile");
    } finally {
      setCreating(false);
    }
  };

  const handleAssign = async (docId: string) => {
    if (!selected) return;
    await kidsAdminApi.assignBook(selected.id, { document_id: docId });
    loadLibrary(selected.id);
  };

  const handleUnassign = async (docId: string) => {
    if (!selected) return;
    await kidsAdminApi.unassignBook(selected.id, docId);
    loadLibrary(selected.id);
  };

  const handleDelete = async (profileId: string) => {
    if (!confirm("Delete this profile? All progress will be lost.")) return;
    await kidsAdminApi.deleteProfile(profileId);
    setSelected(null);
    loadProfiles();
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f7fafc" }}>
        <div style={{ fontSize: 48 }}>Loading...</div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f7fafc", padding: "24px 16px" }}>
      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1a202c", margin: 0 }}>
              {selected ? `${selected.name}'s Library` : "Kids Reading"}
            </h1>
            {selected && (
              <p style={{ fontSize: 16, color: "#718096", marginTop: 4 }}>
                Age {selected.age} ({selected.age_band})
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <a href="/kids" target="_blank" style={{ ...btnStyle, background: "#e9d8fd", color: "#553c9a", textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
              Open Kids Mode
            </a>
            {!selected && (
              <button onClick={() => setShowCreate(!showCreate)} style={{ ...btnStyle, background: "#667eea", color: "white" }}>
                {showCreate ? "Cancel" : "+ Add Child"}
              </button>
            )}
          </div>
        </div>

        {error && <div style={{ color: "#e53e3e", marginBottom: 16 }}>{error}</div>}

        {/* Create form */}
        {showCreate && !selected && (
          <div style={{ ...cardStyle, marginBottom: 24 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, marginTop: 0, marginBottom: 16 }}>New Child Profile</h3>
            <div style={{ display: "grid", gap: 12 }}>
              <div>
                <label style={labelStyle}>Child Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Emma"
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={labelStyle}>Date of Birth</label>
                <input
                  type="date"
                  value={birthDate}
                  onChange={(e) => setBirthDate(e.target.value)}
                  max={new Date().toISOString().split("T")[0]}
                  style={inputStyle}
                />
                <div style={{ fontSize: 13, color: "#a0aec0", marginTop: 4 }}>
                  Quiz difficulty auto-adjusts as your child grows
                </div>
              </div>
              <div>
                <label style={labelStyle}>Parent PIN (optional)</label>
                <input
                  type="password"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  placeholder="4-8 digits"
                  maxLength={8}
                  style={inputStyle}
                />
                <div style={{ fontSize: 13, color: "#a0aec0", marginTop: 4 }}>
                  Required to enter Kids mode if set
                </div>
              </div>
              <button
                onClick={handleCreate}
                disabled={!name.trim() || !birthDate || creating}
                style={{ ...btnStyle, background: "#48bb78", color: "white", marginTop: 8, opacity: (!name.trim() || !birthDate) ? 0.5 : 1 }}
              >
                {creating ? "Creating..." : "Create Profile"}
              </button>
            </div>
          </div>
        )}

        {/* Profile list */}
        {!selected && (
          <>
            {profiles.length === 0 && !showCreate ? (
              <div style={{ ...cardStyle, textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48, marginBottom: 8 }}>👶</div>
                <p style={{ fontSize: 18, color: "#718096" }}>No child profiles yet</p>
                <p style={{ fontSize: 14, color: "#a0aec0" }}>Click "+ Add Child" to create one</p>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 16 }}>
                {profiles.map((p, i) => (
                  <div
                    key={p.id}
                    onClick={() => setSelected(p)}
                    style={{ ...cardStyle, cursor: "pointer", textAlign: "center", transition: "box-shadow 0.2s" }}
                  >
                    <div style={{ fontSize: 48, marginBottom: 8 }}>{AVATARS[i % AVATARS.length]}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: "#2d3748" }}>{p.name}</div>
                    <div style={{ fontSize: 14, color: "#718096", marginTop: 4 }}>
                      Age {p.age ?? "?"} ({p.age_band ?? "?"})
                    </div>
                    <div style={{ fontSize: 13, color: p.has_pin ? "#805ad5" : "#a0aec0", marginTop: 4 }}>
                      {p.has_pin ? "PIN protected" : "No PIN"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Profile detail: manage books */}
        {selected && (
          <div>
            <button onClick={() => setSelected(null)} style={{ ...btnStyle, background: "#e2e8f0", color: "#4a5568", marginBottom: 16 }}>
             All Children
           </button>

            {/* Child's dedicated link */}
            <div style={{ ...cardStyle, marginBottom: 16, background: "#f0f4ff" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#553c9a", marginBottom: 8 }}>
                🔗 {selected.name}&apos;s Reading Link
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <code style={{
                  flex: 1, fontSize: 13, color: "#4a5568", background: "white",
                  padding: "8px 12px", borderRadius: 8, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {typeof window !== "undefined"
                    ? `${window.location.origin}/kids/p/${selected.id}`
                    : `/kids/p/${selected.id}`}
                </code>
                <button
                  onClick={() => copyDeviceUrl(selected)}
                  style={{ ...miniBtn, background: copiedId === selected.id ? "#c6f6d5" : "#e9d8fd", color: "#553c9a" }}
                >
                  {copiedId === selected.id ? "✓ Copied!" : "Copy"}
                </button>
              </div>
              <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 8 }}>
                Bookmark this on your child&apos;s device — they tap it to go straight to their books.
              </div>
            </div>

            {/* Assigned books */}
            <div style={{ ...cardStyle, marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 0, marginBottom: 12 }}>
                {selected.name}&apos;s Books ({library.length})
              </h3>
              {library.length === 0 ? (
                <p style={{ color: "#a0aec0", fontSize: 14 }}>No books assigned yet. Pick from the list below.</p>
              ) : (
                library.map((item) => {
                  const doc = item.document as Record<string, any>;
                  return (
                    <div key={item.assignment.document_id} style={rowStyle}>
                      <span style={{ flex: 1, fontSize: 15 }}>
                        {doc.title}
                      </span>
                      <span style={{ fontSize: 13, color: "#d69e2e" }}>
                        {item.progress.total_stars} stars
                      </span>
                      <button onClick={() => handleUnassign(item.assignment.document_id)} style={{ ...miniBtn, background: "#fed7d7", color: "#c53030" }}>
                        Remove
                      </button>
                    </div>
                  );
                })
              )}
            </div>

            {/* Available to assign */}
            {allDocs.length > library.length && (
              <div style={cardStyle}>
                <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 0, marginBottom: 12 }}>
                  Add Books
                </h3>
                {allDocs
                  .filter((d) => !library.some((l) => l.assignment.document_id === d.id))
                  .map((doc) => (
                    <div key={doc.id} style={rowStyle}>
                      <span style={{ flex: 1, fontSize: 15 }}>{doc.title}</span>
                      <span style={{ fontSize: 13, color: "#a0aec0" }}>{doc.source_format}</span>
                      <button onClick={() => handleAssign(doc.id)} style={{ ...miniBtn, background: "#c6f6d5", color: "#276749" }}>
                        Assign
                      </button>
                    </div>
                  ))}
              </div>
            )}

            {/* Delete */}
            <div style={{ marginTop: 24, textAlign: "center" }}>
              <button
                onClick={() => handleDelete(selected.id)}
                style={{ ...miniBtn, background: "transparent", color: "#e53e3e", border: "1px solid #fed7d7", padding: "6px 16px" }}
              >
                Delete {selected.name}&apos;s profile
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  border: "none", borderRadius: 10, padding: "10px 20px",
  fontSize: 14, fontWeight: 600, cursor: "pointer",
};

const cardStyle: React.CSSProperties = {
  background: "white", borderRadius: 12, padding: 20,
  boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
  border: "1px solid #edf2f7",
};

const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 14, fontWeight: 600,
  color: "#4a5568", marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "10px 14px", borderRadius: 8,
  border: "2px solid #e2e8f0", fontSize: 16, outline: "none",
};

const rowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 12,
  padding: "10px 0", borderBottom: "1px solid #edf2f7",
};

const miniBtn: React.CSSProperties = {
  border: "none", borderRadius: 6, padding: "4px 12px",
  fontSize: 13, fontWeight: 600, cursor: "pointer",
};
