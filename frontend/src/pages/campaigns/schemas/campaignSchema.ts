import { z } from "zod";

// --- Step 1: Name ---

export const nameSchema = z.object({
  name: z.string().min(1, "Campaign name is required").max(200, "Name must be under 200 characters"),
  description: z.string().max(1000, "Description must be under 1000 characters").optional().default(""),
});

// --- Step 2: Contacts ---

export const parsedContactSchema = z.object({
  first_name: z.string().default(""),
  last_name: z.string().default(""),
  email: z.string().default(""),
  linkedin_url: z.string().default(""),
  company: z.string().default(""),
  title: z.string().default(""),
  selected: z.boolean().default(true),
  id: z.number().optional(),
});

export const contactsSchema = z.object({
  contactSource: z.enum(["crm", "csv"]),
  crmSelectedIds: z.array(z.number()).default([]),
  csvContacts: z.array(parsedContactSchema).default([]),
}).superRefine((data, ctx) => {
  if (data.contactSource === "crm" && data.crmSelectedIds.length === 0) {
    ctx.addIssue({ code: "custom", path: ["crmSelectedIds"], message: "Select at least 1 contact" });
  }
  if (data.contactSource === "csv") {
    const selected = data.csvContacts.filter(c => c.selected);
    if (selected.length === 0) {
      ctx.addIssue({ code: "custom", path: ["csvContacts"], message: "Upload a CSV with at least 1 contact" });
    }
  }
});

// --- Step 3: Sequence ---

const channelEnum = z.enum(["email", "linkedin_connect", "linkedin_message", "linkedin"]);

export const sequenceStepSchema = z.object({
  _id: z.string(),
  step_order: z.number(),
  channel: z.string(),
  delay_days: z.number().min(0),
  template_id: z.number().nullable().default(null),
  draft_mode: z.enum(["template", "ai"]).optional(),
});

export const sequenceSchema = z.object({
  touchpoints: z.number().min(1).max(10).default(5),
  channels: z.array(channelEnum)
    .min(1, "Select at least 1 channel")
    .refine(a => new Set(a).size === a.length, "Duplicate channels"),
  steps: z.array(sequenceStepSchema).min(1, "At least 1 sequence step required"),
});

// --- Step 4: Messages ---

export const stepMessageSchema = z.object({
  mode: z.enum(["template", "manual", "ai"]).default("template"),
  templateId: z.number().nullable().default(null),
  subject: z.string().optional().default(""),
  body: z.string().optional().default(""),
  refTemplateId: z.number().nullable().default(null),
});

export const messagesSchema = z.object({
  stepMessages: z.record(z.string(), stepMessageSchema).default({}),
  productDescription: z.string().optional().default(""),
});

// --- Full campaign schema (used at launch for cross-step validation) ---

export const fullCampaignSchema = nameSchema
  .merge(contactsSchema)
  .merge(sequenceSchema)
  .merge(messagesSchema);

// --- Derived TypeScript types ---

export type WizardFormData = z.infer<typeof fullCampaignSchema>;
export type NameFormData = z.infer<typeof nameSchema>;
export type ContactsFormData = z.infer<typeof contactsSchema>;
export type SequenceFormData = z.infer<typeof sequenceSchema>;
export type MessagesFormData = z.infer<typeof messagesSchema>;
export type StepMessageData = z.infer<typeof stepMessageSchema>;
export type ParsedContact = z.infer<typeof parsedContactSchema>;

// --- Step field names for trigger() validation ---

export const STEP_FIELDS = {
  name: ["name", "description"] as const,
  contacts: ["contactSource", "crmSelectedIds", "csvContacts"] as const,
  sequence: ["touchpoints", "channels", "steps"] as const,
  messages: ["stepMessages", "productDescription"] as const,
} as const;

// --- Empty defaults for fresh wizard ---

export const EMPTY_DEFAULTS: WizardFormData = {
  name: "",
  description: "",
  contactSource: "crm",
  crmSelectedIds: [],
  csvContacts: [],
  touchpoints: 5,
  channels: ["email", "linkedin"],
  steps: [],
  stepMessages: {},
  productDescription: "",
};
