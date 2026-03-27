import { useCallback } from "react";
import type { QueueItem } from "../types";

/**
 * Caches queue item metadata to localStorage for offline fallback.
 * Stores only non-PII fields: contact_id, contact_name, company_name,
 * campaign_name, channel, step_order, has_research, message_draft (boolean only),
 * rendered_email (boolean only).
 *
 * NOT cached: email subjects, email bodies, AI draft text, LinkedIn URLs,
 * investor contact details.
 */

export interface CachedQueueItem {
  contact_id: number;
  contact_name: string;
  company_name: string;
  campaign_name: string | null;
  campaign_id: number | null;
  channel: string;
  step_order: number;
  has_research: boolean;
  has_message_draft: boolean;
  has_rendered_email: boolean;
}

export interface CachedQueue {
  items: CachedQueueItem[];
  timestamp: number;
  total: number;
}

const CACHE_KEY_PREFIX = "queue-cache-";
const CACHE_MAX_AGE_MS = 15 * 60 * 1000; // 15 minutes
const CACHE_MAX_SIZE = 500 * 1024; // 500KB

export function useQueueCache(userId: number | string) {
  const cacheKey = `${CACHE_KEY_PREFIX}${userId}`;

  /** Write cache on successful fetch */
  const writeCache = useCallback(
    (items: QueueItem[], total: number) => {
      if (!userId) return; // no cache for unauthenticated state
      try {
        const cached: CachedQueue = {
          items: items.map((item) => ({
            contact_id: item.contact_id,
            contact_name: item.contact_name,
            company_name: item.company_name,
            campaign_name: item.campaign_name ?? null,
            campaign_id: item.campaign_id ?? null,
            channel: item.channel,
            step_order: item.step_order,
            has_research: item.has_research ?? false,
            has_message_draft: item.message_draft != null,
            has_rendered_email: item.rendered_email != null,
          })),
          timestamp: Date.now(),
          total,
        };
        const json = JSON.stringify(cached);
        if (json.length > CACHE_MAX_SIZE) return; // size guard
        localStorage.setItem(cacheKey, json);
      } catch {
        // localStorage quota exceeded -- silently skip
      }
    },
    [cacheKey],
  );

  /** Read cache (returns null if expired or missing) */
  const readCache = useCallback((): CachedQueue | null => {
    if (!userId) return null;
    try {
      const raw = localStorage.getItem(cacheKey);
      if (!raw) return null;
      const cached: CachedQueue = JSON.parse(raw);
      if (Date.now() - cached.timestamp > CACHE_MAX_AGE_MS) {
        localStorage.removeItem(cacheKey); // lazy eviction
        return null;
      }
      return cached;
    } catch {
      localStorage.removeItem(cacheKey); // corrupted
      return null;
    }
  }, [cacheKey]);

  /** Clear cache (on send success) */
  const clearCache = useCallback(() => {
    localStorage.removeItem(cacheKey);
  }, [cacheKey]);

  /** Get cache age in minutes (for "Using cached data (X min ago)" banner) */
  const getCacheAge = useCallback((): number | null => {
    const cached = readCache();
    if (!cached) return null;
    return Math.round((Date.now() - cached.timestamp) / 60000);
  }, [readCache]);

  return { writeCache, readCache, clearCache, getCacheAge };
}
