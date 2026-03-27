/**
 * Queue session telemetry — logs events to the backend events table.
 * Uses the same auth and base URL as the main API client.
 * Fire-and-forget: telemetry should never block the UI or crash the app.
 */
import { BASE, authHeaders } from "../api/request";

type QueueEvent =
  | { type: "queue.session_start" }
  | { type: "queue.batch_approve"; count: number }
  | { type: "queue.review_gate_open"; count: number }
  | { type: "queue.review_gate_confirm"; count: number }
  | { type: "queue.batch_send_result"; sent: number; failed: number }
  | { type: "queue.undo_triggered" }
  | { type: "queue.shortcut_used"; key: string }
  | { type: "queue.cache_hit"; age_minutes: number }
  | { type: "queue.selection_change"; count: number };

export function logQueueEvent(event: QueueEvent) {
  // Fire and forget — telemetry should never block the UI
  try {
    const headers = authHeaders();
    if (!headers.Authorization) return;

    fetch(`${BASE}/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...headers,
      },
      body: JSON.stringify({
        event_type: event.type,
        metadata: event,
      }),
    }).catch(() => {}); // swallow errors — telemetry is best-effort
  } catch {
    // Never let telemetry crash the app
  }
}
