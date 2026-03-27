/**
 * Shared quality indicator computation for queue items.
 * Used by smart defaults (pre-check green items) and ReviewGateModal badges.
 * Single source of truth -- DRY.
 */

import type { MessageDraft, RenderedEmail } from '../types';

export type QualityLevel = 'green' | 'amber' | 'red';

export function computeQualityIndicator(item: {
  message_draft?: MessageDraft | null;
  has_research?: boolean;
  rendered_email?: RenderedEmail | null;
}): QualityLevel {
  // Green: has AI draft AND research backing
  if (item.message_draft != null && item.has_research === true) return 'green';
  // Amber: has rendered template but no AI draft
  if (item.rendered_email != null) return 'amber';
  // Red: no content at all
  return 'red';
}

/**
 * Map quality level to existing StatusBadge color tokens.
 * Matches CLAUDE.md design system: green-600, yellow-600, red-600.
 */
export function qualityColor(level: QualityLevel): string {
  switch (level) {
    case 'green': return 'bg-green-100 text-green-700';
    case 'amber': return 'bg-yellow-100 text-yellow-700';
    case 'red': return 'bg-red-100 text-red-700';
  }
}

/** Dot-only background class for inline quality indicators (w-2 h-2 dots). */
export function qualityDotClass(level: QualityLevel): string {
  switch (level) {
    case 'green': return 'bg-green-500';
    case 'amber': return 'bg-yellow-500';
    case 'red': return 'bg-red-500';
  }
}

export function qualityLabel(level: QualityLevel): string {
  switch (level) {
    case 'green': return 'Research + AI draft';
    case 'amber': return 'Template only';
    case 'red': return 'No content';
  }
}
