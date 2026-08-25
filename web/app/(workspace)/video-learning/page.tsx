"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  claimPairingCode,
  createVideoNote,
  deleteVideoNote,
  formatPosition,
  getSessionCommand,
  listRemoteSessions,
  listVideoNotes,
  revokeDevice,
  listDevices,
  sendSessionCommand,
  type RemoteNote,
  type RemoteSession,
} from "@/lib/video-learning-remote-api";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForCommand(sessionId: string, commandId: string) {
  for (let i = 0; i < 20; i += 1) {
    const command = await getSessionCommand(sessionId, commandId);
    if (command.status === "acked" || command.status === "failed" || command.status === "expired") {
      return command;
    }
    await sleep(250);
  }
  throw new Error("Command timed out waiting for iPad acknowledgement");
}

export default function VideoLearningRemotePage() {
  const [code, setCode] = useState("");
  const [sessions, setSessions] = useState<RemoteSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");
  const [notes, setNotes] = useState<RemoteNote[]>([]);
  const [noteBody, setNoteBody] = useState("");
  const [devices, setDevices] = useState<Array<{ device_id: string; device_name: string; active: boolean }>>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = useMemo(
    () => sessions.find((session) => session.session_id === selectedSessionId) || sessions[0] || null,
    [sessions, selectedSessionId],
  );

  const refresh = useCallback(async () => {
    const [nextSessions, nextDevices] = await Promise.all([listRemoteSessions(), listDevices()]);
    setSessions(nextSessions);
    setDevices(nextDevices);
    const active = nextSessions.find((session) => session.session_id === selectedSessionId) || nextSessions[0];
    if (active) {
      setSelectedSessionId(active.session_id);
      setNotes(await listVideoNotes(active.video_id));
    } else {
      setNotes([]);
    }
  }, [selectedSessionId]);

  useEffect(() => {
    void refresh().catch((err) => setError(String(err.message || err)));
    const timer = setInterval(() => {
      void refresh().catch(() => undefined);
    }, 1000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function onClaim() {
    setBusy(true);
    setError("");
    try {
      await claimPairingCode(code.trim());
      setCode("");
      setStatus("iPad claimed");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function runCommand(payload: { type: string; position_ms?: number; delta_ms?: number }) {
    if (!selected) return;
    if (!selected.online) {
      setError("iPad session is offline");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const command = await sendSessionCommand(selected.session_id, payload);
      const result = await waitForCommand(selected.session_id, command.command_id);
      if (result.status !== "acked") {
        throw new Error(result.error || `Command ${result.status}`);
      }
      setStatus(`${payload.type} ok`);
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onCreateNote() {
    if (!selected || !noteBody.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createVideoNote(selected.video_id, {
        body: noteBody.trim(),
        session_id: selected.session_id,
      });
      setNoteBody("");
      setStatus("Note saved at iPad timestamp");
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function onJumpNote(note: RemoteNote) {
    if (!selected) return;
    await runCommand({ type: "seek", position_ms: note.position_ms });
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4 px-4 py-4 pb-24">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Video Remote</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Pair an Invidious iPad tab, control playback, and save timestamped notes.
        </p>
      </header>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Pair iPad</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-base"
            inputMode="numeric"
            placeholder="6-digit code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <button
            className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
            disabled={busy || code.trim().length < 4}
            onClick={() => void onClaim()}
          >
            Claim
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">Now playing</h2>
          <span className="text-xs text-[var(--muted-foreground)]">
            {selected?.online ? "online" : "offline"}
          </span>
        </div>
        {selected ? (
          <div className="space-y-2">
            <div className="text-base font-medium">{selected.title || selected.video_id}</div>
            <div className="text-sm text-[var(--muted-foreground)]">
              {formatPosition(selected.position_ms)} / {formatPosition(selected.duration_ms)} ·{" "}
              {selected.playback_state}
            </div>
            <div className="grid grid-cols-4 gap-2">
              <button
                className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
                disabled={busy || !selected.online}
                onClick={() => void runCommand({ type: "seek", delta_ms: -10000 })}
              >
                -10s
              </button>
              <button
                className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
                disabled={busy || !selected.online}
                onClick={() => void runCommand({ type: "pause" })}
              >
                Pause
              </button>
              <button
                className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
                disabled={busy || !selected.online}
                onClick={() => void runCommand({ type: "play" })}
              >
                Play
              </button>
              <button
                className="rounded-md border border-[var(--border)] px-2 py-3 text-sm disabled:opacity-50"
                disabled={busy || !selected.online}
                onClick={() => void runCommand({ type: "seek", delta_ms: 10000 })}
              >
                +10s
              </button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted-foreground)]">No live Invidious session yet.</p>
        )}
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Notes</h2>
        <div className="mb-3 flex gap-2">
          <input
            className="flex-1 rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-base"
            placeholder="Note at current iPad time"
            value={noteBody}
            onChange={(event) => setNoteBody(event.target.value)}
          />
          <button
            className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
            disabled={busy || !selected || !noteBody.trim()}
            onClick={() => void onCreateNote()}
          >
            Save
          </button>
        </div>
        <ul className="space-y-2">
          {notes.map((note) => (
            <li key={note.note_id} className="rounded-md border border-[var(--border)] p-2">
              <button
                className="w-full text-left"
                disabled={busy || !selected?.online}
                onClick={() => void onJumpNote(note)}
              >
                <div className="text-xs text-[var(--muted-foreground)]">{formatPosition(note.position_ms)}</div>
                <div className="text-sm">{note.body}</div>
              </button>
              <button
                className="mt-1 text-xs text-[var(--muted-foreground)] underline"
                onClick={() =>
                  void deleteVideoNote(note.note_id)
                    .then(refresh)
                    .catch((err) => setError(String(err.message || err)))
                }
              >
                Delete
              </button>
            </li>
          ))}
          {notes.length === 0 && (
            <li className="text-sm text-[var(--muted-foreground)]">No notes for this video yet.</li>
          )}
        </ul>
      </section>

      <section className="rounded-lg border border-[var(--border)] p-3">
        <h2 className="mb-2 text-sm font-medium">Devices</h2>
        <ul className="space-y-2">
          {devices.map((device) => (
            <li key={device.device_id} className="flex items-center justify-between gap-2 text-sm">
              <span>
                {device.device_name || device.device_id} {device.active ? "" : "(revoked)"}
              </span>
              {device.active && (
                <button
                  className="text-xs underline"
                  onClick={() =>
                    void revokeDevice(device.device_id)
                      .then(refresh)
                      .catch((err) => setError(String(err.message || err)))
                  }
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
          {devices.length === 0 && (
            <li className="text-sm text-[var(--muted-foreground)]">No paired devices.</li>
          )}
        </ul>
      </section>

      {(status || error) && (
        <div className="text-sm">
          {status && <p className="text-[var(--muted-foreground)]">{status}</p>}
          {error && <p className="text-red-500">{error}</p>}
        </div>
      )}
    </div>
  );
}
