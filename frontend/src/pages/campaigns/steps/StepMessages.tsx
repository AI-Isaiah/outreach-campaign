import { useState, useRef, useMemo } from "react";
import { useFormContext } from "react-hook-form";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, Wand2 } from "lucide-react";
import Button from "../../../components/ui/Button";
import { api } from "../../../api/client";
import { useToast } from "../../../components/Toast";
import type { WizardFormData, StepMessageData } from "../schemas/campaignSchema";
import type { Template } from "../../../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isEmailChannel(channel: string): boolean {
  return channel === "email";
}

// ---------------------------------------------------------------------------
// StepMessages -- Step 4 of the Campaign Wizard
//
// Grok R4: ZERO non-context useState for form fields.
// All message data lives in the form via useFormContext<WizardFormData>().
// Only UI-only ephemeral state (expand/collapse, AI loading spinners,
// improve-mode instruction input, smart-input visibility) uses useState.
// ---------------------------------------------------------------------------

export default function StepMessages() {
  const { watch, setValue, getValues } = useFormContext<WizardFormData>();
  const { toast } = useToast();

  // ---- Form-bound reads ----
  const steps = watch("steps");
  const stepMessages = watch("stepMessages");
  const productDescription = watch("productDescription");

  // ---- UI-only state (not in form schema) ----
  const [showSmartInput, setShowSmartInput] = useState(false);
  const [descriptionPrompt, setDescriptionPrompt] = useState("");
  const [improveStep, setImproveStep] = useState<number | null>(null);
  const [improveInstruction, setImproveInstruction] = useState("");

  const descriptionRef = useRef<HTMLTextAreaElement>(null);

  // ---- Template query ----
  const { data: templates = [] } = useQuery<Template[]>({
    queryKey: ["templates"],
    queryFn: () => api.listTemplates(undefined, true),
  });

  // ---- Helpers to read/write per-step message data ----

  function getMsg(stepOrder: number): StepMessageData {
    return (
      stepMessages[String(stepOrder)] ?? {
        mode: "template",
        templateId: null,
        subject: "",
        body: "",
        refTemplateId: null,
      }
    );
  }

  function setMsgField<K extends keyof StepMessageData>(
    stepOrder: number,
    field: K,
    value: StepMessageData[K],
  ) {
    // react-hook-form cannot infer the value type for dynamic path strings,
    // so we use `as any` here. The generic constraint ensures callers pass
    // the correct value type for the given field key.
    setValue(
      `stepMessages.${String(stepOrder)}.${field}` as any,
      value as any,
      { shouldDirty: true },
    );
  }

  // ---- AI: generate full sequence ----

  const sequenceMutation = useMutation({
    mutationFn: () =>
      api.generateSequenceMessages({
        steps: steps.map((s) => ({
          step_order: s.step_order,
          channel: s.channel,
          delay_days: s.delay_days,
        })),
        product_description: productDescription ?? "",
      }),
    onSuccess: (data) => {
      for (const msg of data.messages) {
        const key = String(msg.step_order);
        setValue(`stepMessages.${key}.mode`, "manual", { shouldDirty: true });
        if (msg.subject) {
          setValue(`stepMessages.${key}.subject`, msg.subject, {
            shouldDirty: true,
          });
        }
        setValue(`stepMessages.${key}.body`, msg.body, { shouldDirty: true });
      }
      toast(
        `Generated messages for ${data.messages.length} steps`,
        "success",
      );
    },
    onError: () => {
      toast("AI generation failed. Set messages manually.", "error");
    },
  });

  // ---- AI: improve single message ----

  const improveMutation = useMutation({
    mutationFn: (params: {
      stepOrder: number;
      channel: string;
      body: string;
      subject?: string;
      instruction: string;
    }) =>
      api.improveMessage({
        channel: params.channel,
        body: params.body,
        subject: params.subject,
        instruction: params.instruction,
      }),
    onSuccess: (data, vars) => {
      const key = String(vars.stepOrder);
      if (data.subject) {
        setValue(`stepMessages.${key}.subject`, data.subject, {
          shouldDirty: true,
        });
      }
      setValue(`stepMessages.${key}.body`, data.body, { shouldDirty: true });
      setImproveStep(null);
      setImproveInstruction("");
      toast("Message improved", "success");
    },
    onError: () => {
      toast("Failed to improve message. Try again.", "error");
    },
  });

  // ---- Pre-group templates by channel (avoids re-filtering per step per keystroke) ----

  const { emailTemplates, linkedinTemplates } = useMemo(() => ({
    emailTemplates: templates.filter((t) => t.channel === "email"),
    linkedinTemplates: templates.filter((t) => t.channel !== "email"),
  }), [templates]);

  const filteredTemplates = (channel: string) =>
    isEmailChannel(channel) ? emailTemplates : linkedinTemplates;

  // ---- Render ----

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Choose message templates</h2>
      <p className="text-sm text-gray-500">
        Pick a template, write your own message, or use AI to generate
        personalized drafts from research data.
      </p>

      {/* ── AI sequence-level generation toggle ── */}
      {!showSmartInput ? (
        <button
          type="button"
          onClick={() => setShowSmartInput(true)}
          className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-lg border-2 border-dashed border-purple-200 bg-purple-50/50 text-purple-700 text-sm font-medium hover:bg-purple-50 hover:border-purple-300 transition-colors"
        >
          <Sparkles size={16} />
          Generate All Messages with AI
        </button>
      ) : (
        <div className="p-4 rounded-lg border border-purple-200 bg-purple-50/30 space-y-3">
          <label className="block text-sm font-medium text-gray-700">
            Describe what you're selling / your fund thesis
          </label>
          {descriptionPrompt && (
            <p className="text-sm text-purple-700 bg-purple-100 rounded-md px-3 py-2">
              {descriptionPrompt}
            </p>
          )}
          <textarea
            ref={descriptionRef}
            value={productDescription ?? ""}
            onChange={(e) => {
              setValue("productDescription", e.target.value, {
                shouldDirty: true,
              });
              setDescriptionPrompt("");
            }}
            placeholder="e.g., We run a $200M crypto-native fund focused on DePIN infrastructure. Looking to connect with allocators exploring digital asset exposure..."
            className="w-full h-20 p-3 border border-gray-200 rounded-md text-sm resize-y focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => sequenceMutation.mutate()}
              loading={sequenceMutation.isPending}
              disabled={(productDescription ?? "").trim().length < 10}
              leftIcon={<Sparkles size={14} />}
              className="!bg-purple-600 hover:!bg-purple-700"
            >
              Generate All Messages
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSmartInput(false)}
              disabled={sequenceMutation.isPending}
            >
              Cancel
            </Button>
            {(productDescription ?? "").trim().length > 0 &&
              (productDescription ?? "").trim().length < 10 && (
                <span className="text-xs text-gray-400">
                  Minimum 10 characters
                </span>
              )}
          </div>
        </div>
      )}

      {/* ── Per-step message cards ── */}
      <div className="space-y-4">
        {steps.map((s) => {
          const msg = getMsg(s.step_order);
          const mode = msg.mode || "template";
          const isEmail = isEmailChannel(s.channel);
          const available = filteredTemplates(s.channel);
          const hasBody = (msg.body || "").trim().length > 0;

          return (
            <div
              key={s.step_order}
              className={`p-4 border rounded-lg space-y-3 ${
                sequenceMutation.isPending
                  ? "border-purple-200 bg-purple-50/20"
                  : "border-gray-200"
              }`}
            >
              {/* Step header */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400 shrink-0">
                  Step {s.step_order} &middot; Day {s.delay_days}
                </span>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded shrink-0 ${
                    isEmail
                      ? "bg-blue-100 text-blue-700"
                      : "bg-indigo-100 text-indigo-700"
                  }`}
                >
                  {isEmail ? "Email" : "LinkedIn"}
                </span>
              </div>

              {sequenceMutation.isPending ? (
                /* Skeleton while AI generates */
                <div className="space-y-2 animate-pulse">
                  <div className="h-4 bg-purple-100 rounded w-3/4" />
                  <div className="h-4 bg-purple-100 rounded w-full" />
                  <div className="h-4 bg-purple-100 rounded w-5/6" />
                  <p className="text-xs text-purple-500 font-medium">
                    Generating personalized sequence...
                  </p>
                </div>
              ) : (
                <>
                  {/* Mode selector (radio group) */}
                  <div
                    className="flex flex-col sm:flex-row gap-2 sm:gap-4"
                    role="radiogroup"
                    aria-label={`Template mode for Step ${s.step_order}: ${s.channel}`}
                  >
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name={`mode-${s.step_order}`}
                        checked={mode === "template"}
                        onChange={() =>
                          setMsgField(s.step_order, "mode", "template")
                        }
                        className="text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      />
                      <span className="text-sm font-medium text-gray-700">
                        Select template
                      </span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name={`mode-${s.step_order}`}
                        checked={mode === "manual"}
                        onChange={() =>
                          setMsgField(s.step_order, "mode", "manual")
                        }
                        className="text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      />
                      <span className="text-sm font-medium text-gray-700">
                        Write manually
                      </span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name={`mode-${s.step_order}`}
                        checked={mode === "ai"}
                        onChange={() =>
                          setMsgField(s.step_order, "mode", "ai")
                        }
                        className="text-purple-600 focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2"
                      />
                      <Sparkles size={14} className="text-purple-500" />
                      <span className="text-sm font-medium text-purple-600">
                        AI draft
                      </span>
                    </label>
                  </div>

                  {/* ── Template mode ── */}
                  {mode === "template" && (
                    <div>
                      <select
                        value={msg.templateId ?? ""}
                        onChange={(e) =>
                          setMsgField(
                            s.step_order,
                            "templateId",
                            e.target.value ? Number(e.target.value) : null,
                          )
                        }
                        className="bg-white border border-gray-200 rounded-md px-3 py-2 text-sm w-full"
                      >
                        <option value="">Choose later...</option>
                        {available.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                            {t.variant_label ? ` (${t.variant_label})` : ""}
                          </option>
                        ))}
                      </select>
                      {available.length === 0 && (
                        <p className="text-xs text-gray-400 mt-1">
                          No {isEmail ? "email" : "LinkedIn"} templates yet --
                          write manually or use AI.
                        </p>
                      )}
                      {msg.templateId &&
                        (() => {
                          const tpl = templates.find(
                            (t) => t.id === msg.templateId,
                          );
                          if (!tpl) return null;
                          return (
                            <div className="bg-gray-50 rounded-md p-3 text-sm text-gray-600 mt-2 whitespace-pre-wrap border border-gray-100 max-h-64 overflow-y-auto">
                              {tpl.subject && (
                                <div className="font-medium text-gray-800 mb-2 pb-2 border-b border-gray-200">
                                  Subject: {tpl.subject}
                                </div>
                              )}
                              {tpl.body_template}
                            </div>
                          );
                        })()}
                    </div>
                  )}

                  {/* ── Manual mode ── */}
                  {mode === "manual" && (
                    <div className="space-y-2">
                      <p className="text-xs text-gray-400">
                        Variables:{" "}
                        <code className="text-purple-600 font-medium">
                          {"{{first_name}}"}
                        </code>
                        ,{" "}
                        <code className="text-purple-600 font-medium">
                          {"{{company_name}}"}
                        </code>
                        ,{" "}
                        <code className="text-purple-600 font-medium">
                          {"{{title}}"}
                        </code>
                      </p>
                      {isEmail && (
                        <input
                          type="text"
                          placeholder="Subject line"
                          value={msg.subject || ""}
                          onChange={(e) =>
                            setMsgField(
                              s.step_order,
                              "subject",
                              e.target.value,
                            )
                          }
                          className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        />
                      )}
                      <textarea
                        placeholder="Message body..."
                        value={msg.body || ""}
                        onChange={(e) =>
                          setMsgField(s.step_order, "body", e.target.value)
                        }
                        className="w-full h-28 p-3 border border-gray-200 rounded-md text-sm resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      {hasBody && (
                        <>
                          {improveStep === s.step_order ? (
                            <div className="flex gap-2">
                              <input
                                type="text"
                                value={improveInstruction}
                                onChange={(e) =>
                                  setImproveInstruction(e.target.value)
                                }
                                placeholder="What would you like to improve?"
                                className="flex-1 px-3 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                                onKeyDown={(e) => {
                                  if (
                                    e.key === "Enter" &&
                                    improveInstruction.trim()
                                  ) {
                                    improveMutation.mutate({
                                      stepOrder: s.step_order,
                                      channel: s.channel,
                                      body: msg.body || "",
                                      subject: isEmail
                                        ? msg.subject || undefined
                                        : undefined,
                                      instruction: improveInstruction,
                                    });
                                  }
                                }}
                                autoFocus
                              />
                              <Button
                                variant="primary"
                                size="sm"
                                onClick={() =>
                                  improveMutation.mutate({
                                    stepOrder: s.step_order,
                                    channel: s.channel,
                                    body: msg.body || "",
                                    subject: isEmail
                                      ? msg.subject || undefined
                                      : undefined,
                                    instruction: improveInstruction,
                                  })
                                }
                                loading={improveMutation.isPending}
                                disabled={!improveInstruction.trim()}
                                className="!bg-purple-600 hover:!bg-purple-700"
                              >
                                Apply
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => {
                                  setImproveStep(null);
                                  setImproveInstruction("");
                                }}
                                disabled={improveMutation.isPending}
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setImproveStep(s.step_order);
                                setImproveInstruction("");
                              }}
                              className="inline-flex items-center gap-1 text-xs text-purple-600 hover:text-purple-700 font-medium"
                            >
                              <Wand2 size={12} />
                              Improve with AI
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {/* ── AI mode ── */}
                  {mode === "ai" && (
                    <div className="space-y-3">
                      {msg.body ? (
                        <>
                          <div className="bg-purple-50 rounded-md p-3 text-sm text-gray-700 whitespace-pre-wrap border border-purple-100">
                            {isEmail && msg.subject && (
                              <div className="font-medium text-gray-800 mb-2 pb-2 border-b border-purple-200">
                                Subject: {msg.subject}
                              </div>
                            )}
                            {msg.body}
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                setMsgField(s.step_order, "mode", "manual")
                              }
                              className="text-xs text-gray-500 hover:text-gray-700"
                            >
                              Edit manually
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setMsgField(s.step_order, "body", "");
                                if (isEmail) {
                                  setMsgField(s.step_order, "subject", "");
                                }
                              }}
                              className="text-xs text-red-500 hover:text-red-700"
                            >
                              Regenerate
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <p className="text-xs text-gray-500">
                            AI generates a personalized message for Step{" "}
                            {s.step_order} (
                            {isEmail ? "email" : "LinkedIn"}).
                            {s.step_order > 1 &&
                              ` Context: the contact has already seen Steps 1\u2013${s.step_order - 1}.`}
                          </p>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={() => {
                                if (
                                  !(productDescription ?? "").trim()
                                ) {
                                  setShowSmartInput(true);
                                  setDescriptionPrompt(
                                    "Please describe what you\u2019re selling, so AI can prepare your message drafts.",
                                  );
                                  setTimeout(
                                    () => descriptionRef.current?.focus(),
                                    100,
                                  );
                                  return;
                                }
                                sequenceMutation.mutate();
                              }}
                              loading={sequenceMutation.isPending}
                              className="!bg-purple-600 hover:!bg-purple-700"
                            >
                              <Sparkles size={14} className="mr-1" />
                              Generate Generic
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                if (
                                  !(productDescription ?? "").trim()
                                ) {
                                  setShowSmartInput(true);
                                  setDescriptionPrompt(
                                    "Please describe what you\u2019re selling, so AI can prepare research-based drafts.",
                                  );
                                  setTimeout(
                                    () => descriptionRef.current?.focus(),
                                    100,
                                  );
                                  return;
                                }
                                toast(
                                  "Research-based generation uses deep research data per company. Set up in Settings \u2192 API Keys if not configured.",
                                  "info",
                                );
                                sequenceMutation.mutate();
                              }}
                              loading={sequenceMutation.isPending}
                            >
                              Based on Research
                            </Button>
                          </div>
                          <div>
                            <label className="block text-xs text-gray-500 mb-1">
                              Reference template (optional)
                            </label>
                            <select
                              value={msg.refTemplateId ?? ""}
                              onChange={(e) =>
                                setMsgField(
                                  s.step_order,
                                  "refTemplateId",
                                  e.target.value
                                    ? Number(e.target.value)
                                    : null,
                                )
                              }
                              className="bg-white border border-gray-200 rounded-md px-3 py-2 text-sm w-full"
                            >
                              <option value="">None</option>
                              {available.map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.name}
                                  {t.variant_label
                                    ? ` (${t.variant_label})`
                                    : ""}
                                </option>
                              ))}
                            </select>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      <p className="text-xs text-gray-400">
        Templates can also be changed later from the campaign's Sequence tab.
      </p>
    </div>
  );
}
