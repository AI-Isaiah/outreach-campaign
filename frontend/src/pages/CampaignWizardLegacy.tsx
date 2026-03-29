import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Upload,
  Check,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Rocket,
  Save,
  Mail,
  Linkedin,
  AlertCircle,
  FileText,
  Loader2,
  Sparkles,
  GripVertical,
  Plus,
  Trash2,
  Wand2,
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";
import { campaignsApi } from "../api/campaigns";
import type { GeneratedStep } from "../api/campaigns";
import { api } from "../api/client";
import type { Template } from "../types";
import { useToast } from "../components/Toast";
import { CHANNEL_LABELS } from "../constants";
import { splitCsvLine } from "../utils/parseCsv";
import {
  TOUCHPOINT_OPTIONS,
  WIZARD_CHANNELS,
  CHANNEL_OPTIONS,
  channelBadgeClass,
  generateLocalSequence,
  recalcSteps,
} from "../utils/sequenceUtils";
import CrmContactPicker from "./campaigns/components/CrmContactPicker";

/*
 * Campaign Wizard — 5-step guided flow
 *
 * Step 1: Name & Goal
 * Step 2: Add Contacts (CSV upload + select)
 * Step 3: Build Sequence (touchpoints + channels)
 * Step 4: Messages (template picker)
 * Step 5: Review & Launch
 */

const STEPS = [
  { label: "Name", shortLabel: "Name" },
  { label: "Contacts", shortLabel: "Contacts" },
  { label: "Sequence", shortLabel: "Sequence" },
  { label: "Messages", shortLabel: "Messages" },
  { label: "Review", shortLabel: "Review" },
] as const;

const MAX_CSV_SIZE_MB = 5;
const MAX_CSV_SIZE_BYTES = MAX_CSV_SIZE_MB * 1024 * 1024;

interface ParsedContact {
  first_name: string;
  last_name: string;
  email: string;
  linkedin_url: string;
  company: string;
  title: string;
  selected: boolean;
  id?: number; // if existing contact
}

export default function CampaignWizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const [step, setStep] = useState(0);
  const [showLeaveDialog, setShowLeaveDialog] = useState(false);

  // Step 1: Name
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // Step 2: Contacts
  const [contactTab, setContactTab] = useState<"crm" | "csv">("crm");
  const [contacts, setContacts] = useState<ParsedContact[]>([]);
  const [csvError, setCsvError] = useState("");
  const [csvFileName, setCsvFileName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [showFormatHelp, setShowFormatHelp] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [crmSelectedIds, setCrmSelectedIds] = useState<Set<number>>(() => {
    const state = location.state as { importedContactIds?: number[] } | null;
    if (state?.importedContactIds?.length) {
      return new Set(state.importedContactIds);
    }
    return new Set();
  });
  const [importedCount] = useState<number>(() => {
    const state = location.state as { importedCount?: number } | null;
    return state?.importedCount ?? 0;
  });

  // Step 3: Sequence
  const [touchpoints, setTouchpoints] = useState(5);
  const [channels, setChannels] = useState<Set<string>>(new Set(["email", "linkedin"]));
  const [generatedSteps, setGeneratedSteps] = useState<GeneratedStep[]>([]);

  // Step 4: Messages
  const [stepTemplates, setStepTemplates] = useState<Record<number, number | null>>({});
  const [templateModes, setTemplateModes] = useState<Record<number, 'template' | 'manual' | 'ai'>>({});
  const [manualSubjects, setManualSubjects] = useState<Record<number, string>>({});
  const [manualBodies, setManualBodies] = useState<Record<number, string>>({});
  const [refTemplates, setRefTemplates] = useState<Record<number, number | null>>({});

  // Launch mutation
  const launchMutation = useMutation({
    mutationFn: async (data: { status: "active" | "draft" }) => {
      // For manual mode steps, create templates on the fly
      const stepData = await Promise.all(
        generatedSteps.map(async ({ _id: _, ...s }) => {
          const mode = templateModes[s.step_order] || "template";

          if (mode === "manual" && manualBodies[s.step_order]?.trim()) {
            const isEmail = s.channel === "email";
            const result = await api.createTemplate({
              name: `${name} - Step ${s.step_order}`,
              channel: s.channel,
              body_template: manualBodies[s.step_order],
              subject: isEmail ? manualSubjects[s.step_order] || "" : undefined,
            });
            return {
              ...s,
              template_id: result.id,
              draft_mode: "template" as const,
            };
          }

          if (mode === "ai") {
            return {
              ...s,
              template_id: refTemplates[s.step_order] ?? null,
              draft_mode: "ai" as const,
            };
          }

          // template mode
          return {
            ...s,
            template_id: stepTemplates[s.step_order] ?? null,
            draft_mode: "template" as const,
          };
        })
      );

      return campaignsApi.launchCampaign({
        name,
        description,
        steps: stepData,
        contact_ids: selectedContactIds,
        status: data.status,
      });
    },
    onSuccess: (data) => {
      if (data.status === "active") {
        toast(
          `Campaign launched! ${data.contacts_enrolled} contacts enrolled.`,
          "success"
        );
      } else {
        toast("Campaign saved as draft.", "info");
      }
      navigate(`/campaigns/${data.name}`);
    },
    onError: (error: Error) => {
      toast(error.message || "Failed to launch campaign", "error");
    },
  });

  const selectedContacts = contacts.filter((c) => c.selected);
  const csvSelectedIds = selectedContacts
    .filter((c) => c.id != null)
    .map((c) => c.id!);
  const selectedContactIds =
    contactTab === "crm" ? Array.from(crmSelectedIds) : csvSelectedIds;
  const totalSelectedCount =
    contactTab === "crm" ? crmSelectedIds.size : selectedContacts.length;

  // Warn on navigate-away
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (name || contacts.length > 0) {
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [name, contacts.length]);

  // Generate sequence when touchpoints/channels change
  useEffect(() => {
    if (channels.size === 0) {
      setGeneratedSteps([]);
      return;
    }
    const channelList = Array.from(channels);
    const steps = generateLocalSequence(touchpoints, channelList);
    setGeneratedSteps(steps);
  }, [touchpoints, channels]);

  const canProceed = useCallback((): boolean => {
    switch (step) {
      case 0: return name.trim().length > 0;
      case 1: return totalSelectedCount > 0;
      case 2: return generatedSteps.length > 0;
      case 3: return true; // templates are optional
      case 4: return true;
      default: return false;
    }
  }, [step, name, totalSelectedCount, generatedSteps.length]);

  const handleCsvUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith(".csv")) {
      setCsvError("Please upload a .csv file");
      return;
    }
    if (file.size > MAX_CSV_SIZE_BYTES) {
      setCsvError(`File too large. Maximum size is ${MAX_CSV_SIZE_MB}MB.`);
      return;
    }

    setCsvError("");
    setUploading(true);
    setCsvFileName(file.name);

    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const text = evt.target?.result as string;
        const parsed = parseCsv(text);
        if (parsed.length === 0) {
          // Dumb parser failed — offer smart import or show format help
          setPendingFile(file);
          setCsvError("PARSE_FAILED");
        } else {
          setContacts(parsed);
          setPendingFile(null);
          setShowFormatHelp(false);
        }
      } catch {
        setPendingFile(file);
        setCsvError("PARSE_FAILED");
      } finally {
        setUploading(false);
      }
    };
    reader.readAsText(file);
  }, []);

  const toggleContact = useCallback((index: number) => {
    setContacts((prev) =>
      prev.map((c, i) => (i === index ? { ...c, selected: !c.selected } : c))
    );
  }, []);

  const toggleAll = useCallback((selected: boolean) => {
    setContacts((prev) => prev.map((c) => ({ ...c, selected })));
  }, []);

  const toggleChannel = useCallback((channel: string) => {
    setChannels((prev) => {
      const next = new Set(prev);
      if (next.has(channel)) {
        if (next.size > 1) next.delete(channel);
      } else {
        next.add(channel);
      }
      return next;
    });
  }, []);

  return (
    <div className="max-w-2xl mx-auto">
      {/* Step indicator — desktop: circles, mobile: compact */}
      <div className="mb-8">
        {/* Desktop step indicator */}
        <div className="hidden sm:flex items-center justify-between">
          {STEPS.map((s, i) => (
            <div key={s.label} className="flex items-center">
              <div className="flex flex-col items-center">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold border-2 ${
                    i < step
                      ? "border-green-500 bg-green-500 text-white"
                      : i === step
                      ? "border-gray-900 bg-gray-900 text-white"
                      : "border-gray-200 text-gray-400"
                  }`}
                >
                  {i < step ? <Check size={14} /> : i + 1}
                </div>
                <span
                  className={`text-xs mt-1.5 ${
                    i === step ? "text-gray-900 font-semibold" : "text-gray-400"
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`h-0.5 w-12 mx-2 mt-[-18px] ${
                    i < step ? "bg-green-500" : "bg-gray-200"
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        {/* Mobile compact stepper */}
        <div className="sm:hidden text-center">
          <span className="text-sm font-medium text-gray-900">
            Step {step + 1} of {STEPS.length}: {STEPS[step].label}
          </span>
          <div className="flex gap-1 justify-center mt-2" role="progressbar" aria-valuenow={step + 1} aria-valuemax={STEPS.length}>
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`h-1 rounded-full ${
                  i <= step ? "bg-gray-900 w-8" : "bg-gray-200 w-4"
                }`}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Step content */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {step === 0 && (
          <StepName
            name={name}
            setName={setName}
            description={description}
            setDescription={setDescription}
          />
        )}
        {step === 1 && (
          <StepContacts
            contactTab={contactTab}
            setContactTab={setContactTab}
            contacts={contacts}
            csvError={csvError}
            csvFileName={csvFileName}
            uploading={uploading}
            showFormatHelp={showFormatHelp}
            pendingFile={pendingFile}
            onUpload={handleCsvUpload}
            onToggle={toggleContact}
            onToggleAll={toggleAll}
            onShowFormatHelp={() => setShowFormatHelp(true)}
            onSmartImport={() => {
              if (pendingFile) {
                navigate("/import/smart", { state: { file: pendingFile } });
              }
            }}
            crmSelectedIds={crmSelectedIds}
            setCrmSelectedIds={setCrmSelectedIds}
            importedCount={importedCount}
          />
        )}
        {step === 2 && (
          <StepSequence
            touchpoints={touchpoints}
            setTouchpoints={setTouchpoints}
            channels={channels}
            toggleChannel={toggleChannel}
            steps={generatedSteps}
            onStepsChange={setGeneratedSteps}
          />
        )}
        {step === 3 && (
          <StepMessages
            steps={generatedSteps}
            stepTemplates={stepTemplates}
            setStepTemplates={setStepTemplates}
            templateModes={templateModes}
            setTemplateModes={setTemplateModes}
            manualSubjects={manualSubjects}
            setManualSubjects={setManualSubjects}
            manualBodies={manualBodies}
            setManualBodies={setManualBodies}
            refTemplates={refTemplates}
            setRefTemplates={setRefTemplates}
          />
        )}
        {step === 4 && (
          <StepReview
            name={name}
            description={description}
            contactCount={totalSelectedCount}
            steps={generatedSteps}
            channels={channels}
          />
        )}
      </div>

      {/* Navigation buttons */}
      <div className="flex justify-between mt-6">
        <Button
          variant="secondary"
          onClick={() => (step === 0 ? setShowLeaveDialog(true) : setStep(step - 1))}
          leftIcon={step > 0 ? <ChevronLeft size={16} /> : undefined}
        >
          {step === 0 ? "Cancel" : "Back"}
        </Button>

        <div className="flex gap-3">
          {step === 4 && (
            <Button
              variant="secondary"
              onClick={() => launchMutation.mutate({ status: "draft" })}
              loading={launchMutation.isPending}
              leftIcon={<Save size={16} />}
            >
              Save as Draft
            </Button>
          )}
          {step < 4 ? (
            <Button
              variant="primary"
              onClick={() => setStep(step + 1)}
              disabled={!canProceed()}
              rightIcon={<ChevronRight size={16} />}
              aria-label={`Go to step ${step + 2}: ${STEPS[step + 1]?.label}`}
            >
              Next
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => launchMutation.mutate({ status: "active" })}
              loading={launchMutation.isPending}
              disabled={!canProceed()}
              leftIcon={<Rocket size={16} />}
            >
              Launch Campaign
            </Button>
          )}
        </div>
      </div>

      {/* Leave confirmation dialog */}
      {showLeaveDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/30" onClick={() => setShowLeaveDialog(false)} />
          <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-sm mx-4">
            <h3 className="text-lg font-semibold mb-2">Leave wizard?</h3>
            <p className="text-sm text-gray-500 mb-4">Your progress will be lost.</p>
            <div className="flex gap-3 justify-end">
              <Button variant="secondary" onClick={() => setShowLeaveDialog(false)}>
                Stay
              </Button>
              <Button variant="danger" onClick={() => navigate("/")}>
                Leave
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Step 1: Name & Goal ───────────────────────────────────────────

function StepName({
  name,
  setName,
  description,
  setDescription,
}: {
  name: string;
  setName: (v: string) => void;
  description: string;
  setDescription: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Name your campaign</h2>
      <p className="text-sm text-gray-500">
        Give it a clear name so you can find it later.
      </p>
      <Input
        label="Campaign name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g., Q2 Fund Allocator Outreach"
        autoFocus
      />
      <div className="space-y-1">
        <label className="block text-sm font-medium text-gray-700">
          Description (optional)
        </label>
        <textarea
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What's this campaign about?"
        />
      </div>
    </div>
  );
}

// ─── Step 2: Add Contacts ──────────────────────────────────────────

function StepContacts({
  contactTab,
  setContactTab,
  contacts,
  csvError,
  csvFileName,
  uploading,
  showFormatHelp,
  pendingFile,
  onUpload,
  onToggle,
  onToggleAll,
  onShowFormatHelp,
  onSmartImport,
  crmSelectedIds,
  setCrmSelectedIds,
  importedCount,
}: {
  contactTab: "crm" | "csv";
  setContactTab: (t: "crm" | "csv") => void;
  contacts: ParsedContact[];
  csvError: string;
  csvFileName: string;
  uploading: boolean;
  showFormatHelp: boolean;
  pendingFile: File | null;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onToggle: (i: number) => void;
  onToggleAll: (selected: boolean) => void;
  onShowFormatHelp: () => void;
  onSmartImport: () => void;
  crmSelectedIds: Set<number>;
  setCrmSelectedIds: (ids: Set<number>) => void;
  importedCount: number;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Add contacts</h2>
      <p className="text-sm text-gray-500">
        Pick contacts from your CRM or upload a CSV file.
      </p>

      {importedCount > 0 && crmSelectedIds.size > 0 && (
        <div className="flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          <CheckCircle size={16} className="shrink-0" />
          <span>{crmSelectedIds.size} recently imported contacts pre-selected</span>
        </div>
      )}

      {/* Tab group */}
      <div className="flex border-b border-gray-200">
        <button
          className={`px-4 py-2.5 text-sm font-medium ${
            contactTab === "crm"
              ? "text-gray-900 border-b-2 border-gray-900"
              : "text-gray-500 hover:text-gray-700"
          }`}
          onClick={() => setContactTab("crm")}
        >
          From CRM
        </button>
        <button
          className={`px-4 py-2.5 text-sm font-medium ${
            contactTab === "csv"
              ? "text-gray-900 border-b-2 border-gray-900"
              : "text-gray-500 hover:text-gray-700"
          }`}
          onClick={() => setContactTab("csv")}
        >
          Upload CSV
        </button>
      </div>

      {contactTab === "crm" ? (
        <CrmContactPicker
          selectedIds={crmSelectedIds}
          onSelectionChange={setCrmSelectedIds}
        />
      ) : (
        <CsvUploadTab
          contacts={contacts}
          csvError={csvError}
          csvFileName={csvFileName}
          uploading={uploading}
          showFormatHelp={showFormatHelp}
          pendingFile={pendingFile}
          onUpload={onUpload}
          onToggle={onToggle}
          onToggleAll={onToggleAll}
          onShowFormatHelp={onShowFormatHelp}
          onSmartImport={onSmartImport}
        />
      )}
    </div>
  );
}

// ─── CSV Upload Tab ────────────────────────────────────────────────

function CsvUploadTab({
  contacts,
  csvError,
  csvFileName,
  uploading,
  showFormatHelp,
  pendingFile,
  onUpload,
  onToggle,
  onToggleAll,
  onShowFormatHelp,
  onSmartImport,
}: {
  contacts: ParsedContact[];
  csvError: string;
  csvFileName: string;
  uploading: boolean;
  showFormatHelp: boolean;
  pendingFile: File | null;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onToggle: (i: number) => void;
  onToggleAll: (selected: boolean) => void;
  onShowFormatHelp: () => void;
  onSmartImport: () => void;
}) {
  const selectedCount = contacts.filter((c) => c.selected).length;

  return (
    <div className="space-y-4">
      {/* CSV upload zone */}
      <label className="flex flex-col items-center justify-center border-2 border-dashed border-gray-200 rounded-lg p-8 cursor-pointer hover:border-gray-400 transition-colors">
        {uploading ? (
          <Loader2 size={24} className="animate-spin text-gray-400" />
        ) : (
          <>
            <Upload size={24} className="text-gray-400 mb-2" />
            <span className="text-sm font-medium text-gray-600">
              {csvFileName || "Click to upload CSV"}
            </span>
            <span className="text-xs text-gray-400 mt-1">Max {MAX_CSV_SIZE_MB}MB</span>
          </>
        )}
        <input
          type="file"
          accept=".csv"
          onChange={onUpload}
          className="hidden"
          aria-label="Upload CSV file"
        />
      </label>

      {/* Parse failed — offer smart import or show format help */}
      {csvError === "PARSE_FAILED" && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-amber-600 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800">
                Couldn't auto-detect the columns in this file.
              </p>
              <p className="text-sm text-amber-700 mt-1">
                Your CSV may use non-standard column names or have multiple contacts per row.
                You have two options:
              </p>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 ml-6">
            <button
              onClick={onSmartImport}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Sparkles size={14} />
              Use AI Smart Import
            </button>
            <button
              onClick={onShowFormatHelp}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-white border border-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              Show expected format
            </button>
          </div>
          <p className="text-xs text-amber-600 ml-6">
            Smart Import uses an LLM (Anthropic, OpenAI, or Gemini) to map any column format. Requires an API key in Settings.
          </p>
        </div>
      )}

      {/* Regular errors (not parse failure) */}
      {csvError && csvError !== "PARSE_FAILED" && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 p-3 rounded-lg">
          <AlertCircle size={16} />
          {csvError}
        </div>
      )}

      {/* Format help panel */}
      {showFormatHelp && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Expected CSV format</h3>
          <p className="text-xs text-gray-600">
            Your CSV should have a header row with columns matching these names (case-insensitive):
          </p>
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1 pr-4 font-medium text-gray-700">Field</th>
                  <th className="text-left py-1 font-medium text-gray-700">Accepted column names</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                <tr><td className="py-1 pr-4 text-gray-600">Name</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">first_name</code>, <code className="bg-gray-100 px-1 rounded">Primary Contact</code>, <code className="bg-gray-100 px-1 rounded">Vorname</code></td></tr>
                <tr><td className="py-1 pr-4 text-gray-600">Last name</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">last_name</code>, <code className="bg-gray-100 px-1 rounded">Last Name</code>, <code className="bg-gray-100 px-1 rounded">Nachname</code></td></tr>
                <tr><td className="py-1 pr-4 text-gray-600">Email</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">email</code>, <code className="bg-gray-100 px-1 rounded">Primary Email</code>, <code className="bg-gray-100 px-1 rounded">E-Mail</code></td></tr>
                <tr><td className="py-1 pr-4 text-gray-600">LinkedIn</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">linkedin_url</code>, <code className="bg-gray-100 px-1 rounded">Primary LinkedIn</code>, <code className="bg-gray-100 px-1 rounded">LinkedIn</code></td></tr>
                <tr><td className="py-1 pr-4 text-gray-600">Company</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">company</code>, <code className="bg-gray-100 px-1 rounded">Firm Name</code>, <code className="bg-gray-100 px-1 rounded">Firma</code></td></tr>
                <tr><td className="py-1 pr-4 text-gray-600">Title</td><td className="py-1"><code className="bg-gray-100 px-1 rounded">title</code>, <code className="bg-gray-100 px-1 rounded">Position</code>, <code className="bg-gray-100 px-1 rounded">Job Title</code></td></tr>
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-500">
            Each row = one contact. Extra columns are ignored. Need multiple contacts per company row?
            Use <button onClick={onSmartImport} className="text-blue-600 hover:underline font-medium">Smart Import</button> instead.
          </p>
        </div>
      )}

      {/* Contact list */}
      {contacts.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">
              {selectedCount} of {contacts.length} selected
            </span>
            <div className="flex gap-2">
              <button
                className="text-xs text-blue-600 hover:underline"
                onClick={() => onToggleAll(true)}
              >
                Select all
              </button>
              <button
                className="text-xs text-gray-500 hover:underline"
                onClick={() => onToggleAll(false)}
              >
                Deselect all
              </button>
            </div>
          </div>
          <div className="border border-gray-200 rounded-lg overflow-hidden max-h-64 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="w-10 px-3 py-2"></th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase">Company</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase">Email</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {contacts.map((c, i) => (
                  <tr
                    key={i}
                    className={`hover:bg-gray-50 cursor-pointer ${c.selected ? "" : "opacity-50"}`}
                    onClick={() => onToggle(i)}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={c.selected}
                        onChange={() => onToggle(i)}
                        className="rounded border-gray-300"
                        aria-label={`Select ${c.first_name} ${c.last_name}`}
                      />
                    </td>
                    <td className="px-3 py-2 font-medium">{c.first_name} {c.last_name}</td>
                    <td className="px-3 py-2 text-gray-500">{c.company}</td>
                    <td className="px-3 py-2 text-gray-500">{c.email}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selectedCount === 0 && (
            <p className="text-xs text-amber-600 mt-2">
              Select at least one contact to continue.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Step 3: Build Sequence ────────────────────────────────────────

/** Single sortable step row in the sequence editor. */
function SortableStep({
  step,
  index,
  totalSteps,
  hasLinkedInConnect,
  onChangeChannel,
  onDelete,
}: {
  step: GeneratedStep;
  index: number;
  totalSteps: number;
  hasLinkedInConnect: boolean;
  onChangeChannel: (channel: string) => void;
  onDelete: () => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step._id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-3 py-2.5 px-2 rounded-lg ${
        isDragging ? "bg-white shadow-md" : "hover:bg-white/60"
      } ${index < totalSteps - 1 ? "border-b border-gray-100" : ""}`}
    >
      {/* Drag handle */}
      <button
        {...attributes}
        {...listeners}
        className="text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing shrink-0"
        tabIndex={-1}
        aria-label="Drag to reorder"
      >
        <GripVertical size={16} />
      </button>

      {/* Day */}
      <span className="text-xs text-gray-400 w-14 shrink-0">
        Day {step.delay_days}
      </span>

      {/* Channel selector */}
      <select
        value={step.channel}
        onChange={(e) => onChangeChannel(e.target.value)}
        className={`text-xs font-medium px-2 py-1 rounded border-0 cursor-pointer ${channelBadgeClass(step.channel)}`}
      >
        {CHANNEL_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Step number */}
      <span className="text-xs text-gray-500 flex-1">
        Step {index + 1}
      </span>

      {/* Delete */}
      {totalSteps > 1 && (
        <button
          onClick={onDelete}
          className="text-gray-300 hover:text-red-500 transition-colors shrink-0"
          title="Remove step"
        >
          <Trash2 size={14} />
        </button>
      )}
    </div>
  );
}

function StepSequence({
  touchpoints,
  setTouchpoints,
  channels,
  toggleChannel,
  steps,
  onStepsChange,
}: {
  touchpoints: number;
  setTouchpoints: (v: number) => void;
  channels: Set<string>;
  toggleChannel: (c: string) => void;
  steps: GeneratedStep[];
  onStepsChange: (steps: GeneratedStep[]) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const hasLinkedInConnect = steps.some((s) => s.channel === "linkedin_connect");

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = steps.findIndex((s) => s._id === active.id);
    const newIndex = steps.findIndex((s) => s._id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(steps, oldIndex, newIndex);
    // Recalculate step_order and delay_days
    onStepsChange(recalcSteps(reordered));
  };

  const handleChangeChannel = (index: number, channel: string) => {
    let updated = [...steps];

    if (channel === "linkedin_connect") {
      const existingIdx = updated.findIndex(
        (s, i) => i !== index && s.channel === "linkedin_connect"
      );
      if (existingIdx !== -1) {
        // Swap the existing linkedin_connect:
        // If new position is BEFORE old → old becomes linkedin_message (connect already happened)
        // If new position is AFTER old → old becomes email (connect hasn't happened yet at that point)
        updated[existingIdx] = {
          ...updated[existingIdx],
          channel: index < existingIdx ? "linkedin_message" : "email",
        };
      }
    }

    updated[index] = { ...updated[index], channel };
    onStepsChange(recalcSteps(updated));
  };

  const handleDelete = (index: number) => {
    const updated = steps.filter((_, i) => i !== index);
    onStepsChange(recalcSteps(updated));
  };

  const handleAdd = () => {
    // Default to email, or linkedin_message if no email channel
    const defaultChannel = channels.has("email") ? "email" : "linkedin_message";
    const lastDelay = steps.length > 0 ? steps[steps.length - 1].delay_days : 0;
    const newStep: GeneratedStep = {
      _id: crypto.randomUUID(),
      step_order: steps.length + 1,
      channel: defaultChannel,
      delay_days: lastDelay + 3,
      template_id: null,
    };
    onStepsChange(recalcSteps([...steps, newStep]));
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Build your sequence</h2>
        <p className="text-sm text-gray-500 mt-1">
          Generate a starting sequence, then drag to reorder and customize.
        </p>
      </div>

      {/* Touchpoint selector */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">Start with a template</h3>
        <div className="grid grid-cols-3 gap-3">
          {TOUCHPOINT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              className={`border-2 rounded-lg p-4 text-center transition-colors ${
                touchpoints === opt.value
                  ? "border-gray-900 bg-gray-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
              onClick={() => setTouchpoints(opt.value)}
            >
              <div className="text-2xl font-bold">{opt.value}</div>
              <div className="text-xs text-gray-500 mt-1">{opt.label}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Channel toggles */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">Which channels?</h3>
        <div className="flex gap-3">
          {[
            { key: "email", label: "Email", icon: Mail },
            { key: "linkedin", label: "LinkedIn", icon: Linkedin },
          ].map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={`flex items-center gap-2 px-4 py-2 rounded-full border-2 text-sm font-medium transition-colors ${
                channels.has(key)
                  ? "border-gray-900 bg-gray-900 text-white"
                  : "border-gray-200 text-gray-500 hover:border-gray-300"
              }`}
              onClick={() => toggleChannel(key)}
            >
              {channels.has(key) && <Check size={14} />}
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Sequence editor */}
      {steps.length > 0 && (
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Sequence &mdash; drag to reorder
          </h4>

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={steps.map((s) => s._id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-0">
                {steps.map((s, i) => (
                  <SortableStep
                    key={s._id}
                    step={s}
                    index={i}
                    totalSteps={steps.length}
                    hasLinkedInConnect={hasLinkedInConnect}
                    onChangeChannel={(ch) => handleChangeChannel(i, ch)}
                    onDelete={() => handleDelete(i)}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>

          {/* Add step button */}
          <button
            onClick={handleAdd}
            className="mt-3 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors w-full justify-center py-2 border border-dashed border-gray-200 rounded-lg hover:border-gray-400"
          >
            <Plus size={14} />
            Add step
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Step 4: Messages ──────────────────────────────────────────────

function isEmailChannel(channel: string): boolean {
  return channel === "email";
}

function StepMessages({
  steps,
  stepTemplates,
  setStepTemplates,
  templateModes,
  setTemplateModes,
  manualSubjects,
  setManualSubjects,
  manualBodies,
  setManualBodies,
  refTemplates,
  setRefTemplates,
}: {
  steps: GeneratedStep[];
  stepTemplates: Record<number, number | null>;
  setStepTemplates: (v: Record<number, number | null>) => void;
  templateModes: Record<number, 'template' | 'manual' | 'ai'>;
  setTemplateModes: (v: Record<number, 'template' | 'manual' | 'ai'>) => void;
  manualSubjects: Record<number, string>;
  setManualSubjects: (v: Record<number, string>) => void;
  manualBodies: Record<number, string>;
  setManualBodies: (v: Record<number, string>) => void;
  refTemplates: Record<number, number | null>;
  setRefTemplates: (v: Record<number, number | null>) => void;
}) {
  const { toast } = useToast();
  const { data: templates = [] } = useQuery<Template[]>({
    queryKey: ["templates"],
    queryFn: () => api.listTemplates(undefined, true),
  });

  const [productDescription, setProductDescription] = useState("");
  const [showSmartInput, setShowSmartInput] = useState(false);
  const [descriptionPrompt, setDescriptionPrompt] = useState("");
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const [improveStep, setImproveStep] = useState<number | null>(null);
  const [improveInstruction, setImproveInstruction] = useState("");
  const [aiModel, setAiModel] = useState<"haiku" | "sonnet" | "opus">("haiku");

  const sequenceMutation = useMutation({
    mutationFn: () =>
      api.generateSequenceMessages({
        steps: steps.map((s) => ({
          step_order: s.step_order,
          channel: s.channel,
          delay_days: s.delay_days,
        })),
        product_description: productDescription,
        model: aiModel,
      }),
    onSuccess: (data) => {
      const messages = data?.messages;
      if (!messages || !Array.isArray(messages) || messages.length === 0) {
        toast("AI returned no messages. Try again or write manually.", "error");
        return;
      }
      const newModes: Record<number, 'template' | 'manual' | 'ai'> = {};
      const newSubjects: Record<number, string> = { ...manualSubjects };
      const newBodies: Record<number, string> = { ...manualBodies };
      for (const msg of messages) {
        newModes[msg.step_order] = "manual";
        if (msg.subject) newSubjects[msg.step_order] = msg.subject;
        if (msg.body) newBodies[msg.step_order] = msg.body;
      }
      setTemplateModes({ ...templateModes, ...newModes });
      setManualSubjects(newSubjects);
      setManualBodies(newBodies);
      toast(`Generated messages for ${messages.length} steps`, "success");
    },
    onError: (err: Error) => {
      toast(`AI generation failed: ${err.message}. Try again or write manually.`, "error");
    },
  });

  const improveMutation = useMutation({
    mutationFn: (params: { stepOrder: number; channel: string; body: string; subject?: string; instruction: string }) =>
      api.improveMessage({
        channel: params.channel,
        body: params.body,
        subject: params.subject,
        instruction: params.instruction,
      }),
    onSuccess: (data, vars) => {
      if (data.subject) {
        setManualSubjects({ ...manualSubjects, [vars.stepOrder]: data.subject });
      }
      setManualBodies({ ...manualBodies, [vars.stepOrder]: data.body });
      setImproveStep(null);
      setImproveInstruction("");
      toast("Message improved", "success");
    },
    onError: () => {
      toast("Failed to improve message. Try again.", "error");
    },
  });

  const getMode = (stepOrder: number) => templateModes[stepOrder] || "template";

  const setMode = (stepOrder: number, mode: 'template' | 'manual' | 'ai') => {
    setTemplateModes({ ...templateModes, [stepOrder]: mode });
  };

  const filteredTemplates = (channel: string) =>
    templates.filter((t) =>
      isEmailChannel(channel) ? t.channel === "email" : t.channel !== "email"
    );

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Choose message templates</h2>
      <p className="text-sm text-gray-500">
        Pick a template, write your own message, or use AI to generate personalized drafts from research data.
      </p>

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
            value={productDescription}
            onChange={(e) => { setProductDescription(e.target.value); setDescriptionPrompt(""); }}
            placeholder="e.g., We run a $200M crypto-native fund focused on DePIN infrastructure. Looking to connect with allocators exploring digital asset exposure..."
            className="w-full h-20 p-3 border border-gray-200 rounded-md text-sm resize-y focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
          />
          <div className="flex items-center gap-2">
            <select
              value={aiModel}
              onChange={(e) => setAiModel(e.target.value as "haiku" | "sonnet" | "opus")}
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
            >
              <option value="haiku">Haiku (fast, $)</option>
              <option value="sonnet">Sonnet (balanced, $$)</option>
              <option value="opus">Opus (best, $$$)</option>
            </select>
            <Button
              variant="primary"
              size="sm"
              onClick={() => sequenceMutation.mutate()}
              loading={sequenceMutation.isPending}
              disabled={productDescription.trim().length < 10}
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
            {productDescription.trim().length > 0 && productDescription.trim().length < 10 && (
              <span className="text-xs text-gray-400">Minimum 10 characters</span>
            )}
          </div>
        </div>
      )}

      <div className="space-y-4">
        {steps.map((s) => {
          const mode = getMode(s.step_order);
          const isEmail = isEmailChannel(s.channel);
          const available = filteredTemplates(s.channel);
          const hasBody = (manualBodies[s.step_order] || "").trim().length > 0;

          return (
            <div
              key={s.step_order}
              className={`p-4 border rounded-lg space-y-3 ${
                sequenceMutation.isPending
                  ? "border-purple-200 bg-purple-50/20"
                  : "border-gray-200"
              }`}
            >
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
                  {CHANNEL_LABELS[s.channel] ?? s.channel}
                </span>
              </div>

              {sequenceMutation.isPending ? (
                <div className="space-y-2 animate-pulse">
                  <div className="h-4 bg-purple-100 rounded w-3/4" />
                  <div className="h-4 bg-purple-100 rounded w-full" />
                  <div className="h-4 bg-purple-100 rounded w-5/6" />
                  <p className="text-xs text-purple-500 font-medium">Generating personalized sequence...</p>
                </div>
              ) : (
                <>
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
                        onChange={() => setMode(s.step_order, "template")}
                        className="text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      />
                      <span className="text-sm font-medium text-gray-700">Select template</span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name={`mode-${s.step_order}`}
                        checked={mode === "manual"}
                        onChange={() => setMode(s.step_order, "manual")}
                        className="text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      />
                      <span className="text-sm font-medium text-gray-700">Write manually</span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name={`mode-${s.step_order}`}
                        checked={mode === "ai"}
                        onChange={() => setMode(s.step_order, "ai")}
                        className="text-purple-600 focus-visible:ring-2 focus-visible:ring-purple-500 focus-visible:ring-offset-2"
                      />
                      <Sparkles size={14} className="text-purple-500" />
                      <span className="text-sm font-medium text-purple-600">AI draft</span>
                    </label>
                  </div>

                  {mode === "template" && (
                    <div>
                      <select
                        value={stepTemplates[s.step_order] ?? ""}
                        onChange={(e) =>
                          setStepTemplates({
                            ...stepTemplates,
                            [s.step_order]: e.target.value ? Number(e.target.value) : null,
                          })
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
                          No {isEmail ? "email" : "LinkedIn"} templates yet -- write manually or use AI.
                        </p>
                      )}
                      {stepTemplates[s.step_order] && (() => {
                        const tpl = templates.find((t) => t.id === stepTemplates[s.step_order]);
                        if (!tpl) return null;
                        return (
                          <div className="bg-gray-50 rounded-md p-3 text-sm text-gray-600 mt-2 whitespace-pre-wrap border border-gray-100 max-h-64 overflow-y-auto">
                            {tpl.subject && <div className="font-medium text-gray-800 mb-2 pb-2 border-b border-gray-200">Subject: {tpl.subject}</div>}
                            {tpl.body_template}
                          </div>
                        );
                      })()}
                    </div>
                  )}

                  {mode === "manual" && (
                    <div className="space-y-2">
                      <p className="text-xs text-gray-400">
                        Variables: <code className="text-purple-600 font-medium">{"{{first_name}}"}</code>, <code className="text-purple-600 font-medium">{"{{company_name}}"}</code>, <code className="text-purple-600 font-medium">{"{{title}}"}</code>
                      </p>
                      {isEmail && (
                        <input
                          type="text"
                          placeholder="Subject line"
                          value={manualSubjects[s.step_order] || ""}
                          onChange={(e) =>
                            setManualSubjects({ ...manualSubjects, [s.step_order]: e.target.value })
                          }
                          className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        />
                      )}
                      <textarea
                        placeholder="Message body..."
                        value={manualBodies[s.step_order] || ""}
                        onChange={(e) =>
                          setManualBodies({ ...manualBodies, [s.step_order]: e.target.value })
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
                                onChange={(e) => setImproveInstruction(e.target.value)}
                                placeholder="What would you like to improve?"
                                className="flex-1 px-3 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && improveInstruction.trim()) {
                                    improveMutation.mutate({
                                      stepOrder: s.step_order,
                                      channel: s.channel,
                                      body: manualBodies[s.step_order],
                                      subject: isEmail ? manualSubjects[s.step_order] : undefined,
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
                                    body: manualBodies[s.step_order],
                                    subject: isEmail ? manualSubjects[s.step_order] : undefined,
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

                  {mode === "ai" && (
                    <div className="space-y-3">
                      {manualBodies[s.step_order] ? (
                        <>
                          <div className="bg-purple-50 rounded-md p-3 text-sm text-gray-700 whitespace-pre-wrap border border-purple-100">
                            {isEmail && manualSubjects[s.step_order] && (
                              <div className="font-medium text-gray-800 mb-2 pb-2 border-b border-purple-200">
                                Subject: {manualSubjects[s.step_order]}
                              </div>
                            )}
                            {manualBodies[s.step_order]}
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setMode(s.step_order, "manual")}
                              className="text-xs text-gray-500 hover:text-gray-700"
                            >
                              Edit manually
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setManualBodies({ ...manualBodies, [s.step_order]: "" });
                                if (isEmail) setManualSubjects({ ...manualSubjects, [s.step_order]: "" });
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
                            AI generates a personalized message for Step {s.step_order} ({isEmail ? "email" : "LinkedIn"}).
                            {s.step_order > 1 && ` Context: the contact has already seen Steps 1–${s.step_order - 1}.`}
                          </p>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              onClick={() => {
                                if (!productDescription.trim()) {
                                  setShowSmartInput(true);
                                  setDescriptionPrompt("Please describe what you\u2019re selling, so AI can prepare your message drafts.");
                                  setTimeout(() => descriptionRef.current?.focus(), 100);
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
                                if (!productDescription.trim()) {
                                  setShowSmartInput(true);
                                  setDescriptionPrompt("Please describe what you\u2019re selling, so AI can prepare research-based drafts.");
                                  setTimeout(() => descriptionRef.current?.focus(), 100);
                                  return;
                                }
                                toast("Research-based generation uses deep research data per company. Set up in Settings \u2192 API Keys if not configured.", "info");
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
                              value={refTemplates[s.step_order] ?? ""}
                              onChange={(e) =>
                                setRefTemplates({
                                  ...refTemplates,
                                  [s.step_order]: e.target.value ? Number(e.target.value) : null,
                                })
                              }
                              className="bg-white border border-gray-200 rounded-md px-3 py-2 text-sm w-full"
                            >
                              <option value="">None</option>
                              {available.map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.name}
                                  {t.variant_label ? ` (${t.variant_label})` : ""}
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

// ─── Step 5: Review & Launch ───────────────────────────────────────

function StepReview({
  name,
  description,
  contactCount,
  steps,
  channels,
}: {
  name: string;
  description: string;
  contactCount: number;
  steps: GeneratedStep[];
  channels: Set<string>;
}) {
  const totalDays = steps.length > 0 ? steps[steps.length - 1].delay_days : 0;
  const channelList = channels instanceof Set ? Array.from(channels) : [];

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Review & Launch</h2>

      <div className="bg-gray-50 rounded-lg p-4 space-y-3">
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Campaign</span>
          <span className="font-medium">{name}</span>
        </div>
        {description && (
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">Description</span>
            <span className="text-gray-700">{description}</span>
          </div>
        )}
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Contacts</span>
          <span className="font-medium">{contactCount}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Steps</span>
          <span className="font-medium">{steps.length} over {totalDays} days</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">Channels</span>
          <span className="font-medium">{channelList.join(", ") || "none"}</span>
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Click "Launch Campaign" to start, or "Save as Draft" to launch later.
      </p>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────

export function parseCsv(text: string): ParsedContact[] {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];

  const headers = splitCsvLine(lines[0]).map((h) => h.trim().toLowerCase().replace(/['"]/g, ""));

  const colMap: Record<string, string[]> = {
    first_name: ["first_name", "first name", "firstname", "first", "primary contact", "contact name", "contact 1"],
    last_name: ["last_name", "last name", "lastname", "last"],
    email: ["email", "email_address", "e-mail", "primary email", "contact email"],
    linkedin_url: ["linkedin_url", "linkedin", "linkedin url", "linkedin_profile", "primary linkedin"],
    company: ["company", "company_name", "organization", "org", "firm name", "firm", "firma", "unternehmen"],
    title: ["title", "job_title", "position", "role", "titel", "funktion"],
  };

  const findCol = (field: string): number => {
    const aliases = colMap[field] || [field];
    return headers.findIndex((h) => aliases.includes(h));
  };

  const indices = {
    first_name: findCol("first_name"),
    last_name: findCol("last_name"),
    email: findCol("email"),
    linkedin_url: findCol("linkedin_url"),
    company: findCol("company"),
    title: findCol("title"),
  };

  const contacts: ParsedContact[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = splitCsvLine(lines[i]);
    if (cols.length < 2) continue;

    const get = (field: keyof typeof indices) =>
      indices[field] >= 0 ? cols[indices[field]] || "" : "";

    const email = get("email");
    const firstName = get("first_name");
    const lastName = get("last_name");

    if (!email && !firstName) continue;

    contacts.push({
      first_name: firstName,
      last_name: lastName,
      email,
      linkedin_url: get("linkedin_url"),
      company: get("company"),
      title: get("title"),
      selected: true,
    });
  }

  return contacts;
}

// Re-export for backwards compatibility (tests import from this module)
export { generateLocalSequence } from "../utils/sequenceUtils";
