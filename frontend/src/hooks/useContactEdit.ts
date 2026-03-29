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
  handleSaveEdit: () => void;
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

  const patchMutation = useMutation({
    mutationFn: (fields: Parameters<typeof api.patchContact>[1]) =>
      api.patchContact(item.contact_id, fields),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
      setShowEdit(false);
    },
  });

  const handleSaveEdit = () => {
    const fields: Record<string, string> = {};
    const [curFirst, curLast] = splitName(item.contact_name);
    if (editFirst !== curFirst) fields.first_name = editFirst;
    if (editLast !== curLast) fields.last_name = editLast;
    if (editLinkedIn !== (item.linkedin_url || "")) fields.linkedin_url = editLinkedIn;
    if (Object.keys(fields).length === 0) { setShowEdit(false); return; }
    patchMutation.mutate(fields);
  };

  const handleCancelEdit = () => {
    setEditFirst(splitName(item.contact_name)[0]);
    setEditLast(splitName(item.contact_name)[1]);
    setEditLinkedIn(item.linkedin_url || "");
    patchMutation.reset();
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
    isSaving: patchMutation.isPending,
    editError: patchMutation.error as Error | null,
  };
}
