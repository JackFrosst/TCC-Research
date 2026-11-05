import re


def compile_query(provider: str, canonical_query: str) -> str:
    query = " ".join(canonical_query.split())
    if provider in {"dblp", "semantic_scholar"}:
        return _representative_terms(query)
    if provider == "openaire":
        return _openaire_query(query)
    if provider == "arxiv":
        return f"all:({query})"
    return query


def _representative_terms(query: str) -> str:
    groups = re.split(r"\s+AND\s+", query, flags=re.IGNORECASE)
    selected = []
    for group in groups:
        first_alternative = re.split(r"\s+OR\s+", group, maxsplit=1, flags=re.IGNORECASE)[0]
        cleaned = re.sub(r"[()]", " ", first_alternative).replace('"', " ")
        cleaned = re.sub(r"\bNOT\b", " ", cleaned, flags=re.IGNORECASE)
        if cleaned.strip():
            selected.append(cleaned.strip())
    return " ".join(selected)


def _openaire_query(query: str) -> str:
    groups = re.split(r"\s+AND\s+", query, flags=re.IGNORECASE)[:3]
    operator_budget = max(0, 4 - (len(groups) - 1))
    compiled_groups: list[str] = []
    for group in groups:
        alternatives = re.split(r"\s+OR\s+", group, flags=re.IGNORECASE)
        selected = alternatives[: min(len(alternatives), operator_budget + 1)]
        operator_budget -= max(0, len(selected) - 1)
        cleaned = [item.strip().strip("()").strip() for item in selected if item.strip("() ")]
        if len(cleaned) > 1:
            compiled_groups.append(f"({' OR '.join(cleaned)})")
        elif cleaned:
            compiled_groups.append(cleaned[0])
    return " AND ".join(compiled_groups)
