//! Mirror of `OriginalPythonCodes/core/ServiceStorage.py::ConfigManager`.
//!
//! Responsibilities:
//! - Load / write `config.ini`.
//! - Resolve API key with env-var precedence (GENAI_API_KEY → GOOGLE_API_KEY → config).
//! - Surface proxy settings as a normalized struct.

use std::path::{Path, PathBuf};

use camino::Utf8PathBuf;
use configparser::ini::Ini;

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("ini parse error: {0}")]
    Ini(String),
}

#[derive(Debug, Clone)]
pub struct ProxySettings {
    pub url: String,
    pub user: Option<String>,
    pub password: Option<String>,
}

pub struct ConfigManager {
    pub path: Utf8PathBuf,
    ini: Ini,
}

impl ConfigManager {
    pub fn load(path: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let path: Utf8PathBuf = Utf8PathBuf::from_path_buf(PathBuf::from(path.as_ref()))
            .map_err(|p| ConfigError::Ini(format!("non-utf8 path: {p:?}")))?;
        let mut ini = Ini::new();
        if path.exists() {
            ini.load(path.as_std_path()).map_err(ConfigError::Ini)?;
        }
        Ok(Self { path, ini })
    }

    pub fn get(&self, section: &str, option: &str) -> Option<String> {
        self.ini.get(section, option)
    }

    pub fn set(&mut self, section: &str, option: &str, value: &str) -> Result<(), ConfigError> {
        self.ini.set(section, option, Some(value.to_string()));
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        self.ini.write(self.path.as_std_path()).map_err(ConfigError::Io)
    }

    /// Env vars take precedence over `config.ini [API].api_key`.
    pub fn get_api_key(&self) -> Option<String> {
        std::env::var("GENAI_API_KEY")
            .ok()
            .or_else(|| std::env::var("GOOGLE_API_KEY").ok())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .or_else(|| self.get("API", "api_key"))
    }

    pub fn get_proxy(&self) -> Option<ProxySettings> {
        let url = self.get("Proxy", "url")?;
        if !is_valid_proxy_url(&url) {
            return None;
        }
        Some(ProxySettings {
            url,
            user: self.get("Proxy", "user").filter(|s| !s.is_empty()),
            password: self.get("Proxy", "password").filter(|s| !s.is_empty()),
        })
    }

    pub fn get_priority_terms(&self) -> Vec<String> {
        self.get("Classifier", "priority_terms")
            .map(|s| {
                s.split(',')
                    .map(|t| t.trim().to_string())
                    .filter(|t| !t.is_empty())
                    .collect()
            })
            .unwrap_or_default()
    }
}

fn is_valid_proxy_url(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }
    let lower = s.to_ascii_lowercase();
    (lower.starts_with("http://") || lower.starts_with("https://"))
        && s.split_once("://").map_or(false, |(_, rest)| !rest.is_empty())
}
