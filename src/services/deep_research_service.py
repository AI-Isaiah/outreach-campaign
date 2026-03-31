"""Per-company deep research pipeline.

This is a facade module that re-exports all symbols from the split sub-modules.
All callers can continue to import from this module unchanged.
"""

# Query construction, Perplexity API, signal extraction, cost estimation
from src.services.deep_research_queries import (  # noqa: F401
    DEEP_RESEARCH_MODEL,
    COST_PERPLEXITY_QUERY,
    COST_SONNET_SYNTHESIS,
    SYNTHESIS_PROMPT,
    _HIGH_RECENCY_PATTERNS,
    _MEDIUM_RECENCY_PATTERNS,
    _LOW_RECENCY_PATTERNS,
    _SIGNAL_TYPE_PATTERNS,
    _recency_score,
    _detect_signal_type,
    _extract_fund_signals,
    _perplexity_query,
    _build_research_queries,
    estimate_cost,
)

# Sonnet synthesis, contact enrichment, previous score lookup
from src.services.deep_research_enrichment import (  # noqa: F401
    _synthesize_with_sonnet,
    _enrich_contacts,
    _get_previous_crypto_score,
)

# Background orchestration, status management, thread spawning
from src.services.deep_research_orchestrator import (  # noqa: F401
    _is_cancelled,
    _update_status,
    run_deep_research,
    _execute_deep_research,
    start_deep_research_background,
)
