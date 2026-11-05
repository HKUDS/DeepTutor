# DeepTutor Apps

Clients that host DeepTutor outside a browser tab. Each folder is
self-contained (its own README, dependencies and build scripts) and never
copies core code: apps start or connect to the DeepTutor core and display the
same `web/` interface.

| Folder     | Client                  | Platforms          | Status                     |
| ---------- | ----------------------- | ------------------ | -------------------------- |
| `desktop/` | Open DeepTutor (Electron) | MacOS (Apple Silicon, Intel), Windows (x64) | Preview, built on every release |

Desktop platforms share `desktop/`; each build target has its own folder in
`desktop/platforms/`, so a Linux build belongs there rather than in a new app. Mobile clients cannot run the Python core locally,
so they will live in their own folders as remote clients.

Every app is versioned with the core it ships and names itself in full, e.g.
`Open DeepTutor for MacOS with Apple Silicon v<version>` or
`Open DeepTutor for Windows v<version>`, next to the web UI's
`Open DeepTutor Web v<version>`.
