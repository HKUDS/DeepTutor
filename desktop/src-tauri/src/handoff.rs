//! Queue of things the OS asked us to open, waiting for the UI to be ready.
//!
//! A hand-off can arrive before the loopback UI exists (cold start from a
//! `deeptutor://` link, or the OS launching the app *because* a PDF was
//! double-clicked), so requests are parked here rather than pushed straight into
//! a webview that may still be showing the splash.

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

use tauri::Url;
use tauri_plugin_deeptutor::OpenRequestPayload;

use crate::deeplink::{classify_args, classify_url, OpenRequest};

/// A double-clicked selection of files can be long; past this, the queue keeps
/// the most recent hand-offs and drops the rest rather than growing forever.
const MAX_QUEUED: usize = 8;
/// Same reasoning for the read allowances: enough for a hand-off or a
/// multi-select, small enough that it cannot grow without bound.
const MAX_READABLE: usize = 32;

struct Queued {
    request: OpenRequest,
    source: &'static str,
    raw: String,
    at: Instant,
}

/// FIFO of pending hand-offs. The UI drains it with `take_open_request`.
#[derive(Default)]
pub struct OpenQueue {
    pending: Mutex<VecDeque<Queued>>,
    /// Paths the shell itself handed over, i.e. the only ones the webview is
    /// allowed to read back.
    ///
    /// `plugin:deeptutor|read_local_file` used to accept any absolute path,
    /// which made one script inside the loopback-served UI enough to exfiltrate
    /// any readable file on the machine. An allowance is granted when the shell
    /// queues a file hand-off (Dock drop, file association, "Open with") or when
    /// the user picks a file in the native panel, and the read consumes it.
    readable: Mutex<VecDeque<PathBuf>>,
}

impl OpenQueue {
    pub fn new() -> Self {
        Self::default()
    }

    /// Classify and queue each URL the OS handed over (macOS `RunEvent::Opened`,
    /// or the deep-link plugin's event). Returns how many were accepted.
    pub fn push_urls<'a, I: IntoIterator<Item = &'a Url>>(
        &self,
        urls: I,
        source: &'static str,
    ) -> usize {
        let mut accepted = 0;
        for url in urls {
            if let Some(request) = classify_url(url) {
                self.push(request, source, url.as_str());
                accepted += 1;
            }
        }
        accepted
    }

    /// Classify and queue command-line arguments (Windows/Linux second launch).
    ///
    /// `args` is a whole command line, including `argv[0]`, because that is
    /// what both callers have in hand.
    pub fn push_args<I: IntoIterator<Item = String>>(
        &self,
        args: I,
        source: &'static str,
    ) -> usize {
        let args: Vec<String> = args.into_iter().collect();
        let mut accepted = 0;
        for (request, argument) in classify_args(&args) {
            self.push(request, source, &argument);
            accepted += 1;
        }
        accepted
    }

    pub fn push(&self, request: OpenRequest, source: &'static str, raw: &str) {
        // A file hand-off is also the permission to read that one file back:
        // the webview cannot see real paths, so this queue is where the path
        // and the trust to open it come from together.
        if let OpenRequest::File { path } = &request {
            self.grant_read(path);
        }
        let mut pending = self.pending.lock().expect("handoff lock poisoned");
        if pending.len() >= MAX_QUEUED {
            pending.pop_front();
        }
        pending.push_back(Queued {
            request,
            source,
            raw: raw.to_string(),
            at: Instant::now(),
        });
    }

    /// Allow one read of `path` through the shell's IPC bridge.
    ///
    /// Grants stack (up to [`MAX_READABLE`]): handing the same file over twice
    /// has to allow two reads, because the UI claims and reads them one by one.
    pub fn grant_read(&self, path: &Path) {
        let mut readable = self.readable.lock().expect("handoff lock poisoned");
        if readable.len() >= MAX_READABLE {
            readable.pop_front();
        }
        readable.push_back(path.to_path_buf());
    }

    /// Consume the allowance for `path`; false when it was never granted.
    pub fn take_read_grant(&self, path: &Path) -> bool {
        let mut readable = self.readable.lock().expect("handoff lock poisoned");
        match readable.iter().position(|granted| granted == path) {
            Some(index) => {
                readable.remove(index);
                true
            }
            None => false,
        }
    }

    pub fn take(&self) -> Option<OpenRequestPayload> {
        let mut pending = self.pending.lock().expect("handoff lock poisoned");
        let taken = pending.pop_front()?;
        let kind = taken.request.kind().to_string();
        let (route, path) = match taken.request {
            OpenRequest::Route { route } => (Some(route), None),
            OpenRequest::File { path } => (None, Some(path.to_string_lossy().into_owned())),
        };
        Some(OpenRequestPayload {
            kind,
            route,
            path,
            source: taken.source.to_string(),
            raw: taken.raw,
            age_ms: taken.at.elapsed().as_millis() as u64,
        })
    }

    pub fn len(&self) -> usize {
        self.pending.lock().map(|queue| queue.len()).unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(raw: &str) -> Url {
        Url::parse(raw).expect("test url")
    }

    #[test]
    fn urls_are_classified_and_drained_in_order() {
        let queue = OpenQueue::new();
        let urls = [
            url("deeptutor://chat/1f0c"),
            url("https://example.com/ignored"),
            url("file:///tmp/paper.pdf"),
        ];
        assert_eq!(queue.push_urls(&urls, "deep-link"), 2);

        let first = queue.take().expect("first");
        assert_eq!(first.kind, "route");
        assert_eq!(first.route.as_deref(), Some("/chat/1f0c"));
        assert!(first.path.is_none());
        assert_eq!(first.source, "deep-link");
        assert_eq!(first.raw, "deeptutor://chat/1f0c");

        let second = queue.take().expect("second");
        assert_eq!(second.kind, "file");
        assert_eq!(second.path.as_deref(), Some("/tmp/paper.pdf"));
        assert!(queue.take().is_none());
        assert!(queue.is_empty());
    }

    #[test]
    fn the_queue_keeps_the_newest_hand_offs() {
        let queue = OpenQueue::new();
        for index in 0..MAX_QUEUED + 3 {
            queue.push(
                OpenRequest::Route {
                    route: format!("/chat/{index}"),
                },
                "deep-link",
                &format!("deeptutor://chat/{index}"),
            );
        }
        assert_eq!(queue.len(), MAX_QUEUED);
        // The oldest three were dropped, so the first one back is #3.
        assert_eq!(
            queue.take().expect("head").route.as_deref(),
            Some("/chat/3")
        );
    }

    #[test]
    fn arguments_only_contribute_links_and_paths() {
        let queue = OpenQueue::new();
        let accepted = queue.push_args(
            vec![
                "--flag".to_string(),
                "deeptutor://settings".to_string(),
                "/tmp/notes.md".to_string(),
            ],
            "argv",
        );
        assert_eq!(accepted, 2);
        assert_eq!(queue.take().expect("route").kind, "route");
        let file = queue.take().expect("file");
        assert_eq!(file.path.as_deref(), Some("/tmp/notes.md"));
        assert_eq!(file.source, "argv");
    }

    /// The webview may only read files the shell handed it (or the user picked),
    /// and each allowance is good for exactly one read.
    #[test]
    fn only_handed_over_paths_may_be_read_back() {
        let queue = OpenQueue::new();
        assert!(!queue.take_read_grant(Path::new("/etc/passwd")));

        queue.push_args(
            vec!["argv0".to_string(), "/tmp/paper.pdf".to_string()],
            "argv",
        );
        // The path is readable even after `take` drained the queue: the read
        // happens after the UI has claimed the hand-off.
        let request = queue.take().expect("file request");
        assert_eq!(request.path.as_deref(), Some("/tmp/paper.pdf"));
        assert!(queue.take_read_grant(Path::new("/tmp/paper.pdf")));
        assert!(!queue.take_read_grant(Path::new("/tmp/paper.pdf")));
        assert!(!queue.take_read_grant(Path::new("/tmp/other.pdf")));

        // Picker results are granted explicitly, one read per grant.
        queue.grant_read(Path::new("/tmp/picked.pdf"));
        queue.grant_read(Path::new("/tmp/picked.pdf"));
        assert!(queue.take_read_grant(Path::new("/tmp/picked.pdf")));
        assert!(queue.take_read_grant(Path::new("/tmp/picked.pdf")));
        assert!(!queue.take_read_grant(Path::new("/tmp/picked.pdf")));
    }

    #[test]
    fn the_read_allowance_stays_bounded() {
        let queue = OpenQueue::new();
        for index in 0..MAX_READABLE + 5 {
            queue.grant_read(Path::new(&format!("/tmp/file-{index}")));
        }
        assert!(!queue.take_read_grant(Path::new("/tmp/file-0")));
        assert!(queue.take_read_grant(Path::new(&format!("/tmp/file-{}", MAX_READABLE + 4))));
    }
}
