//! Shared plumbing for the progress-streaming (SSE) commands.
//!
//! Fetching titles, fetching previews, link-checking, autotagging and AI
//! classification all follow the same shape: resolve a batch of bookmark ids,
//! do something per item, stream a progress event for each, finish with a
//! `done` event. Each one used to hand-roll the channel, the spawned task, the
//! shared `AtomicUsize`, the `buffer_unordered` and the `serde_json` mapping —
//! five near-identical copies that had already drifted apart (one of them ran
//! sequentially and ignored the configured concurrency).

use std::convert::Infallible;
use std::future::Future;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use axum::response::sse::{Event, KeepAlive, Sse};
use futures_util::stream::{Stream, StreamExt};
use serde::Serialize;
use tokio::sync::mpsc;

/// Channel depth for progress events. Deep enough that a slow client does not
/// stall the workers, small enough to apply backpressure.
const CHANNEL_DEPTH: usize = 64;

/// Create the channel a streaming handler reports through.
pub fn channel<T>() -> (mpsc::Sender<T>, mpsc::Receiver<T>) {
    mpsc::channel(CHANNEL_DEPTH)
}

/// Turn a receiver of progress events into the SSE response axum hands back.
pub fn progress_stream<T: Serialize + Send + 'static>(
    rx: mpsc::Receiver<T>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|event| {
        let data = serde_json::to_string(&event).unwrap_or_default();
        Ok(Event::default().data(data))
    });
    Sse::new(stream).keep_alive(KeepAlive::default())
}

/// Handed to each unit of work so it can emit its own event type without
/// having to own the shared counter.
pub struct Reporter<T> {
    tx: mpsc::Sender<T>,
    processed: Arc<AtomicUsize>,
    total: usize,
}

impl<T> Reporter<T> {
    /// How many items were queued. Note this is the number that actually
    /// resolved in the tree, not the number requested — the `done` event has
    /// to agree with it or the progress bar never reaches 100%.
    pub fn total(&self) -> usize {
        self.total
    }

    /// Count this item as processed and send the event built from the running
    /// `(processed, total)` counts. Completion order is not deterministic when
    /// work runs in parallel, hence the shared counter.
    pub async fn send(&self, build: impl FnOnce(usize, usize) -> T) {
        let processed = self.processed.fetch_add(1, Ordering::Relaxed) + 1;
        let _ = self.tx.send(build(processed, self.total)).await;
    }
}

impl<T> Clone for Reporter<T> {
    fn clone(&self) -> Self {
        Self {
            tx: self.tx.clone(),
            processed: Arc::clone(&self.processed),
            total: self.total,
        }
    }
}

/// Run `work` over `items` with at most `concurrency` futures in flight, then
/// send the terminal event that `done` builds from the total.
///
/// Returns immediately; the work happens in a spawned task so the SSE response
/// can start streaming.
pub fn spawn_workers<I, T, F, Fut>(
    items: Vec<I>,
    concurrency: usize,
    tx: mpsc::Sender<T>,
    work: F,
    done: impl FnOnce(usize) -> T + Send + 'static,
) where
    I: Send + 'static,
    T: Send + 'static,
    F: Fn(I, Reporter<T>) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = ()> + Send,
{
    let total = items.len();
    let reporter = Reporter {
        tx: tx.clone(),
        processed: Arc::new(AtomicUsize::new(0)),
        total,
    };
    tokio::spawn(async move {
        let work = Arc::new(work);
        futures_util::stream::iter(items)
            .map(|item| {
                let work = Arc::clone(&work);
                let reporter = reporter.clone();
                async move { work(item, reporter).await }
            })
            .buffer_unordered(concurrency.max(1))
            .collect::<()>()
            .await;
        let _ = tx.send(done(total)).await;
    });
}
