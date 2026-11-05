# Choose a server folder as a workspace

In a new conversation, open the workspace menu next to the composer and choose
**Choose a server folder**. Open folders until the desired project is displayed,
then choose **Select this folder**. New registrations use the folder name;
existing registrations retain their names and settings. Selecting an archived
registration restores it. Conversations with messages keep their existing binding.

The same picker is available in **Settings → Workspaces → New workspace**,
where it fills the existing-folder path and a default workspace name.
Browsing folders is read-only. Registration continues to use the existing
workspace validation and output-directory initialization.

## Deployment

The picker browses the filesystem of the backend, rather than the computer
running the browser. In Docker, project folders must be bind-mounted first.
For example, mount `/srv/projects` at `/srv/projects` inside the container and
set `DEEPTUTOR_WORKSPACE_BROWSER_ROOTS=/srv/projects`.

Multiple roots are separated by the backend platform's path separator (`:` on
Linux/macOS, `;` on Windows). Without this setting, the picker uses the roots
already provided by the content-workspace policy. Configured roots are also
checked against that policy for the requesting user; this setting does not
grant a non-admin access to additional folders. Admins remain confined to the
picker's configured browsing roots as well.

The picker shows accessible non-hidden subdirectories and omits symlinks that
resolve outside the current root. Each directory scan is bounded to 10,000
entries and returns at most 500 folders. Filtering applies to the displayed
directory, not recursively to the whole project tree. The API is
`GET /api/settings/workspace/folders?path=...` and inherits settings authentication.
