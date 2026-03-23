import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Upload,
  Check,
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
} from "lucide-react";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";
import { campaignsApi } from "../api/campaigns";
import type { GeneratedStep } from "../api/campaigns";
import { useToast } from "../components/Toast";
import { splitCsvLine } from "../utils/parseCsv";

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
  const { toast } = useToast();
  const [step, setStep] = useState(0);
  const [showLeaveDialog, setShowLeaveDialog] = useState(false);

  // Step 1: Name
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // Step 2: Contacts
  const [contacts, setContacts] = useState<ParsedContact[]>([]);
  const [csvError, setCsvError] = useState("");
  const [csvFileName, setCsvFileName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [showFormatHelp, setShowFormatHelp] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  // Step 3: Sequence
  const [touchpoints, setTouchpoints] = useState(5);
  const [channels, setChannels] = useState<Set<string>>(new Set(["email", "linkedin"]));
  const [generatedSteps, setGeneratedSteps] = useState<GeneratedStep[]>([]);

  // Step 4: Messages (template_id per step — null means "pick later")
  const [stepTemplates, setStepTemplates] = useState<Record<number, number | null>>({});

  // Launch mutation
  const launchMutation = useMutation({
    mutationFn: (data: { status: "active" | "draft" }) =>
      campaignsApi.launchCampaign({
        name,
        description,
        steps: generatedSteps.map((s) => ({
          ...s,
          template_id: stepTemplates[s.step_order] ?? null,
        })),
        contact_ids: selectedContactIds,
        status: data.status,
      }),
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
  const selectedContactIds = selectedContacts
    .filter((c) => c.id != null)
    .map((c) => c.id!);

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
      case 1: return selectedContacts.length > 0;
      case 2: return generatedSteps.length > 0;
      case 3: return true; // templates are optional
      case 4: return true;
      default: return false;
    }
  }, [step, name, selectedContacts.length, generatedSteps.length]);

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
                window.open("/import/smart", "_blank");
              }
            }}
          />
        )}
        {step === 2 && (
          <StepSequence
            touchpoints={touchpoints}
            setTouchpoints={setTouchpoints}
            channels={channels}
            toggleChannel={toggleChannel}
            steps={generatedSteps}
          />
        )}
        {step === 3 && (
          <StepMessages
            steps={generatedSteps}
            stepTemplates={stepTemplates}
            setStepTemplates={setStepTemplates}
          />
        )}
        {step === 4 && (
          <StepReview
            name={name}
            description={description}
            contactCount={selectedContacts.length}
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
      <h2 className="text-lg font-semibold">Add contacts</h2>
      <p className="text-sm text-gray-500">
        Upload a CSV file with your contacts. We'll try to auto-detect the columns.
      </p>

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

const TOUCHPOINT_OPTIONS = [
  { value: 3, label: "Quick", desc: "3 touchpoints" },
  { value: 5, label: "Standard", desc: "5 touchpoints" },
  { value: 7, label: "Thorough", desc: "7 touchpoints" },
];

function StepSequence({
  touchpoints,
  setTouchpoints,
  channels,
  toggleChannel,
  steps,
}: {
  touchpoints: number;
  setTouchpoints: (v: number) => void;
  channels: Set<string>;
  toggleChannel: (c: string) => void;
  steps: GeneratedStep[];
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Build your sequence</h2>
        <p className="text-sm text-gray-500 mt-1">
          We'll generate a sequence with optimal spacing. You can adjust after.
        </p>
      </div>

      {/* Touchpoint selector */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">How many touchpoints?</h3>
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

      {/* Generated sequence preview */}
      {steps.length > 0 && (
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Generated Sequence
          </h4>
          <div className="space-y-0">
            {steps.map((s, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 py-2 ${
                  i < steps.length - 1 ? "border-b border-gray-100" : ""
                }`}
              >
                <span className="text-xs text-gray-400 w-14 shrink-0">
                  Day {s.delay_days}
                </span>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded ${
                    s.channel === "email"
                      ? "bg-blue-100 text-blue-700"
                      : "bg-indigo-100 text-indigo-700"
                  }`}
                >
                  {s.channel === "email" ? "Email" : s.channel === "linkedin_connect" ? "LinkedIn Connect" : "LinkedIn Message"}
                </span>
                <span className="text-xs text-gray-500">
                  Step {s.step_order}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Step 4: Messages ──────────────────────────────────────────────

function StepMessages({
  steps,
  stepTemplates,
  setStepTemplates,
}: {
  steps: GeneratedStep[];
  stepTemplates: Record<number, number | null>;
  setStepTemplates: (v: Record<number, number | null>) => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Choose message templates</h2>
      <p className="text-sm text-gray-500">
        Pick a template for each step, or leave blank to choose later from the campaign dashboard.
      </p>

      <div className="space-y-3">
        {steps.map((s) => (
          <div
            key={s.step_order}
            className="flex items-center gap-4 p-3 border border-gray-200 rounded-lg"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs text-gray-400 shrink-0">Day {s.delay_days}</span>
              <span
                className={`text-xs font-medium px-2 py-0.5 rounded shrink-0 ${
                  s.channel === "email"
                    ? "bg-blue-100 text-blue-700"
                    : "bg-indigo-100 text-indigo-700"
                }`}
              >
                {s.channel === "email" ? "Email" : "LinkedIn"}
              </span>
            </div>
            <div className="flex-1 flex items-center gap-2">
              <FileText size={14} className="text-gray-400 shrink-0" />
              <span className="text-sm text-gray-500">
                {stepTemplates[s.step_order]
                  ? `Template #${stepTemplates[s.step_order]}`
                  : "No template selected"}
              </span>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-400">
        Templates can be assigned later from the campaign's Sequence tab.
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
          <span className="font-medium">{Array.from(channels).join(", ")}</span>
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

export function generateLocalSequence(touchpoints: number, channels: string[]): GeneratedStep[] {
  const steps: GeneratedStep[] = [];
  const hasEmail = channels.includes("email");
  const hasLinkedin = channels.includes("linkedin");
  const isSingleChannel = channels.length === 1;

  let linkedinToggle = false; // alternates between connect and message

  for (let i = 0; i < touchpoints; i++) {
    let channel: string;
    let delay: number;

    if (isSingleChannel) {
      channel = channels[0] === "linkedin"
        ? (!linkedinToggle ? "linkedin_connect" : "linkedin_message")
        : channels[0];
      // Increasing gaps for single channel
      if (i === 0) delay = 0;
      else if (i <= 2) delay = steps[i - 1].delay_days + 3 + i;
      else delay = steps[i - 1].delay_days + 4 + i;

      if (channels[0] === "linkedin") linkedinToggle = !linkedinToggle;
    } else {
      // Alternate email and linkedin
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
