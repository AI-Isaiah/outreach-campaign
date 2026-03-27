import { useState } from "react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Conversation } from "../../types";
import Button from "../ui/Button";
import Card from "../ui/Card";

const CONVERSATION_CHANNELS = [
  "conference", "phone", "telegram", "whatsapp", "email", "linkedin", "in_person", "video_call",
];

export default function ContactConversations({ contactId, inline }: { contactId: number; inline?: boolean }) {
  const queryClient = useQueryClient();

  const [convForm, setConvForm] = useState({
    channel: "phone",
    title: "",
    notes: "",
    outcome: "" as string,
  });
  const [showConvForm, setShowConvForm] = useState(false);

  const { data: conversations } = useQuery<Conversation[]>({
    queryKey: ["conversations", contactId],
    queryFn: () => api.listConversations(contactId),
    enabled: !!contactId,
  });

  const convMutation = useMutation({
    mutationFn: () =>
      api.createConversation(contactId, {
        channel: convForm.channel,
        title: convForm.title,
        notes: convForm.notes || undefined,
        outcome: convForm.outcome || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations", contactId] });
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", contactId], exact: false });
      setConvForm({ channel: "phone", title: "", notes: "", outcome: "" });
      setShowConvForm(false);
    },
  });

  const deleteConvMutation = useMutation({
    mutationFn: (convId: number) => api.deleteConversation(convId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations", contactId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", contactId], exact: false });
    },
  });

  const Wrapper = inline ? "div" : Card;

  return (
    <Wrapper>
      <div className="flex items-center justify-between mb-4">
        <h2 className={`font-semibold text-gray-900 ${inline ? "text-sm" : ""}`}>Conversations</h2>
        <Button
          variant={showConvForm ? "ghost" : "primary"}
          size="sm"
          onClick={() => setShowConvForm(!showConvForm)}
        >
          {showConvForm ? "Cancel" : "Log Conversation"}
        </Button>
      </div>

      {showConvForm && (
        <div className="mb-4 p-4 bg-gray-50 rounded-lg space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <select
              value={convForm.channel}
              onChange={(e) => setConvForm((f) => ({ ...f, channel: e.target.value }))}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CONVERSATION_CHANNELS.map((ch) => (
                <option key={ch} value={ch}>{ch.replace(/_/g, " ")}</option>
              ))}
            </select>
            <select
              value={convForm.outcome}
              onChange={(e) => setConvForm((f) => ({ ...f, outcome: e.target.value }))}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">No outcome</option>
              <option value="successful">Successful</option>
              <option value="unsuccessful">Unsuccessful</option>
            </select>
          </div>
          <input
            type="text"
            value={convForm.title}
            onChange={(e) => setConvForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Title (e.g. Token2049 sidebar, Intro call)"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <textarea
            value={convForm.notes}
            onChange={(e) => setConvForm((f) => ({ ...f, notes: e.target.value }))}
            placeholder="What was discussed..."
            rows={3}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <Button
            variant="accent"
            size="md"
            onClick={() => convMutation.mutate()}
            disabled={!convForm.title}
            loading={convMutation.isPending}
          >
            Save Conversation
          </Button>
        </div>
      )}

      {(conversations || []).length > 0 ? (
        <div className="space-y-2">
          {conversations!.map((c: Conversation) => (
            <div key={c.id} className="bg-gray-50 rounded-lg p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500 capitalize bg-gray-200 px-2 py-0.5 rounded-full">
                    {c.channel.replace(/_/g, " ")}
                  </span>
                  <span className="text-sm font-medium text-gray-900">{c.title}</span>
                </div>
                <div className="flex items-center gap-2">
                  {c.outcome && (
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      c.outcome === "successful" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}>
                      {c.outcome}
                    </span>
                  )}
                  <span className="text-xs text-gray-400">
                    {new Date(c.occurred_at).toLocaleDateString()}
                  </span>
                  <button
                    onClick={() => deleteConvMutation.mutate(c.id)}
                    className="text-xs text-red-400 hover:text-red-600 font-medium"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {c.notes && <p className="text-sm text-gray-600 mt-1">{c.notes}</p>}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">No conversations logged yet.</p>
      )}
    </Wrapper>
  );
}
