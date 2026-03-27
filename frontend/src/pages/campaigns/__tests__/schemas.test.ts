import { describe, it, expect } from "vitest";
import {
  nameSchema,
  contactsSchema,
  sequenceSchema,
  messagesSchema,
  fullCampaignSchema,
  EMPTY_DEFAULTS,
} from "../schemas/campaignSchema";

describe("nameSchema", () => {
  it("accepts valid name", () => {
    const result = nameSchema.safeParse({ name: "Q1 2026 Campaign", description: "Fund outreach" });
    expect(result.success).toBe(true);
  });

  it("rejects empty name", () => {
    const result = nameSchema.safeParse({ name: "", description: "" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("required");
    }
  });

  it("rejects name over 200 chars", () => {
    const result = nameSchema.safeParse({ name: "x".repeat(201) });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("200");
    }
  });
});

describe("contactsSchema", () => {
  it("accepts CRM mode with selected contacts", () => {
    const result = contactsSchema.safeParse({
      contactSource: "crm",
      crmSelectedIds: [1, 2, 3],
      csvContacts: [],
    });
    expect(result.success).toBe(true);
  });

  it("rejects CRM mode with 0 contacts", () => {
    const result = contactsSchema.safeParse({
      contactSource: "crm",
      crmSelectedIds: [],
      csvContacts: [],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("Select at least 1");
    }
  });

  it("accepts CSV mode with selected contacts", () => {
    const result = contactsSchema.safeParse({
      contactSource: "csv",
      crmSelectedIds: [],
      csvContacts: [
        { first_name: "John", last_name: "Doe", email: "john@example.com", linkedin_url: "", company: "Acme", title: "CTO", selected: true },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("rejects CSV mode with 0 selected contacts", () => {
    const result = contactsSchema.safeParse({
      contactSource: "csv",
      crmSelectedIds: [],
      csvContacts: [
        { first_name: "John", last_name: "Doe", email: "john@example.com", linkedin_url: "", company: "Acme", title: "CTO", selected: false },
      ],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("Upload a CSV");
    }
  });

  it("rejects CSV mode with empty contacts array", () => {
    const result = contactsSchema.safeParse({
      contactSource: "csv",
      crmSelectedIds: [],
      csvContacts: [],
    });
    expect(result.success).toBe(false);
  });
});

describe("sequenceSchema", () => {
  const validStep = {
    _id: "step-1",
    step_order: 1,
    channel: "email",
    delay_days: 0,
    template_id: null,
  };

  it("accepts valid sequence", () => {
    const result = sequenceSchema.safeParse({
      touchpoints: 5,
      channels: ["email", "linkedin"],
      steps: [validStep],
    });
    expect(result.success).toBe(true);
  });

  it("rejects 0 steps", () => {
    const result = sequenceSchema.safeParse({
      touchpoints: 5,
      channels: ["email"],
      steps: [],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("At least 1");
    }
  });

  it("rejects 0 channels", () => {
    const result = sequenceSchema.safeParse({
      touchpoints: 5,
      channels: [],
      steps: [validStep],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("at least 1");
    }
  });

  it("rejects duplicate channels", () => {
    const result = sequenceSchema.safeParse({
      touchpoints: 5,
      channels: ["email", "email"],
      steps: [validStep],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("Duplicate");
    }
  });
});

describe("messagesSchema", () => {
  it("accepts template mode with templateId", () => {
    const result = messagesSchema.safeParse({
      stepMessages: {
        "1": { mode: "template", templateId: 42, subject: "", body: "" },
      },
      productDescription: "Crypto fund thesis",
    });
    expect(result.success).toBe(true);
  });

  it("accepts empty stepMessages (messages are optional per step)", () => {
    const result = messagesSchema.safeParse({
      stepMessages: {},
      productDescription: "",
    });
    expect(result.success).toBe(true);
  });

  it("accepts ai mode with null templateId", () => {
    const result = messagesSchema.safeParse({
      stepMessages: {
        "1": { mode: "ai", templateId: null, subject: "", body: "" },
      },
    });
    expect(result.success).toBe(true);
  });
});

describe("fullCampaignSchema", () => {
  it("validates complete campaign data at launch", () => {
    const data = {
      ...EMPTY_DEFAULTS,
      name: "Q1 Campaign",
      crmSelectedIds: [1, 2],
      channels: ["email"],
      steps: [
        { _id: "s1", step_order: 1, channel: "email", delay_days: 0, template_id: null },
      ],
    };
    const result = fullCampaignSchema.safeParse(data);
    expect(result.success).toBe(true);
  });

  it("rejects campaign with missing name and contacts", () => {
    const result = fullCampaignSchema.safeParse(EMPTY_DEFAULTS);
    expect(result.success).toBe(false);
    if (!result.success) {
      // Should have at least name error + contacts error + steps error
      expect(result.error.issues.length).toBeGreaterThanOrEqual(2);
    }
  });
});
