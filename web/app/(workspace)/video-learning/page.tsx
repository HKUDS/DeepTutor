"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  createVideoNote,
  deleteVideoNote,
  formatPosition,
  getSessionCommand,
  listDevices,
  listRemoteSessions,
  listVideoNotes,
  revokeDevice,
  sendSessionCommand,
  updateVideoNote,
  type RemoteNote,
  type RemoteSession,
} from "@/lib/video-learning-remote-api";

type CommandPayload = Parameters<typeof sendSessionCommand>[1];

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForCommand(sessionId: string, commandId: string) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const command = await getSessionCommand(sessionId, commandId);
    if (command.status === "acked" || command.status === "failed" || command.status === "expired") {
      return command;
    }
    await sleep(250);
  }
  throw new Error("videoRemote.commandTimeout");
}

function VideoLearningRemoteContent() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const lockedSessionId = searchParams.get("viewer_session") || "";
  const [sessions, setSessions] = useState<RemoteSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState(lockedSessionId);
  const [notes, setNotes] = useState<RemoteNote[]>([]);
  const [devices, setDevices] = useState<Array<{ device_id: string; device_name: string; active: boolean }>>([]);
  const [noteBody, setNoteBody] = useState("");
  const [editingNote, setEditingNote] = useState<{ id: string; body: string } | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const loadedVideoRef = useRef("");
  const [seekMs, setSeekMs] = useState(0);
  const [seekDragging, setSeekDragging] = useState(false);
  const [volume, setVolume] = useState(100);

  const selected = useMemo(() => {
    if (lockedSessionId) return sessions.find((session) => session.session_id === lockedSessionId) || null;
    return sessions.find((session) => session.session_id === selectedSessionId) || sessions[0] || null;
  }, [lockedSessionId, selectedSessionId, sessions]);

  const refresh = useCallback(async () => {
    const nextSessions = await listRemoteSessions();
    setSessions(nextSessions);
    const active = lockedSessionId
      ? nextSessions.find((session) => session.session_id === lockedSessionId)
      : nextSessions.find((session) => session.session_id === selectedSessionId) || nextSessions[0];
    if (active) {
      setSelectedSessionId(active.session_id);
      if (loadedVideoRef.current !== active.video_id) {
        loadedVideoRef.current = active.video_id;
        setNotes(await listVideoNotes(active.video_id));
      }
    } else {
      setSelectedSessionId("");
      setNotes([]);
      loadedVideoRef.current = "";
    }
  }, [lockedSessionId, selectedSessionId]);

  const refreshDevices = useCallback(async () => {
    setDevices(await listDevices());
  }, []);

  useEffect(() => {
    void refresh().catch((err) => setError(String(err.message || err)));
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    void refreshDevices().catch(() => undefined);
    const timer = window.setInterval(() => {
      void refreshDevices().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [refreshDevices]);

  useEffect(() => {
    if (selected && !seekDragging) {
      setSeekMs(selected.position_ms);
    }
  }, [seekDragging, selected]);

  async function runCommand(payload: CommandPayload, successMessage?: string) {
    if (!selected) return;
    if (!selected.online) {
      setError(t("videoRemote.viewerOffline"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const command = await sendSessionCommand(selected.session_id, payload);
      const result = await waitForCommand(selected.session_id, command.command_id);
      if (result.status !== "acked") {
        throw new Error(result.error || t("videoRemote.commandDeviceBlocked", { status: result.status }));
      }
      setStatus(successMessage || t("videoRemote.commandAcknowledged", { type: payload.type }));
      await refresh();
    } catch (err) {
      const message = String((err as Error).message || err);
      setError(message.startsWith("videoRemote.") ? t(message) : message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreateNote() {
    if (!selected || !noteBody.trim()) return;
    setBusy(true);
    setError("");
    try {
      const note = await createVideoNote(selected.video_id, {
        body: noteBody.trim(),
        session_id: selected.session_id,
      });
      setNotes((rows) => [...rows, note]);
      setNoteBody("");
      setStatus(t("videoRemote.noteSavedAt", { time: formatPosition(note.position_ms) }));
    } catch (err) {
      const message = String((err as Error).message || err);
      setError(message.startsWith("videoRemote.") ? t(message) : message);
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEditedNote() {
    if (!editingNote || !editingNote.body.trim()) return;
    setBusy(true);
    setError("");
    try {
      const updated = await updateVideoNote(editingNote.id, editingNote.body.trim());
      setNotes((rows) => rows.map((note) => (note.note_id === updated.note_id ? updated : note)));
      setEditingNote(null);
      setStatus(t("videoRemote.noteUpdated"));
    } catch (err) {
      const message = String((err as Error).message || err);
      setError(message.startsWith("videoRemote.") ? t(message) : message);
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteNote(noteId: string) {
    setBusy(true);
    setError("");
    try {
      await deleteVideoNote(noteId);
      setNotes((rows) => rows.filter((note) => note.note_id !== noteId));
      setStatus(t("videoRemote.noteDeleted"));
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  const commitSeek = () => {
    setSeekDragging(false);
    if (selected && seekMs !== selected.position_ms) {
      void runCommand({ type: "seek", position_ms: seekMs }, t("videoRemote.positionUpdated"));
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-4 px-4 pb-28 pt-4">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("videoRemote.title")}</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {lockedSessionId
            ? t("videoRemote.lockedDescription")
            : t("videoRemote.selectDescription")}
        </p>
      </header>

      <section className="rounded-xl border border-[var(--border)] p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">
              {selected?.title || selected?.video_id || t("videoRemote.noSession")}
            </h2>
            {selected && (
              <p className="text-xs text-[var(--muted-foreground)]">
                {formatPosition(selected.position_ms)} / {formatPosition(selected.duration_ms)} · {selected.playback_state} · {selected.playback_rate}x
              </p>
            )}
          </div>
          <span className={`rounded-full px-2 py-1 text-xs ${selected?.online ? "bg-green-500/10 text-green-600" : "bg-red-500/10 text-red-500"}`}>
            {selected?.online ? t("videoRemote.online") : t("videoRemote.offline")}
          </span>
        </div>

        {!lockedSessionId && sessions.length > 1 && (
          <select
            className="mb-3 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
            value={selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            {sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {session.title || session.video_id}
              </option>
            ))}
          </select>
        )}

        {selected ? (
          <div className="space-y-4">
            <input
              type="range"
              min={0}
              max={Math.max(1, selected.duration_ms)}
              step={1000}
              value={Math.min(seekMs, selected.duration_ms)}
              disabled={busy || !selected.online}
              onChange={(event) => setSeekMs(Number(event.target.value))}
              onPointerUp={commitSeek}
              onTouchEnd={commitSeek}
              onKeyUp={commitSeek}
              className="w-full"
              aria-label={t("videoRemote.playbackPosition")}
              onPointerDown={() => setSeekDragging(true)}
            />
            <div className="grid grid-cols-4 gap-2">
              <button className="rounded-lg border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "seek", delta_ms: -10000 })}>
                {t("videoRemote.backTenSeconds")}
              </button>
              <button className="rounded-lg border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "pause" })}>
                {t("videoRemote.pause")}
              </button>
              <button className="rounded-lg border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "play" })}>
                {t("videoRemote.play")}
              </button>
              <button className="rounded-lg border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "seek", delta_ms: 10000 })}>
                {t("videoRemote.forwardTenSeconds")}
              </button>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-[var(--muted-foreground)]">
                <label htmlFor="volume">{t("videoRemote.volume")}</label>
                <span>{volume}%</span>
              </div>
              <input
                id="volume"
                type="range"
                min={0}
                max={100}
                value={volume}
                disabled={busy || !selected.online}
                onChange={(event) => setVolume(Number(event.target.value))}
                onPointerUp={() => void runCommand({ type: "volume", volume }, t("videoRemote.volumeUpdated"))}
                onTouchEnd={() => void runCommand({ type: "volume", volume }, t("videoRemote.volumeUpdated"))}
                onKeyUp={() => void runCommand({ type: "volume", volume }, t("videoRemote.volumeUpdated"))}
                className="w-full"
              />
              <div className="grid grid-cols-2 gap-2">
                <button className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "mute", muted: true })}>
                  {t("videoRemote.mute")}
                </button>
                <button className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "mute", muted: false })}>
                  {t("videoRemote.unmute")}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs text-[var(--muted-foreground)]">{t("videoRemote.speed")}</div>
              <div className="grid grid-cols-6 gap-1">
                {[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => (
                  <button
                    key={rate}
                    className={`rounded-md border border-[var(--border)] px-1 py-2 text-xs disabled:opacity-50 ${selected.playback_rate === rate ? "bg-[var(--muted)] font-semibold" : ""}`}
                    disabled={busy || !selected.online}
                    onClick={() => void runCommand(
                      { type: "playback_rate", playback_rate: rate },
                      t("videoRemote.speedUpdated", { rate }),
                    )}
                  >
                    {rate}x
                  </button>
                ))}
              </div>
              <button className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50" disabled={busy || !selected.online} onClick={() => void runCommand({ type: "fullscreen" }, t("videoRemote.fullscreenRequested"))}>
                {t("videoRemote.fullscreen")}
              </button>
              <p className="text-xs text-[var(--muted-foreground)]">
                {t("videoRemote.platformControlNote")}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted-foreground)]">
            {lockedSessionId
              ? t("videoRemote.qrNoLongerBound")
              : t("videoRemote.openInvidiousFirst")}
          </p>
        )}
      </section>

      <section className="rounded-xl border border-[var(--border)] p-4">
        <h2 className="mb-3 text-sm font-semibold">{t("videoRemote.notesTitle")}</h2>
        <textarea
          className="min-h-20 w-full rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-base"
          placeholder={selected
            ? t("videoRemote.noteAt", { time: formatPosition(selected.position_ms) })
            : t("videoRemote.waitingForSession")}
          value={noteBody}
          disabled={!selected || busy}
          onChange={(event) => setNoteBody(event.target.value)}
        />
        <button
          className="mt-2 w-full rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm font-medium text-[var(--background)] disabled:opacity-50"
          disabled={!selected || busy || !noteBody.trim()}
          onClick={() => void onCreateNote()}
        >
          {t("videoRemote.saveNoteAtCurrentTime")}
        </button>

        <ul className="mt-4 space-y-2">
          {notes.map((note) => (
            <li key={note.note_id} className="rounded-lg border border-[var(--border)] p-3">
              {editingNote?.id === note.note_id ? (
                <div className="space-y-2">
                  <textarea
                    className="min-h-20 w-full rounded-md border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
                    value={editingNote.body}
                    onChange={(event) => setEditingNote({ ...editingNote, body: event.target.value })}
                  />
                  <div className="flex gap-2">
                    <button className="rounded-md bg-[var(--foreground)] px-2 py-1 text-xs text-[var(--background)] disabled:opacity-50" disabled={busy || !editingNote.body.trim()} onClick={() => void onSaveEditedNote()}>
                      {t("videoRemote.save")}
                    </button>
                    <button className="rounded-md border border-[var(--border)] px-2 py-1 text-xs" onClick={() => setEditingNote(null)}>
                      {t("videoRemote.cancel")}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    className="w-full text-left disabled:opacity-50"
                    disabled={busy || !selected?.online}
                    onClick={() => void runCommand(
                      { type: "seek", position_ms: note.position_ms },
                      t("videoRemote.jumpedToNote"),
                    )}
                  >
                    <div className="text-xs font-medium text-[var(--primary)]">{formatPosition(note.position_ms)}</div>
                    <div className="whitespace-pre-wrap text-sm">{note.body}</div>
                  </button>
                  <div className="mt-2 flex gap-3 text-xs text-[var(--muted-foreground)]">
                    <button onClick={() => setEditingNote({ id: note.note_id, body: note.body })}>
                      {t("videoRemote.edit")}
                    </button>
                    <button disabled={busy} onClick={() => void onDeleteNote(note.note_id)}>
                      {t("videoRemote.delete")}
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
          {notes.length === 0 && (
            <li className="text-sm text-[var(--muted-foreground)]">
              {t("videoRemote.noNotes")}
            </li>
          )}
        </ul>
      </section>

      <section className="rounded-xl border border-[var(--border)] p-4">
        <h2 className="mb-2 text-sm font-semibold">{t("videoRemote.viewingDevices")}</h2>
        <ul className="space-y-2">
          {devices.map((device) => (
            <li key={device.device_id} className="flex items-center justify-between gap-2 text-sm">
              <span>
                {device.device_name || device.device_id}
                {device.active ? "" : t("videoRemote.revokedSuffix")}
              </span>
              {device.active && (
                <button
                  className="text-xs text-red-500 underline disabled:opacity-50"
                  disabled={busy}
                  onClick={() => void revokeDevice(device.device_id)
                    .then(refreshDevices)
                    .catch((err) => {
                      const message = String(err.message || err);
                      setError(message.startsWith("videoRemote.") ? t(message) : message);
                    })}
                >
                  {t("videoRemote.revoke")}
                </button>
              )}
            </li>
          ))}
          {devices.length === 0 && (
            <li className="text-sm text-[var(--muted-foreground)]">
              {t("videoRemote.noViewingDevices")}
            </li>
          )}
        </ul>
      </section>

      {(status || error) && (
        <div className="fixed inset-x-0 bottom-0 border-t border-[var(--border)] bg-[var(--background)] px-4 py-3 text-sm">
          {status && <p className="text-[var(--muted-foreground)]">{status}</p>}
          {error && <p className="text-red-500">{error}</p>}
        </div>
      )}
    </main>
  );
}

export default function VideoLearningRemotePage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--muted-foreground)]" aria-live="polite" />}>
      <VideoLearningRemoteContent />
    </Suspense>
  );
}
