import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import { Upload, FileText, CheckCircle, AlertCircle } from "lucide-react";

type Step = "upload" | "preview" | "import";

interface ParsedCsv {
  headers: string[];
  rows: string[][];
}

function parseCsvPreview(text: string): ParsedCsv {
  const lines = text.trim().split("\n");
  if (lines.length === 0) return { headers: [], rows: [] };

  const splitLine = (line: string): string[] => {
    const result: string[] = [];
    let current = "";
    let inQuotes = false;
    for (const char of line) {
      if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === "," && !inQuotes) {
        result.push(current.trim());
        current = "";
      } else {
        current += char;
      }
    }
    result.push(current.trim());
    return result;
  };

  const headers = splitLine(lines[0]);
  const rows = lines.slice(1, 6).map(splitLine);

  return { headers, rows };
}

export default function ImportWizard() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ParsedCsv | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const importMutation = useMutation({
    mutationFn: (f: File) => api.importCsv(f),
    onSuccess: (data) => {
      toast(`Imported ${data.imported} contacts`, "success");
      setStep("import");
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const handleFile = useCallback((f: File) => {
    if (!f.name.endsWith(".csv")) {
      toast("Please select a CSV file", "error");
      return;
    }
    setFile(f);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      const parsed = parseCsvPreview(text);
      setPreview(parsed);
      setStep("preview");
    };
    reader.readAsText(f);
  }, [toast]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) handleFile(f);
      e.target.value = "";
    },
    [handleFile],
  );

  const handleImport = () => {
    if (file) importMutation.mutate(file);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <button
          onClick={() => navigate("/contacts")}
          className="text-sm text-gray-400 hover:text-gray-600"
        >
          &larr; Contacts
        </button>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">Import Contacts</h1>
        <p className="text-gray-500 mt-1">Upload a CSV file to import contacts</p>
      </div>

      {/* Steps indicator */}
      <div className="flex items-center gap-4 text-sm">
        {(["upload", "preview", "import"] as Step[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <span
              className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                step === s
                  ? "bg-gray-900 text-white"
                  : i < (["upload", "preview", "import"] as Step[]).indexOf(step)
                    ? "bg-green-600 text-white"
                    : "bg-gray-200 text-gray-500"
              }`}
            >
              {i + 1}
            </span>
            <span className={step === s ? "font-medium text-gray-900" : "text-gray-500"}>
              {s === "upload" ? "Upload" : s === "preview" ? "Preview" : "Results"}
            </span>
            {i < 2 && <span className="text-gray-300 mx-1">/</span>}
          </div>
        ))}
      </div>

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
            dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white"
          }`}
        >
          <Upload className="mx-auto text-gray-300 mb-4" size={48} />
          <p className="text-gray-600 font-medium mb-1">
            Drag and drop your CSV file here
          </p>
          <p className="text-sm text-gray-400 mb-4">or click to browse</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleInputChange}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
          >
            Choose File
          </button>
        </div>
      )}

      {/* Step 2: Preview */}
      {step === "preview" && preview && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 text-sm text-gray-600">
            <FileText size={16} className="text-gray-400" />
            <span>{file?.name}</span>
            <span className="text-gray-400">
              ({preview.rows.length} row{preview.rows.length !== 1 ? "s" : ""} shown)
            </span>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {preview.headers.map((h, i) => (
                    <th
                      key={i}
                      className="text-left px-4 py-2 text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {preview.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">
                        {cell || "-"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleImport}
              disabled={importMutation.isPending}
              className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors"
            >
              {importMutation.isPending ? "Importing..." : "Start Import"}
            </button>
            <button
              onClick={() => { setStep("upload"); setFile(null); setPreview(null); }}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Choose Different File
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Results */}
      {step === "import" && importMutation.data && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
          <div className="flex items-center gap-3 text-green-600">
            <CheckCircle size={24} />
            <h3 className="text-lg font-semibold">Import Complete</h3>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{importMutation.data.imported}</p>
              <p className="text-sm text-green-600">Imported</p>
            </div>
            <div className="bg-yellow-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-yellow-700">{importMutation.data.skipped}</p>
              <p className="text-sm text-yellow-600">Skipped (duplicates)</p>
            </div>
            <div className="bg-red-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-red-700">{importMutation.data.errors.length}</p>
              <p className="text-sm text-red-600">Errors</p>
            </div>
          </div>

          {importMutation.data.errors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <h4 className="text-sm font-medium text-red-800 mb-2">Errors</h4>
              <ul className="text-sm text-red-700 space-y-1 list-disc list-inside">
                {importMutation.data.errors.slice(0, 10).map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
                {importMutation.data.errors.length > 10 && (
                  <li className="text-red-500">
                    ...and {importMutation.data.errors.length - 10} more
                  </li>
                )}
              </ul>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              onClick={() => navigate("/contacts")}
              className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
            >
              View Contacts
            </button>
            <button
              onClick={() => { setStep("upload"); setFile(null); setPreview(null); importMutation.reset(); }}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Import More
            </button>
          </div>
        </div>
      )}

      {/* Import Error */}
      {step === "preview" && importMutation.isError && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg p-4">
          <AlertCircle size={20} className="text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800">Import Failed</p>
            <p className="text-sm text-red-700 mt-1">{(importMutation.error as Error).message}</p>
          </div>
        </div>
      )}
    </div>
  );
}
