import json
import re
from .scoring_fields import FIELD_ALIASES as CONFIRMED_ALIASES, field_state
from typing import Any, Dict

from .field_mapping import FIELD_ALIASES as DATABASE_FIELD_ALIASES


CONTROL_SHEET = "CONTROL_SHEET"
FILTERED = "FILTERED"
GLOBAL = "GLOBAL"
VALID_SCOPE_TYPES = {CONTROL_SHEET, FILTERED, GLOBAL}

FIELD_ALIASES = {
    "source_table": ("source_table", "_source_table", "来源表"),
    "material_code": ("material_code", "material_no", "spare_part_code", "物料号", "物料编码"),
    "manufacturer_name": DATABASE_FIELD_ALIASES["制造商"],
    "manufacturer_code": DATABASE_FIELD_ALIASES["制造厂编码"],
    "cn_description": ("cn_description", "description_cn", "description", "中文描述", "中文名称"),
    "purchase_text": DATABASE_FIELD_ALIASES["采购订单文本（中文）"],
    "material_category": ("material_category", "物料分类", "物资分类"),
    "model": tuple(dict.fromkeys(
        DATABASE_FIELD_ALIASES["型号"] + DATABASE_FIELD_ALIASES["参考号"]
    )),
}


def normalize_control_sheet_scope_value(value: Any) -> str:
    """Normalize KZD text while preserving contains-match semantics."""
    text = str(value or "").strip().upper()
    for dash in ("–", "—", "−", "‑"):
        text = text.replace(dash, "-")
    return re.sub(r"\s+", "", text)


def normalize_scope_type(value: Any, rule_id: Any = None) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "CONTROL": CONTROL_SHEET,
        "CONTROL_SHEET": CONTROL_SHEET,
        "KZD": CONTROL_SHEET,
        "FILTER": FILTERED,
        "FILTERED": FILTERED,
        "MATERIAL": FILTERED,
        "GLOBAL": GLOBAL,
        "ALL": GLOBAL,
    }
    if text:
        normalized = aliases.get(text, text)
        if normalized not in VALID_SCOPE_TYPES:
            raise ValueError("scope_type must be CONTROL_SHEET, FILTERED, or GLOBAL")
        return normalized
    return CONTROL_SHEET if str(rule_id or "").strip() else FILTERED


def parse_scope_conditions(value: Any) -> Dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"scope_conditions must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("scope_conditions must be a JSON object")
        return parsed
    raise ValueError("scope_conditions must be an object or JSON object string")


def dump_scope_conditions(value: Any) -> str:
    return json.dumps(parse_scope_conditions(value), ensure_ascii=False, sort_keys=True)


def build_scope_descriptor(rule: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rule_id": str(rule.get("rule_id") or "").strip(),
        "scope_type": normalize_scope_type(rule.get("scope_type"), rule.get("rule_id")),
        "scope_conditions": parse_scope_conditions(rule.get("scope_conditions")),
        "material_entity": str(rule.get("material_entity") or "").strip(),
    }


def scope_matches(material: Dict[str, Any], scope: Dict[str, Any]) -> bool:
    scope_type = normalize_scope_type(scope.get("scope_type"), scope.get("rule_id"))
    if scope_type == GLOBAL:
        return True
    if scope_type == CONTROL_SHEET:
        expected = normalize_control_sheet_scope_value(scope.get("rule_id"))
        actual = normalize_control_sheet_scope_value(_confirmed_value(material, '控制单编号'))
        return bool(expected and actual and re.search(r'(?<![A-Z0-9])' + re.escape(expected) + r'(?![A-Z0-9])', actual))

    conditions = parse_scope_conditions(scope.get("scope_conditions"))
    if not conditions:
        entity = str(scope.get("material_entity") or "").strip()
        conditions = {"keywords": [entity]} if entity else {}
    if not conditions:
        return False

    mode = str(conditions.pop("match_mode", conditions.pop("_match_mode", "all")) or "all").lower()
    checks = [_condition_matches(material, field, expected) for field, expected in conditions.items()]
    return any(checks) if mode == "any" else all(checks)


def _condition_matches(material: Dict[str, Any], field: str, expected: Any) -> bool:
    if field == "keywords":
        haystack = _confirmed_context(material).lower()
        values = expected if isinstance(expected, list) else [expected]
        return any(str(value or "").strip().lower() in haystack for value in values if str(value or "").strip())

    aliases = FIELD_ALIASES.get(field, (field,))
    canonical = next((name for name, names in CONFIRMED_ALIASES.items() if field == name or field in names), None)
    value = _confirmed_value(material, canonical) if canonical else _first_value(material, aliases)
    actual = ('' if value is None else str(value)).strip().lower()
    values = expected if isinstance(expected, list) else [expected]
    expected_values = [str(value or "").strip().lower() for value in values if str(value or "").strip()]
    if not actual or not expected_values:
        return False
    if field == "source_table":
        return actual in expected_values
    return any(value in actual for value in expected_values)


def _first_value(row: Dict[str, Any], keys) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def confirm_rule_applicability(material, rule):
    """Similarity retrieves candidates; explicit scope and entity evidence authorize execution."""
    scope = dict(rule)
    has_scope = bool(scope.get('scope_type') or scope.get('rule_id'))
    if has_scope and normalize_scope_type(scope.get('scope_type'), scope.get('rule_id')) == CONTROL_SHEET:
        state = (material.get('_field_states') or {}).get('控制单编号') or field_state(material, '控制单编号')
        if state.get('state') == 'mapping_pending':
            return {'confirmed':False, 'reason':'控制单字段映射冲突，须先确认来源'}
    if has_scope and not scope_matches(material, scope):
        return {'confirmed': False, 'reason': '控制单或声明的适用范围未确认'}
    # Additional declared category/field filters also constrain control-sheet rules.
    conditions = parse_scope_conditions(scope.get('scope_conditions'))
    if conditions and normalize_scope_type(scope.get('scope_type'), scope.get('rule_id')) != FILTERED:
        if not scope_matches(material, {'scope_type': FILTERED, 'scope_conditions': conditions}):
            return {'confirmed': False, 'reason': '分类或字段适用条件不满足'}
    entity = str(scope.get('material_entity') or '').strip()
    if entity:
        entity_values = [_confirmed_value(material, key) for key in
                         ('物料描述', '物资分类', '一级分类', '二级分类', '三级分类')]
        entity_values.extend(material.get(key) for key in ('material_entity', '物料实体'))
        context = ' '.join(str(value) for value in entity_values if value not in (None, '')).lower()
        # Hierarchical labels retain all substantive levels; generic "备件" is not an entity proof.
        parts = [part.strip().lower() for part in re.split(r'[:：>]', entity) if part.strip()]
        parts = [part for part in parts if part not in ('备件', '物料', '通用')]
        if not parts or not all(part in context for part in parts):
            return {'confirmed': False, 'reason': '物料实体缺少明确对应依据：' + entity}
    return {'confirmed': True, 'reason': '控制单/声明范围及实体已核对' if has_scope else '字段规则未声明额外范围'}


def _confirmed_value(material, canonical):
    state = (material.get('_field_states') or {}).get(canonical) or field_state(material, canonical)
    return state.get('value') if state.get('state') == 'present' else ''


def _confirmed_context(material):
    # Never search raw snapshots, diagnostics, or unselected revisions as business evidence.
    values = [_confirmed_value(material, name) for name in CONFIRMED_ALIASES]
    aliases = {alias for names in CONFIRMED_ALIASES.values() for alias in names}
    selected = set((material.get('_field_selection') or {}).values())
    for key, value in material.items():
        if key.startswith('_') or key in aliases or key in selected:
            continue
        if any(key.startswith(alias + '_') for alias in aliases):
            continue
        if isinstance(value, (str, int, float, bool)):
            values.append(value)
    return ' '.join(str(value) for value in values if value not in (None, ''))
