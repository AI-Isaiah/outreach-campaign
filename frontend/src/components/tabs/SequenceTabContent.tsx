import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ListOrdered } from "lucide-react";
import { campaignsApi } from "../../api/campaigns";
import type { CampaignContact } from "../../api/campaigns";
import { request } from "../../api/request";
import SequenceEditorDetail from "../SequenceEditorDetail";
import type { SequenceStep } from "../SequenceEditorDetail";
import { SkeletonTable } from "../Skeleton";

export default function SequenceTabContent({ campaignName, campaignId }: { campaignName: string; campaignId: number }) {
  const { data: steps, isLoading } = useQuery<SequenceStep[]>({
    queryKey: ["campaign-sequence", campaignId],
    queryFn: () => request<SequenceStep[]>(`/campaigns/${campaignId}/sequence`),
    enabled: !!campaignId,
  });

  const { data: contactsData } = useQuery<CampaignContact[]>({
    queryKey: ["campaign-contacts-count", campaignId],
    queryFn: () => campaignsApi.getCampaignContacts(campaignId),
  });
  const enrolledCount = contactsData?.length ?? 0;

  const queryClient = useQueryClient();
  const addFirstStep = useMutation({
    mutationFn: () =>
      campaignsApi.addSequenceStep(campaignId, {
        channel: "linkedin_connect",
        delay_days: 0,
        step_order: 1,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["campaign-sequence", campaignId] }),
  });

  if (isLoading) return <SkeletonTable rows={3} cols={4} />;

  if (!steps || steps.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-12 h-12 rounded-full bg-purple-50 flex items-center justify-center mx-auto mb-3">
          <ListOrdered size={24} className="text-purple-500" />
        </div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">No sequence set up</h3>
        <p className="text-sm text-gray-500 mb-4">
          Add a message sequence to automate your outreach for this campaign.
        </p>
        <a
          href={`/campaigns/wizard?editCampaign=${campaignId}&step=2`}
          className="inline-flex items-center gap-1.5 bg-gray-900 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-800"
        >
          Set Up Sequence
        </a>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-end mb-4">
        <a
          href={`/campaigns/wizard?editCampaign=${campaignId}&step=2`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.855z"/></svg>
          Edit in Wizard
        </a>
      </div>
      <SequenceEditorDetail
        campaignId={campaignId}
        steps={steps}
        enrolledCount={enrolledCount}
      />
    </div>
  );
}
