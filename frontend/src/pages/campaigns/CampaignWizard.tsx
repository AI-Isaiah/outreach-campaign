import { useState, useCallback, useMemo, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useForm, useFormContext, FormProvider } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { request } from "../../api/request";
import { Check, Loader2 } from "lucide-react";
import { campaignsApi } from "../../api/campaigns";
import { api } from "../../api/client";
import { useToast } from "../../components/Toast";
import {
  fullCampaignSchema,
  STEP_FIELDS,
  EMPTY_DEFAULTS,
  type WizardFormData,
} from "./schemas/campaignSchema";
import { useWizardPersistence } from "./hooks/useWizardPersistence";
import WizardStepWrapper from "./components/WizardStepWrapper";
import StepName from "./steps/StepName";
import StepContacts from "./steps/StepContacts";
import StepSequence from "./steps/StepSequence";
import StepMessages from "./steps/StepMessages";
import StepReview from "./steps/StepReview";

/*
 * Campaign Wizard — 5-step guided flow (Approach B redesign)
 *
 * Architecture:
 *   FormProvider (react-hook-form + Zod) wraps all steps.
 *   Each step uses useFormContext() — zero local useState for form fields.
 *   useWizardPersistence() handles localStorage + API draft sync.
 *
 * Step 1: Name & Goal
 * Step 2: Add Contacts (CRM picker + CSV upload)
 * Step 3: Build Sequence (touchpoints + channels + drag-drop)
 * Step 4: Messages (template / manual / AI per step)
 * Step 5: Review & Launch
 */

const STEPS = [
  { label: "Name", shortLabel: "Name" },
  { label: "Contacts", shortLabel: "Contacts" },
  { label: "Sequence", shortLabel: "Sequence" },
  { label: "Messages", shortLabel: "Messages" },
  { label: "Review", shortLabel: "Review" },
] as const;

// Map step index to field names for per-step validation via trigger()
const STEP_VALIDATION: Record<number, readonly string[]> = {
  0: STEP_FIELDS.name,
  1: STEP_FIELDS.contacts,
  2: STEP_FIELDS.sequence,
  3: STEP_FIELDS.messages,
};

export default function CampaignWizard() {
  const form = useForm<WizardFormData>({
    resolver: zodResolver(fullCampaignSchema) as any,
    mode: "onTouched",
    defaultValues: EMPTY_DEFAULTS,
  });

  // FormProvider MUST wrap everything that calls useFormContext —
  // including useWizardPersistence which lives inside CampaignWizardInner
  return (
    <FormProvider {...form}>
      <CampaignWizardInner />
    </FormProvider>
  );
}

function CampaignWizardInner() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { toast } = useToast();
  const form = useFormContext<WizardFormData>();
  const [pendingAction, setPendingAction] = useState<"launch" | "draft" | null>(null);

  // Support editing an existing campaign's sequence (from CampaignDetail)
  const editCampaignId = searchParams.get("editCampaign");
  const initialStep = Number(searchParams.get("step") || "0");
  const [step, setStep] = useState(initialStep);

  // Load existing campaign data + sequence steps when editing
  const { data: existingCampaign } = useQuery({
    queryKey: ["campaign-edit", editCampaignId],
    queryFn: async () => {
      const [campaign, steps] = await Promise.all([
        request<{ campaign: { id: number; name: string; description: string } }>(`/campaigns/${editCampaignId}`),
        request<{ id: number; step_order: number; channel: string; delay_days: number; template_id: number | null }[]>(`/campaigns/${editCampaignId}/sequence`),
      ]);
      return { campaign: campaign.campaign, steps };
    },
    enabled: !!editCampaignId,
  });

  useEffect(() => {
    if (existingCampaign?.campaign) {
      const c = existingCampaign.campaign;
      form.setValue("name", c.name);
      if (c.description) form.setValue("description", c.description);
    }
    if (existingCampaign?.steps && existingCampaign.steps.length > 0) {
      const wizardSteps = existingCampaign.steps.map((s) => ({
        _id: `existing-${s.id}`,
        step_order: s.step_order,
        channel: s.channel,
        delay_days: s.delay_days,
        template_id: s.template_id,
      }));
      form.setValue("steps", wizardSteps);
    }
  }, [existingCampaign, form]);

  const { saveToApi, cleanupDraft, isLoading } = useWizardPersistence(step);

  // ─── Launch / Save-as-Draft ───

  const launchMutation = useMutation({
    mutationFn: async (data: { status: "active" | "draft" }) => {
      const values = form.getValues();

      // Resolve contact IDs based on source (deduplicate — draft persistence can introduce dupes)
      const contactIds = values.contactSource === "crm"
        ? [...new Set(values.crmSelectedIds)]
        : values.csvContacts.filter(c => c.selected).map(c => c.id!).filter(Boolean);

      // Build step data — create templates on-the-fly for manual mode
      const stepData = await Promise.all(
        values.steps.map(async ({ _id: _, ...s }) => {
          const msg = values.stepMessages[String(s.step_order)] || { mode: "template" as const, templateId: null, subject: "", body: "", refTemplateId: null };

          if (msg.mode === "manual" && msg.body?.trim()) {
            const isEmail = s.channel === "email";
            const result = await api.createTemplate({
              name: `${values.name} - Step ${s.step_order}`,
              channel: s.channel,
              body_template: msg.body,
              subject: isEmail ? msg.subject || "" : undefined,
            });
            return { ...s, template_id: result.id, draft_mode: "template" as const };
          }

          if (msg.mode === "ai") {
            return { ...s, template_id: msg.refTemplateId ?? null, draft_mode: "ai" as const };
          }

          return { ...s, template_id: msg.templateId ?? null, draft_mode: "template" as const };
        })
      );

      // Edit mode: replace steps on existing campaign
      if (editCampaignId) {
        const cid = Number(editCampaignId);
        // Delete existing steps first
        const existing = await request<{ id: number }[]>(`/campaigns/${cid}/sequence`);
        for (const s of existing) {
          await request(`/campaigns/${cid}/sequence/${s.id}`, { method: "DELETE" });
        }
        // Add the new steps
        for (const s of stepData) {
          await campaignsApi.addSequenceStep(cid, {
            channel: s.channel,
            delay_days: s.delay_days,
            template_id: s.template_id ?? undefined,
            step_order: s.step_order,
          });
        }
        return { name: values.name, status: data.status, contacts_enrolled: 0 };
      }

      return campaignsApi.launchCampaign({
        name: values.name,
        description: values.description || "",
        steps: stepData,
        contact_ids: contactIds,
        status: data.status,
      });
    },
    onSuccess: (data) => {
      setPendingAction(null);
      cleanupDraft();
      if (editCampaignId) {
        toast("Sequence saved!", "success");
        navigate(`/campaigns/${data.name}`);
        return;
      }
      if (data.status === "active") {
        toast(`Campaign launched! ${data.contacts_enrolled} contacts enrolled.`, "success");
      } else {
        toast("Campaign saved as draft.", "info");
      }
      navigate(`/campaigns/${data.name}`);
    },
    onError: (error: Error) => {
      setPendingAction(null);
      toast(error.message || "Failed to launch campaign", "error");
    },
  });

  // ─── Step Navigation ───

  const handleNext = useCallback(async () => {
    const fieldsToValidate = STEP_VALIDATION[step];
    if (fieldsToValidate) {
      const valid = await form.trigger(fieldsToValidate as any);
      if (!valid) return; // Block navigation, inline errors shown
    }
    saveToApi(step + 1);
    setStep(s => Math.min(s + 1, STEPS.length - 1));
  }, [step, form, saveToApi]);

  const handleBack = useCallback(() => {
    setStep(s => Math.max(s - 1, 0));
  }, []);

  const handleSaveDraft = useCallback(() => {
    setPendingAction("draft");
    launchMutation.mutate({ status: "draft" });
  }, [launchMutation]);

  const handleLaunch = useCallback(async () => {
    // Full schema validation before launch
    const result = fullCampaignSchema.safeParse(form.getValues());
    if (!result.success) {
      const firstError = result.error.issues[0];
      toast(`Validation failed: ${firstError.message}`, "error");
      return;
    }
    setPendingAction("launch");
    launchMutation.mutate({ status: "active" });
  }, [form, launchMutation, toast]);

  // Reactive watches for canProceed — getValues() is a snapshot that won't re-render
  const watchedName = form.watch("name");
  const watchedCrmIds = form.watch("crmSelectedIds");
  const watchedCsvContacts = form.watch("csvContacts");
  const watchedContactSource = form.watch("contactSource");
  const watchedSteps = form.watch("steps");

  const canProceed = useMemo(() => {
    switch (step) {
      case 0: return watchedName.trim().length > 0;
      case 1:
        if (watchedContactSource === "crm") return new Set(watchedCrmIds).size > 0;
        return watchedCsvContacts.filter(c => c.selected).length > 0;
      case 2: return watchedSteps.length > 0;
      default: return true;
    }
  }, [step, watchedName, watchedCrmIds, watchedCsvContacts, watchedContactSource, watchedSteps]);

  // ─── Loading state while restoring draft ───

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <Loader2 size={24} className="animate-spin mb-3" />
          <p className="text-sm">Loading draft...</p>
        </div>
      </div>
    );
  }

  // ─── Render ───

  return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        {/* Step progress indicator */}
        <div className="mb-8">
          {/* Desktop */}
          <div className="hidden sm:flex items-center justify-between">
            {STEPS.map((s, i) => (
              <div key={s.label} className="flex items-center">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                      i < step
                        ? "bg-green-600 text-white"
                        : i === step
                        ? "bg-blue-600 text-white"
                        : "bg-gray-200 text-gray-400"
                    }`}
                  >
                    {i < step ? <Check size={12} /> : i + 1}
                  </div>
                  <span
                    className={`text-xs mt-1.5 ${
                      i < step
                        ? "text-gray-500"
                        : i === step
                        ? "text-gray-900 font-medium"
                        : "text-gray-400"
                    }`}
                  >
                    {s.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div
                    className={`h-0.5 w-12 mx-2 mt-[-18px] ${
                      i < step ? "bg-green-600" : "bg-gray-200"
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
          {/* Mobile */}
          <div className="sm:hidden text-center">
            <span className="text-sm font-medium text-gray-900">
              Step {step + 1} of {STEPS.length}: {STEPS[step].label}
            </span>
            <div className="h-1 bg-gray-200 rounded-full mt-2">
              <div
                className="h-1 bg-blue-600 rounded-full transition-all duration-300"
                style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
              />
            </div>
          </div>
        </div>

        {/* Step content */}
        <WizardStepWrapper
          currentStep={step}
          totalSteps={STEPS.length}
          onNext={handleNext}
          onBack={handleBack}
          onSaveDraft={handleSaveDraft}
          onLaunch={handleLaunch}
          canProceed={canProceed}
          isLaunching={pendingAction === "launch" && launchMutation.isPending}
          isSaving={pendingAction === "draft" && launchMutation.isPending}
        >
          {step === 0 && <StepName />}
          {step === 1 && <StepContacts />}
          {step === 2 && <StepSequence />}
          {step === 3 && <StepMessages />}
          {step === 4 && <StepReview />}
        </WizardStepWrapper>
      </div>
  );
}
