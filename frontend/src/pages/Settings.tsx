import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "../api/client";
import { BASE, authHeaders, request } from "../api/request";

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

export default function Settings() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
  });

  const [configForm, setConfigForm] = useState<Record<string, string>>({});

  const gmailAuth = useMutation({
    mutationFn: api.authorizeGmail,
    onSuccess: (data) => {
      if (data.authorization_url) {
        window.open(data.authorization_url, "_blank");
      }
    },
  });

  const saveConfig = useMutation({
    mutationFn: () => api.updateSettings(configForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setConfigForm({});
    },
  });

  const whatsappSetup = useMutation({
    mutationFn: api.whatsappSetup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const whatsappScan = useMutation({
    mutationFn: api.whatsappScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const config = data?.engine_config || {};
  const mergedConfig = { ...config, ...configForm };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure integrations and engine parameters</p>
      </div>

      {/* API Keys */}
      <ApiKeysCard />

      {/* Gmail */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">Gmail Integration</h2>
        <div className="flex items-center gap-4">
          <div
            className={`w-3 h-3 rounded-full ${
              data?.gmail_authorized ? "bg-green-400" : "bg-red-400"
            }`}
          />
          <span className="text-sm text-gray-700">
            {data?.gmail_authorized ? "Connected" : "Not connected"}
          </span>
          {!data?.gmail_authorized && (
            <button
              onClick={() => gmailAuth.mutate()}
              disabled={gmailAuth.isPending}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {gmailAuth.isPending ? "Connecting..." : "Connect Gmail"}
            </button>
          )}
        </div>
        {gmailAuth.isError && (
          <p className="text-red-500 text-sm">{(gmailAuth.error as Error).message}</p>
        )}
      </div>

      {/* WhatsApp */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">WhatsApp Integration</h2>
        <p className="text-sm text-gray-500">
          Connect WhatsApp Web to capture messages from contacts with phone numbers.
          Requires Playwright to be installed.
        </p>
        <div className="flex items-center gap-4">
          <div
            className={`w-3 h-3 rounded-full ${
              data?.whatsapp_status === "connected" ? "bg-green-400" : "bg-gray-300"
            }`}
          />
          <span className="text-sm text-gray-700">
            {data?.whatsapp_status === "connected"
              ? "Session active"
              : "Not connected"}
          </span>
          <button
            onClick={() => whatsappSetup.mutate()}
            disabled={whatsappSetup.isPending}
            className="px-3 py-1.5 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
          >
            {whatsappSetup.isPending ? "Opening..." : "Setup WhatsApp"}
          </button>
          <button
            onClick={() => whatsappScan.mutate()}
            disabled={whatsappScan.isPending}
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {whatsappScan.isPending ? "Scanning..." : "Scan Messages"}
          </button>
        </div>
        {whatsappSetup.isError && (
          <p className="text-red-500 text-sm">{(whatsappSetup.error as Error).message}</p>
        )}
        {whatsappScan.isError && (
          <p className="text-red-500 text-sm">{(whatsappScan.error as Error).message}</p>
        )}
        {whatsappScan.data && (
          <p className="text-green-600 text-sm">
            Scanned {whatsappScan.data.scanned} contacts, captured {whatsappScan.data.new_messages} new messages
          </p>
        )}
      </div>

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
