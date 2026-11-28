# Local Data Persistence

[Handbook](README.md) · [Workspaces](workspaces.md) · [Containers](CONTAINERIZATION.md)

DeepTutor's default installation does not require PostgreSQL, MySQL, or another
database server. Durable state is written below one runtime-home directory, so
a deployment has one tree to mount, inspect, and back up. Some state is stored
in SQLite, while settings, generated artifacts, knowledge-base indexes, caches,
and imported source files remain ordinary files.

## Where Data Lives

The runtime home is the directory from which you start DeepTutor. Set
`DEEPTUTOR_HOME` or pass `deeptutor start --home` / `deeptutor init --home` to
choose another directory. In the published container, the same tree is mounted
at `/app/data`.

The default admin scope uses this layout:

| Path | Contents |
| --- | --- |
| `data/user/settings/` | JSON/YAML settings and provider credentials |
| `data/user/chat_history.db` | SQLite sessions, messages, turns, question-bank entries, and practice data |
| `data/user/.runtime/` | Private runtime state such as `workspaces.sqlite3` |
| `data/user/workspace/` | Default Content Workspace and generated artifacts |
| `data/user/workspace/notebook/` | Favorite collections and their index as JSON files (legacy directory name) |
| `data/user/workspace/co-writer/documents/doc_<id>/manifest.json` | Authored note pages, blocks, revisions, and page metadata |
| `data/user/logs/` | Application logs |
| `data/knowledge_bases/` | Knowledge-base indexes and versioned source data |
| `data/parse_cache/` | Shared document-parse cache |
| `data/users/<user-id>/` | Per-user workspace roots when local multi-user auth is enabled |
| `data/partners/<partner-id>/` | Synthetic Partner workspaces |
| `data/system/` | Accounts, grants, audit records, indexes, and owner credentials |

A selected Content Workspace can be outside `data/user`. In that case its
private learning state is under `<workspace>/.deeptutor/data/`, while account
settings, credentials, Memory, and workspace registrations remain in the
runtime home. Run `deeptutor workspace show` to print the selected workspace
path.

Favorites and authored notes are separate stores. The legacy `notebook_entries`
SQLite table holds question-bank entries; it is not the storage for authored
note blocks or favorite collections. In a selected external workspace, those
file-based stores live under its private `.deeptutor/data/workspace/` tree,
using the same `notebook/` and `co-writer/documents/` subdirectories. Back up
the full workspace, including hidden `.deeptutor` files, to preserve both the
learning records and the note/favorite content.

## Database Support

SQLite is the supported local backend. There is no supported PostgreSQL or
MySQL connection setting; setting `DATABASE_URL` or a similar environment
variable does not redirect DeepTutor storage.

PocketBase is an optional integration configured through
`data/user/settings/integrations.json`. It stores supported session collections
in PocketBase, but it is not a PostgreSQL adapter and does not move all runtime
state into PocketBase. Settings, credentials, knowledge-base indexes, parse
caches, logs, and workspace artifacts remain in the runtime tree. Current
PocketBase mode is single-user; leave `integrations.pocketbase_url` blank for
the supported local multi-user JSON/SQLite layout.

## Inspecting and Backing Up State

From your runtime home, after DeepTutor has created data, list the SQLite
databases in the private runtime tree:

```bash
find data -type f \( -name '*.db' -o -name '*.sqlite3' \) -print
```

For a selected external Content Workspace, inspect its private database files:

```bash
workspace="$(deeptutor workspace show | sed -n 's/^Path: //p')"
if [ -d "$workspace/.deeptutor/data" ]; then
  find "$workspace/.deeptutor/data" -type f \
    \( -name '*.db' -o -name '*.sqlite3' \) -print
fi
```

Stop DeepTutor and any Partner processes before copying `data` or a workspace.
SQLite may have live write-ahead log files, so copying only `.db` files while
the app runs can lose recent transactions. Back up the complete runtime-home
`data` directory plus each separately configured Content Workspace. Treat every
copy as sensitive because it can contain credentials, private conversation
text, and uploaded learning material.

## Moving Data Between Deployments

The runtime-home tree is self-contained, so moving between deployment shapes
(for example from the published container to the desktop app, or between
machines) is a copy of `data/` into the target's runtime home. Upgrading
between releases needs no migration; this section covers moving the same tree
to a different deployment.

Default runtime home of the desktop app on macOS:
`~/Library/Application Support/Open DeepTutor/workspace/data`.

1. **Stop the source and the target.** SQLite write-ahead log files make a copy
   of a running instance unreliable (see the previous section).

2. **Copy the whole `data/` tree**, including hidden directories such as
   `data/user/.runtime/`, and every top-level directory (`knowledge_bases/`,
   `memory/`, `partners/`, `system/`, and so on), not only `user/`. From a Docker
   named volume:

   ```bash
   mkdir export
   docker run --rm -v <volume>:/data -v "$PWD/export":/out alpine \
     sh -c "cp -a /data/. /out/"
   ```

   A container can mount a different volume than the one you expect (for
   example one created by Compose). Check `docker ps -a` and compare the volume
   sizes before exporting.

3. **Back up the target's existing `data/`**, and set aside the target's own
   copies of the environment-specific files listed in step 4. Remove stale
   `chat_history.db-wal`, `chat_history.db-shm`, `usage.sqlite3-wal` and
   `usage.sqlite3-shm` files from the target, then copy the exported tree over
   it, preserving hidden files (for example `rsync -a export/ "<target>/data/"`).

4. **Keep the target's environment-specific files.** Put the target's own
   copies back after the copy (or exclude them from it):
   - `data/user/settings/system.json` holds ports, CORS and SSL options that
     may not suit the new environment.
   - `data/user/.runtime/workspaces.sqlite3` registers each workspace with an
     absolute `path`. A registry copied from a container lists `/app/data/...`
     paths, which do not exist on the host; the desktop app then fails to start
     new conversations with "The selected workspace folder does not exist."
     Workspace IDs for the default workspaces are the same in both
     deployments, so the target's registry keeps pointing at the copied
     `data/user/workspaces/ws_*` directories.

5. **Start the target** and confirm that sessions, knowledge bases and a model
   response work, and that you can start a new conversation.

Treat every copy as sensitive: it contains provider credentials and private
conversation text, so delete exports once the migration is confirmed.

Verified: published container (named volume, image 1.7.4) → Open DeepTutor
1.7.4 desktop app on macOS (Apple Silicon), with the two default workspaces.
Not verified: other platforms, migrating between releases, or workspaces
registered beyond the defaults (their registry entries are not carried over
when the target's registry is kept).

## Implementation and verification

- [deeptutor/runtime/home.py](../deeptutor/runtime/home.py)
- [deeptutor/services/path_service.py](../deeptutor/services/path_service.py)
- [deeptutor/services/workspace/context.py](../deeptutor/services/workspace/context.py)
