"""Crypto interest research pipeline.

This is a facade module that re-exports all symbols from the split sub-modules
and the previously extracted crypto_scoring / crypto_web_scraper modules.
All callers can continue to import from this module unchanged.
"""

# Re-export from previously extracted modules
from src.services.crypto_scoring import (  # noqa: F401
    classify_crypto_interest,
    estimate_job_cost,
    COST_LLM,
)
from src.services.crypto_web_scraper import (  # noqa: F401
    COST_CRAWL,
    COST_WEB_SEARCH,
    crawl_company_website,
    discover_contacts_at_company,
    research_company_web_search,
)

# CSV parsing, preview, duplicate detection
from src.services.crypto_research_csv import (  # noqa: F401
    _HEADER_ALIASES,
    _build_header_map,
    parse_research_csv,
    preview_research_csv,
    check_duplicate_companies,
)

# Warm intros, company resolution, contact import, batch import
from src.services.crypto_research_import import (  # noqa: F401
    find_warm_intros,
    resolve_or_create_company,
    import_single_contact,
    batch_import_and_enroll,
)

# Job orchestration, status management, background threads
from src.services.crypto_research_orchestrator import (  # noqa: F401
    COST_CONTACT_DISCOVERY,
    _default_api_keys,
    _resolve_api_keys,
    _is_cancelled,
    _update_job_status,
    cancel_research_job,
    retry_failed_results,
    run_research_job,
    _execute_research_job,
    _research_single_company,
    _classify_single_company,
    _mark_result_error,
    start_research_job_background,
    start_retry_background,
)
