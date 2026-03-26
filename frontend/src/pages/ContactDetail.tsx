import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api } from "../api/client";
import type { ContactDetailResponse, Enrollment, ResponseNote, Deal, Conversation, ContactProduct, Product } from "../types";
import StatusBadge from "../components/StatusBadge";
import LifecycleBadge from "../components/LifecycleBadge";
import ProductStageBadge from "../components/ProductStageBadge";
import TagPicker from "../components/TagPicker";
import UnifiedTimeline from "../components/UnifiedTimeline";
import { SkeletonCard, SkeletonMetricCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";
import { LIFECYCLE_STAGES } from "../constants";
const CONVERSATION_CHANNELS = [
  "conference", "phone", "telegram", "whatsapp", "email", "linkedin", "in_person", "video_call",
];
const PRODUCT_STAGES = ["discussed", "interested", "due_diligence", "invested", "declined"];

export default function ContactDetail() {
  const { id } = useParams<{ id: string }>();
  const contactId = Number(id);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery<ContactDetailResponse>({
    queryKey: ["contact", contactId],
    queryFn: () => api.getContact(contactId),
    enabled: !!id,
  });

  const [statusForm, setStatusForm] = useState({
    campaign: "",
    newStatus: "replied_positive",
    note: "",
  });

  const [phoneInput, setPhoneInput] = useState("");
  const [noteInput, setNoteInput] = useState("");

  const [convForm, setConvForm] = useState({
    channel: "phone",
    title: "",
    notes: "",
    outcome: "" as string,
  });
  const [showConvForm, setShowConvForm] = useState(false);

  const [addProductId, setAddProductId] = useState("");

  const { data: dealsData } = useQuery({
    queryKey: ["contact-deals", contactId],
    queryFn: () => api.listDeals({ company_id: data?.contact?.company_id ?? undefined }),
    enabled: !!data?.contact?.company_id && !isLoading,
  });

  const { data: conversations } = useQuery<Conversation[]>({
    queryKey: ["conversations", contactId],
    queryFn: () => api.listConversations(contactId),
    enabled: !!id,
  });

  const { data: contactProducts } = useQuery<ContactProduct[]>({
    queryKey: ["contact-products", contactId],
    queryFn: () => api.listContactProducts(contactId),
    enabled: !!id,
  });

  const { data: allProducts } = useQuery<Product[]>({
    queryKey: ["products"],
    queryFn: () => api.listProducts(),
  });

  const lifecycleMutation = useMutation({
    mutationFn: (stage: string) => api.updateLifecycle(contactId, stage),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact", contactId] }),
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

  const linkProductMutation = useMutation({
    mutationFn: (productId: number) => api.linkContactProduct(contactId, productId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] });
      setAddProductId("");
    },
  });

  const updateProductStageMutation = useMutation({
    mutationFn: ({ productId, stage }: { productId: number; stage: string }) =>
      api.updateContactProductStage(contactId, productId, stage),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] }),
  });

  const removeProductMutation = useMutation({
    mutationFn: (productId: number) => api.removeContactProduct(contactId, productId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] }),
  });

  const noteMutation = useMutation({
    mutationFn: () => api.addNote(contactId, noteInput, "manual"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", contactId], exact: false });
      setNoteInput("");
    },
  });

  const statusMutation = useMutation({
    mutationFn: () =>
      api.updateContactStatus(
        contactId,
        statusForm.campaign,
        statusForm.newStatus,
        statusForm.note || undefined,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", contactId], exact: false });
      setStatusForm((s) => ({ ...s, note: "" }));
    },
  });

  const phoneMutation = useMutation({
    mutationFn: () => api.updatePhone(contactId, phoneInput),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      setPhoneInput("");
    },
  });

  // Set default campaign from first enrollment
  const enrollments: Enrollment[] = data?.enrollments || [];
  useEffect(() => {
    if (!statusForm.campaign && enrollments.length > 0) {
      setStatusForm((s) => ({ ...s, campaign: enrollments[0].campaign_name }));
    }
  }, [enrollments]);

  if (isLoading) {
    return (
      <div className="space-y-8">
        <div>
          <div className="h-4 w-20 bg-gray-200 rounded animate-pulse" />
          <div className="h-8 w-64 bg-gray-200 rounded animate-pulse mt-3" />
          <div className="h-4 w-40 bg-gray-200 rounded animate-pulse mt-2" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SkeletonCard />
          <SkeletonCard />
        </div>
        <SkeletonCard />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-4">
        <Link to="/contacts" className="text-sm text-gray-400 hover:text-gray-600 inline-flex items-center gap-1">
          <ArrowLeft size={14} /> Contacts
        </Link>
        <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />
      </div>
    );
  }

  if (!data) return null;

  const { contact, notes }: { contact: typeof data.contact; notes: ResponseNote[] } = data;

  const displayName =
    contact.full_name ||
    `${contact.first_name || ""} ${contact.last_name || ""}`.trim() ||
    contact.email ||
    `Contact #${contact.id}`;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <Link
          to="/contacts"
          className="text-sm text-gray-400 hover:text-gray-600 inline-flex items-center gap-1"
        >
          <ArrowLeft size={14} /> Contacts
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          {displayName}
        </h1>
        {contact.title && (
          <p className="text-sm text-gray-500 mt-0.5">{contact.title}</p>
        )}
      </div>

      {/* Contact info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <h2 className="font-semibold text-gray-900 mb-3">Contact Info</h2>
          <div className="space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Email</span>
              <span className="text-gray-900">{contact.email || "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Email Status</span>
              <StatusBadge status={contact.email_status} />
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">LinkedIn</span>
              {contact.linkedin_url ? (
                <a
                  href={contact.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 truncate max-w-xs"
                >
                  Profile
                </a>
              ) : (
                <span className="text-gray-400">-</span>
              )}
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Phone</span>
              {contact.phone_number ? (
                <span className="text-gray-900">{contact.phone_number}</span>
              ) : (
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={phoneInput}
                    onChange={(e) => setPhoneInput(e.target.value)}
                    placeholder="+1 555 123 4567"
                    className="w-36 px-2 py-1 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => phoneMutation.mutate()}
                    disabled={!phoneInput}
                    loading={phoneMutation.isPending}
                  >
                    Add
                  </Button>
                </div>
              )}
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Lifecycle</span>
              <div className="flex items-center gap-2">
                <LifecycleBadge stage={contact.lifecycle_stage || "cold"} />
                <select
                  value={contact.lifecycle_stage || "cold"}
                  onChange={(e) => lifecycleMutation.mutate(e.target.value)}
                  className="px-2 py-1 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {LIFECYCLE_STAGES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Priority Rank</span>
              <span className="text-gray-900">{contact.priority_rank}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">GDPR</span>
              {contact.is_gdpr ? (
                <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">GDPR</span>
              ) : (
                <span className="text-gray-400">No</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Unsubscribed</span>
              {contact.unsubscribed ? (
                <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">Yes</span>
              ) : (
                <span className="text-gray-400">No</span>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <h2 className="font-semibold text-gray-900 mb-3">Company</h2>
          <div className="space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Company</span>
              {contact.company_id ? (
                <Link
                  to={`/companies/${contact.company_id}`}
                  className="font-medium text-blue-600 hover:text-blue-800"
                >
                  {contact.company_name || "-"}
                </Link>
              ) : (
                <span className="font-medium text-gray-900">{contact.company_name || "-"}</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">AUM</span>
              <span className="text-gray-900">
                {contact.aum_millions
                  ? `$${contact.aum_millions.toLocaleString()}M`
                  : "-"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Firm Type</span>
              <span className="text-gray-900">{contact.firm_type || "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Country</span>
              <span className="text-gray-900">{contact.country || "-"}</span>
            </div>
          </div>
        </Card>
      </div>

      {/* Tags */}
      <Card>
        <h2 className="font-semibold text-gray-900 mb-3">Tags</h2>
        <TagPicker entityType="contact" entityId={contactId} />
      </Card>

      {/* Campaign Enrollments */}
      {enrollments.length > 0 && (
        <Card padding="none">
          <Card.Header>
            <h2 className="font-semibold text-gray-900">
              Campaign Enrollments
            </h2>
          </Card.Header>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Campaign
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Status
                </th>
                <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Step
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Next Action
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Variant
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {enrollments.map((e: Enrollment) => (
                <tr key={e.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-3">
                    <Link
                      to={`/campaigns/${e.campaign_name}`}
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      {e.campaign_name}
                    </Link>
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={e.status} />
                  </td>
                  <td className="px-5 py-3 text-center text-sm text-gray-700">{e.current_step}</td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {e.next_action_date || "-"}
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {e.assigned_variant || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Log Response */}
      {enrollments.some(
        (e: Enrollment) =>
          e.status === "queued" || e.status === "in_progress",
      ) && (
        <Card>
          <h2 className="font-semibold text-gray-900 mb-4">Log Response</h2>
          <div className="space-y-3">
            <div className="flex gap-3">
              <select
                value={statusForm.campaign}
                onChange={(e) =>
                  setStatusForm((s) => ({ ...s, campaign: e.target.value }))
                }
                className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {enrollments
                  .filter(
                    (e: Enrollment) =>
                      e.status === "queued" || e.status === "in_progress",
                  )
                  .map((e: Enrollment) => (
                    <option key={e.campaign_name} value={e.campaign_name}>
                      {e.campaign_name}
                    </option>
                  ))}
              </select>
              <select
                value={statusForm.newStatus}
                onChange={(e) =>
                  setStatusForm((s) => ({ ...s, newStatus: e.target.value }))
                }
                className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="replied_positive">Positive Reply</option>
                <option value="replied_negative">Negative Reply</option>
                <option value="no_response">No Response</option>
                <option value="bounced">Bounced</option>
              </select>
            </div>
            <textarea
              placeholder="Optional note (e.g., call booked for Tuesday, interested in factsheet...)"
              value={statusForm.note}
              onChange={(e) =>
                setStatusForm((s) => ({ ...s, note: e.target.value }))
              }
              className="w-full h-20 px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                size="md"
                onClick={() => statusMutation.mutate()}
                loading={statusMutation.isPending}
              >
                Log Response
              </Button>
              {statusMutation.isError && (
                <span className="text-red-500 text-sm">
                  {(statusMutation.error as Error).message}
                </span>
              )}
              {statusMutation.isSuccess && (
                <span className="text-green-600 text-sm">Saved</span>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Notes */}
      <Card>
        <h2 className="font-semibold text-gray-900 mb-4">Notes</h2>

        <div className="flex gap-2 mb-4">
          <input
            type="text"
            placeholder="Add a note..."
            value={noteInput}
            onChange={(e) => setNoteInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && noteInput.trim()) noteMutation.mutate();
            }}
            className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <Button
            variant="primary"
            size="md"
            onClick={() => noteMutation.mutate()}
            disabled={!noteInput.trim()}
            loading={noteMutation.isPending}
          >
            Add
          </Button>
        </div>

        {notes.length > 0 ? (
          <div className="space-y-3">
            {notes.map((n: ResponseNote) => (
              <div key={n.id} className="bg-gray-50 rounded-lg p-3">
                <div className="flex justify-between mb-1">
                  <span className="text-xs font-medium text-gray-500 capitalize">
                    {n.note_type.replace(/_/g, " ")}
                  </span>
                  <span className="text-xs text-gray-400">
                    {n.created_at}
                  </span>
                </div>
                <p className="text-sm text-gray-700">{n.content}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No notes yet.</p>
        )}
      </Card>

      {/* Deals */}
      {dealsData?.deals && dealsData.deals.length > 0 && (
        <Card>
          <h2 className="font-semibold text-gray-900 mb-4">Deals</h2>
          <div className="space-y-3">
            {dealsData.deals.map((d: Deal) => (
              <div key={d.id} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
                <div>
                  <div className="text-sm font-medium text-gray-900">{d.title}</div>
                  <div className="text-xs text-gray-500">{d.company_name}</div>
                </div>
                <div className="flex items-center gap-3">
                  {d.amount_millions != null && (
                    <span className="text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
                      ${d.amount_millions}M
                    </span>
                  )}
                  <span className="text-xs font-medium text-gray-600 bg-gray-200 px-2 py-0.5 rounded-full capitalize">
                    {d.stage.replace(/_/g, " ")}
                  </span>
                  <Link
                    to="/pipeline"
                    className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    View in pipeline
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Product Interests */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">Product Interests</h2>
          <div className="flex gap-2">
            <select
              value={addProductId}
              onChange={(e) => setAddProductId(e.target.value)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Add product...</option>
              {(allProducts || [])
                .filter((p) => !(contactProducts || []).some((cp) => cp.product_id === p.id))
                .map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
            </select>
            {addProductId && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => linkProductMutation.mutate(Number(addProductId))}
                loading={linkProductMutation.isPending}
              >
                Add
              </Button>
            )}
          </div>
        </div>

        {(contactProducts || []).length > 0 ? (
          <div className="space-y-2">
            {contactProducts!.map((cp: ContactProduct) => (
              <div key={cp.id} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
                <div>
                  <span className="text-sm font-medium text-gray-900">{cp.product_name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={cp.stage}
                    onChange={(e) =>
                      updateProductStageMutation.mutate({ productId: cp.product_id, stage: e.target.value })
                    }
                    className="px-2 py-1 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {PRODUCT_STAGES.map((s) => (
                      <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                    ))}
                  </select>
                  <ProductStageBadge stage={cp.stage} />
                  <button
                    onClick={() => removeProductMutation.mutate(cp.product_id)}
                    className="text-xs text-red-500 hover:text-red-700 font-medium"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No product interests tracked yet.</p>
        )}
      </Card>

      {/* Conversations */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">Conversations</h2>
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
      </Card>

      {/* Unified Timeline */}
      <Card>
        <h2 className="font-semibold text-gray-900 mb-4">Interaction Timeline</h2>
        <UnifiedTimeline contactId={contactId} />
      </Card>
    </div>
  );
}
