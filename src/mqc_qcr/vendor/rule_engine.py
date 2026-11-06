import json
import re

from .condition_sanitizer import sanitize_runtime_condition
from ..semantic import evaluate_semantic_assertion
from .field_mapping import merge_field_aliases
from .scoring_fields import field_state
from .rule_scope import confirm_rule_applicability


QUALITY_TYPES = [
    "NECESSITY",
    "COMPLETENESS",
    "ACCURACY",
    "UNIQUENESS",
]


FIELD_ALIASES = {
    "编码": ("编码", "material_code", "material_no", "物料号", "物料编码", "备件编码"),
    "物料描述": ("物料描述", "cn_description", "中文描述", "中文名称", "description_cn"),
    "制造商": ("制造商", "制造厂", "制造厂名称", "manufacturer_name", "manufacturer"),

    "规格型号": (
        "规格型号", "型号", "model", "spec_model", "specification_model", "规格",
    ),
    "型号": (
        "型号", "规格型号", "model", "spec_model", "specification_model", "规格",
    ),
    "额定电压": (
        "额定电压", "rated_voltage", "voltage", "ratedVoltage",
    ),
    "参考号": (
        "参考号", "制造厂参考号", "制造商参考号", "制造商零件编号",
        "厂家零件编号", "mfr_ref_no", "manufacturer_ref_no",
        "manufacturer_part_no", "part_no", "reference_no", "reference_number",
    ),
    "制造商零件编号": (
        "制造商零件编号", "制造厂零件编号", "厂家零件编号", "参考号",
        "manufacturer_part_no", "mfr_part_no", "part_no",
    ),
    "RIN码": (
        "RIN码", "RIN 码", "rin", "rin_code", "RIN",
    ),
    "图纸号": (
        "图纸号", "电厂制造厂图号", "电厂制造厂图纸号", "drawing_no",
        "plant_drawing_no", "plant_manufacturer_drawing_no",
    ),
    "图项号": (
        "图项号", "电厂制造厂图项号", "drawing_item_no", "drawing_position_no",
        "plant_drawing_item_no", "plant_manufacturer_drawing_item_no",
    ),
    "内部批注": ("内部批注", "internal_comment", "internal_remark", "internal_remarks", "remark", "备注"),
    "检验文本": ("检验文本", "inspection_text", "inspection_description"),
    "基本物料": ("基本物料", "base_material", "basic_material"),
    "阀体材料": ("阀体材料", "valve_body_material", "body_material", "material_texture", "材质"),
    "采购订单文本（中文）": (
        "采购订单文本（中文）", "采购订单文本", "采购文本", "cn_po_text",
        "purchase_text", "purchase_order_text_cn",
    ),
}

FIELD_ALIASES = merge_field_aliases(FIELD_ALIASES)

COMBINED_DESCRIPTION_FIELD = "物料描述（中文）或采购订单文本（中文）"
COMPOSITE_DRAWING_FIELD = "图纸号+图项号"
KEY_PARAMETER_FIELD = "关键识别参数"

FIELD_ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in FIELD_ALIASES.items()
    for alias in aliases
}

SEMANTIC_FIELD_WORDS = (
    "阀门名称", "RIN码", "RIN 码", "图纸号", "图号", "图项号", "型号",
    "制造商", "制造厂", "物料描述", "中文描述", "字段",
)


class RuleScoringEngine:

    def __init__(self, uniqueness_checker=None, semantic_evaluator=None):

        self.uniqueness_checker = uniqueness_checker
        self.semantic_evaluator = semantic_evaluator or evaluate_semantic_assertion

    def evaluate(self, dsl, material_data):

        source_field_name = str(dsl.get("field_name") or "").strip()

        field_name = canonical_field_name(source_field_name)

        quality_type = str(dsl.get("quality_type") or "").upper().strip()

        operator = (dsl.get("operator") or "").lower().strip()

        expected = normalize_expected_value(field_name, dsl.get("expected_value", ""))

        actual, actual_field_name = resolve_material_value(material_data, field_name)

        raw_condition_text = str(dsl.get("condition_text") or "").strip()
        condition_text = sanitize_runtime_condition(
            raw_condition_text,
            material_entity=dsl.get("material_entity", ""),
        )
        condition_state, condition_reason = evaluate_condition_applicability(
            condition_text,
            material_data,
            dsl.get("material_entity", ""),
        )
        if operator == "conditional_required" and not condition_text and not raw_condition_text:
            condition_state = None
            condition_reason = "条件必填规则缺少可判断的适用条件"

        applicability = confirm_rule_applicability(material_data, dsl)
        alternative_operators = {'required_any', 'any_of', 'one_of', 'alternative', 'alternative_group'}
        group_operators = alternative_operators | {'required_all', 'all_of', 'field_group', 'unique', 'cross_record_unique', 'composite_unique'}
        fields = extract_completeness_fields(dsl, field_name, expected) if operator in group_operators else [field_name]
        states = [material_field_state(material_data, name) for name in fields]
        state = 'present'
        if any(item['state'] == 'mapping_pending' for item in states):
            state = 'mapping_pending'
        elif any(item['state'] == 'missing_column' for item in states):
            state = 'missing_column'
        elif any(item['state'] == 'empty' for item in states):
            state = 'empty'
        if not applicability['confirmed']:
            condition_state, condition_reason = None, applicability['reason']
        elif operator not in ('semantic_assertion', 'informational', 'optional') and state in ('mapping_pending', 'missing_column'):
            # required_any may pass if an available alternative supplies the evidence.
            has_alternative = operator in alternative_operators and any(item['state'] == 'present' for item in states)
            if has_alternative:
                state = 'present'
            else:
                condition_state = None
                condition_reason = ('字段映射待确认：' if state == 'mapping_pending' else '未上传规则所需字段，无法判断单元格是否缺失：') + '、'.join(item['field_name'] for item in states if item['state'] in ('mapping_pending', 'missing_column'))
        if condition_state is False:
            state = 'not_applicable'
        semantic_result = None
        if condition_state is True and operator == "semantic_assertion":
            try:
                semantic_result = self.semantic_evaluator(dsl, material_data)
            except Exception as exc:
                semantic_result = {
                    "passed": None,
                    "reason": f"语义规则执行失败，待核实计0分: {exc}",
                    "evidence_fields": [],
                    "confidence": 0.0,
                }

        if quality_type == "UNIQUENESS" and operator in {
            "required", "exists", "conditional_required", "required_any",
            "required_all", "source",
        }:
            passed = None
            reason = (
                "唯一性不按字段缺失评分；"
                "应通过相似编码/重复编码检查判断"
            )
        else:
            passed = None
            reason = ""

        invalid_reason = invalid_dsl_reason(field_name, operator, expected)
        if reason:
            pass
        elif condition_state is not True:
            passed = None
            reason = condition_reason
        elif semantic_result is not None:
            passed = semantic_result["passed"]
            actual_field_name = " / ".join(semantic_result.get("evidence_fields") or [])
            actual = actual_field_name or "语义证据"
            reason = semantic_result["reason"]
        elif invalid_reason:
            passed = None
            reason = invalid_reason
        elif operator in ("unique", "cross_record_unique", "composite_unique"):
            passed, actual, actual_field_name, reason = self._execute_uniqueness(
                dsl, material_data, field_name, expected
            )
        elif operator == "source_consistent":
            passed, reason = evaluate_source_consistency(dsl, material_data, field_name, actual)
        elif quality_type == "COMPLETENESS":
            passed, actual, actual_field_name, reason = self._execute_completeness(
                dsl=dsl,
                material_data=material_data,
                field_name=field_name,
                operator=operator,
                expected=expected,
            )
        else:
            passed = self._execute(operator, actual, expected, field_name)
            reason = self._reason(field_name, operator, expected, actual, passed)


        return {
            # =========================
            # DSL基础信息
            # =========================
            "applicability": {**applicability, "condition_state": condition_state},
            "field_state": state,
            "field_sources": states,
            "dsl_id": dsl.get("dsl_id"),
            "source_rule_id": dsl.get("source_rule_id"),
            "rule_id": dsl.get("rule_id"),
            "rule_name": dsl.get("rule_name"),
            # =========================
            # ⭐新增
            # 保存实体层级
            # =========================
            "material_entity": dsl.get("material_entity", ""),
            "quality_type": quality_type,
            "field_name": field_name,
            "source_field_name": source_field_name,
            "actual_field_name": actual_field_name,
            "operator": operator,
            "expected_value": expected,
            "actual_value": actual,
            "passed": passed,
            "reason": reason,
            "missing_fields": completeness_missing_fields(dsl, material_data, field_name)
                if quality_type == "COMPLETENESS" and passed is False else [],
            "rule_title": dsl.get("rule_title", ""),
            "rule_text": dsl.get("rule_text", ""),
            "source_type": dsl.get("source_type", "extracted"),
            "rule_weight": float(dsl.get("rule_weight", 1.0)),
            "semantic_confidence": (
                semantic_result.get("confidence") if semantic_result is not None else None
            ),
            "semantic_evidence_fields": (
                semantic_result.get("evidence_fields") if semantic_result is not None else []
            ),
        }


    def _execute_uniqueness(self, dsl, material, field_name, expected):
        fields = [canonical_field_name(part) for part in split_candidate_fields(field_name)]
        fields = list(dict.fromkeys(fields))
        values = [resolve_material_value(material, field) for field in fields]
        missing = [field for field, (value, _) in zip(fields, values) if is_empty_value(value)]
        actual = json.dumps([value for value, _ in values], ensure_ascii=False, default=str)
        actual_fields = " / ".join(name for _, name in values)
        if missing or not fields:
            return None, actual, actual_fields, "唯一性证据不足，缺少组合字段：" + "、".join(missing)
        if self.uniqueness_checker is None:
            return None, actual, actual_fields, "唯一性证据不足：没有可用的判重结果"
        # Preserve the existing three-argument checker contract. The checker is
        # backed by the material's duplicate model / candidate-pool evidence.
        checked_actual = values[0][0] if len(values) == 1 else actual
        passed = self.uniqueness_checker(field_name, checked_actual, expected)
        if passed is None:
            reason = "唯一性证据不足：判重器暂时无法判断"
        else:
            reason = "组合字段已完整取值，判重通过" if passed else "组合字段已完整取值，存在重复风险"
        return passed, checked_actual, actual_fields, reason


    def _execute_completeness(
        self,
        dsl,
        material_data,
        field_name,
        operator,
        expected,
    ):
        """
        完整性专用评分执行器。

        True/False 参与评分；
        None 只用于 optional / informational / 无法可靠执行的 DSL。
        """

        operator = str(operator or "").lower().strip()

        if operator in ("optional", "informational"):
            actual, actual_field_name = resolve_material_value(
                material_data,
                field_name,
            )
            return (
                None,
                actual,
                actual_field_name,
                f"{field_name} 为可选/说明性字段，不参与完整性评分",
            )

        if operator in ("required", "exists", "conditional_required"):
            actual, actual_field_name = resolve_material_value(
                material_data,
                field_name,
            )
            passed = not is_empty_value(actual)
            reason = (
                f"{field_name} 已填写"
                if passed
                else f"{field_name} 缺失或为空"
            )
            return passed, actual, actual_field_name, reason

        candidate_fields = extract_completeness_fields(
            dsl=dsl,
            field_name=field_name,
            expected=expected,
        )

        if operator in (
            "required_any",
            "any_of",
            "one_of",
            "alternative",
            "alternative_group",
        ):
            if not candidate_fields:
                return self._unsupported_completeness(
                    dsl,
                    field_name,
                    operator,
                    expected,
                    "",
                    field_name,
                    "未解析到候选字段",
                )

            values = []
            actual_fields = []

            for candidate in candidate_fields:
                value, actual_field = resolve_material_value(
                    material_data,
                    candidate,
                )
                values.append(value)
                actual_fields.append(actual_field)

            passed = any(
                not is_empty_value(value)
                for value in values
            )

            actual = " || ".join(
                display_value_for_engine(value)
                for value in values
            )

            reason = (
                "至少一个候选字段已填写"
                if passed
                else "以下候选字段至少需要填写一个："
                + "、".join(candidate_fields)
            )

            return (
                passed,
                actual,
                " / ".join(actual_fields),
                reason,
            )

        if operator in (
            "required_all",
            "all_of",
            "field_group",
        ):
            if not candidate_fields:
                return self._unsupported_completeness(
                    dsl,
                    field_name,
                    operator,
                    expected,
                    "",
                    field_name,
                    "未解析到候选字段",
                )

            values = []
            actual_fields = []

            for candidate in candidate_fields:
                value, actual_field = resolve_material_value(
                    material_data,
                    candidate,
                )
                values.append(value)
                actual_fields.append(actual_field)

            passed = bool(values) and all(
                not is_empty_value(value)
                for value in values
            )

            missing_fields = [
                candidate
                for candidate, value in zip(candidate_fields, values)
                if is_empty_value(value)
            ]

            actual = " || ".join(
                display_value_for_engine(value)
                for value in values
            )

            reason = (
                "全部必填字段均已填写"
                if passed
                else "缺失字段：" + "、".join(missing_fields)
            )

            return (
                passed,
                actual,
                " / ".join(actual_fields),
                reason,
            )

        generic_operators = {
            "equals",
            "not_equals",
            "contains",
            "starts_with",
            "ends_with",
            "regex",
            "regex_any",
            "source",
        }

        actual, actual_field_name = resolve_material_value(
            material_data,
            field_name,
        )

        if operator in generic_operators:
            passed = self._execute(
                operator,
                actual,
                expected,
                field_name,
            )
            reason = self._reason(
                field_name,
                operator,
                expected,
                actual,
                passed,
            )
            return passed, actual, actual_field_name, reason

        return self._unsupported_completeness(
            dsl,
            field_name,
            operator,
            expected,
            actual,
            actual_field_name,
        )

    def _unsupported_completeness(
        self,
        dsl,
        field_name,
        operator,
        expected,
        actual,
        actual_field_name,
        extra_reason="",
    ):
        print(
            "[COMPLETENESS UNSUPPORTED DSL] "
            f"dsl_id={dsl.get('dsl_id')} | "
            f"source_rule_id={dsl.get('source_rule_id')} | "
            f"field={field_name} | "
            f"operator={operator} | "
            f"expected={expected} | "
            f"reason={extra_reason}",
            flush=True,
        )

        reason = f"{field_name} 未执行有效的 {operator} 完整性检查"
        if extra_reason:
            reason += f"：{extra_reason}"

        return None, actual, actual_field_name, reason

    def _execute(self, operator, actual, expected, field_name=""):

        actual_text = "" if actual is None else str(actual)

        expected_text = "" if expected is None else str(expected)

        if operator == "optional":
            return None

        if operator == "informational":
            return None

        if operator in ("required", "exists", "required_any"):
            return actual_text.strip() != ""

        if operator == "required_all":
            values = actual_text.split("||")
            return bool(values) and all(value.strip() for value in values)

        if operator == "equals":
            return actual_text == expected_text

        if operator == "not_equals":
            return actual_text != expected_text

        if operator == "contains":

            return expected_text in actual_text

        if operator == "starts_with":

            return actual_text.startswith(expected_text)

        if operator == "ends_with":

            return actual_text.endswith(expected_text)

        if operator == "regex":
            try:
                return re.search(expected_text, actual_text) is not None
            except re.error:
                return None

        if operator == "regex_any":
            try:
                return re.search(expected_text, actual_text) is not None
            except re.error:
                return None

        if operator == "source":

            return actual_text.strip() != ""

        if operator in ("unique", "cross_record_unique", "composite_unique"):

            if not actual_text.strip() or self.uniqueness_checker is None:
                return None

            return self.uniqueness_checker(field_name, actual, expected)

        return None

    def _reason(self, field_name, operator, expected, actual, passed):

        if passed is None:

            if operator == "informational":
                return f"{field_name} 为说明性规则，不参与评分"

            return f"{field_name} 未执行有效的 {operator} 检查"

        if passed:

            return f"{field_name} " f"满足 {operator} 规则"

        if operator in ("required", "exists"):

            return f"{field_name} 缺失或为空"

        return (
            f"{field_name} "
            f"不满足 {operator}，"
            f"期望={expected}，"
            f"实际={actual}"
        )


def aggregate_scores(details):

    scores = {}

    details = dedupe_scoring_details(details)

    for quality_type in QUALITY_TYPES:

        items = [
            d for d in details
            if d.get("quality_type") == quality_type and d.get("passed") is not None
        ]

        if not items:

            scores[quality_type.lower()] = None

            continue

        total_weight = sum(rule_weight(d) for d in items)

        passed_weight = sum(rule_weight(d) for d in items if d.get("passed"))

        scores[quality_type.lower()] = (
            round(passed_weight / total_weight, 4) if total_weight > 0 else None
        )

    dimension_scores = [scores[k.lower()] for k in QUALITY_TYPES]
    scores["final"] = (
        round(sum(dimension_scores) / len(dimension_scores), 4)
        if all(value is not None for value in dimension_scores)
        else None
    )

    return scores


def rule_weight(detail):

    try:

        weight = float(detail.get("rule_weight", 1.0))

    except (TypeError, ValueError):

        weight = 1.0

    return max(weight, 0.0)


def canonical_field_name(field_name):
    value = str(field_name or "").strip()
    return FIELD_ALIAS_TO_CANONICAL.get(value, value)


def evaluate_condition_applicability(condition_text, material_data, material_entity=""):
    """Determine whether a rule condition applies to the current material.

    Undecidable conditions are excluded from scoring instead of being treated
    as unconditional requirements.
    """

    text = str(condition_text or "").strip()
    if not text:
        return True, "无额外适用条件"

    compact = re.sub(r"\s+", "", text)
    if compact in {"通用", "全部", "所有物料", "无条件", "始终适用"}:
        return True, f"适用条件成立：{text}"

    material_text = " ".join(
        str(value or "")
        for key, value in material_data.items()
        if not str(key).startswith("_")
    ).lower()

    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_text = str(alias)
            if alias_text not in text:
                continue
            actual, _ = resolve_material_value(material_data, canonical)
            empty = is_empty_value(actual)
            if re.search(rf"(?:无|没有|未提供|未填写|缺少){re.escape(alias_text)}", compact):
                matched = empty
                return matched, (
                    f"适用条件成立：{text}"
                    if matched
                    else f"适用条件不成立：{alias_text}已有值"
                )
            if re.search(rf"(?:有|存在|已提供|已填写){re.escape(alias_text)}", compact):
                matched = not empty
                return matched, (
                    f"适用条件成立：{text}"
                    if matched
                    else f"适用条件不成立：{alias_text}为空"
                )

    comparison = re.search(r"([^,，;；]+?)(?:=|：|:|为)([^,，;；]+)", text)
    if comparison:
        field_token = comparison.group(1).strip(" 当若仅限适用对象字段")
        expected_token = comparison.group(2).strip(" 时的物料。.")
        actual, _ = resolve_material_value(
            material_data,
            canonical_field_name(field_token),
        )
        actual_text = str(actual or "").strip().lower()
        expected_lower = expected_token.strip().lower()
        # 已识别到明确条件字段时，只比较该字段，避免其他描述字段误命中。
        matched = bool(expected_lower) and (
            expected_lower == actual_text or expected_lower in actual_text
        )
        return matched, (
            f"适用条件成立：{text}"
            if matched
            else f"适用条件不成立：{text}"
        )

    entity = str(material_entity or "").strip().lower()
    if entity and entity in text.lower():
        matched = entity in material_text
        return matched, (
            f"适用条件成立：{text}"
            if matched
            else f"适用条件不成立：{text}"
        )

    return None, f"适用条件无法从当前物料字段可靠判断，不参与评分：{text}"


def material_field_state(material, name):
    # These are compositions, not aliases for the same value.
    alternatives = {
        COMBINED_DESCRIPTION_FIELD: ('物料描述', '采购订单文本（中文）'),
        KEY_PARAMETER_FIELD: ('关键识别参数', '物料描述', '采购订单文本（中文）', '英文描述', '基本物料'),
    }
    if name in alternatives:
        parts = [dict(field_state(material, key, FIELD_ALIASES.get(key, (key,))), field_name=key)
                 for key in alternatives[name]]
        present = [part for part in parts if part['state'] == 'present']
        state = 'present' if present else ('mapping_pending' if any(p['state'] == 'mapping_pending' for p in parts)
                else 'empty' if any(p['state'] == 'empty' for p in parts) else 'missing_column')
        return {'state':state, 'field_name':name, 'source_field':' / '.join(p['source_field'] for p in present),
                'value':' || '.join(str(p['value']) for p in present), 'candidates':parts}
    known = (material.get('_field_states') or {}).get(name)
    if known is not None:
        return dict(known, field_name=name)
    return dict(field_state(material, name, FIELD_ALIASES.get(name, (name,))), field_name=name)


def resolve_material_value(material_data, field_name):
    if field_name == COMBINED_DESCRIPTION_FIELD:
        values = []
        actual_fields = []
        for candidate in ("物料描述", "采购订单文本（中文）"):
            value, actual_field = resolve_material_value(material_data, candidate)
            if value not in (None, ""):
                values.append(str(value))
                actual_fields.append(actual_field)
        return "\n".join(values), " / ".join(actual_fields) or field_name

    if field_name == COMPOSITE_DRAWING_FIELD:
        drawing, drawing_field = resolve_material_value(material_data, "图纸号")
        item, item_field = resolve_material_value(material_data, "图项号")
        return f"{drawing or ''}||{item or ''}", f"{drawing_field} + {item_field}"

    if field_name == KEY_PARAMETER_FIELD:
        # 保留自项目版 (fix-code-quality-issues): "关键识别参数" 合成字段
        values = []
        actual_fields = []
        for candidate in (
            "中文描述",
            "英文描述",
            "采购订单文本（中文）",
            "采购订单文本（英文）",
            "基本物料",
        ):
            value, actual_field = resolve_material_value(material_data, candidate)
            if not is_empty_value(value):
                values.append(str(value).strip())
                actual_fields.append(actual_field)
        return "||".join(values), " + ".join(actual_fields) or field_name

    info = material_field_state(material_data, field_name)
    if info['state'] == 'mapping_pending':
        return None, ''
    if info['state'] in ('present', 'empty'):
        return info['value'], info['source_field']
    aliases = FIELD_ALIASES.get(field_name, (field_name,))
    found = []
    for alias in aliases:
        if alias not in material_data:
            continue
        value = material_data.get(alias)
        found.append((alias, value))
        if value not in (None, ""):
            return value, alias
    if found:
        return found[0][1], found[0][0]
    return "", field_name


def normalize_expected_value(field_name, expected):
    text = "" if expected is None else str(expected).strip()
    if field_name == "制造商":
        text = re.split(r"(?:制造厂|制造商)编码\s*[:：]", text, maxsplit=1)[0].strip()
    return text


def invalid_dsl_reason(field_name, operator, expected):
    if field_name == "编码" and operator == "contains":
        if any(word in str(expected or "") for word in SEMANTIC_FIELD_WORDS):
            return "该规则描述的是编码信息构成，不能对物料编码执行文本包含检查"
    return ""



def extract_completeness_fields(dsl, field_name, expected):
    """
    从完整性 DSL 中解析字段组。

    支持：
    - expected_value 为 list / tuple / set
    - JSON 数组字符串
    - 用 | 、 ， , ; ； + / 分隔的字段组
    - field_name 自身为组合字段
    """

    candidates = []
    raw_expected = dsl.get("expected_value")

    if isinstance(raw_expected, (list, tuple, set)):
        candidates.extend(
            str(item).strip()
            for item in raw_expected
            if str(item).strip()
        )

    elif isinstance(raw_expected, str):
        text = raw_expected.strip()

        if text.startswith("[") and text.endswith("]"):
            try:
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    candidates.extend(
                        str(item).strip()
                        for item in loaded
                        if str(item).strip()
                    )
            except Exception:
                pass

        if not candidates and text:
            parts = split_candidate_fields(text)
            if len(parts) > 1 and looks_like_field_group(parts):
                candidates.extend(parts)

    if len(candidates) <= 1:
        field_parts = split_candidate_fields(
            str(field_name or "")
        )
        if len(field_parts) > 1:
            candidates = field_parts

    if not candidates and field_name:
        candidates = [str(field_name).strip()]

    result = []

    for candidate in candidates:
        canonical = canonical_field_name(
            clean_field_token(candidate)
        )
        if canonical and canonical not in result:
            result.append(canonical)

    return result


def split_candidate_fields(text):
    text = str(text or "").strip()

    if not text:
        return []

    parts = re.split(
        r"\s*(?:\|\||\||、|，|,|；|;|\+|/)\s*",
        text,
    )

    parts = [
        clean_field_token(part)
        for part in parts
        if clean_field_token(part)
    ]

    return parts or [clean_field_token(text)]


def clean_field_token(value):
    text = str(value or "").strip()
    text = re.sub(r"^[\[\(\{【（]+", "", text)
    text = re.sub(r"[\]\)\}】）]+$", "", text)
    text = re.sub(r"^(?:字段|参数)\s*[:：]\s*", "", text)
    return text.strip()


def looks_like_field_group(parts):
    known = set(FIELD_ALIAS_TO_CANONICAL.keys()) | set(FIELD_ALIASES.keys())

    recognized = 0

    for part in parts:
        token = clean_field_token(part)
        canonical = canonical_field_name(token)
        if token in known or canonical in FIELD_ALIASES:
            recognized += 1

    return recognized >= 2


def is_empty_value(value):
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() == ""

    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0

    return False


def display_value_for_engine(value):
    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)

    if isinstance(value, dict):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        except Exception:
            return str(value)

    return str(value)


def scoring_detail_identity(detail):
    dsl_id=detail.get('dsl_id')
    if dsl_id not in (None,''):
        return ('dsl',str(dsl_id))
    return ('detail',str(detail.get('source_rule_id') or ''),str(detail.get('quality_type') or '').upper(),canonical_field_name(detail.get('field_name')),str(detail.get('operator') or '').lower(),str(detail.get('expected_value') or '').strip(),str(detail.get('material_entity') or ''))


def dedupe_scoring_details(details):
    result=[]; seen=set()
    for detail in details:
        identity=scoring_detail_identity(detail)
        if identity in seen: continue
        seen.add(identity); result.append(detail)
    return result


def build_low_indicators(scores, details, threshold=0.8):

    indicators = []

    for quality_type in QUALITY_TYPES:

        key = quality_type.lower()

        score = scores.get(key)

        if score is None:
            continue

        if score >= threshold:
            continue

        failed = [
            d
            for d in details
            if d.get("quality_type") == quality_type and d.get("passed") is False
        ]

        field_issues = build_field_issues(failed)

        indicators.append(
            {
                "quality_type": quality_type,
                "score": score,
                "failed_count": len(field_issues),
                "failed_fields": [item["field_name"] for item in field_issues],
                "material_entities": list(
                    {
                        d.get("material_entity", "")
                        for d in failed
                        if d.get("material_entity")
                    }
                ),
                "reasons": [item["reason"] for item in field_issues],
                "field_issues": field_issues,
            }
        )

    return indicators


def build_field_issues(failed_details):

    issues = []
    seen = set()

    for detail in failed_details:

        field_name = str(detail.get("field_name") or "相关字段").strip()
        missing = detail.get("missing_fields")
        if missing:
            field_name = "、".join(missing)
        operator = str(detail.get("operator") or "").lower().strip()
        expected = display_value(detail.get("expected_value"))
        actual = display_value(detail.get("actual_value"))
        material_entity = str(detail.get("material_entity") or "").strip()
        reason = customer_reason(field_name, operator, expected, actual)
        if detail.get("quality_type") == "COMPLETENESS" and detail.get("missing_fields") == []:
            reason = detail.get("reason") or reason
        action = customer_action(field_name, operator, expected)
        identity = (field_name, operator, expected, actual)

        if identity in seen:
            continue

        seen.add(identity)
        issues.append(
            {
                "field_name": field_name,
                "material_entity": material_entity,
                "actual_value": actual,
                "expected_value": expected,
                "reason": reason,
                "suggestion": action,
            }
        )

    return issues


def display_value(value, max_length=120):

    text = "" if value is None else str(value).strip()
    if not text:
        return "未填写"
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def customer_reason(field_name, operator, expected, actual):

    if operator in ("required", "exists", "source", "conditional_required", "required_any", "required_all", "any_of", "all_of", "one_of", "alternative", "alternative_group", "field_group"):
        return f"{field_name}未填写"
    if operator in ("unique", "cross_record_unique", "composite_unique"):
        return f"{field_name}存在重复风险，当前值：{actual}"
    if operator == "equals":
        return f"{field_name}填写不正确，当前值：{actual}，应为：{expected}"
    if operator == "not_equals":
        return f"{field_name}不能填写为：{expected}，当前值：{actual}"
    if operator in ("contains", "regex_any"):
        return f"{field_name}内容不完整，当前值：{actual}，应包含：{expected}"
    if operator == "starts_with":
        return f"{field_name}格式不正确，当前值：{actual}，应以“{expected}”开头"
    if operator == "ends_with":
        return f"{field_name}格式不正确，当前值：{actual}，应以“{expected}”结尾"
    return f"{field_name}需要复核，当前值：{actual}，要求：{expected}"


def customer_action(field_name, operator, expected):

    if operator in ("required", "exists", "source", "conditional_required", "required_any", "required_all", "any_of", "all_of", "one_of", "alternative", "alternative_group", "field_group"):
        return f"请补充{field_name}"
    if operator in ("unique", "cross_record_unique", "composite_unique"):
        return f"请核对{field_name}是否重复，并确认保留或合并方式"
    if operator == "equals":
        return f"请核对并将{field_name}修正为：{expected}"
    if operator == "not_equals":
        return f"请核对并修正{field_name}，该字段不能为：{expected}"
    if operator in ("contains", "regex_any"):
        return f"请补充或修正{field_name}，确保包含：{expected}"
    if operator == "starts_with":
        return f"请修正{field_name}格式，确保以“{expected}”开头"
    if operator == "ends_with":
        return f"请修正{field_name}格式，确保以“{expected}”结尾"
    return f"请根据业务资料复核并修正{field_name}"


def completeness_missing_fields(dsl, material, field_name):
    operator = str(dsl.get("operator") or "").lower().strip()
    groups = {"required_all", "all_of", "field_group", "required_any", "any_of", "one_of", "alternative", "alternative_group"}
    fields = extract_completeness_fields(dsl, field_name, dsl.get("expected_value")) if operator in groups else [field_name]
    return [field for field in fields if is_empty_value(resolve_material_value(material, field)[0])]


def evaluate_source_consistency(dsl, material, field_name, actual):
    """Compare a field against explicit source evidence; never invent evidence.

    material.source_evidence: [{"source": "EOMM", "fields": {"cn_description": "..."}}]
    expected_value: comma-separated allowed sources, or {"sources": ["EOMM"]}.
    A structured {"reference_field": "..."} explicitly selects a local reference.
    Conflicting source values remain undetermined and require human review.
    """
    expected = dsl.get("expected_value")
    if isinstance(expected, str):
        try:
            specification = json.loads(expected)
        except (ValueError, TypeError):
            specification = {"sources": [v.strip() for v in re.split(r"[,，;；|]", expected) if v.strip()]}
    else:
        specification = expected
    if isinstance(specification, list):
        specification = {"sources": specification}
    if not isinstance(specification, dict):
        return None, "来源一致性规则缺少有效的来源配置"
    allowed = specification.get("sources") or []
    if isinstance(allowed, str):
        allowed = [allowed]
    def normalize(value):
        return re.sub(r"\s+", " ", str(value)).strip()
    reference_values = []
    reference_field = specification.get("reference_field")
    if reference_field and canonical_field_name(reference_field) == field_name:
        return None, "来源配置无效：不能将待校验字段自身作为来源证据"
    if reference_field:
        value, _ = resolve_material_value(material, canonical_field_name(reference_field))
        if not is_empty_value(value):
            reference_values.append(value)
    evidence = material.get("source_evidence") or material.get("_source_evidence") or []
    if isinstance(evidence, dict):
        evidence = [{"source": source, "fields": fields} for source, fields in evidence.items()]
    if not isinstance(evidence, list):
        evidence = []
    if allowed:
        for item in evidence:
            if not isinstance(item, dict) or item.get("source") not in allowed:
                continue
            fields = item.get("fields")
            if not isinstance(fields, dict):
                continue
            value, _ = resolve_material_value(fields, field_name)
            if not is_empty_value(value):
                reference_values.append(value)
    unique_values = {normalize(value) for value in reference_values}
    if not unique_values:
        return None, "来源证据不足：未提供指定来源的字段值，不能判断一致性"
    if len(unique_values) > 1:
        return None, "指定来源的字段值互相冲突，需要人工复核"
    if is_empty_value(actual):
        return False, "待校验字段未填写，与已提供的来源字段值不一致"
    passed = normalize(actual) in unique_values
    return passed, "字段与指定来源一致" if passed else "字段与指定来源不一致"
