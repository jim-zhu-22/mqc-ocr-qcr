"""No global credentials and no implicit fallback to a network model."""
import re


def evaluate_semantic_assertion(dsl, material):
    return {"passed": None, "reason": "未配置语义执行器，待核实计0分", "evidence_fields": [], "confidence": None}


def identity_check(material, catalog, expected, unique=False):
    expected = expected if isinstance(expected, dict) else {}
    model_fields = expected.get("model_fields") or ["model", "spec_model"]
    params = expected.get("parameter_fields") or []
    values = material.get("key_parameters") or {}
    missing = [key for key in params if values.get(key) is None or str(values.get(key)).strip() == ""]
    models = {str(material[k]).strip() for k in model_fields if material.get(k) is not None and str(material[k]).strip()}
    if not models:
        for field in ("cn_description", "cn_po_text", "en_description", "en_po_text"):
            models.update(re.findall(r"\[([^\[\]]+)\]", str(material.get(field) or "")))
        models.discard("UNK")
    trace = {"model_values": sorted(models), "required_parameters": params, "missing_parameters": missing, "catalog_available": bool(catalog)}
    if len(models) > 1:
        return None, "型号字段冲突，待核实", trace
    if not catalog or not isinstance(catalog.get("references"), list):
        return None, "缺少身份参考库，不能验证完整型号或唯一设备", trace
    refs = catalog["references"]
    mid = {(str(r.get("canonical_manufacturer", "")), str(r.get("model", ""))) for r in refs if models and r.get("model") in models}
    pid = {(str(r.get("canonical_manufacturer", "")), str(r.get("model", ""))) for r in refs if params and not missing and all(str(r.get("key_parameters", {}).get(k)) == str(values[k]) for k in params)}
    trace.update(model_candidates=[list(x) for x in sorted(mid)], parameter_candidates=[list(x) for x in sorted(pid)])
    complete = bool(mid) or bool(params and not missing)
    if not unique:
        return complete, "完整型号或全部规定参数已具备" if complete else "没有已验证完整型号，规定参数不完整", trace
    if len(mid) == 1 and len(pid) == 1 and mid != pid:
        return None, "型号与参数指向不同设备，待核实", trace
    if len(mid) == 1 or len(pid) == 1:
        return True, "型号或完整参数组合确定唯一设备", trace
    if len(mid) > 1 or len(pid) > 1:
        return False, "识别信息对应多个设备", trace
    return None, "参考库中无匹配或识别信息不足，待核实", trace
