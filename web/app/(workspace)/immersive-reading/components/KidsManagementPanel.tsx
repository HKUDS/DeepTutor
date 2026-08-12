"use client";

import { useCallback, useEffect, useState } from "react";
import { kidsAdminApi, type KidsProfile, type KidsLibraryItem } from "@/lib/kids-api";

const AVATARS = ["fox", "panda", "unicorn", "frog", "cat", "dog", "lion", "bunny"];

export default function KidsManagementPanel({ onClose }: { onClose: () => void }) {
  const [profiles, setProfiles] = useState<KidsProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<KidsProfile | null>(null);
  const [library, setLibrary] = useState<KidsLibraryItem[]>([]);
  const [allDocs, setAllDocs] = useState<Record<string, any>[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newBirthDate, setNewBirthDate] = useState("");
  const [newPin, setNewPin] = useState("");
  const [report, setReport] = useState<Record<string, any> | null>(null);

  const loadProfiles = useCallback(async () => {
    try {
      const { profiles } = await kidsAdminApi.listProfiles();
      setProfiles(profiles);
    } catch {
      // ignore
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

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    if (selectedProfile) {
      loadLibrary(selectedProfile.id);
      kidsAdminApi.learningReport(selectedProfile.id).then(setReport).catch(() => {});
    }
  }, [selectedProfile, loadLibrary]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await kidsAdminApi.createProfile({
      name: newName.trim(),
      birth_date: newBirthDate,
      parent_pin: newPin || undefined,
    });
    setNewName("");
    setNewPin("");
    setShowCreate(false);
    loadProfiles();
  };

  const handleAssign = async (docId: string) => {
    if (!selectedProfile) return;
    await kidsAdminApi.assignBook(selectedProfile.id, { document_id: docId });
    loadLibrary(selectedProfile.id);
  };

  const handleUnassign = async (docId: string) => {
    if (!selectedProfile) return;
    await kidsAdminApi.unassignBook(selectedProfile.id, docId);
    loadLibrary(selectedProfile.id);
  };

  const handleDeleteProfile = async (profileId: string) => {
    if (!confirm("Delete this child profile? Progress data will be lost.")) return;
    await kidsAdminApi.deleteProfile(profileId);
    setSelectedProfile(null);
    loadProfiles();
  };

  if (loading) return <div style={{ padding: 40, textAlign: "center" }}>Loading...</div>;

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      background: "rgba(0,0,0,0.5)", zIndex: 50,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        background: "var(--background, white)", borderRadius: 16,
        maxWidth: 720, width: "90%", maxHeight: "85vh", overflowY: "auto",
        padding: 24, boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>
            {selectedProfile ? `${selectedProfile.name}'s Library` : "Kids Content Management"}
          </h2>
          <button onClick={onClose} style={closeBtn}>X</button>
        </div>

        {!selectedProfile ? (
          <>
            <div style={{ marginBottom: 16 }}>
              <button onClick={() => setShowCreate(!showCreate)} style={primaryBtn}>
                {showCreate ? "Cancel" : "+ Add Child Profile"}
              </button>
            </div>

            {showCreate && (
              <div style={{ marginBottom: 20, padding: 16, border: "1px solid var(--border, #e2e8f0)", borderRadius: 12 }}>
                <input
                  placeholder="Child name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={inputStyle}
                />
                <input
                  type="date"
                  value={newBirthDate}
                  onChange={(e) => setNewBirthDate(e.target.value)}
                  style={inputStyle}
                  max={new Date().toISOString().split("T")[0]}
                />
                <input
                  type="password"
                  placeholder="Parent PIN (optional, 4+ digits)"
                  value={newPin}
                  onChange={(e) => setNewPin(e.target.value)}
                  maxLength={8}
                  style={inputStyle}
                />
                <button onClick={handleCreate} style={primaryBtn} disabled={!newName.trim()}>
                  Create Profile
                </button>
              </div>
            )}

            {profiles.length === 0 ? (
              <p style={{ color: "var(--muted, #718096)", textAlign: "center", padding: 20 }}>
                No profiles yet. Create one to get started.
              </p>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
                {profiles.map((p) => (
                  <div
                    key={p.id}
                    style={{ padding: 16, border: "1px solid var(--border, #e2e8f0)", borderRadius: 12, cursor: "pointer" }}
                    onClick={() => setSelectedProfile(p)}
                  >
                    <div style={{ fontWeight: 600, fontSize: 18 }}>{p.name}</div>
                    <div style={{ fontSize: 14, color: "var(--muted, #718096)" }}>Age: {p.age ?? "?"} ({p.age_band})</div>
                    <div style={{ fontSize: 14, color: "var(--muted, #718096)" }}>
                      {p.has_pin ? "PIN protected" : "No PIN"}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div style={{ marginTop: 16, padding: 12, background: "var(--surface-2, #f7fafc)", borderRadius: 8 }}>
              <a href="/kids" target="_blank" style={{ color: "#667eea", fontWeight: 600 }}>
                Open Kids Mode {"->"} /kids
              </a>
            </div>
          </>
        ) : (
          <>
            <button onClick={() => setSelectedProfile(null)} style={{ ...secondaryBtn, marginBottom: 16 }}>
              All Profiles
            </button>

            {report && (
              <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
                <div style={statCard}>
                  <div style={statValue}>{report.total_stars || 0}</div>
                  <div style={statLabel}>Total Stars</div>
                </div>
                <div style={statCard}>
                  <div style={statValue}>{report.total_books || 0}</div>
                  <div style={statLabel}>Books</div>
                </div>
                <div style={statCard}>
                  <div style={statValue}>{Math.round((report.total_time_seconds || 0) / 60)}m</div>
                  <div style={statLabel}>Reading Time</div>
                </div>
                <div style={statCard}>
                  <div style={statValue}>{report.total_quiz_attempts || 0}</div>
                  <div style={statLabel}>Quizzes</div>
                </div>
              </div>
            )}

            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Assigned Books</h3>
            {library.length === 0 ? (
              <p style={{ color: "var(--muted, #718096)" }}>No books assigned.</p>
            ) : (
              <div style={{ marginBottom: 20 }}>
                {library.map((item) => {
                  const doc = item.document as Record<string, any>;
                  return (
                    <div key={item.assignment.document_id} style={bookRow}>
                      <span style={{ flex: 1 }}>{doc.title}</span>
                      <span style={{ fontSize: 14, color: "var(--muted)" }}>
                        Stars: {item.progress.total_stars}
                      </span>
                      <button
                        onClick={() => handleUnassign(item.assignment.document_id)}
                        style={{ ...miniBtn, background: "#fed7d7" }}
                      >
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Add Books</h3>
            <div style={{ maxHeight: 200, overflowY: "auto" }}>
              {allDocs
                .filter((d) => !library.some((l) => l.assignment.document_id === d.id))
                .map((doc) => (
                  <div key={doc.id} style={bookRow}>
                    <span style={{ flex: 1 }}>{doc.title}</span>
                    <button onClick={() => handleAssign(doc.id)} style={{ ...miniBtn, background: "#c6f6d5" }}>
                      Assign
                    </button>
                  </div>
                ))}
            </div>

            <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border, #e2e8f0)" }}>
              <button
                onClick={() => handleDeleteProfile(selectedProfile.id)}
                style={{ ...miniBtn, background: "#fed7d7", color: "#c53030" }}
              >
                Delete Profile
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const closeBtn: React.CSSProperties = {
  background: "transparent", border: "none", fontSize: 22, cursor: "pointer", padding: "4px 8px",
};
const primaryBtn: React.CSSProperties = {
  background: "#667eea", color: "white", border: "none", borderRadius: 8,
  padding: "8px 16px", fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const secondaryBtn: React.CSSProperties = {
  background: "var(--surface-2, #e2e8f0)", border: "none", borderRadius: 8,
  padding: "8px 16px", fontSize: 14, fontWeight: 600, cursor: "pointer",
};
const inputStyle: React.CSSProperties = {
  display: "block", width: "100%", marginBottom: 8, padding: "8px 12px",
  borderRadius: 8, border: "1px solid var(--border, #e2e8f0)", fontSize: 16,
  background: "var(--surface, white)", color: "var(--foreground)",
};
const statCard: React.CSSProperties = {
  padding: "12px 20px", background: "var(--surface-2, #f7fafc)", borderRadius: 12,
  textAlign: "center", minWidth: 80,
};
const statValue: React.CSSProperties = { fontSize: 28, fontWeight: 800, color: "#667eea" };
const statLabel: React.CSSProperties = { fontSize: 12, color: "var(--muted, #718096)" };
const bookRow: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 12, padding: "8px 0",
  borderBottom: "1px solid var(--border, #edf2f7)",
};
const miniBtn: React.CSSProperties = {
  border: "none", borderRadius: 6, padding: "4px 12px",
  fontSize: 13, fontWeight: 600, cursor: "pointer",
};
