//! One error type for the whole HTTP surface.
//!
//! Handlers used to return `Result<Json<T>, (StatusCode, Json<ApiError>)>` and
//! map every failure by hand — 38 `err(StatusCode::…, e)` call sites and a
//! `map_tree_err` sprinkled over a dozen more. Mapping a domain error to a
//! status code is a property of the error, not of the handler, so it lives here
//! once and `?` does the rest.
//!
//! The wire format is unchanged: `{"error": "<message>"}` with the same status
//! codes as before.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use nbm_core::backup::BackupError;
use nbm_core::db::DbError;
use nbm_core::organize::OrganizeError;
use nbm_core::tree::TreeError;
use serde::Serialize;

/// What every fallible handler returns.
pub type ApiResult<T> = Result<Json<T>, ApiError>;

#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("{0}")]
    NotFound(String),
    #[error("{0}")]
    BadRequest(String),
    #[error("{0}")]
    Conflict(String),
    /// A capability the server was not configured with (no DB, no backup
    /// manager). Distinct from an internal failure: nothing went wrong, the
    /// feature simply is not wired up in this install.
    #[error("{0}")]
    Unavailable(String),
    #[error("{0}")]
    Internal(String),
}

impl ApiError {
    pub fn not_found(msg: impl ToString) -> Self {
        Self::NotFound(msg.to_string())
    }
    pub fn bad_request(msg: impl ToString) -> Self {
        Self::BadRequest(msg.to_string())
    }
    pub fn conflict(msg: impl ToString) -> Self {
        Self::Conflict(msg.to_string())
    }
    pub fn unavailable(msg: impl ToString) -> Self {
        Self::Unavailable(msg.to_string())
    }
    pub fn internal(msg: impl ToString) -> Self {
        Self::Internal(msg.to_string())
    }

    fn status(&self) -> StatusCode {
        match self {
            Self::NotFound(_) => StatusCode::NOT_FOUND,
            Self::BadRequest(_) => StatusCode::BAD_REQUEST,
            Self::Conflict(_) => StatusCode::CONFLICT,
            Self::Unavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

#[derive(Serialize)]
struct ErrorBody {
    error: String,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = ErrorBody { error: self.to_string() };
        (self.status(), Json(body)).into_response()
    }
}

impl From<TreeError> for ApiError {
    fn from(e: TreeError) -> Self {
        match e {
            TreeError::FolderNotFound(_) | TreeError::BookmarkNotFound(_) => {
                Self::NotFound(e.to_string())
            }
            TreeError::NotFolder(_) | TreeError::Invalid(_) => Self::BadRequest(e.to_string()),
        }
    }
}

impl From<OrganizeError> for ApiError {
    /// All organize failures answer 400, as they did before this type existed.
    /// `OrganizeError::FolderNotFound` arguably deserves 404, but that is a
    /// visible API change rather than a refactor, so it is left alone.
    fn from(e: OrganizeError) -> Self {
        Self::BadRequest(e.to_string())
    }
}

impl From<DbError> for ApiError {
    fn from(e: DbError) -> Self {
        Self::Internal(e.to_string())
    }
}

impl From<BackupError> for ApiError {
    fn from(e: BackupError) -> Self {
        Self::Internal(e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tree_errors_map_to_the_status_the_frontend_expects() {
        assert_eq!(
            ApiError::from(TreeError::BookmarkNotFound("x".into())).status(),
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            ApiError::from(TreeError::FolderNotFound("x".into())).status(),
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            ApiError::from(TreeError::Invalid("x".into())).status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            ApiError::from(TreeError::NotFolder("x".into())).status(),
            StatusCode::BAD_REQUEST
        );
    }

    #[test]
    fn the_message_survives_into_the_body() {
        let e = ApiError::from(TreeError::BookmarkNotFound("abc".into()));
        assert_eq!(e.to_string(), "bookmark not found: abc");
    }
}
