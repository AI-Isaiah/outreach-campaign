import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { ExternalLink, Check, ChevronDown, ChevronRight, Mail } from "lucide-react";
import { api } from "../api/client";
import { BASE, authHeaders, request } from "../api/request";
import {
  getEmailConfig,
  saveSmtpConfig,
  saveComplianceConfig,
  disconnectGmail,
} from "../api/settings";
import type { EmailConfig } from "../api/settings";

const apiKeysApi = {
  get: () => request<{
    anthropic_api_key: string;
    perplexity_api_key: string;
    anthropic_configured: boolean;
    perplexity_configured: boolean;
    is_founder: boolean;
  }>("/settings/api-keys"),
  update: (keys: { anthropic_api_key?: string; perplexity_api_key?: string }) =>
    request<{ success: boolean }>("/settings/api-keys", {
      method: "PUT",
      body: JSON.stringify(keys),
    }),
};

/* ── Email Sending Card ─────────────────────────────────────────────── */

function EmailSendingCard({ emailConfig, justConnected }: {
  emailConfig: EmailConfig | undefined;
  justConnected: boolean;
}) {
  const queryClient = useQueryClient();

  const disconnect = useMutation({
    mutationFn: disconnectGmail,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-config"] });
    },
  });

  return (
    <div className="bg-white rounded-lg border p-5 space-y-4">
      <h2 className="text-lg font-semibold text-gray-900">Email Sending</h2>
      <p className="text-sm text-gray-500">
        Connect Gmail to send emails directly, or configure SMTP for another provider.
      </p>

      {/* Gmail connected state */}
      {emailConfig?.gmail_connected && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {justConnected ? (
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center animate-pulse">
                    <Check size={18} className="text-green-600" />
                  </div>
                  <div className="absolute inset-0 rounded-full border-2 border-green-400 animate-ping" />
                </div>
              ) : (
                <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center">
                  <Check size={18} className="text-green-600" />
                </div>
              )}
              <div>
                <span className="text-sm font-medium text-green-800">
                  {justConnected ? "Gmail connected!" : "Gmail connected"}
                </span>
                {emailConfig.gmail_email && (
                  <p className="text-sm text-green-700">{emailConfig.gmail_email}</p>
                )}
              </div>
            </div>
            <button
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
              className="text-sm text-red-600 hover:text-red-700 underline disabled:opacity-50"
            >
              {disconnect.isPending ? "Disconnecting..." : "Disconnect"}
            </button>
          </div>
        </div>
      )}

      {/* Gmail not connected */}
      {!emailConfig?.gmail_connected && (
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center">
            <Mail size={18} className="text-gray-400" />
          </div>
          <div className="flex-1">
            <span className="text-sm text-gray-700">Gmail not connected</span>
            <p className="text-xs text-gray-500">
              Recommended: send emails with your Google account.
            </p>
          </div>
          <a
            href={`${BASE}/auth/gmail/connect`}
            className="bg-gray-900 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-800 inline-flex items-center gap-2"
          >
            Connect Gmail
          </a>
        </div>
      )}

      {disconnect.isError && (
        <p className="text-red-500 text-sm">{(disconnect.error as Error).message}</p>
      )}
    </div>
  );
}

/* ── SMTP Settings Card ─────────────────────────────────────────────── */

function SmtpSettingsCard({ emailConfig }: { emailConfig: EmailConfig | undefined }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState({
    host: "",
    port: "587",
    username: "",
    password: "",
    use_tls: true,
    from_email: "",
    from_name: "",
  });

  // Pre-fill form when config is available
  useEffect(() => {
    if (emailConfig?.smtp_configured) {
      setForm((f) => ({
        ...f,
        host: emailConfig.smtp_host || "",
        from_email: emailConfig.smtp_from_email || "",
        from_name: emailConfig.smtp_from_name || "",
      }));
    }
  }, [emailConfig?.smtp_configured, emailConfig?.smtp_host, emailConfig?.smtp_from_email, emailConfig?.smtp_from_name]);

  const save = useMutation({
    mutationFn: () =>
      saveSmtpConfig({
        ...form,
        port: parseInt(form.port, 10),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-config"] });
      setForm((f) => ({ ...f, password: "" }));
    },
  });

  const updateField = (field: string, value: string | boolean) =>
    setForm((f) => ({ ...f, [field]: value }));

  const inputClass =
    "w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";
  const labelClass = "block text-sm font-medium text-gray-700 mb-1";

  return (
    <div className="bg-white rounded-lg border p-5 space-y-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 font-medium"
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {emailConfig?.smtp_configured ? "SMTP configured" : "Configure SMTP instead"}
        {emailConfig?.smtp_configured && (
          <span className="ml-1 w-2 h-2 rounded-full bg-green-400 inline-block" />
        )}
      </button>

      {expanded && (
        <div className="space-y-4 pt-2">
          <div>
            <label className={labelClass}>SMTP Host</label>
            <input
              type="text"
              value={form.host}
              onChange={(e) => updateField("host", e.target.value)}
              placeholder="smtp.gmail.com"
              className={inputClass}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>Port</label>
              <input
                type="text"
                value={form.port}
                onChange={(e) => updateField("port", e.target.value)}
                placeholder="587"
                className={inputClass}
              />
            </div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.use_tls}
                  onChange={(e) => updateField("use_tls", e.target.checked)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                Use TLS
              </label>
            </div>
          </div>

          <div>
            <label className={labelClass}>Username</label>
            <input
              type="text"
              value={form.username}
              onChange={(e) => updateField("username", e.target.value)}
              placeholder="you@example.com"
              className={inputClass}
            />
          </div>

          <div>
            <label className={labelClass}>Password</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => updateField("password", e.target.value)}
              placeholder={emailConfig?.smtp_configured ? "Leave blank to keep current" : "App password or SMTP password"}
              className={inputClass}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass}>From Email</label>
              <input
                type="email"
                value={form.from_email}
                onChange={(e) => updateField("from_email", e.target.value)}
                placeholder="you@example.com"
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>From Name</label>
              <input
                type="text"
                value={form.from_name}
                onChange={(e) => updateField("from_name", e.target.value)}
                placeholder="Your Name"
                className={inputClass}
              />
            </div>
          </div>

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending || !form.host || !form.from_email}
              className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
            >
              {save.isPending ? "Saving..." : "Save SMTP Settings"}
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="px-4 py-2 text-gray-600 border border-gray-200 rounded-lg text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
            {save.isError && (
              <span className="text-red-500 text-sm self-center">
                {(save.error as Error).message}
              </span>
            )}
            {save.isSuccess && (
              <span className="text-green-600 text-sm self-center">Saved</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Compliance Settings Card ───────────────────────────────────────── */

function ComplianceSettingsCard({ emailConfig }: { emailConfig: EmailConfig | undefined }) {
  const queryClient = useQueryClient();
  const [address, setAddress] = useState("");
  const [calendlyUrl, setCalendlyUrl] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (emailConfig) {
      setAddress(emailConfig.physical_address || "");
      setCalendlyUrl(emailConfig.calendly_url || "");
    }
  }, [emailConfig]);

  const save = useMutation({
    mutationFn: () =>
      saveComplianceConfig({
        physical_address: address,
        calendly_url: calendlyUrl,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-config"] });
      setDirty(false);
    },
  });

  const handleChange = (field: "address" | "calendly", value: string) => {
    if (field === "address") setAddress(value);
    else setCalendlyUrl(value);
    setDirty(true);
  };

  const inputClass =
    "w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent";

  return (
    <div className="bg-white rounded-lg border p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Compliance Settings</h2>
        <p className="text-sm text-gray-500">
          Required for CAN-SPAM compliance. Included in every outbound email.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Physical Address
        </label>
        <textarea
          value={address}
          onChange={(e) => handleChange("address", e.target.value)}
          placeholder="123 Main St, Suite 100&#10;New York, NY 10001"
          rows={3}
          className={inputClass}
        />
        <p className="text-xs text-gray-400 mt-1">
          CAN-SPAM requires a valid physical postal address in every commercial email.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Calendly URL
        </label>
        <input
          type="url"
          value={calendlyUrl}
          onChange={(e) => handleChange("calendly", e.target.value)}
          placeholder="https://calendly.com/you/30min"
          className={inputClass}
        />
        <p className="text-xs text-gray-400 mt-1">
          Injected into email templates as the meeting booking link.
        </p>
      </div>

      {dirty && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
          >
            {save.isPending ? "Saving..." : "Save Compliance Settings"}
          </button>
          <button
            onClick={() => {
              setAddress(emailConfig?.physical_address || "");
              setCalendlyUrl(emailConfig?.calendly_url || "");
              setDirty(false);
            }}
            className="px-4 py-2 text-gray-600 border border-gray-200 rounded-lg text-sm hover:bg-gray-50"
          >
            Reset
          </button>
          {save.isError && (
            <span className="text-red-500 text-sm self-center">
              {(save.error as Error).message}
            </span>
          )}
          {save.isSuccess && (
            <span className="text-green-600 text-sm self-center">Saved</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── API Keys Card ──────────────────────────────────────────────────── */

function ApiKeysCard() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["api-keys"], queryFn: apiKeysApi.get });
  const [anthropic, setAnthropic] = useState("");
  const [perplexity, setPerplexity] = useState("");
  const [editing, setEditing] = useState(false);

  const save = useMutation({
    mutationFn: () => {
      const keys: Record<string, string> = {};
      if (anthropic) keys.anthropic_api_key = anthropic;
      if (perplexity) keys.perplexity_api_key = perplexity;
      return apiKeysApi.update(keys);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setAnthropic("");
      setPerplexity("");
      setEditing(false);
    },
  });

  const keys = [
    {
      id: "anthropic",
      label: "Anthropic (Claude)",
      configured: data?.anthropic_configured,
      masked: data?.anthropic_api_key,
      value: anthropic,
      setValue: setAnthropic,
      placeholder: "sk-ant-...",
      url: "https://console.anthropic.com/settings/keys",
      urlLabel: "Get key from Anthropic Console",
      description: "Used for AI classification in the research pipeline (Claude Haiku).",
    },
    {
      id: "perplexity",
      label: "Perplexity (Sonar)",
      configured: data?.perplexity_configured,
      masked: data?.perplexity_api_key,
      value: perplexity,
      setValue: setPerplexity,
      placeholder: "pplx-...",
      url: "https://docs.perplexity.ai/guides/getting-started",
      urlLabel: "Get key from Perplexity",
      description: "Used for web search to research companies' crypto interest.",
    },
  ];

  return (
    <div className="bg-white rounded-lg border p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-gray-900">API Keys</h2>
          <p className="text-sm text-gray-500">
            Required for the research pipeline. Keys are stored per account.
          </p>
        </div>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            {data?.anthropic_configured && data?.perplexity_configured ? "Update Keys" : "Configure Keys"}
          </button>
        )}
      </div>

      <div className="space-y-3">
        {keys.map((k) => (
          <div key={k.id} className="rounded-lg border border-gray-100 p-3">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${k.configured ? "bg-green-400" : "bg-red-400"}`} />
                <span className="text-sm font-medium text-gray-900">{k.label}</span>
              </div>
              {k.configured && !editing && (
                <span className="text-xs text-gray-400 font-mono">{k.masked}</span>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-2">{k.description}</p>
            {editing && (
              <div className="space-y-2">
                <input
                  type="password"
                  value={k.value}
                  onChange={(e) => k.setValue(e.target.value)}
                  placeholder={k.configured ? "Leave blank to keep current key" : k.placeholder}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <a
                  href={k.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                >
                  <ExternalLink size={12} />
                  {k.urlLabel}
                </a>
              </div>
            )}
          </div>
        ))}
      </div>

      {editing && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || (!anthropic && !perplexity)}
            className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
          >
            {save.isPending ? "Saving..." : "Save Keys"}
          </button>
          <button
            onClick={() => { setEditing(false); setAnthropic(""); setPerplexity(""); }}
            className="px-4 py-2 text-gray-600 border border-gray-200 rounded-lg text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          {save.isError && (
            <span className="text-red-500 text-sm self-center">{(save.error as Error).message}</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Settings Page ──────────────────────────────────────────────────── */

export default function Settings() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const justConnected = searchParams.get("gmail") === "connected";

  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
  });

  const emailConfigQuery = useQuery({
    queryKey: ["email-config"],
    queryFn: getEmailConfig,
  });

  // Clear the ?gmail=connected param after showing the celebration
  useEffect(() => {
    if (justConnected) {
      const timer = setTimeout(() => {
        searchParams.delete("gmail");
        setSearchParams(searchParams, { replace: true });
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [justConnected, searchParams, setSearchParams]);

  const [configForm, setConfigForm] = useState<Record<string, string>>({});

  const saveConfig = useMutation({
    mutationFn: () => api.updateSettings(configForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setConfigForm({});
    },
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const config = data?.engine_config || {};

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure integrations and engine parameters</p>
      </div>

      {/* Email Sending */}
      <EmailSendingCard
        emailConfig={emailConfigQuery.data}
        justConnected={justConnected}
      />

      {/* SMTP Settings */}
      <SmtpSettingsCard emailConfig={emailConfigQuery.data} />

      {/* Compliance Settings */}
      <ComplianceSettingsCard emailConfig={emailConfigQuery.data} />

      {/* API Keys */}
      <ApiKeysCard />

      {/* Engine Config */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">Engine Configuration</h2>
        <p className="text-sm text-gray-500">
          Key-value settings for the adaptive engine.
        </p>

        <div className="space-y-3">
          {[
            { key: "explore_rate", label: "Explore Rate", placeholder: "0.15" },
            { key: "max_daily_emails", label: "Max Daily Emails", placeholder: "10" },
            { key: "default_campaign", label: "Default Campaign", placeholder: "Q1_2026_initial" },
          ].map(({ key, label, placeholder }) => (
            <div key={key} className="flex items-center gap-3">
              <label className="text-sm text-gray-700 w-40">{label}</label>
              <input
                value={configForm[key] ?? config[key] ?? ""}
                onChange={(e) =>
                  setConfigForm((f) => ({ ...f, [key]: e.target.value }))
                }
                placeholder={placeholder}
                className="flex-1 px-3 py-1.5 border rounded-md text-sm"
              />
            </div>
          ))}
        </div>

        {Object.keys(configForm).length > 0 && (
          <div className="flex gap-2 pt-2">
            <button
              onClick={() => saveConfig.mutate()}
              disabled={saveConfig.isPending}
              className="px-4 py-2 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800 disabled:opacity-50"
            >
              {saveConfig.isPending ? "Saving..." : "Save Settings"}
            </button>
            <button
              onClick={() => setConfigForm({})}
              className="px-4 py-2 text-gray-600 border rounded-md text-sm hover:bg-gray-50"
            >
              Reset
            </button>
          </div>
        )}

        {/* Show all stored config values */}
        {Object.keys(config).length > 0 && (
          <div className="mt-4 pt-4 border-t">
            <h3 className="text-xs font-medium text-gray-500 uppercase mb-2">All Stored Config</h3>
            <div className="space-y-1">
              {Object.entries(config).map(([k, v]) => (
                <div key={k} className="flex justify-between text-sm">
                  <span className="text-gray-500 font-mono">{k}</span>
                  <span className="text-gray-700">{v as string}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
