import { useEffect, useRef, useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useFormContext } from "react-hook-form";
import { useMutation } from "@tanstack/react-query";
import type { WizardFormData } from "../schemas/campaignSchema";
import { request } from "../../../api/request";
import { useToast } from "../../../components/Toast";

// ─── API helpers ───

const draftsApi = {
  create: (name?: string) =>
    request<{ id: number; version: number }>("/campaigns/draft", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  get: (id: number) =>
    request<{
      id: number;
      form_data: Partial<WizardFormData>;
      current_step: number;
      version: number;
      updated_at: string;
    }>(`/campaigns/draft/${id}`),
  update: (id: number, data: { form_data: WizardFormData; current_step: number }) =>
    request<{ id: number; version: number }>(`/campaigns/draft/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  remove: (id: number) =>
    request<{ success: boolean }>(`/campaigns/draft/${id}`, { method: "DELETE" }),
};

// ─── localStorage helpers ───

const LS_PENDING_KEY = "wizard-draft-pending";
const lsKey = (id: number | null) => id ? `wizard-draft-${id}` : LS_PENDING_KEY;

interface LSData {
  formValues: Partial<WizardFormData>;
  currentStep: number;
  version: number;
  draftId: number | null;
  savedAt: number; // Date.now() for fallback comparison
}

function lsSave(draftId: number | null, values: WizardFormData, step: number, version: number) {
  try {
    const data: LSData = { formValues: values, currentStep: step, version, draftId, savedAt: Date.now() };
    const json = JSON.stringify(data);
    // 2MB size guard
    if (json.length > 2 * 1024 * 1024) {
      console.warn("Wizard draft too large for localStorage, skipping save");
      return;
    }
    localStorage.setItem(lsKey(draftId), json);
    // Rename pending → named key when draftId is assigned
    if (draftId && localStorage.getItem(LS_PENDING_KEY)) {
      localStorage.removeItem(LS_PENDING_KEY);
    }
  } catch (e) {
    // QuotaExceeded or other error — non-blocking
    console.warn("localStorage save failed:", e);
  }
}

function lsLoad(draftId: number | null): LSData | null {
  try {
    const raw = localStorage.getItem(lsKey(draftId));
    if (!raw) {
      // Also check pending key if no draftId-specific key
      if (draftId) {
        const pending = localStorage.getItem(LS_PENDING_KEY);
        if (pending) return JSON.parse(pending);
      }
      return null;
    }
    return JSON.parse(raw);
  } catch {
    // Corrupted JSON — clear and return null
    localStorage.removeItem(lsKey(draftId));
    localStorage.removeItem(LS_PENDING_KEY);
    return null;
  }
}

function lsClear(draftId: number | null) {
  localStorage.removeItem(lsKey(draftId));
  localStorage.removeItem(LS_PENDING_KEY);
}

// ─── Hook ───

interface UsePersistenceReturn {
  draftId: number | null;
  version: number;
  isLoading: boolean;
  saveError: string | null;
  /** Call on step navigation to persist to API */
  saveToApi: (currentStep: number) => void;
  /** Call after successful campaign launch */
  cleanupDraft: () => void;
}

export function useWizardPersistence(
  currentStep: number,
  /** When true, skip localStorage/API draft restore (editing an existing campaign provides its own data) */
  skipRestore = false,
): UsePersistenceReturn {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const { getValues, reset, formState } = useFormContext<WizardFormData>();

  // Refs for stable access in beforeunload
  const getValuesRef = useRef(getValues);
  getValuesRef.current = getValues;

  const draftIdRef = useRef<number | null>(
    searchParams.get("draftId") ? Number(searchParams.get("draftId")) : null
  );
  const versionRef = useRef(0);
  const creatingRef = useRef(false); // Race guard for draft creation
  const [isLoading, setIsLoading] = useState(!!searchParams.get("draftId"));
  const [saveError, setSaveError] = useState<string | null>(null);

  // ─── Draft creation (first isDirty → POST) ───

  const createMutation = useMutation({
    mutationFn: () => draftsApi.create(getValues("name") || undefined),
    onSuccess: (data) => {
      draftIdRef.current = data.id;
      versionRef.current = data.version;
      setSearchParams({ draftId: String(data.id) }, { replace: true });
      lsSave(data.id, getValuesRef.current(), currentStep, data.version);
      creatingRef.current = false;
    },
    onError: () => {
      creatingRef.current = false;
      toast("Couldn't save draft to server — working offline", "error");
    },
  });

  // Watch for first dirty state → create draft
  useEffect(() => {
    if (!formState.isDirty || draftIdRef.current || creatingRef.current) return;
    // Debounce 500ms to avoid StrictMode double-fire
    const timer = setTimeout(() => {
      if (!draftIdRef.current && !creatingRef.current) {
        creatingRef.current = true;
        createMutation.mutate();
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [formState.isDirty]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Auto-save to localStorage (debounced 2s) ───

  useEffect(() => {
    if (!formState.isDirty) return;
    const timer = setTimeout(() => {
      lsSave(draftIdRef.current, getValuesRef.current(), currentStep, versionRef.current);
    }, 2000);
    return () => clearTimeout(timer);
  }, [formState.isDirty, currentStep]); // re-save when step changes

  // ─── API save (called on step navigation) ───

  const updateMutation = useMutation({
    mutationFn: (step: number) => {
      if (!draftIdRef.current) return Promise.resolve(null);
      return draftsApi.update(draftIdRef.current, {
        form_data: getValuesRef.current(),
        current_step: step,
      });
    },
    onSuccess: (data) => {
      if (data) {
        versionRef.current = data.version;
        setSaveError(null);
      }
    },
    onError: () => {
      setSaveError("Draft save failed");
      toast("Draft save failed — your work is safe locally", "error");
    },
    retry: 1,
  });

  const saveToApi = useCallback((step: number) => {
    if (draftIdRef.current) {
      updateMutation.mutate(step);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── beforeunload (save to localStorage via live getValues ref) ───

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (formState.isDirty) {
        // Save to localStorage synchronously using live ref
        lsSave(draftIdRef.current, getValuesRef.current(), currentStep, versionRef.current);
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [formState.isDirty, currentStep]);

  // ─── Draft restore on mount ───

  useEffect(() => {
    // When editing an existing campaign, skip draft restore entirely —
    // the campaign data useEffect in CampaignWizard handles pre-population.
    if (skipRestore) {
      setIsLoading(false);
      return;
    }

    const urlDraftId = searchParams.get("draftId");
    if (!urlDraftId) {
      // No URL draftId — check localStorage
      const lsData = lsLoad(null);
      if (lsData && (Date.now() - lsData.savedAt) < 24 * 60 * 60 * 1000) {
        reset(lsData.formValues as WizardFormData);
        if (lsData.draftId) {
          draftIdRef.current = lsData.draftId;
          versionRef.current = lsData.version;
          setSearchParams({ draftId: String(lsData.draftId) }, { replace: true });
        }
        toast(`Restored draft from ${new Date(lsData.savedAt).toLocaleTimeString()}`, "info");
      }
      setIsLoading(false);
      return;
    }

    // URL has draftId — fetch from API
    const id = Number(urlDraftId);
    draftsApi.get(id)
      .then((data) => {
        draftIdRef.current = data.id;
        versionRef.current = data.version;

        // Compare with localStorage version
        const lsData = lsLoad(id);
        if (lsData && lsData.version > data.version) {
          // localStorage is newer — use it and sync to API
          reset(lsData.formValues as WizardFormData);
          updateMutation.mutate(lsData.currentStep);
        } else {
          reset(data.form_data as WizardFormData);
        }
        setIsLoading(false);
      })
      .catch((err: Error) => {
        setIsLoading(false);
        if (err.message.includes("404") || err.message.includes("not found")) {
          toast("Draft not found — starting fresh", "info");
          lsClear(id);
          setSearchParams({}, { replace: true });
        } else if (err.message.includes("403")) {
          toast("Not authorized", "error");
          setSearchParams({}, { replace: true });
        } else {
          // Network error — try localStorage fallback
          const lsData = lsLoad(id);
          if (lsData) {
            reset(lsData.formValues as WizardFormData);
            toast("Couldn't load draft from server — using local backup", "info");
          } else {
            toast("Couldn't load draft — starting fresh", "error");
            setSearchParams({}, { replace: true });
          }
        }
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Post-launch cleanup ───

  const cleanupDraft = useCallback(() => {
    const id = draftIdRef.current;
    if (!id) return;

    lsClear(id);

    // Best-effort DELETE with retry
    draftsApi.remove(id).catch(() => {
      // Retry once
      setTimeout(() => {
        draftsApi.remove(id).catch(() => {
          // Give up — expiry cleanup will catch it
          console.warn(`Draft ${id} cleanup failed — will expire in 30 days`);
        });
      }, 1000);
    });
  }, []);

  return {
    draftId: draftIdRef.current,
    version: versionRef.current,
    isLoading,
    saveError,
    saveToApi,
    cleanupDraft,
  };
}
