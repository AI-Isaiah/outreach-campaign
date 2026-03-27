import { CHANNEL_LABELS } from "../constants";
import type { GeneratedStep } from "../api/campaigns";

// ─── Constants ─────────────────────────────────────────────────────

export const TOUCHPOINT_OPTIONS = [
  { value: 3, label: "Quick", desc: "3 touchpoints" },
  { value: 5, label: "Standard", desc: "5 touchpoints" },
  { value: 7, label: "Thorough", desc: "7 touchpoints" },
];

export const WIZARD_CHANNELS = ["email", "linkedin_connect", "linkedin_message"] as const;
export const CHANNEL_OPTIONS = WIZARD_CHANNELS.map((ch) => ({
  value: ch,
  label: CHANNEL_LABELS[ch] ?? ch,
}));

export function channelBadgeClass(ch: string): string {
  return ch === "email" ? "bg-blue-100 text-blue-700" : "bg-indigo-100 text-indigo-700";
}

// ─── Sequence generation ───────────────────────────────────────────

export function generateLocalSequence(touchpoints: number, channels: string[]): GeneratedStep[] {
  const steps: GeneratedStep[] = [];
  const hasEmail = channels.includes("email");
  const hasLinkedin = channels.includes("linkedin");
  const isSingleChannel = channels.length === 1;

  let linkedinConnectUsed = false; // only one connect allowed per sequence

  for (let i = 0; i < touchpoints; i++) {
    let channel: string;
    let delay: number;

    if (isSingleChannel) {
      if (channels[0] === "linkedin") {
        channel = !linkedinConnectUsed ? "linkedin_connect" : "linkedin_message";
        linkedinConnectUsed = true;
      } else {
        channel = "email";
      }
      // Increasing gaps for single channel
      if (i === 0) delay = 0;
      else if (i <= 2) delay = steps[i - 1].delay_days + 3 + i;
      else delay = steps[i - 1].delay_days + 4 + i;
    } else {
      // Alternate email and linkedin
      const isEmail = i % 2 === 0 ? hasEmail : !hasEmail;
      if (isEmail) {
        channel = "email";
      } else {
        channel = !linkedinConnectUsed ? "linkedin_connect" : "linkedin_message";
        linkedinConnectUsed = true;
      }

      if (i === 0) delay = 0;
      else {
        const prevChannel = steps[i - 1].channel;
        const sameType = (channel === "email" && prevChannel === "email") ||
          (channel !== "email" && prevChannel !== "email");
        const minGap = sameType ? 3 : 2;
        const backoff = Math.floor(i / 3);
        delay = steps[i - 1].delay_days + minGap + backoff;
      }
    }

    steps.push({
      _id: crypto.randomUUID(),
      step_order: i + 1,
      channel,
      delay_days: delay,
      template_id: null,
    });
  }

  return steps;
}

// ─── Helpers ───────────────────────────────────────────────────────

/** Recalculate step_order (1-indexed) and delay_days after reorder/edit. */
export function recalcSteps(steps: GeneratedStep[]): GeneratedStep[] {
  // Ensure the first LinkedIn step is always linkedin_connect
  const hasConnect = steps.some((s) => s.channel === "linkedin_connect");
  if (!hasConnect) {
    const firstLinkedInIdx = steps.findIndex((s) =>
      s.channel === "linkedin_message" || s.channel === "linkedin_engage" || s.channel === "linkedin_insight"
    );
    if (firstLinkedInIdx !== -1) {
      steps = steps.map((s, i) =>
        i === firstLinkedInIdx ? { ...s, channel: "linkedin_connect" } : s
      );
    }
  }

  return steps.map((s, i) => {
    let delay: number;
    if (i === 0) {
      delay = 0;
    } else {
      const prev = steps[i - 1];
      const sameType =
        (s.channel === "email" && prev.channel === "email") ||
        (s.channel !== "email" && prev.channel !== "email");
      const minGap = sameType ? 3 : 2;
      const backoff = Math.floor(i / 3);
      delay = prev.delay_days + minGap + backoff;
    }
    return {
      ...s,
      step_order: i + 1,
      delay_days: delay,
    };
  });
}
