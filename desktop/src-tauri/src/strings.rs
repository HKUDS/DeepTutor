//! The language the shell itself speaks.
//!
//! The web UI is translated by the Next app, but the shell's own surfaces are
//! not part of that bundle: the splash, the first-run wizard, native dialogs,
//! the menu bar and the `detail` lines the settings page prints verbatim. Those
//! are written here, in the language the shell is configured for — the wizard's
//! answer, which the web app keeps in step once it knows its own locale.
//!
//! Every string exists twice. Keeping them next to each other at the call site
//! (`tr(locale, "中文", "English")`) is deliberate: a missing translation then
//! looks like a formatting mistake, not a silent fallback.

/// The two languages the product ships.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Locale {
    Zh,
    En,
}

impl Locale {
    /// The configured language, falling back to the OS locale.
    ///
    /// Anything that is not English is treated as Chinese: that is the product's
    /// original language, so an unrecognised code (a regional variant, a typo)
    /// degrades to something a user can act on.
    pub fn resolve(setting: &str, os_default: &str) -> Self {
        let value = if setting.trim().is_empty() {
            os_default
        } else {
            setting
        };
        if value.trim().to_ascii_lowercase().starts_with("en") {
            Self::En
        } else {
            Self::Zh
        }
    }

    /// The code stored in `shell.json` and sent over IPC.
    pub fn code(self) -> &'static str {
        match self {
            Self::Zh => "zh-CN",
            Self::En => "en",
        }
    }
}

/// `tr(locale, "中文", "English")` — the shell's translation function.
pub fn tr(locale: Locale, zh: impl Into<String>, en: impl Into<String>) -> String {
    match locale {
        Locale::Zh => zh.into(),
        Locale::En => en.into(),
    }
}

/// The same, for a language code that may come from anywhere (a plugin command,
/// a stored value that has not been parsed yet).
pub fn tr_code(code: &str, zh: impl Into<String>, en: impl Into<String>) -> String {
    tr(Locale::resolve(code, ""), zh, en)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_setting_wins_over_the_os_locale() {
        assert_eq!(Locale::resolve("en", "zh-CN"), Locale::En);
        assert_eq!(Locale::resolve("zh-CN", "en_US"), Locale::Zh);
        // An empty setting means "whatever the system says".
        assert_eq!(Locale::resolve("", "en_US"), Locale::En);
        assert_eq!(Locale::resolve("  ", "zh_CN"), Locale::Zh);
        // Regional variants and odd values land on the product's default.
        assert_eq!(Locale::resolve("en-GB", ""), Locale::En);
        assert_eq!(Locale::resolve("fr", ""), Locale::Zh);
    }

    #[test]
    fn every_string_has_both_languages() {
        assert_eq!(tr(Locale::Zh, "本地服务", "local service"), "本地服务");
        assert_eq!(tr(Locale::En, "本地服务", "local service"), "local service");
        assert_eq!(
            tr_code("en-US", "中文", "English"),
            "English",
            "a plugin command only has the stored code"
        );
        assert_eq!(Locale::Zh.code(), "zh-CN");
        assert_eq!(Locale::En.code(), "en");
    }
}
