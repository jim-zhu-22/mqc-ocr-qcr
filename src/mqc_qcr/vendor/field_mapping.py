"""Database-to-scoring field mappings for the four code-list tables.

The aliases in this module follow ``数据库字段结构中英对照_v1.0.xlsx``.
Keep database column names here so API, batch scoring and DSL evaluation use
the same material context.
"""

from typing import Any, Dict, Iterable, Mapping, Sequence


TABLE_NAME_GROUPS = (
    ("historical_code_list_group",),
    ("historical_code_list_plant",),
    # The deployed database has used both names. Prefer the existing project
    # name, while accepting the name in the database field workbook.
    ("standard_code_list", "standard_list_code"),
    ("batch_code_list",),
)

CODE_SCORE_TABLES = [group[0] for group in TABLE_NAME_GROUPS]
CODE_SCORE_TABLE_NAMES = {
    name for group in TABLE_NAME_GROUPS for name in group
}


from .scoring_fields import FIELD_ALIASES, field_state


def merge_field_aliases(existing: Mapping[str, Sequence[str]]) -> Dict[str, tuple[str, ...]]:
    """Merge local aliases with the database workbook aliases without loss."""
    merged: Dict[str, tuple[str, ...]] = {}
    canonical_names = list(FIELD_ALIASES) + [
        name for name in existing if name not in FIELD_ALIASES
    ]
    for canonical in canonical_names:
        values = list(FIELD_ALIASES.get(canonical, ())) + list(existing.get(canonical, ()))
        merged[canonical] = tuple(dict.fromkeys(str(value) for value in values if str(value)))
    return merged


def first_non_empty(row: Mapping[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def normalize_material_record(
    row: Mapping[str, Any] | None,
    source_table: str = "",
) -> Dict[str, Any]:
    """Preserve the raw row and add stable Chinese/English scoring aliases."""
    data: Dict[str, Any] = dict(row or {})
    raw_source = str(
        source_table
        or data.get("_source_table")
        or data.get("source_table")
        or data.get("_table_name")
        or ""
    ).strip()

    source = dict(row or {})
    states = {canonical: field_state(source, canonical, aliases)
              for canonical, aliases in FIELD_ALIASES.items()}
    data['_field_states'] = states
    for canonical, state in states.items():
        if state['state'] in ('present', 'empty'):
            data[canonical] = state['value']
        elif state['state'] == 'mapping_pending':
            # Preserve raw input in _source_record; do not silently choose a revision.
            data[canonical] = None

    material_code = first_non_empty(data, FIELD_ALIASES["编码"])
    data["_material_code"] = material_code
    if material_code not in (None, ""):
        if data.get("material_code") in (None, ""):
            data["material_code"] = material_code

    kzd = first_non_empty(data, FIELD_ALIASES["控制单编号"])
    if kzd not in (None, ""):
        data["kzd"] = kzd

    # 给 matcher 提供稳定的分类层级键。
    # 评分表当前至少提供 material_category + level3_category；
    # level2 若来自 API / 其他数据源也会自动兼容。
    level1 = first_non_empty(data, FIELD_ALIASES["一级分类"])
    level2 = first_non_empty(data, FIELD_ALIASES["二级分类"])
    level3 = first_non_empty(data, FIELD_ALIASES["三级分类"])
    if level1 not in (None, ""):
        data["level1_category"] = level1
    if level2 not in (None, ""):
        data["level2_category"] = level2
    if level3 not in (None, ""):
        data["level3_category"] = level3

    if raw_source:
        data["_source_table"] = raw_source
        data["source_table"] = raw_source
        data["_table_name"] = raw_source
    data.setdefault("_source_record", dict(row or {}))
    return data


def resolve_code_score_tables(conn) -> list[str]:
    """Return one existing physical table for each logical code-list table."""
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        rows = cur.fetchall() or []

    existing = set()
    for row in rows:
        if isinstance(row, dict):
            existing.update(str(value) for value in row.values())
        elif isinstance(row, (tuple, list)) and row:
            existing.add(str(row[0]))

    resolved = []
    for candidates in TABLE_NAME_GROUPS:
        selected = next((name for name in candidates if name in existing), "")
        if selected:
            resolved.append(selected)
    return resolved


def is_code_score_table(table_name: Any) -> bool:
    return str(table_name or "").strip() in CODE_SCORE_TABLE_NAMES
