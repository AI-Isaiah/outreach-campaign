import { useState, useCallback, useMemo } from "react";
import { useFormContext } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { CheckCircle, Upload, AlertCircle, Loader2, Sparkles } from "lucide-react";
import CrmContactPicker from "../components/CrmContactPicker";
import type { WizardFormData, ParsedContact } from "../schemas/campaignSchema";
import { splitCsvLine } from "../../../utils/parseCsv";

const MAX_CSV_SIZE_MB = 5;
const MAX_CSV_SIZE_BYTES = MAX_CSV_SIZE_MB * 1024 * 1024;

export default function StepContacts() {
  const navigate = useNavigate();
  const { setValue, watch, formState: { errors } } = useFormContext<WizardFormData>();
  const contactSource = watch("contactSource");
  const crmSelectedIds = watch("crmSelectedIds");
  const csvContacts = watch("csvContacts");

  // CSV-related UI state (not in form — ephemeral)
  const [csvError, setCsvError] = useState("");
  const [csvFileName, setCsvFileName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [showFormatHelp, setShowFormatHelp] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  // Bridge: form stores number[], CrmContactPicker uses Set<number>
  const selectedIdsSet = useMemo(() => new Set(crmSelectedIds), [crmSelectedIds]);
  const handleCrmSelectionChange = useCallback((ids: Set<number>) => {
    setValue("crmSelectedIds", Array.from(ids), { shouldDirty: true });
  }, [setValue]);

  const handleTabChange = useCallback((tab: "crm" | "csv") => {
    setValue("contactSource", tab, { shouldDirty: true });
  }, [setValue]);

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
          setPendingFile(file);
          setCsvError("PARSE_FAILED");
        } else {
          setValue("csvContacts", parsed, { shouldDirty: true });
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
  }, [setValue]);

  const toggleCsvContact = useCallback((index: number) => {
    const updated = csvContacts.map((c, i) =>
      i === index ? { ...c, selected: !c.selected } : c
    );
    setValue("csvContacts", updated, { shouldDirty: true });
  }, [csvContacts, setValue]);

  const toggleAllCsv = useCallback((selected: boolean) => {
    const updated = csvContacts.map((c) => ({ ...c, selected }));
    setValue("csvContacts", updated, { shouldDirty: true });
  }, [csvContacts, setValue]);

  const contactError = errors.crmSelectedIds?.message || errors.csvContacts?.message;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Add contacts</h2>
      <p className="text-sm text-gray-500">
        Pick contacts from your CRM or upload a CSV file.
      </p>

      {/* Tab group */}
      <div className="flex border-b border-gray-200">
        <button
          className={`px-4 py-2.5 text-sm font-medium ${
            contactSource === "crm"
              ? "text-gray-900 border-b-2 border-gray-900"
              : "text-gray-500 hover:text-gray-700"
          }`}
          onClick={() => handleTabChange("crm")}
        >
          From CRM
        </button>
        <button
          className={`px-4 py-2.5 text-sm font-medium ${
            contactSource === "csv"
              ? "text-gray-900 border-b-2 border-gray-900"
              : "text-gray-500 hover:text-gray-700"
          }`}
          onClick={() => handleTabChange("csv")}
        >
          Upload CSV
        </button>
      </div>

      {contactSource === "crm" ? (
        <CrmContactPicker
          selectedIds={selectedIdsSet}
          onSelectionChange={handleCrmSelectionChange}
        />
      ) : (
        <CsvUploadTab
          contacts={csvContacts}
          csvError={csvError}
          csvFileName={csvFileName}
          uploading={uploading}
          showFormatHelp={showFormatHelp}
          pendingFile={pendingFile}
          onUpload={handleCsvUpload}
          onToggle={toggleCsvContact}
          onToggleAll={toggleAllCsv}
          onShowFormatHelp={() => setShowFormatHelp(true)}
          onSmartImport={() => {
            if (pendingFile) {
              navigate("/import/smart", { state: { file: pendingFile } });
            }
          }}
        />
      )}

      {contactError && (
        <p className="text-sm text-red-600 mt-1">{contactError}</p>
      )}
    </div>
  );
}

// ─── CSV Upload Tab (local component, not extracted — tightly coupled to wizard) ───

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
      <label className="flex flex-col items-center justify-center border-2 border-dashed border-gray-200 rounded-lg p-8 cursor-pointer hover:border-gray-400 transition-colors">
        {uploading ? (
          <Loader2 size={24} className="animate-spin text-gray-400" />
        ) : (
          <>
            <Upload size={24} className="text-gray-400 mb-2" />
            <span className="text-sm font-medium text-gray-600">
              {csvFileName || "Drop CSV or click to upload"}
            </span>
            <span className="text-xs text-gray-400 mt-1">Max {MAX_CSV_SIZE_MB}MB</span>
          </>
        )}
        <input type="file" accept=".csv" onChange={onUpload} className="hidden" aria-label="Upload CSV file" />
      </label>

      {csvError === "PARSE_FAILED" && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-amber-600 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800">Couldn't auto-detect the columns in this file.</p>
              <p className="text-sm text-amber-700 mt-1">Your CSV may use non-standard column names or have multiple contacts per row.</p>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 ml-6">
            <button onClick={onSmartImport} className="inline-flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
              <Sparkles size={14} /> Use AI Smart Import
            </button>
            <button onClick={onShowFormatHelp} className="inline-flex items-center gap-1.5 px-3 py-2 bg-white border border-gray-200 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
              Show expected format
            </button>
          </div>
        </div>
      )}

      {csvError && csvError !== "PARSE_FAILED" && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 p-3 rounded-lg">
          <AlertCircle size={16} /> {csvError}
        </div>
      )}

      {showFormatHelp && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Expected CSV format</h3>
          <p className="text-xs text-gray-600">Header row with columns: first_name, last_name, email, linkedin_url, company, title (case-insensitive).</p>
        </div>
      )}

      {contacts.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">{selectedCount} of {contacts.length} selected</span>
            <div className="flex gap-2">
              <button className="text-xs text-blue-600 hover:underline" onClick={() => onToggleAll(true)}>Select all</button>
              <button className="text-xs text-gray-500 hover:underline" onClick={() => onToggleAll(false)}>Deselect all</button>
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
                  <tr key={i} className={`hover:bg-gray-50 cursor-pointer ${c.selected ? "" : "opacity-50"}`} onClick={() => onToggle(i)}>
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={c.selected} onChange={() => onToggle(i)} className="rounded border-gray-300" aria-label={`Select ${c.first_name} ${c.last_name}`} />
                    </td>
                    <td className="px-3 py-2 font-medium">{c.first_name} {c.last_name}</td>
                    <td className="px-3 py-2 text-gray-500">{c.company}</td>
                    <td className="px-3 py-2 text-gray-500">{c.email}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── CSV Parser (migrated from monolith) ───

function parseCsv(text: string): ParsedContact[] {
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

  const hasAnyColumn = Object.values(indices).some((i) => i >= 0);
  if (!hasAnyColumn) return [];

  const contacts: ParsedContact[] = [];
  for (let row = 1; row < lines.length; row++) {
    const cols = splitCsvLine(lines[row]);
    if (cols.length === 0 || cols.every((c) => !c.trim())) continue;

    const get = (field: keyof typeof indices) => {
      const idx = indices[field];
      return idx >= 0 ? (cols[idx] || "").trim().replace(/^['"]|['"]$/g, "") : "";
    };

    contacts.push({
      first_name: get("first_name"),
      last_name: get("last_name"),
      email: get("email"),
      linkedin_url: get("linkedin_url"),
      company: get("company"),
      title: get("title"),
      selected: true,
    });
  }

  return contacts;
}
