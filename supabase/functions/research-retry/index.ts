/**
 * Supabase Edge Function: research-retry
 *
 * Retries all errored results in a completed/failed research job.
 * Resets errored results to pending, then invokes research-job to reprocess.
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async (req) => {
  try {
    const { job_id, api_keys } = await req.json();
    if (!job_id) {
      return new Response(JSON.stringify({ error: "job_id required" }), { status: 400 });
    }

    const db = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    // Reset errored results to pending
    const { count } = await db
      .from("research_results")
      .update({ status: "pending", classification_reasoning: null, updated_at: new Date().toISOString() })
      .eq("job_id", job_id)
      .eq("status", "error")
      .select("id", { count: "exact", head: true });

    if (!count) {
      return new Response(JSON.stringify({ error: "No errored results to retry" }), { status: 400 });
    }

    // Update job status back to researching
    await db.from("research_jobs").update({
      status: "researching",
      error_message: null,
      updated_at: new Date().toISOString(),
    }).eq("id", job_id);

    // Invoke the main research-job function to reprocess
    await fetch(`${SUPABASE_URL}/functions/v1/research-job`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id, api_keys, offset: 0 }),
    });

    return new Response(JSON.stringify({ success: true, retrying: count }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error("Research retry error:", e);
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
