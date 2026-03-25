import { useState, useCallback, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Product, NewsletterAttachment } from "../types";
import RichTextEditor from "../components/RichTextEditor";
import StatusBadge from "../components/StatusBadge";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { LIFECYCLE_STAGES } from "../constants";

const LIFECYCLE_OPTIONS = LIFECYCLE_STAGES.map((s) => ({
  value: s,
  label: s.charAt(0).toUpperCase() + s.slice(1),
}));

export default function NewsletterComposer() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();
  const isNew = !id || id === "new";
  const [showSendConfirm, setShowSendConfirm] = useState(false);

  const [subject, setSubject] = useState("");
  const [bodyHtml, setBodyHtml] = useState("<p>Write your newsletter here...</p>");
  const [newsletterId, setNewsletterId] = useState<number | null>(isNew ? null : Number(id));
  const [selectedStages, setSelectedStages] = useState<string[]>([]);
  const [selectedProducts, setSelectedProducts] = useState<number[]>([]);
  const [newsletterOnly, setNewsletterOnly] = useState(true);
  const [showPreview, setShowPreview] = useState(false);

  // Load existing newsletter
  const { data: existing } = useQuery({
    queryKey: ["newsletter", newsletterId],
    queryFn: () => api.getNewsletter(newsletterId!),
    enabled: !!newsletterId && !isNew,
  });

  // Populate form from loaded data
  useState(() => {
    if (existing?.newsletter) {
      setSubject(existing.newsletter.subject);
      setBodyHtml(existing.newsletter.body_html);
    }
  });

  // Products for filter
  const { data: products } = useQuery<Product[]>({
    queryKey: ["products"],
    queryFn: () => api.listProducts(),
  });

  // Recipient preview
  const { data: recipientData, refetch: refetchRecipients } = useQuery({
    queryKey: ["recipients-preview", newsletterId, selectedStages, selectedProducts, newsletterOnly],
    queryFn: () =>
      api.previewRecipients(newsletterId!, {
        lifecycle_stages: selectedStages.length ? selectedStages : undefined,
        product_ids: selectedProducts.length ? selectedProducts : undefined,
        newsletter_only: newsletterOnly,
      }),
    enabled: !!newsletterId,
  });

  // Save draft
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (newsletterId) {
        await api.updateNewsletter(newsletterId, { subject, body_html: bodyHtml });
        return newsletterId;
      } else {
        const res = await api.createNewsletter({ subject, body_html: bodyHtml });
        return res.id;
      }
    },
    onSuccess: (id) => {
      setNewsletterId(id);
      queryClient.invalidateQueries({ queryKey: ["newsletters"] });
      queryClient.invalidateQueries({ queryKey: ["newsletter", id] });
      if (isNew) navigate(`/newsletters/${id}`, { replace: true });
    },
  });

  // Upload attachment
  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadNewsletterAttachment(newsletterId!, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["newsletter", newsletterId] });
    },
  });

  // Delete attachment
  const deleteAttMutation = useMutation({
    mutationFn: (attachmentId: number) => api.deleteNewsletterAttachment(newsletterId!, attachmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["newsletter", newsletterId] });
    },
  });

  // Send
  const sendMutation = useMutation<{ sent: number; failed: number; total: number }>({
    mutationFn: () =>
      api.sendNewsletter(newsletterId!, {
        lifecycle_stages: selectedStages.length ? selectedStages : undefined,
        product_ids: selectedProducts.length ? selectedProducts : undefined,
        newsletter_only: newsletterOnly,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["newsletters"] });
      queryClient.invalidateQueries({ queryKey: ["newsletter", newsletterId] });
      toast(`Sent to ${data.sent} recipients (${data.failed} failed)`, data.failed > 0 ? "error" : "success");
    },
    onError: (err: Error) => {
      toast(err.message, "error");
    },
  });

  const handleSendClick = () => {
    setShowSendConfirm(true);
  };

  const handleSendConfirm = () => {
    setShowSendConfirm(false);
    sendMutation.mutate();
  };

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) uploadMutation.mutate(file);
      e.target.value = "";
    },
    [uploadMutation],
  );

  const toggleStage = (stage: string) => {
    setSelectedStages((s) =>
      s.includes(stage) ? s.filter((x) => x !== stage) : [...s, stage],
    );
  };

  const toggleProduct = (pid: number) => {
    setSelectedProducts((s) =>
      s.includes(pid) ? s.filter((x) => x !== pid) : [...s, pid],
    );
  };

  const isSent = existing?.newsletter?.status === "sent" || existing?.newsletter?.status === "sending";
  const attachments: NewsletterAttachment[] = existing?.attachments || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate("/newsletters")}
            className="text-sm text-gray-400 hover:text-gray-600"
          >
            &larr; Newsletters
          </button>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">
            {isNew ? "Compose Newsletter" : `Edit: ${existing?.newsletter?.subject || "..."}`}
          </h1>
        </div>
        <div className="flex gap-2">
          {!isSent && (
            <>
              <button
                onClick={() => saveMutation.mutate()}
                disabled={!subject || saveMutation.isPending}
                className="px-4 py-2 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
              >
                {saveMutation.isPending ? "Saving..." : "Save Draft"}
              </button>
              {newsletterId && (
                <button
                  onClick={handleSendClick}
                  disabled={sendMutation.isPending || !recipientData?.count}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                >
                  {sendMutation.isPending ? "Sending..." : `Send to ${recipientData?.count || 0} Recipients`}
                </button>
              )}
            </>
          )}
          {isSent && <StatusBadge status="sent" />}
        </div>
      </div>

      {sendMutation.isSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
          Newsletter sent: {sendMutation.data?.sent} delivered, {sendMutation.data?.failed} failed
        </div>
      )}
      {sendMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800">
          {(sendMutation.error as Error).message}
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Editor — 2/3 width */}
        <div className="col-span-2 space-y-4">
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Newsletter subject..."
            disabled={isSent}
            className="w-full px-4 py-3 border border-gray-200 rounded-lg text-lg font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <RichTextEditor content={bodyHtml} onChange={setBodyHtml} />

          {newsletterId && (
            <button
              type="button"
              onClick={() => setShowPreview(!showPreview)}
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              {showPreview ? "Hide Preview" : "Preview HTML"}
            </button>
          )}

          {showPreview && (
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <div dangerouslySetInnerHTML={{ __html: bodyHtml }} />
            </div>
          )}
        </div>

        {/* Sidebar — 1/3 width */}
        <div className="space-y-4">
          {/* Recipients filter */}
          <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
            <h3 className="font-semibold text-gray-900 text-sm">Recipients</h3>

            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase mb-2">
                Lifecycle Stage
              </label>
              <div className="space-y-1">
                {LIFECYCLE_OPTIONS.map((o) => (
                  <label key={o.value} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedStages.includes(o.value)}
                      onChange={() => toggleStage(o.value)}
                      className="rounded border-gray-300"
                    />
                    {o.label}
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase mb-2">
                Product Interest
              </label>
              <div className="space-y-1">
                {(products || []).map((p) => (
                  <label key={p.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedProducts.includes(p.id)}
                      onChange={() => toggleProduct(p.id)}
                      className="rounded border-gray-300"
                    />
                    {p.name}
                  </label>
                ))}
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={newsletterOnly}
                onChange={(e) => setNewsletterOnly(e.target.checked)}
                className="rounded border-gray-300"
              />
              Newsletter subscribers only
            </label>

            <div className="pt-2 border-t border-gray-100">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Matching recipients</span>
                <span className="text-lg font-bold text-gray-900">
                  {recipientData?.count ?? "-"}
                </span>
              </div>
              {newsletterId && (
                <button
                  type="button"
                  onClick={() => refetchRecipients()}
                  className="mt-2 text-xs text-blue-600 hover:text-blue-800"
                >
                  Refresh count
                </button>
              )}
            </div>
          </div>

          {/* Attachments */}
          {newsletterId && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
              <h3 className="font-semibold text-gray-900 text-sm">PDF Attachments</h3>

              {attachments.map((att) => (
                <div key={att.id} className="flex items-center justify-between bg-gray-50 rounded-md px-3 py-2">
                  <div className="text-sm text-gray-700 truncate">{att.filename}</div>
                  <div className="flex items-center gap-2">
                    {att.file_size_bytes && (
                      <span className="text-xs text-gray-400">
                        {(att.file_size_bytes / 1024).toFixed(0)}KB
                      </span>
                    )}
                    {!isSent && (
                      <button
                        onClick={() => deleteAttMutation.mutate(att.id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {!isSent && (
                <>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploadMutation.isPending}
                    className="w-full px-3 py-2 border-2 border-dashed border-gray-200 rounded-lg text-sm text-gray-500 hover:border-gray-300 hover:text-gray-600 transition-colors"
                  >
                    {uploadMutation.isPending ? "Uploading..." : "Upload PDF"}
                  </button>
                </>
              )}

              {uploadMutation.isError && (
                <p className="text-xs text-red-600">
                  {(uploadMutation.error as Error).message}
                </p>
              )}
            </div>
          )}

          {/* Send stats */}
          {existing?.send_stats && Object.keys(existing.send_stats).length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-2">
              <h3 className="font-semibold text-gray-900 text-sm">Send Stats</h3>
              {Object.entries(existing.send_stats).map(([status, count]) => (
                <div key={status} className="flex justify-between text-sm">
                  <span className="text-gray-500 capitalize">{status}</span>
                  <span className="font-medium">{count as number}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={showSendConfirm}
        title="Send Newsletter?"
        message={`You're about to send "${subject || "Untitled"}" to ${recipientData?.count || 0} recipients.${attachments.length > 0 ? ` Includes ${attachments.length} attachment${attachments.length !== 1 ? "s" : ""}.` : ""}\n\nThis cannot be undone.`}
        confirmLabel="Send Now"
        cancelLabel="Cancel"
        variant="default"
        onConfirm={handleSendConfirm}
        onCancel={() => setShowSendConfirm(false)}
      />
    </div>
  );
}
