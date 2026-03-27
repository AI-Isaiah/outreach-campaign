import { useState, useMemo } from "react";
import { CheckCircle, AlertTriangle, RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import Modal from "./ui/Modal";
import type { QueueItem, BatchBatchValidationErrors } from "../types";

interface ReviewGateModalProps {
  open: boolean;
  onClose: () => void;
  selectedItems: QueueItem[];
  onConfirmSend: (force: boolean) => void;
  validationErrors: BatchValidationErrors | null;
  isConfirming: boolean;
  scheduleMode?: string | null;
}

function ReviewGateModal({
  open,
  onClose,
  selectedItems,
  onConfirmSend,
  validationErrors,
  isConfirming,
  scheduleMode,
}: ReviewGateModalProps) {
  const [sampleSeed, setSampleSeed] = useState(Date.now());
  const [expandedSamples, setExpandedSamples] = useState<Set<number>>(new Set());
  const [showAllEmails, setShowAllEmails] = useState(false);

  const emailItems = useMemo(
    () => selectedItems.filter((i) => i.channel === "email"),
    [selectedItems],
  );
  const linkedinItems = useMemo(
    () => selectedItems.filter((i) => i.channel?.startsWith("linkedin")),
    [selectedItems],
  );
  const uniqueCompanies = useMemo(
    () => new Set(selectedItems.map((i) => i.company_id)).size,
    [selectedItems],
  );
  const gdprCount = useMemo(
    () => selectedItems.filter((i) => i.is_gdpr).length,
    [selectedItems],
  );

  // Client-side safety checks
  const companyDupes = useMemo(() => {
    const groups: Record<number, QueueItem[]> = {};
    for (const item of selectedItems) {
      (groups[item.company_id] ??= []).push(item);
    }
    return Object.entries(groups)
      .filter(([, items]) => items.length > 1)
      .map(([, items]) => ({ company_name: items[0].company_name, count: items.length }));
  }, [selectedItems]);

  const emailDupes = useMemo(() => {
    const groups: Record<string, QueueItem[]> = {};
    for (const item of selectedItems) {
      if (item.email) (groups[item.email] ??= []).push(item);
    }
    return Object.entries(groups)
      .filter(([, items]) => items.length > 1)
      .map(([email, items]) => ({ email, count: items.length }));
  }, [selectedItems]);

  // Random samples — scaled by batch size
  const sampleTarget = emailItems.length < 10 ? 3 : emailItems.length <= 20 ? 5 : 8;
  const samples = useMemo(() => {
    if (emailItems.length <= sampleTarget) return emailItems;
    const shuffled = [...emailItems];
    // Seeded shuffle using sampleSeed
    let seed = sampleSeed;
    for (let i = shuffled.length - 1; i > 0; i--) {
      seed = (seed * 16807) % 2147483647;
      const j = seed % (i + 1);
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled.slice(0, sampleTarget);
  }, [emailItems, sampleTarget, sampleSeed]);

  const hasServerErrors = validationErrors &&
    ((validationErrors.company_duplicates?.length ?? 0) > 0 ||
     (validationErrors.email_duplicates?.length ?? 0) > 0);

  const isLinkedInOnly = emailItems.length === 0 && linkedinItems.length > 0;

  const ctaText = scheduleMode
    ? `Schedule ${emailItems.length} Emails`
    : hasServerErrors
      ? `Send Anyway (${emailItems.length})`
      : `Send ${emailItems.length} Emails Now`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Review Before Sending"
      description={`${emailItems.length} emails across ${uniqueCompanies} companies`}
      size="2xl"
    >
      <Modal.Body className="max-h-[60vh] overflow-y-auto">
        {isLinkedInOnly ? (
          <div className="text-center py-8">
            <p className="text-gray-500 text-sm">
              {linkedinItems.length} LinkedIn items selected. These are exported, not sent via email.
            </p>
          </div>
        ) : (
          <>
            {/* Stats grid */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <p className="text-xl font-bold text-blue-700">{emailItems.length}</p>
                <p className="text-xs text-blue-600">Emails to send</p>
              </div>
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <p className="text-xl font-bold text-green-700">{uniqueCompanies}</p>
                <p className="text-xs text-green-600">Unique companies</p>
              </div>
              {gdprCount > 0 && (
                <div className="bg-amber-50 rounded-lg p-3 text-center">
                  <p className="text-xl font-bold text-amber-700">{gdprCount}</p>
                  <p className="text-xs text-amber-600">GDPR contacts</p>
                </div>
              )}
            </div>

            {/* Safety checklist — only dynamic checks that can fail */}
            <div className="mb-4 space-y-1">
              {companyDupes.length === 0 && !validationErrors?.company_duplicates?.length ? (
                <div className="flex items-center gap-2 text-sm text-green-700">
                  <CheckCircle size={14} /> 1 email per company
                </div>
              ) : (
                <div className="flex items-start gap-2 text-sm text-red-700">
                  <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                  <span>
                    {(validationErrors?.company_duplicates || companyDupes).map((d) =>
                      `${d.count} emails to ${"company_name" in d ? d.company_name : ""}`
                    ).join(", ")}
                  </span>
                </div>
              )}
              {emailDupes.length === 0 && !validationErrors?.email_duplicates?.length ? (
                <div className="flex items-center gap-2 text-sm text-green-700">
                  <CheckCircle size={14} /> No duplicate recipients
                </div>
              ) : (
                <div className="flex items-start gap-2 text-sm text-red-700">
                  <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                  <span>
                    Duplicate recipients: {(validationErrors?.email_duplicates || emailDupes).map((d) =>
                      d.email
                    ).join(", ")}
                  </span>
                </div>
              )}
            </div>

            {/* Random samples */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-gray-700">
                  Random Sample ({samples.length} of {emailItems.length})
                </h3>
                {emailItems.length > sampleTarget && (
                  <button
                    onClick={() => {
                      setSampleSeed(Date.now());
                      setExpandedSamples(new Set());
                    }}
                    className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1"
                  >
                    <RefreshCw size={12} /> Shuffle
                  </button>
                )}
              </div>
              <div className="space-y-2">
                {samples.map((item, idx) => (
                  <div key={item.contact_id} className="bg-gray-50 rounded-lg border border-gray-200 p-3">
                    <p className="text-xs text-gray-500">
                      To: {item.contact_name} &middot; {item.company_name} &middot; Step {item.step_order}
                    </p>
                    <p className="text-sm font-medium text-gray-900 mt-1">
                      {item.rendered_email?.subject || item.message_draft?.draft_subject || "(no subject)"}
                    </p>
                    {(() => {
                      const body = item.rendered_email?.body_text || item.message_draft?.draft_text || "";
                      const bodyLines = body.split("\n");
                      const truncated = bodyLines.length > 3;
                      return (
                        <>
                          <p className="text-xs text-gray-600 mt-1 leading-relaxed">
                            {expandedSamples.has(idx) ? body : bodyLines.slice(0, 3).join("\n") + (truncated ? "..." : "")}
                          </p>
                          {truncated && (
                            <button
                              onClick={() => {
                                const next = new Set(expandedSamples);
                                next.has(idx) ? next.delete(idx) : next.add(idx);
                                setExpandedSamples(next);
                              }}
                              className="text-xs text-blue-600 hover:text-blue-700 mt-1"
                              aria-expanded={expandedSamples.has(idx)}
                            >
                              {expandedSamples.has(idx) ? "Show less" : "Show more"}
                            </button>
                          )}
                        </>
                      );
                    })()}
                  </div>
                ))}
              </div>
            </div>

            {/* Show all emails (collapsible) */}
            {emailItems.length > sampleTarget && (
              <div className="mb-2">
                <button
                  onClick={() => setShowAllEmails(!showAllEmails)}
                  className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800"
                  aria-expanded={showAllEmails}
                >
                  {showAllEmails ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  Show all {emailItems.length} emails
                </button>
                {showAllEmails && (
                  <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                    {emailItems.map((item) => (
                      <div key={item.contact_id} className="text-xs text-gray-600 py-1 px-2 hover:bg-gray-50 rounded">
                        {item.contact_name} &middot; {item.company_name} &middot;{" "}
                        {item.rendered_email?.subject || item.message_draft?.draft_subject || "(no subject)"}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Modal.Body>

      <Modal.Footer>
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
        >
          Back to Queue
        </button>
        {!isLinkedInOnly && (
          <button
            onClick={() => onConfirmSend(!!hasServerErrors)}
            disabled={isConfirming}
            className={`px-4 py-2.5 text-sm font-medium text-white rounded-lg disabled:opacity-50 ${
              hasServerErrors
                ? "bg-red-600 hover:bg-red-700"
                : "bg-gray-900 hover:bg-gray-800"
            }`}
          >
            {isConfirming ? "Validating..." : ctaText}
          </button>
        )}
      </Modal.Footer>
    </Modal>
  );
}

export default ReviewGateModal;
