"""Reusable SQL query builder for dynamic WHERE/JOIN construction.

Eliminates repeated condition-list + params-list patterns across route files.
"""

from __future__ import annotations


class QueryBuilder:
    """Accumulates WHERE conditions, JOIN clauses, and parameters."""

    def __init__(self) -> None:
        self._conditions: list[str] = []
        self._joins: list[str] = []
        self._params: list = []

    def add_condition(self, clause: str, *values: object) -> "QueryBuilder":
        """Append a WHERE clause fragment and its parameter values."""
        self._conditions.append(clause)
        self._params.extend(values)
        return self

    def add_join(self, join_clause: str) -> "QueryBuilder":
        """Append a JOIN clause."""
        self._joins.append(join_clause)
        return self

    @property
    def where_clause(self) -> str:
        """Return ``WHERE ...`` string, or empty string if no conditions."""
        if not self._conditions:
            return ""
        return "WHERE " + " AND ".join(self._conditions)

    @property
    def join_clause(self) -> str:
        """Return concatenated JOIN clauses separated by newlines."""
        return "\n".join(self._joins)

    @property
    def params(self) -> list:
        """Return the accumulated parameter list."""
        return list(self._params)

    @staticmethod
    def build_update(fields: dict, exclude_none: bool = True) -> tuple[str, list]:
        """Build SET clause from a dict of field->value pairs.

        Returns (set_clause, params) for use in UPDATE ... SET {set_clause} WHERE ...
        """
        parts: list[str] = []
        params: list = []
        for field, value in fields.items():
            if exclude_none and value is None:
                continue
            parts.append(f"{field} = %s")
            params.append(value)
        return ", ".join(parts), params
