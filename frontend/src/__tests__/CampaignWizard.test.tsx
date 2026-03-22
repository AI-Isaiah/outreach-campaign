import { describe, it, expect } from "vitest";
import { generateLocalSequence, parseCsv } from "../pages/CampaignWizard";

describe("generateLocalSequence", () => {
  it("generates 3-step email-only sequence", () => {
    const steps = generateLocalSequence(3, ["email"]);
    expect(steps).toHaveLength(3);
    expect(steps[0].delay_days).toBe(0);
    expect(steps.every((s) => s.channel === "email")).toBe(true);
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i].delay_days).toBeGreaterThan(steps[i - 1].delay_days);
    }
  });

  it("generates 5-step email+linkedin sequence", () => {
    const steps = generateLocalSequence(5, ["email", "linkedin"]);
    expect(steps).toHaveLength(5);
    expect(steps[0].channel).toBe("email");
    expect(steps[0].delay_days).toBe(0);
    const channels = steps.map((s) => s.channel === "email" ? "email" : "linkedin");
    expect(channels[0]).toBe("email");
    expect(channels[1]).toBe("linkedin");
    expect(channels[2]).toBe("email");
  });

  it("generates 7-step sequence", () => {
    const steps = generateLocalSequence(7, ["email", "linkedin"]);
    expect(steps).toHaveLength(7);
    expect(steps[0].delay_days).toBe(0);
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i].delay_days).toBeGreaterThan(steps[i - 1].delay_days);
    }
  });

  it("uses linkedin_connect first, then linkedin_message", () => {
    const steps = generateLocalSequence(5, ["email", "linkedin"]);
    const linkedinSteps = steps.filter((s) => s.channel.startsWith("linkedin"));
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
    expect(result.every((c) => c.selected)).toBe(true);
  });
});
