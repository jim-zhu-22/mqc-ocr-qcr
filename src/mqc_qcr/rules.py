import json
import re
from pathlib import Path
from .client import parse_json
from .contracts import Rule

PROMPTS = Path(__file__).parent / "prompts"
OPERATORS = {"required", "exists", "equals", "contains", "starts_with", "ends_with", "regex", "required_any", "required_all", "regex_any", "source_consistent", "semantic_assertion", "identification_complete", "identity_unique", "UNKNOWN"}


def photo_rule(rule):
    return bool(re.search(r"照片|photo(?:graph)?", rule.get("rule_title", ""), re.I))


def normalize_rules(raw, sections):
    section_map = {s["section"]: s for s in sections}
    items = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("规则响应必须包含非空rules数组")
    normalized, excluded = [], []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError("规则必须是JSON对象")
        if photo_rule(item):
            excluded.append({"rule": item, "reason": "照片说明不参与四性评分"})
            continue
        refs = item.get("source_sections", [])
        if not refs or any(x not in section_map for x in refs):
            raise ValueError(f"第{index}条规则引用了不存在或空的章节")
        data = {k: item[k] for k in ("quality_type", "rule_title", "rule_text", "material_entity", "condition_text", "source_sections") if k in item}
        data.update(id=f"R{index:04d}", source_pages=sorted({p for s in refs for p in section_map[s]["pages"]}))
        normalized.append(Rule.model_validate(data).model_dump())
    if not normalized:
        raise ValueError("排除照片后没有可用评分规则")
    return normalized, excluded


def normalize_checks(items, quality):
    if not isinstance(items, list) or not items:
        raise ValueError("编译响应缺少非空checks数组")
    checks = []
    for item in items:
        if not isinstance(item, dict) or not item.get("field_name") or not item.get("operator"):
            raise ValueError("每个IR检查须含field_name和operator")
        check = {k: item.get(k, "") for k in ("field_name", "operator", "expected_value", "semantic")}
        check["operator"] = str(check["operator"]).strip()
        if check["operator"] not in OPERATORS:
            check.update(operator="UNKNOWN", semantic="不支持的操作符，需人工修订")
        if quality == "COMPLETENESS" and check["operator"] == "semantic_assertion":
            check.update(operator="UNKNOWN", semantic="完整性必须使用确定性检查，禁止模型评分")
        if check["operator"] in ("identity_unique", "identification_complete"):
            value = check["expected_value"]
            if isinstance(value, str):
                value = parse_json(value)
            if not isinstance(value, dict) or not isinstance(value.get("parameter_fields", []), list) or not isinstance(value.get("model_fields", []), list):
                raise ValueError("身份检查须提供结构化model_fields / parameter_fields")
            check["expected_value"] = value
        if check["operator"] in ("regex", "regex_any"):
            try:
                re.compile(str(check["expected_value"]))
            except re.error:
                check.update(operator="UNKNOWN", semantic="无效正则表达式，需人工修订")
        checks.append(check)
    return checks


def compile_rules(rules, sections, document_id, client=None, on_progress=None):
    ir, dsl, errors = [], [], []
    section_map = {s["section"]: s for s in sections}
    for rule in rules:
        if not rule["enabled"] or photo_rule(rule):
            continue
        try:
            if rule.get("checks"):
                checks = normalize_checks(rule["checks"], rule["quality_type"])
            elif client:
                payload = {"rule": rule, "source": [section_map[x] for x in rule["source_sections"]]}
                raw = client.call((PROMPTS / "compile_v1.txt").read_text(encoding="utf-8") + json.dumps(payload, ensure_ascii=False), tag="compile:" + rule["id"])
                parsed = parse_json(raw)
                checks = normalize_checks(parsed.get("checks"), rule["quality_type"])
            else:
                raise ValueError("无已编辑检查或已配置文本模型，无法编译")
        except Exception as exc:
            errors.append({"rule_id": rule["id"], "code": getattr(exc, "code", "COMPILE_FAILED"), "message": str(exc) if isinstance(exc, ValueError) else "模型编译失败，请查看原始调用产物"})
            checks = [{"field_name": "UNKNOWN", "operator": "UNKNOWN", "expected_value": "", "semantic": "编译失败，待核实计0分"}]
        ir.append({"source_rule_id": rule["id"], "quality_type": rule["quality_type"], "semantic_items": checks, "source_pages": rule["source_pages"]})
        for index, check in enumerate(checks, 1):
            dsl.append({**check, "dsl_id": f"{rule['id']}.{index}", "rule_id": document_id, "source_rule_id": rule["id"], "rule_title": rule["rule_title"], "quality_type": rule["quality_type"], "material_entity": rule["material_entity"], "condition_text": rule["condition_text"], "source_text": rule["rule_text"], "source_type": rule["source_type"], "source_sections": rule["source_sections"], "source_pages": rule["source_pages"], "rule_weight": rule["weight"], "execution_status": "pending_review" if check["operator"] == "UNKNOWN" else "ready"})
        if on_progress:
            on_progress(ir, dsl, errors)
    return ir, dsl, errors
