import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QueueItem } from "../types";
import { splitName } from "../utils/queue";

export interface ContactEditState {
  showEdit: boolean;
  setShowEdit: (show: boolean) => void;
  editFirst: string;
  setEditFirst: (v: string) => void;
  editLast: string;
  setEditLast: (v: string) => void;
  editLinkedIn: string;
  setEditLinkedIn: (v: string) => void;
  handleSaveEdit: () => Promise<void>;
  handleCancelEdit: () => void;
  isSaving: boolean;
  editError: Error | null;
}

export function useContactEdit(item: QueueItem): ContactEditState {
  const [showEdit, setShowEdit] = useState(false);
  const [editFirst, setEditFirst] = useState(() => splitName(item.contact_name)[0]);
  const [editLast, setEditLast] = useState(() => splitName(item.contact_name)[1]);
  const [editLinkedIn, setEditLinkedIn] = useState(item.linkedin_url || "");

  const queryClient = useQueryClient();

  const nameMutation = useMutation({
    mutationFn: () => api.updateContactName(item.contact_id, editFirst, editLast),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
    },
  });

  const linkedInMutation = useMutation({
    mutationFn: () => api.updateLinkedInUrl(item.contact_id, editLinkedIn),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
    },
  });

  const handleSaveEdit = async () => {
    const promises: Promise<any>[] = [];
    const currentName = item.contact_name;
    const newName = `${editFirst} ${editLast}`.trim();
    if (newName !== currentName) {
      promises.push(nameMutation.mutateAsync());
    }
    if (editLinkedIn !== (item.linkedin_url || "")) {
      promises.push(linkedInMutation.mutateAsync());
    }
    try {
      if (promises.length > 0) {
        await Promise.all(promises);
      }
      setShowEdit(false);
    } catch {
      // Error is surfaced via mutation state
    }
  };

  const handleCancelEdit = () => {
    setEditFirst(splitName(item.contact_name)[0]);
    setEditLast(splitName(item.contact_name)[1]);
    setEditLinkedIn(item.linkedin_url || "");
    setShowEdit(false);
  };

  return {
    showEdit,
    setShowEdit,
    editFirst,
    setEditFirst,
    editLast,
    setEditLast,
    editLinkedIn,
    setEditLinkedIn,
    handleSaveEdit,
    handleCancelEdit,
    isSaving: nameMutation.isPending || linkedInMutation.isPending,
    editError: (nameMutation.error || linkedInMutation.error) as Error | null,
  };
}
