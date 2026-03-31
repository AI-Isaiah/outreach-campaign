"""Smart CSV import engine — LLM-powered column mapping, transform, preview, execute.

This is a facade module that re-exports all symbols from the split sub-modules.
All callers can continue to import from this module unchanged.
"""

# LLM column mapping, header detection, heuristic fallback, caching
from src.services.smart_import_llm import (  # noqa: F401
    _build_prompt,
    _HEADER_KEYWORDS,
    _detect_header_row,
    parse_csv_with_header_detection,
    _heuristic_mapping,
    _header_fingerprint,
    _get_cached_mapping,
    _save_mapping_cache,
    analyze_csv,
)

# Row transformation, preview, field-level diffs
from src.services.smart_import_transform import (  # noqa: F401
    _parse_aum,
    transform_rows,
    _build_field_diffs,
    _existing_contact_dict,
    preview_import,
)

# Execute import and merge logic
from src.services.smart_import_execute import (  # noqa: F401
    execute_import,
    _merge_contact,
)
