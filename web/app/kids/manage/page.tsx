"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  kidsAdminApi,
  type KidsProfile,
  type KidsFamilyLibraryItem,
  type KidsLibraryItem,
  type KidsDeviceSessionItem,
} from "@/lib/kids-api";

const AVATARS = ["🦊", "🐼", "🦄", "🐸", "🐱", "🐶", "🦁", "🐰"];

type TabKey = "children" | "library" | "devices";
type LibraryFilter = "all" | "pending" | "approved" | "archived";

type KidsReportSummary = {
  chapters_completed?: number;
  completed_books?: number;
  total_books?: number;
  quiz_average_percent?: number;
  chapter_quiz_attempts?: number;
  chapter_quiz_exemptions?: number;
  chapter_quiz_average_percent?: number;
  total_time_seconds?: number;
};

export default function KidsManagePage() {
  const [activeTab, setActiveTab] = useState<TabKey>("children");
  const [profiles, setProfiles] = useState<KidsProfile[]>([]);
  const [selectedChild, setSelectedChild] = useState<KidsProfile | null>(null);
  const [childLibrary, setChildLibrary] = useState<KidsLibraryItem[]>([]);
  const [report, setReport] = useState<KidsReportSummary | null>(null);
  const [usage, setUsage] = useState<{
    used_seconds: number;
    limit_seconds: number;
    bonus_seconds: number;
  } | null>(null);

  // Library tab state
  const [familyLibrary, setFamilyLibrary] = useState<KidsFamilyLibraryItem[]>([]);
  const [libraryFilter, setLibraryFilter] = useState<LibraryFilter>("all");
  const [personalCandidates, setPersonalCandidates] = useState<Record<string, any>[]>([]);
  const [showPersonalModal, setShowPersonalModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Review & Assign modal state
  const [reviewingBook, setReviewingBook] = useState<KidsFamilyLibraryItem | null>(null);
  const [selectedAgeBands, setSelectedAgeBands] = useState<string[]>(["6-8"]);
  const [reviewNote, setReviewNote] = useState("");
  const [confirmSafety, setConfirmSafety] = useState(false);
  const [targetChildIds, setTargetChildIds] = useState<string[]>([]);
  const [savingReview, setSavingReview] = useState(false);

  // Device pairing state
  const [devices, setDevices] = useState<KidsDeviceSessionItem[]>([]);
  const [pairingModalChild, setPairingModalChild] = useState<KidsProfile | null>(null);
  const [activePairingCode, setActivePairingCode] = useState<{ code: string; expires_at: number } | null>(null);

  // Profile creation state
  const [showCreateChild, setShowCreateChild] = useState(false);
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [pin, setPin] = useState("");
  const [creating, setCreating] = useState(false);

  // Purge confirmation modal state
  const [purgingBook, setPurgingBook] = useState<KidsFamilyLibraryItem | null>(null);
  const [purgeConfirmTitle, setPurgeConfirmTitle] = useState("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successToast, setSuccessToast] = useState("");

  const showToast = (msg: string) => {
    setSuccessToast(msg);
    setTimeout(() => setSuccessToast(""), 3000);
  };

  const loadProfiles = useCallback(async () => {
    try {
      const { profiles } = await kidsAdminApi.listProfiles();
      setProfiles(profiles);
      return profiles;
    } catch {
      setError("Failed to load profiles");
      return [];
    }
  }, []);

  const loadFamilyLibrary = useCallback(async () => {
    try {
      const data = await kidsAdminApi.getFamilyLibrary();
      setFamilyLibrary(data.items || []);
    } catch {
      // ignore
    }
  }, []);

  const loadDevices = useCallback(async () => {
    try {
      const data = await kidsAdminApi.listDeviceSessions();
      setDevices(data.devices || []);
    } catch {
      // ignore
    }
  }, []);

  const loadChildDetails = useCallback(async (profileId: string) => {
    try {
      const [lib, rep] = await Promise.all([
        kidsAdminApi.listAssignedBooks(profileId),
        kidsAdminApi.learningReport(profileId),
      ]);
      setChildLibrary(lib.library || []);
      setReport(rep as KidsReportSummary);
      setUsage(rep.usage as typeof usage);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.all([loadProfiles(), loadFamilyLibrary(), loadDevices()]);
      setLoading(false);
    })();
  }, [loadProfiles, loadFamilyLibrary, loadDevices]);

  useEffect(() => {
    if (selectedChild) {
      loadChildDetails(selectedChild.id);
    }
  }, [selectedChild, loadChildDetails]);

  // Handle child creation
  const handleCreateProfile = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setError("");
    try {
      const normalizedDate = (birthDate || "").trim().replace(/\//g, "-").replace(/\./g, "-");
      const { profile } = await kidsAdminApi.createProfile({
        name: name.trim(),
        birth_date: normalizedDate || undefined,
        parent_pin: pin || undefined,
      });
      setName("");
      setBirthDate("");
      setPin("");
      setShowCreateChild(false);
      await loadProfiles();
      setSelectedChild(profile);
      showToast("Child profile created!");
    } catch (e: any) {
      setError(e?.message || "Failed to create profile");
    } finally {
      setCreating(false);
    }
  };

  // Handle direct file upload into Kids Family Library
  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await kidsAdminApi.importKidsBook(file, { auto_approve: false, age_bands: "6-8" });
      await loadFamilyLibrary();
      showToast("Book uploaded to Kids Library (Pending Review)!");
    } catch (err: any) {
      setError(err?.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Handle opening personal candidates modal
  const handleOpenPersonalCandidates = async () => {
    try {
      const { candidates } = await kidsAdminApi.listPersonalCandidates();
      setPersonalCandidates(candidates);
      setShowPersonalModal(true);
    } catch {
      setError("Failed to load personal books");
    }
  };

  // Handle sharing a book from personal bookshelf to kids family library
  const handleShareFromPersonal = async (docId: string) => {
    try {
      await kidsAdminApi.shareFromPersonal(docId, { auto_approve: false, approved_age_bands: ["6-8"] });
      setShowPersonalModal(false);
      await loadFamilyLibrary();
      showToast("Book added to Kids Library for review!");
    } catch (e: any) {
      setError(e?.message || "Failed to share book");
    }
  };

  // Open review modal
  const openReviewModal = (item: KidsFamilyLibraryItem) => {
    setReviewingBook(item);
    setSelectedAgeBands(
      item.entry.approved_age_bands && item.entry.approved_age_bands.length > 0
        ? [...item.entry.approved_age_bands]
        : ["6-8"]
    );
    setReviewNote(item.entry.reviewer_note || "");
    setConfirmSafety(item.entry.kids_review_status === "approved");
    setTargetChildIds(item.assigned_profiles ? item.assigned_profiles.map((p) => p.id) : []);
  };

  // Save review & assignments
  const handleSaveReviewAndAssign = async () => {
    if (!reviewingBook) return;
    if (!confirmSafety) {
      setError("Please confirm you have reviewed the book content for safety.");
      return;
    }
    setSavingReview(true);
    setError("");
    try {
      const docId = reviewingBook.document.id;
      // 1. Update review status
      await kidsAdminApi.reviewBook(docId, {
        status: "approved",
        approved_age_bands: selectedAgeBands as any,
        reviewer_note: reviewNote,
      });
      // 2. Assign to selected children
      await kidsAdminApi.assignToProfiles(docId, {
        profile_ids: targetChildIds,
        content_confirmed: true,
      });

      setReviewingBook(null);
      await Promise.all([loadFamilyLibrary(), selectedChild ? loadChildDetails(selectedChild.id) : Promise.resolve()]);
      showToast("Book approved & assigned successfully!");
    } catch (e: any) {
      setError(e?.message || "Failed to save review and assignment");
    } finally {
      setSavingReview(false);
    }
  };

  // Handle archive/unarchive
  const handleToggleArchive = async (item: KidsFamilyLibraryItem) => {
    try {
      if (item.entry.kids_review_status === "archived") {
        await kidsAdminApi.unarchiveBook(item.document.id);
        showToast("Book restored to approved library!");
      } else {
        await kidsAdminApi.archiveBook(item.document.id);
        showToast("Book archived (child progress preserved)!");
      }
      await loadFamilyLibrary();
    } catch (e: any) {
      setError(e?.message || "Archive action failed");
    }
  };

  // Handle purge
  const handleExecutePurge = async () => {
    if (!purgingBook) return;
    try {
      await kidsAdminApi.purgeBook(purgingBook.document.id, purgeConfirmTitle);
      setPurgingBook(null);
      setPurgeConfirmTitle("");
      await loadFamilyLibrary();
      showToast("Book removed from kids library.");
    } catch (e: any) {
      setError(e?.message || "Failed to delete book");
    }
  };

  // Handle device pairing code generation
  const handleGeneratePairingCode = async (child: KidsProfile) => {
    setPairingModalChild(child);
    try {
      const { pairing } = await kidsAdminApi.createDevicePairing(child.id, 600);
      setActivePairingCode({ code: pairing.code, expires_at: pairing.expires_at });
    } catch (e: any) {
      setError(e?.message || "Failed to generate pairing code");
    }
  };

  // Handle revoking device session
  const handleRevokeDevice = async (sessionId: string) => {
    if (!confirm("Revoke access for this device?")) return;
    try {
      await kidsAdminApi.revokeDeviceSession(sessionId);
      await loadDevices();
      showToast("Device revoked.");
    } catch (e: any) {
      setError(e?.message || "Failed to revoke device");
    }
  };

  // Handle unassign from child
  const handleUnassignChildBook = async (docId: string) => {
    if (!selectedChild) return;
    try {
      await kidsAdminApi.unassignBook(selectedChild.id, docId);
      await loadChildDetails(selectedChild.id);
      showToast("Book removed from child bookshelf.");
    } catch (e: any) {
      setError(e?.message || "Failed to unassign");
    }
  };

  // Handle delete child profile
  const handleDeleteChildProfile = async (profileId: string) => {
    if (!confirm("Delete this child profile? All reading stars and progress will be deleted.")) return;
    try {
      await kidsAdminApi.deleteProfile(profileId);
      setSelectedChild(null);
      await loadProfiles();
      showToast("Profile deleted.");
    } catch (e: any) {
      setError(e?.message || "Failed to delete profile");
    }
  };

  const filteredLibrary = familyLibrary.filter((item) => {
    if (libraryFilter === "all") return true;
    if (libraryFilter === "pending") return item.entry.kids_review_status === "pending";
    if (libraryFilter === "approved") return item.entry.kids_review_status === "approved";
    if (libraryFilter === "archived") return item.entry.kids_review_status === "archived";
    return true;
  });

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f8fafc" }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: "#64748b" }}>Loading Parent Center...</div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", padding: "24px 16px", color: "#1e293b" }}>
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* Top Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 32 }}>🛡️</span>
              <h1 style={{ fontSize: 26, fontWeight: 800, margin: 0, color: "#0f172a" }}>
                Family Kids Reading Center / 家长中心
              </h1>
            </div>
            <p style={{ fontSize: 14, color: "#64748b", margin: "4px 0 0 42px" }}>
              Isolated, safe, parent-approved reading library and child supervision.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <a
              href="/kids"
              target="_blank"
              rel="noreferrer"
              style={{
                ...btnStyle,
                background: "#e0e7ff",
                color: "#4338ca",
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span>🚀</span> Open Kids Portal
            </a>
          </div>
        </div>

        {/* Global Notifications */}
        {error && (
          <div style={{ background: "#fee2e2", color: "#b91c1c", padding: "12px 16px", borderRadius: 10, marginBottom: 16, display: "flex", justifyContent: "space-between" }}>
            <span>{error}</span>
            <button onClick={() => setError("")} style={{ border: "none", background: "transparent", cursor: "pointer", fontWeight: 700 }}>✕</button>
          </div>
        )}
        {successToast && (
          <div style={{ background: "#dcfce7", color: "#15803d", padding: "12px 16px", borderRadius: 10, marginBottom: 16 }}>
            {successToast}
          </div>
        )}

        {/* Main Navigation Tabs */}
        <div style={{ display: "flex", gap: 8, borderBottom: "2px solid #e2e8f0", marginBottom: 24 }}>
          <button
            onClick={() => { setActiveTab("children"); setSelectedChild(null); }}
            style={{
              ...tabBtnStyle,
              borderBottom: activeTab === "children" ? "3px solid #6366f1" : "3px solid transparent",
              color: activeTab === "children" ? "#4f46e5" : "#64748b",
              fontWeight: activeTab === "children" ? 700 : 500,
            }}
          >
            👶 Children (孩子档案) {profiles.length > 0 && `(${profiles.length})`}
          </button>
          <button
            onClick={() => setActiveTab("library")}
            style={{
              ...tabBtnStyle,
              borderBottom: activeTab === "library" ? "3px solid #6366f1" : "3px solid transparent",
              color: activeTab === "library" ? "#4f46e5" : "#64748b",
              fontWeight: activeTab === "library" ? 700 : 500,
            }}
          >
            📚 Kids Family Library (家庭儿童书库) {familyLibrary.length > 0 && `(${familyLibrary.length})`}
          </button>
          <button
            onClick={() => setActiveTab("devices")}
            style={{
              ...tabBtnStyle,
              borderBottom: activeTab === "devices" ? "3px solid #6366f1" : "3px solid transparent",
              color: activeTab === "devices" ? "#4f46e5" : "#64748b",
              fontWeight: activeTab === "devices" ? 700 : 500,
            }}
          >
            📱 Device Management (设备配对) {devices.length > 0 && `(${devices.length})`}
          </button>
        </div>

        {/* TAB 1: CHILDREN */}
        {activeTab === "children" && (
          <div>
            {!selectedChild ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Child Profiles</h2>
                  <button
                    onClick={() => setShowCreateChild(!showCreateChild)}
                    style={{ ...btnStyle, background: "#6366f1", color: "white" }}
                  >
                    {showCreateChild ? "Cancel" : "+ Add Child Profile"}
                  </button>
                </div>

                {showCreateChild && (
                  <div style={{ ...cardStyle, marginBottom: 20, border: "2px solid #e0e7ff" }}>
                    <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 0, marginBottom: 14 }}>New Child Profile</h3>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                      <div>
                        <label style={labelStyle}>Child Name</label>
                        <input
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          placeholder="e.g. Bao"
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
                      </div>
                    </div>
                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14, gap: 8 }}>
                      <button onClick={() => setShowCreateChild(false)} style={{ ...btnStyle, background: "#e2e8f0", color: "#475569" }}>
                        Cancel
                      </button>
                      <button
                        onClick={handleCreateProfile}
                        disabled={!name.trim() || creating}
                        style={{ ...btnStyle, background: "#10b981", color: "white", opacity: !name.trim() ? 0.5 : 1 }}
                      >
                        {creating ? "Creating..." : "Create Profile"}
                      </button>
                    </div>
                  </div>
                )}

                {profiles.length === 0 && !showCreateChild ? (
                  <div style={{ ...cardStyle, textAlign: "center", padding: 40 }}>
                    <div style={{ fontSize: 48, marginBottom: 10 }}>👶</div>
                    <h3 style={{ fontSize: 18, color: "#475569", margin: 0 }}>No child profiles yet</h3>
                    <p style={{ fontSize: 14, color: "#94a3b8", marginTop: 6 }}>
                      Create a profile to assign books, set reading limits, and generate device pairing codes.
                    </p>
                  </div>
                ) : (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
                    {profiles.map((p, i) => (
                      <div
                        key={p.id}
                        onClick={() => setSelectedChild(p)}
                        style={{
                          ...cardStyle,
                          cursor: "pointer",
                          textAlign: "center",
                          transition: "transform 0.15s, box-shadow 0.15s",
                        }}
                      >
                        <div style={{ fontSize: 48, marginBottom: 8 }}>{AVATARS[i % AVATARS.length]}</div>
                        <div style={{ fontSize: 19, fontWeight: 700, color: "#0f172a" }}>{p.name}</div>
                        <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
                          Age {p.age ?? "?"} ({p.age_band ?? "?"})
                        </div>
                        <div style={{ fontSize: 12, color: p.has_pin ? "#7c3aed" : "#94a3b8", marginTop: 4 }}>
                          {p.has_pin ? "🔒 PIN Protected" : "🔓 No PIN"}
                        </div>
                        <div style={{ marginTop: 12, display: "flex", gap: 6, justifyContent: "center" }}>
                          <span style={{ fontSize: 12, background: "#eff6ff", color: "#2563eb", padding: "4px 8px", borderRadius: 6 }}>
                            Manage & Books →
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div>
                <button
                  onClick={() => setSelectedChild(null)}
                  style={{ ...btnStyle, background: "#e2e8f0", color: "#475569", marginBottom: 16 }}
                >
                  ← All Children
                </button>

                <div style={{ ...cardStyle, marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
                    <div>
                      <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>{selectedChild.name}&apos;s Dashboard</h2>
                      <p style={{ fontSize: 14, color: "#64748b", marginTop: 4 }}>
                        Age {selectedChild.age} · Age Band {selectedChild.age_band} ({
                          selectedChild.age_band === "3-5"
                            ? "Parent-supervised co-reading"
                            : selectedChild.age_band === "6-8"
                            ? "Independent: Recall & Vocabulary"
                            : "Independent: Inference & Comprehension"
                        })
                      </p>
                    </div>
                    <button
                      onClick={() => handleGeneratePairingCode(selectedChild)}
                      style={{ ...btnStyle, background: "#6366f1", color: "white", display: "inline-flex", alignItems: "center", gap: 6 }}
                    >
                      <span>🔑</span> Generate Device Pairing Code
                    </button>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12, marginTop: 18, borderTop: "1px solid #f1f5f9", paddingTop: 16 }}>
                    <div style={statBox}>
                      <div style={statLabel}>Today Reading</div>
                      <div style={statValue}>{usage ? Math.round(usage.used_seconds / 60) : 0}m</div>
                      <div style={{ fontSize: 11, color: "#94a3b8" }}>
                        Limit: {selectedChild.daily_limit_minutes + Math.round((usage?.bonus_seconds || 0) / 60)}m
                      </div>
                    </div>
                    <div style={statBox}>
                      <div style={statLabel}>Total Stars</div>
                      <div style={{ ...statValue, color: "#d97706" }}>⭐ {(report as any)?.total_stars ?? 0}</div>
                    </div>
                    <div style={statBox}>
                      <div style={statLabel}>Chapters Done</div>
                      <div style={statValue}>{report?.chapters_completed ?? 0}</div>
                    </div>
                    <div style={statBox}>
                      <div style={statLabel}>Quiz Best Avg</div>
                      <div style={{ ...statValue, color: "#10b981" }}>{Math.round(report?.chapter_quiz_average_percent ?? 0)}%</div>
                    </div>
                  </div>
                </div>

                <div style={{ ...cardStyle, marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>
                      Assigned Books ({childLibrary.length})
                    </h3>
                    <button
                      onClick={() => setActiveTab("library")}
                      style={{ ...miniBtn, background: "#e0e7ff", color: "#4338ca" }}
                    >
                      + Assign More from Kids Library
                    </button>
                  </div>

                  {childLibrary.length === 0 ? (
                    <div style={{ textAlign: "center", padding: 24, color: "#94a3b8" }}>
                      No books assigned yet. Go to the <strong>Kids Family Library</strong> tab to review and assign books.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {childLibrary.map((item) => {
                        const doc = item.document as Record<string, any>;
                        const totalCh = Array.isArray(doc.sections) ? doc.sections.length : 0;
                        const completedCh = item.progress.completed_section_ids.length;
                        return (
                          <div key={item.assignment.document_id} style={rowStyle}>
                            <div style={{ flex: 1, minWidth: 180 }}>
                              <div style={{ fontWeight: 600, fontSize: 15 }}>{doc.title}</div>
                              <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                                Progress: {completedCh}/{totalCh} chapters · Stars: {item.progress.total_stars}
                              </div>
                            </div>
                            <button
                              onClick={() => handleUnassignChildBook(item.assignment.document_id)}
                              style={{ ...miniBtn, background: "#fee2e2", color: "#b91c1c" }}
                            >
                              Remove from child
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div style={{ textAlign: "center", marginTop: 24 }}>
                  <button
                    onClick={() => handleDeleteChildProfile(selectedChild.id)}
                    style={{ ...miniBtn, background: "transparent", color: "#ef4444", border: "1px solid #fecaca", padding: "8px 16px" }}
                  >
                    Delete {selectedChild.name}&apos;s Profile
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: KIDS FAMILY LIBRARY */}
        {activeTab === "library" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 10 }}>
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Kids Family Library / 儿童书库</h2>
                <p style={{ fontSize: 13, color: "#64748b", margin: "2px 0 0 0" }}>
                  Only approved books in this library can be seen and read by children.
                </p>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  onClick={handleOpenPersonalCandidates}
                  style={{ ...btnStyle, background: "#f1f5f9", color: "#334155" }}
                >
                  + Add from Personal Bookshelf
                </button>
                <button
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                  style={{ ...btnStyle, background: "#6366f1", color: "white" }}
                >
                  {uploading ? "Uploading..." : "+ Upload New Kids Book"}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".epub,.pdf,.txt,.md"
                  style={{ display: "none" }}
                  onChange={handleUploadFile}
                />
              </div>
            </div>

            <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
              {(
                [
                  ["all", "All"],
                  ["pending", "Pending Review (待审核)"],
                  ["approved", "Approved (已审核/可分配)"],
                  ["archived", "Archived (已下架)"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setLibraryFilter(key)}
                  style={{
                    ...miniBtn,
                    background: libraryFilter === key ? "#0f172a" : "#f1f5f9",
                    color: libraryFilter === key ? "white" : "#475569",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {filteredLibrary.length === 0 ? (
              <div style={{ ...cardStyle, textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48, marginBottom: 10 }}>📖</div>
                <h3 style={{ fontSize: 18, color: "#475569", margin: 0 }}>No books in this view</h3>
                <p style={{ fontSize: 14, color: "#94a3b8", marginTop: 6 }}>
                  Click &quot;+ Upload New Kids Book&quot; to upload an EPUB/PDF or add from your personal reading shelf.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {filteredLibrary.map((item) => {
                  const doc = item.document;
                  const entry = item.entry;
                  const isPending = entry.kids_review_status === "pending";
                  const isApproved = entry.kids_review_status === "approved";
                  const isArchived = entry.kids_review_status === "archived";

                  return (
                    <div key={doc.id} style={{ ...cardStyle, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                      <div
                        style={{
                          width: 56,
                          height: 76,
                          borderRadius: 6,
                          background: "linear-gradient(135deg, #6366f1, #9333ea)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "white",
                          fontWeight: 700,
                          fontSize: 18,
                          overflow: "hidden",
                          flexShrink: 0,
                        }}
                      >
                        {doc.cover_url ? (
                          <img src={doc.cover_url} alt={doc.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                        ) : (
                          doc.title.slice(0, 2).toUpperCase()
                        )}
                      </div>

                      <div style={{ flex: 1, minWidth: 220 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 700, fontSize: 16, color: "#0f172a" }}>{doc.title}</span>
                          {isPending && (
                            <span style={{ fontSize: 11, background: "#fef3c7", color: "#92400e", padding: "2px 8px", borderRadius: 12, fontWeight: 600 }}>
                              ⏳ Pending Review
                            </span>
                          )}
                          {isApproved && (
                            <span style={{ fontSize: 11, background: "#dcfce7", color: "#15803d", padding: "2px 8px", borderRadius: 12, fontWeight: 600 }}>
                              ✓ Approved
                            </span>
                          )}
                          {isArchived && (
                            <span style={{ fontSize: 11, background: "#f1f5f9", color: "#64748b", padding: "2px 8px", borderRadius: 12, fontWeight: 600 }}>
                              📦 Archived
                            </span>
                          )}
                        </div>

                        <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>
                          {doc.sections ? doc.sections.length : 0} chapters · Format: {doc.source_format}
                          {entry.approved_age_bands && entry.approved_age_bands.length > 0 && (
                            <span style={{ marginLeft: 8, color: "#4f46e5", fontWeight: 500 }}>
                              Ages: {entry.approved_age_bands.join(", ")}
                            </span>
                          )}
                        </div>

                        <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                          Assigned to: {item.assigned_profiles && item.assigned_profiles.length > 0
                            ? item.assigned_profiles.map((p) => p.name).join(", ")
                            : "None yet"}
                        </div>
                      </div>

                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button
                          onClick={() => openReviewModal(item)}
                          style={{
                            ...miniBtn,
                            background: isPending ? "#6366f1" : "#e0e7ff",
                            color: isPending ? "white" : "#4338ca",
                            fontWeight: 600,
                          }}
                        >
                          {isPending ? "Review & Assign" : "Edit Review / Assign"}
                        </button>

                        <button
                          onClick={() => handleToggleArchive(item)}
                          style={{ ...miniBtn, background: "#f1f5f9", color: "#475569" }}
                        >
                          {isArchived ? "Restore" : "Archive"}
                        </button>

                        <button
                          onClick={() => { setPurgingBook(item); setPurgeConfirmTitle(""); }}
                          style={{ ...miniBtn, background: "transparent", color: "#ef4444", border: "1px solid #fee2e2" }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* TAB 3: DEVICES */}
        {activeTab === "devices" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Device Pairing & Supervision</h2>
                <p style={{ fontSize: 13, color: "#64748b", margin: "2px 0 0 0" }}>
                  Pair your child&apos;s iPad, phone, or laptop with a single 6-digit code.
                </p>
              </div>
            </div>

            <div style={{ ...cardStyle, marginBottom: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 0, marginBottom: 12 }}>
                Active Paired Devices ({devices.length})
              </h3>
              {devices.length === 0 ? (
                <div style={{ textAlign: "center", padding: 24, color: "#94a3b8" }}>
                  No active devices paired yet. Click a child profile below to generate a pairing code.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {devices.map((d) => (
                    <div key={d.id} style={rowStyle}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 15 }}>
                          {d.device_name} — <span style={{ color: "#4f46e5" }}>{d.profile_name}</span>
                        </div>
                        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
                          Last active: {new Date(d.last_seen_at * 1000).toLocaleString()}
                        </div>
                      </div>
                      <button
                        onClick={() => handleRevokeDevice(d.id)}
                        style={{ ...miniBtn, background: "#fee2e2", color: "#b91c1c" }}
                      >
                        Revoke Access
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={cardStyle}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 0, marginBottom: 12 }}>
                Pair a New Device for Child
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
                {profiles.map((p, i) => (
                  <button
                    key={p.id}
                    onClick={() => handleGeneratePairingCode(p)}
                    style={{
                      ...cardStyle,
                      border: "1px solid #e2e8f0",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: 12,
                      background: "#f8fafc",
                    }}
                  >
                    <span style={{ fontSize: 24 }}>{AVATARS[i % AVATARS.length]}</span>
                    <div style={{ textAlign: "left" }}>
                      <div style={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "#6366f1" }}>Generate 6-digit Code →</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* MODALS */}
        {/* Review & Assign Modal */}
        {reviewingBook && (
          <div style={modalOverlay}>
            <div style={{ ...modalBox, maxWidth: 640 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Review & Assign Book</h3>
                <button onClick={() => setReviewingBook(null)} style={closeBtn}>✕</button>
              </div>

              <div style={{ marginBottom: 14, background: "#f8fafc", padding: 12, borderRadius: 8 }}>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{reviewingBook.document.title}</div>
                <div style={{ fontSize: 13, color: "#64748b", marginTop: 2 }}>
                  {reviewingBook.document.sections?.length || 0} chapters · Format: {reviewingBook.document.source_format}
                </div>
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>Recommended Age Bands (适龄范围)</label>
                <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                  {["3-5", "6-8", "9-12"].map((band) => (
                    <label key={band} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={selectedAgeBands.includes(band)}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedAgeBands([...selectedAgeBands, band]);
                          else setSelectedAgeBands(selectedAgeBands.filter((b) => b !== band));
                        }}
                      />
                      <span>Ages {band}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>Assign to Child(ren) (分配给孩子)</label>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                  {profiles.map((p) => (
                    <label key={p.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={targetChildIds.includes(p.id)}
                        onChange={(e) => {
                          if (e.target.checked) setTargetChildIds([...targetChildIds, p.id]);
                          else setTargetChildIds(targetChildIds.filter((id) => id !== p.id));
                        }}
                      />
                      <span>{p.name} (Age {p.age})</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ marginBottom: 20, padding: 12, background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, color: "#15803d", cursor: "pointer", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={confirmSafety}
                    onChange={(e) => setConfirmSafety(e.target.checked)}
                  />
                  <span>I have reviewed this content and confirm it is appropriate for children.</span>
                </label>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button onClick={() => setReviewingBook(null)} style={{ ...btnStyle, background: "#e2e8f0", color: "#475569" }}>
                  Cancel
                </button>
                <button
                  onClick={handleSaveReviewAndAssign}
                  disabled={!confirmSafety || savingReview}
                  style={{
                    ...btnStyle,
                    background: confirmSafety ? "#10b981" : "#cbd5e1",
                    color: "white",
                    cursor: confirmSafety ? "pointer" : "not-allowed",
                  }}
                >
                  {savingReview ? "Saving..." : "Confirm & Assign"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Personal Books Candidates Modal */}
        {showPersonalModal && (
          <div style={modalOverlay}>
            <div style={{ ...modalBox, maxWidth: 560 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Add from Personal Bookshelf</h3>
                <button onClick={() => setShowPersonalModal(false)} style={closeBtn}>✕</button>
              </div>

              <p style={{ fontSize: 13, color: "#64748b", marginTop: 0, marginBottom: 14 }}>
                Choose a book from your personal reading library. It will be added into the Kids Library in <strong>Pending Review</strong> status for your inspection.
              </p>

              {personalCandidates.length === 0 ? (
                <div style={{ textAlign: "center", padding: 24, color: "#94a3b8" }}>
                  No available personal books to share.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 300, overflowY: "auto" }}>
                  {personalCandidates.map((cand) => (
                    <div key={cand.id} style={rowStyle}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{cand.title}</div>
                        <div style={{ fontSize: 12, color: "#64748b" }}>{cand.sections?.length || 0} chapters</div>
                      </div>
                      <button
                        onClick={() => handleShareFromPersonal(cand.id)}
                        style={{ ...miniBtn, background: "#6366f1", color: "white" }}
                      >
                        + Add to Kids Library
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Pairing Code Display Modal */}
        {pairingModalChild && activePairingCode && (
          <div style={modalOverlay}>
            <div style={{ ...modalBox, maxWidth: 440, textAlign: "center" }}>
              <div style={{ fontSize: 48, marginBottom: 8 }}>📱</div>
              <h3 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>
                Pair Device for {pairingModalChild.name}
              </h3>
              <p style={{ fontSize: 14, color: "#64748b", marginTop: 6 }}>
                Open <strong>/kids</strong> on your child&apos;s device and enter this 6-digit code:
              </p>

              <div
                style={{
                  fontSize: 40,
                  fontWeight: 900,
                  letterSpacing: 10,
                  color: "#4f46e5",
                  background: "#f1f5f9",
                  padding: "16px 20px",
                  borderRadius: 16,
                  margin: "16px 0",
                }}
              >
                {activePairingCode.code}
              </div>

              <p style={{ fontSize: 12, color: "#94a3b8" }}>
                This code expires in 10 minutes and can only be used once.
              </p>

              <button
                onClick={() => { setPairingModalChild(null); setActivePairingCode(null); loadDevices(); }}
                style={{ ...btnStyle, background: "#0f172a", color: "white", marginTop: 12 }}
              >
                Done
              </button>
            </div>
          </div>
        )}

        {/* Purge Modal */}
        {purgingBook && (
          <div style={modalOverlay}>
            <div style={{ ...modalBox, maxWidth: 460 }}>
              <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: "#b91c1c" }}>
                Permanent Delete Confirmation
              </h3>
              <p style={{ fontSize: 14, color: "#475569", marginTop: 8 }}>
                Are you sure you want to permanently delete <strong>{purgingBook.document.title}</strong> from the Kids Library?
              </p>
              <p style={{ fontSize: 13, color: "#64748b" }}>
                Please type the book title <code>{purgingBook.document.title}</code> to confirm:
              </p>
              <input
                value={purgeConfirmTitle}
                onChange={(e) => setPurgeConfirmTitle(e.target.value)}
                placeholder={purgingBook.document.title}
                style={inputStyle}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
                <button onClick={() => setPurgingBook(null)} style={{ ...btnStyle, background: "#e2e8f0", color: "#475569" }}>
                  Cancel
                </button>
                <button
                  onClick={handleExecutePurge}
                  disabled={purgeConfirmTitle.trim() !== purgingBook.document.title.trim()}
                  style={{
                    ...btnStyle,
                    background: "#ef4444",
                    color: "white",
                    opacity: purgeConfirmTitle.trim() !== purgingBook.document.title.trim() ? 0.5 : 1,
                  }}
                >
                  Confirm Delete
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const tabBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  padding: "10px 16px",
  fontSize: 15,
  cursor: "pointer",
  transition: "all 0.15s",
};

const btnStyle: React.CSSProperties = {
  border: "none",
  borderRadius: 8,
  padding: "8px 16px",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
};

const miniBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 6,
  padding: "6px 12px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

const cardStyle: React.CSSProperties = {
  background: "white",
  borderRadius: 12,
  padding: 18,
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
  border: "1px solid #f1f5f9",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "#334155",
  marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 12px",
  borderRadius: 8,
  border: "1px solid #cbd5e1",
  fontSize: 15,
  outline: "none",
};

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "10px 0",
  borderBottom: "1px solid #f1f5f9",
  flexWrap: "wrap",
};

const statBox: React.CSSProperties = {
  background: "#f8fafc",
  borderRadius: 10,
  padding: "10px 14px",
  textAlign: "center",
};

const statLabel: React.CSSProperties = {
  fontSize: 12,
  color: "#64748b",
  fontWeight: 600,
};

const statValue: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 800,
  color: "#0f172a",
  marginTop: 2,
};

const modalOverlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.5)",
  backdropFilter: "blur(4px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
  padding: 16,
};

const modalBox: React.CSSProperties = {
  background: "white",
  borderRadius: 16,
  padding: 24,
  width: "100%",
  boxShadow: "0 20px 25px -5px rgba(0,0,0,0.1)",
  maxHeight: "90vh",
  overflowY: "auto",
};

const closeBtn: React.CSSProperties = {
  background: "transparent",
  border: "none",
  fontSize: 18,
  cursor: "pointer",
  color: "#94a3b8",
};
