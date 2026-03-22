import { describe, it, expect } from "vitest";

// Test the local sequence generator logic (pure function, no React needed)
// Import the function directly from the module

describe("generateLocalSequence", () => {
  // Inline the function for testing since it's not exported
  function generateLocalSequence(touchpoints: number, channels: string[]) {
    const steps: any[] = [];
    const hasEmail = channels.includes("email");
    const hasLinkedin = channels.includes("linkedin");
    const isSingleChannel = channels.length === 1;
    let linkedinToggle = false;

    for (let i = 0; i < touchpoints; i++) {
      let channel: string;
      let delay: number;

      if (isSingleChannel) {
        channel = channels[0] === "linkedin"
          ? (!linkedinToggle ? "linkedin_connect" : "linkedin_message")
          : channels[0];
        if (i === 0) delay = 0;
        else if (i <= 2) delay = steps[i - 1].delay_days + 3 + i;
        else delay = steps[i - 1].delay_days + 4 + i;
        if (channels[0] === "linkedin") linkedinToggle = !linkedinToggle;
      } else {
        const isEmail = i % 2 === 0 ? hasEmail : !hasEmail;
        if (isEmail) {
          channel = "email";
        } else {
          channel = !linkedinToggle ? "linkedin_connect" : "linkedin_message";
          linkedinToggle = !linkedinToggle;
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
        step_order: i + 1,
        channel,
        delay_days: delay,
        template_id: null,
      });
    }
    return steps;
  }

  it("generates 3-step email-only sequence", () => {
    const steps = generateLocalSequence(3, ["email"]);
    expect(steps).toHaveLength(3);
    expect(steps[0].delay_days).toBe(0);
    expect(steps.every((s: any) => s.channel === "email")).toBe(true);
    // Each step should have increasing delays
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i].delay_days).toBeGreaterThan(steps[i - 1].delay_days);
    }
  });

  it("generates 5-step email+linkedin sequence", () => {
    const steps = generateLocalSequence(5, ["email", "linkedin"]);
    expect(steps).toHaveLength(5);
    expect(steps[0].channel).toBe("email");
    expect(steps[0].delay_days).toBe(0);
    // Should alternate channels
    const channels = steps.map((s: any) => s.channel === "email" ? "email" : "linkedin");
    expect(channels[0]).toBe("email");
    expect(channels[1]).toBe("linkedin");
    expect(channels[2]).toBe("email");
  });

  it("generates 7-step sequence", () => {
    const steps = generateLocalSequence(7, ["email", "linkedin"]);
    expect(steps).toHaveLength(7);
    expect(steps[0].delay_days).toBe(0);
    // All delays should be non-negative and increasing
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i].delay_days).toBeGreaterThan(steps[i - 1].delay_days);
    }
  });

  it("uses linkedin_connect first, then linkedin_message", () => {
    const steps = generateLocalSequence(5, ["email", "linkedin"]);
    const linkedinSteps = steps.filter((s: any) => s.channel.startsWith("linkedin"));
    expect(linkedinSteps[0].channel).toBe("linkedin_connect");
    if (linkedinSteps.length > 1) {
      expect(linkedinSteps[1].channel).toBe("linkedin_message");
    }
  });

  it("handles linkedin-only sequence", () => {
    const steps = generateLocalSequence(3, ["linkedin"]);
    expect(steps).toHaveLength(3);
    expect(steps[0].channel).toBe("linkedin_connect");
    expect(steps[1].channel).toBe("linkedin_message");
    expect(steps[2].channel).toBe("linkedin_connect");
  });

  it("respects minimum gaps between same-channel steps", () => {
    const steps = generateLocalSequence(5, ["email"]);
    for (let i = 1; i < steps.length; i++) {
      const gap = steps[i].delay_days - steps[i - 1].delay_days;
      expect(gap).toBeGreaterThanOrEqual(3);
    }
  });

  it("respects minimum gaps between cross-channel steps", () => {
    const steps = generateLocalSequence(5, ["email", "linkedin"]);
    for (let i = 1; i < steps.length; i++) {
      const gap = steps[i].delay_days - steps[i - 1].delay_days;
      expect(gap).toBeGreaterThanOrEqual(2);
    }
  });
});

describe("CSV parsing", () => {
  function parseCsv(text: string) {
    const lines = text.trim().split("\n");
    if (lines.length < 2) return [];
    const headers = lines[0].split(",").map((h: string) => h.trim().toLowerCase().replace(/['"]/g, ""));
    const colMap: Record<string, string[]> = {
      first_name: ["first_name", "first name", "firstname", "first"],
      last_name: ["last_name", "last name", "lastname", "last"],
      email: ["email", "email_address", "e-mail"],
      linkedin_url: ["linkedin_url", "linkedin", "linkedin url"],
      company: ["company", "company_name", "organization"],
      title: ["title", "job_title", "position"],
    };
    const findCol = (field: string): number => {
      const aliases = colMap[field] || [field];
      return headers.findIndex((h: string) => aliases.includes(h));
    };
    const indices = {
      first_name: findCol("first_name"),
      last_name: findCol("last_name"),
      email: findCol("email"),
      linkedin_url: findCol("linkedin_url"),
      company: findCol("company"),
      title: findCol("title"),
    };
    const contacts: any[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(",").map((c: string) => c.trim().replace(/^["']|["']$/g, ""));
      if (cols.length < 2) continue;
      const get = (field: keyof typeof indices) => indices[field] >= 0 ? cols[indices[field]] || "" : "";
      const email = get("email");
      const firstName = get("first_name");
      if (!email && !firstName) continue;
      contacts.push({ first_name: firstName, last_name: get("last_name"), email, company: get("company"), selected: true });
    }
    return contacts;
  }

  it("parses standard column names", () => {
    const csv = "first_name,last_name,email,company\nJohn,Doe,john@example.com,Acme";
    const result = parseCsv(csv);
    expect(result).toHaveLength(1);
    expect(result[0].first_name).toBe("John");
    expect(result[0].email).toBe("john@example.com");
  });

  it("handles alternative column names", () => {
    const csv = "First Name,Last Name,E-Mail,Organization\nJane,Smith,jane@co.com,BigCorp";
    const result = parseCsv(csv);
    expect(result).toHaveLength(1);
    expect(result[0].first_name).toBe("Jane");
  });

  it("returns empty for header-only CSV", () => {
    expect(parseCsv("first_name,email")).toHaveLength(0);
  });

  it("skips empty rows", () => {
    const csv = "first_name,email\nJohn,john@test.com\n\nJane,jane@test.com";
    const result = parseCsv(csv);
    expect(result).toHaveLength(2);
  });

  it("marks all contacts as selected by default", () => {
    const csv = "first_name,email\nA,a@b.com\nB,b@b.com";
    const result = parseCsv(csv);
    expect(result.every((c: any) => c.selected)).toBe(true);
  });
});
