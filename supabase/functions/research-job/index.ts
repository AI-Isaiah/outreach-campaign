/**
 * Supabase Edge Function: research-job
 *
 * Runs the crypto interest research pipeline for a batch of companies.
 * Processes 2-3 companies per invocation (within 150s timeout),
 * then self-invokes for remaining companies.
 *
 * Triggered by: POST from FastAPI endpoint (create_research_job / retry)
 * Payload: { job_id: number, api_keys?: { anthropic: string, perplexity: string }, offset?: number }
 */

import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const CLASSIFIER_MODEL = "claude-haiku-4-5-20251001";
const BATCH_SIZE = 3;

// Cost estimates per operation
const COST_WEB_SEARCH = 0.005;
const COST_LLM = 0.001;
const COST_CONTACT_DISCOVERY = 0.005;

interface ApiKeys {
  anthropic: string;
  perplexity: string;
}

interface ResearchResult {
  id: number;
  company_name: string;
  company_website: string | null;
  company_id: number | null;
  web_search_raw?: string | null;
  website_crawl_raw?: string | null;
  status: string;
  _errored?: boolean;
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

async function researchCompanyWebSearch(
  companyName: string,
  website: string | null,
  perplexityKey: string,
): Promise<string> {
  if (!perplexityKey) return JSON.stringify({ error: "PERPLEXITY_API_KEY not configured" });

  const siteInfo = website ? `(${website})` : "(no website)";
  const prompt =
    `Research whether ${companyName} ${siteInfo} invests in or has interest in ` +
    `cryptocurrency, digital assets, blockchain, or related technologies. ` +
    `Look for: public statements, portfolio investments in crypto, participation ` +
    `in fund raises, team members with crypto backgrounds, conference presence, ` +
    `regulatory filings. Provide specific evidence with sources.`;

  try {
    const resp = await fetch("https://api.perplexity.ai/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${perplexityKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "sonar",
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!resp.ok) {
      if (resp.status === 429) throw new Error("RATE_LIMITED");
      return JSON.stringify({ error: `API error: ${resp.status}` });
    }
    const data = await resp.json();
    return data.choices[0].message.content;
  } catch (e) {
    if ((e as Error).message === "RATE_LIMITED") throw e;
    console.error(`Perplexity research failed for ${companyName}:`, e);
    return JSON.stringify({ error: "Research request failed" });
  }
}

async function crawlCompanyWebsite(website: string): Promise<string> {
  if (!website) return "";
  let base = website.replace(/\/+$/, "");
  if (!base.startsWith("http")) base = `https://${base}`;

  const paths = ["", "/about", "/team", "/investments", "/portfolio"];
  const texts: string[] = [];

  for (const path of paths) {
    try {
      const resp = await fetch(`${base}${path}`, {
        headers: { "User-Agent": "Mozilla/5.0 (research bot)" },
        redirect: "follow",
        signal: AbortSignal.timeout(10000),
      });
      if (resp.ok) {
        let text = await resp.text();
        text = text.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "");
        text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "");
        text = text.replace(/<[^>]+>/g, " ");
        text = text.replace(/\s+/g, " ").trim();
        if (text) texts.push(`[${path || "/"}] ${text.slice(0, 2000)}`);
      }
    } catch {
      continue;
    }
  }
  return texts.join("\n\n").slice(0, 10000);
}

async function classifyCryptoInterest(
  companyName: string,
  webData: string,
  crawlData: string,
  anthropicKey: string,
): Promise<Record<string, unknown>> {
  if (!anthropicKey) {
    return {
      crypto_score: 0,
      category: "no_signal",
      evidence_summary: "ANTHROPIC_API_KEY not configured",
      evidence: [],
      reasoning: "Cannot classify without API key",
    };
  }

  let research = webData ? `Web search results:\n${webData}` : "";
  if (crawlData) research += `\n\nWebsite content:\n${crawlData}`;

  const prompt =
    `Given the following research about ${companyName}, score their crypto/digital asset ` +
    `investment interest from 0-100 and categorize them.\n\n` +
    `Scoring guide:\n` +
    `- 80-100: confirmed_investor (clear evidence of crypto investments)\n` +
    `- 60-79: likely_interested (strong signals like crypto hires, conference presence)\n` +
    `- 40-59: possible (some indirect signals)\n` +
    `- 20-39: no_signal (no relevant evidence found)\n` +
    `- 0-19: unlikely (traditional-only fund, anti-crypto statements)\n\n` +
    `Research:\n${research}\n\n` +
    `Return valid JSON only with these keys:\n` +
    `{"crypto_score": <0-100>, "category": "<category>", ` +
    `"evidence_summary": "<2-3 sentence summary>", ` +
    `"evidence": [{"source": "<source>", "quote": "<quote>", "relevance": "<high/medium/low>"}], ` +
    `"reasoning": "<your reasoning>"}`;

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": anthropicKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: CLASSIFIER_MODEL,
        max_tokens: 1000,
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!resp.ok) throw new Error(`Anthropic API error: ${resp.status}`);
    const data = await resp.json();
    return JSON.parse(data.content[0].text);
  } catch (e) {
    console.error(`Classification failed for ${companyName}:`, e);
    return {
      crypto_score: 0,
      category: "no_signal",
      evidence_summary: "Classification failed",
      evidence: [],
      reasoning: "API call failed",
    };
  }
}

async function discoverContacts(
  companyName: string,
  website: string | null,
  perplexityKey: string,
): Promise<Record<string, unknown>[]> {
  if (!perplexityKey) return [];

  const siteInfo = website ? `(${website})` : "";
  const prompt =
    `Find key decision-makers at ${companyName} ${siteInfo} involved in investment ` +
    `decisions. Look for CIO, Head of Digital Assets, Head of Alternative Investments, ` +
    `Portfolio Manager, Partner, Managing Director. Provide: full name, title, email if ` +
    `public, LinkedIn URL if available. List up to 5. Return valid JSON array: ` +
    `[{"name": "...", "title": "...", "email": null, "linkedin": null, "source": "..."}]`;

  try {
    const resp = await fetch("https://api.perplexity.ai/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${perplexityKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "sonar",
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!resp.ok) {
      if (resp.status === 429) throw new Error("RATE_LIMITED");
      return [];
    }
    const text = (await resp.json()).choices[0].message.content;
    const match = text.match(/\[[\s\S]*\]/);
    return match ? JSON.parse(match[0]).slice(0, 5) : [];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Database helpers (via Supabase JS client / PostgREST)
// ---------------------------------------------------------------------------

async function isCancelled(db: SupabaseClient, jobId: number): Promise<boolean> {
  const { data } = await db.from("research_jobs").select("status").eq("id", jobId).single();
  return data?.status === "cancelling" || data?.status === "cancelled";
}

async function updateJobStatus(
  db: SupabaseClient,
  jobId: number,
  status: string,
  extra: Record<string, unknown> = {},
): Promise<void> {
  await db.from("research_jobs").update({ status, updated_at: new Date().toISOString(), ...extra }).eq("id", jobId);
}

async function markResultError(db: SupabaseClient, resultId: number, error: string): Promise<void> {
  await db
    .from("research_results")
    .update({ status: "error", classification_reasoning: `Error: ${error}`, updated_at: new Date().toISOString() })
    .eq("id", resultId);
}

async function findWarmIntros(
  db: SupabaseClient,
  companyName: string,
  companyId: number | null,
): Promise<{ contact_ids: number[]; notes: string | null }> {
  const contactIds: number[] = [];
  const notesParts: string[] = [];

  if (companyId) {
    const { data: direct } = await db
      .from("contacts")
      .select("id, full_name, title")
      .eq("company_id", companyId);
    for (const c of direct || []) {
      contactIds.push(c.id);
      notesParts.push(`Direct contact: ${c.full_name} (${c.title || "no title"})`);
    }
  }

  const nameNorm = companyName.toLowerCase().replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
  const { data: nameMatch } = await db
    .from("contacts")
    .select("id, full_name, title, companies(name)")
    .eq("companies.name_normalized", nameNorm)
    .not("id", "in", `(${contactIds.length ? contactIds.join(",") : "0"})`);

  for (const c of nameMatch || []) {
    contactIds.push(c.id);
    notesParts.push(`Name match: ${c.full_name}`);
  }

  return {
    contact_ids: contactIds,
    notes: notesParts.length ? notesParts.join("\n") : null,
  };
}

// ---------------------------------------------------------------------------
// Main pipeline
// ---------------------------------------------------------------------------

async function executeResearchJob(
  db: SupabaseClient,
  jobId: number,
  keys: ApiKeys,
  offset: number,
): Promise<void> {
  // Load job
  const { data: job } = await db.from("research_jobs").select("*").eq("id", jobId).single();
  if (!job) return;
  const method: string = job.method;

  // Load all results
  const { data: allResults } = await db
    .from("research_results")
    .select("*")
    .eq("job_id", jobId)
    .order("id");

  if (!allResults || allResults.length === 0) {
    await updateJobStatus(db, jobId, "completed");
    return;
  }

  let actualCost = job.actual_cost_usd || 0;
  const results = allResults as ResearchResult[];
  const end = Math.min(offset + BATCH_SIZE, results.length);

  // Phase 1: Research (for this batch)
  if (offset === 0) await updateJobStatus(db, jobId, "researching");
  for (let i = offset; i < end; i++) {
    if (await isCancelled(db, jobId)) {
      await updateJobStatus(db, jobId, "cancelled", { actual_cost_usd: actualCost });
      return;
    }

    const result = results[i];
    try {
      // Research
      let webRaw: string | null = null;
      let crawlRaw: string | null = null;

      if (method === "web_search" || method === "hybrid") {
        webRaw = await researchCompanyWebSearch(result.company_name, result.company_website, keys.perplexity);
        actualCost += COST_WEB_SEARCH;
      }
      if ((method === "website_crawl" || method === "hybrid") && result.company_website) {
        crawlRaw = await crawlCompanyWebsite(result.company_website);
      }

      await db
        .from("research_results")
        .update({ web_search_raw: webRaw, website_crawl_raw: crawlRaw, status: "researching", updated_at: new Date().toISOString() })
        .eq("id", result.id);

      // Classify
      const classification = await classifyCryptoInterest(
        result.company_name,
        webRaw || "",
        crawlRaw || "",
        keys.anthropic,
      );
      actualCost += COST_LLM;

      await db
        .from("research_results")
        .update({
          crypto_score: classification.crypto_score ?? 0,
          category: classification.category ?? "no_signal",
          evidence_summary: classification.evidence_summary,
          evidence_json: classification.evidence ?? [],
          classification_reasoning: classification.reasoning,
          status: "classified",
          updated_at: new Date().toISOString(),
        })
        .eq("id", result.id);

      // Discover contacts
      const discovered = await discoverContacts(result.company_name, result.company_website, keys.perplexity);
      actualCost += COST_CONTACT_DISCOVERY;

      const warm = await findWarmIntros(db, result.company_name, result.company_id);

      await db
        .from("research_results")
        .update({
          discovered_contacts_json: discovered.length ? discovered : null,
          warm_intro_contact_ids: warm.contact_ids.length ? warm.contact_ids : null,
          warm_intro_notes: warm.notes,
          status: "completed",
          updated_at: new Date().toISOString(),
        })
        .eq("id", result.id);
    } catch (e) {
      console.error(`Error processing ${result.company_name}:`, e);
      await markResultError(db, result.id, String(e));
    }

    await updateJobStatus(db, jobId, job.status === "classifying" ? "classifying" : "researching", {
      processed_companies: i + 1,
      classified_companies: i + 1,
      actual_cost_usd: Math.round(actualCost * 10000) / 10000,
    });

    // Small delay between companies
    await new Promise((r) => setTimeout(r, 500));
  }

  // If more companies remain, self-invoke for next batch
  if (end < results.length) {
    try {
      await fetch(`${SUPABASE_URL}/functions/v1/research-job`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ job_id: jobId, api_keys: keys, offset: end }),
      });
    } catch (e) {
      console.error("Failed to self-invoke for next batch:", e);
      await updateJobStatus(db, jobId, "failed", {
        error_message: "Failed to continue to next batch",
        actual_cost_usd: actualCost,
      });
    }
    return;
  }

  // All done
  await updateJobStatus(db, jobId, "completed", {
    actual_cost_usd: Math.round(actualCost * 10000) / 10000,
  });
}

// ---------------------------------------------------------------------------
// HTTP handler
// ---------------------------------------------------------------------------

Deno.serve(async (req) => {
  try {
    const { job_id, api_keys, offset = 0 } = await req.json();

    if (!job_id) {
      return new Response(JSON.stringify({ error: "job_id required" }), { status: 400 });
    }

    const keys: ApiKeys = {
      anthropic: api_keys?.anthropic || Deno.env.get("ANTHROPIC_API_KEY") || "",
      perplexity: api_keys?.perplexity || Deno.env.get("PERPLEXITY_API_KEY") || "",
    };

    const db = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    // Run async — respond immediately so the caller doesn't block
    // EdgeRuntime.waitUntil is not available, so we run inline
    await executeResearchJob(db, job_id, keys, offset);

    return new Response(JSON.stringify({ success: true }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error("Research job edge function error:", e);
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
