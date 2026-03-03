import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

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

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const config = data?.engine_config || {};
  const mergedConfig = { ...config, ...configForm };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure integrations and engine parameters</p>
      </div>

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

      {/* WhatsApp (placeholder) */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">WhatsApp Integration</h2>
        <div className="flex items-center gap-4">
          <div className="w-3 h-3 rounded-full bg-gray-300" />
          <span className="text-sm text-gray-500">
            {data?.whatsapp_status === "not_configured"
              ? "Not configured (Phase 5)"
              : data?.whatsapp_status}
          </span>
        </div>
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
