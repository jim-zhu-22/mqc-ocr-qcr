import copy
import json
import math
import httpx
from .client import parse_json
from .contracts import DIMENSIONS, Endpoint
from .semantic import identity_check
from .synthetic_identity import evaluate_semantic_assertion as synthetic_semantic
from .vendor.rule_engine import RuleScoringEngine


class MLResponseError(ValueError):
    def __init__(self, message, http_status=None, raw_response=None):
        super().__init__(message)
        self.http_status = http_status
        self.raw_response = raw_response


def ml_evidence(dimension, material, config):
    """Explicit HTTP bridge to an externally deployed, identified trained model."""
    endpoint = Endpoint.model_validate(config.get("endpoint", {}))
    if not endpoint.base_url:
        raise ValueError("启用ML时必须配置证据服务URL")
    headers = {}
    if endpoint.api_key.get_secret_value():
        headers["Authorization"] = "Bearer " + endpoint.api_key.get_secret_value()
    with httpx.Client(timeout=endpoint.timeout_seconds, trust_env=False, follow_redirects=False) as client:
        response = client.post(endpoint.base_url, headers=headers, json={"dimension": dimension, "material": material})
        if response.status_code != 200:
            raise MLResponseError("ML服务HTTP错误", response.status_code, response.text)
        try:
            value = response.json()
        except ValueError:
            raise MLResponseError("ML服务返回非法JSON", response.status_code, response.text) from None
    if not isinstance(value, dict):
        raise MLResponseError("ML服务返回值必须为对象", response.status_code, response.text)
    score = value.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1 or not value.get("model_version") or not value.get("evidence"):
        raise MLResponseError("ML服务需返回0到1分数、model_version及evidence", response.status_code, response.text)
    if dimension == "uniqueness" and value.get("semantics") != "identity_determinacy":
        raise MLResponseError("唯一性ML证据必须明确identity_determinacy语义，跨记录查重模型不可替代", response.status_code, response.text)
    value["raw_response"] = response.text
    return value


def score_records(dsl, payload, client=None, replay=False, on_progress=None):
    results = []
    for index, original in enumerate(payload.materials):
        material = copy.deepcopy(original)
        traces = {}

        def semantic(rule, record):
            if replay and rule.get("offline_handler"):
                result = synthetic_semantic(rule, record)
                traces[rule["dsl_id"]] = record.get("_semantic_trace", {}).get(str(rule["source_rule_id"]), {})
                return result
            if rule["quality_type"] == "COMPLETENESS":
                return {"passed": None, "reason": "完整性禁止模型评分；请改为确定性检查"}
            if not client:
                return {"passed": None, "reason": "语义规则缺少文本模型配置，待核实计0分"}
            prompt = '仅基于规则和物料中已提供证据判断，不推测外部事实。输出JSON {"passed":true/false/null,"reason":"具体依据或缺少证据原因","evidence_fields":[]}。null表示待核实，计0分。数据：\n'
            raw = client.call(prompt + json.dumps({"rule": rule, "material": record}, ensure_ascii=False), tag=f"score:{index}:{rule['dsl_id']}")
            value = parse_json(raw)
            if not isinstance(value, dict) or (value.get("passed") is not None and type(value.get("passed")) is not bool) or not value.get("reason"):
                raise ValueError("语义评分响应格式无效")
            return value

        engine = RuleScoringEngine(semantic_evaluator=semantic)
        details = []
        for rule in dsl:
            entity = str(material.get("material_entity") or material.get("level3_category") or "").strip().casefold()
            target = rule.get("material_entity", "").strip().casefold()
            different_entity = bool(entity and target and entity != target)
            # Explicit structured entity is authoritative; missing identity remains pending (zero).
            try:
                if rule["operator"] in ("identity_unique", "identification_complete"):
                    probe = {**rule, "operator": "semantic_assertion"}
                    def identity_evaluator(r, m):
                        passed, reason, trace = identity_check(m, payload.catalog, rule["expected_value"], rule["operator"] == "identity_unique")
                        traces[rule["dsl_id"]] = trace
                        return {"passed": passed, "reason": reason}
                    detail = RuleScoringEngine(semantic_evaluator=identity_evaluator).evaluate(probe, material)
                    detail["operator"] = rule["operator"]
                else:
                    executable = {**rule}
                    if isinstance(executable.get("expected_value"), (dict, list)):
                        executable["expected_value"] = json.dumps(executable["expected_value"], ensure_ascii=False)
                    detail = engine.evaluate(executable, material)
            except Exception:
                detail = {**rule, "passed": None, "reason": "规则执行失败；输入或DSL需核实，计0分", "applicability": {}}
            excluded = different_entity or detail.get("applicability", {}).get("condition_state") is False
            score = 1 if not excluded and detail.get("passed") is True else 0
            result = "EXCLUDED" if excluded else "PASS" if score else "ZERO"
            item = {k: detail.get(k) for k in ("rule_id", "source_rule_id", "quality_type", "material_entity", "rule_title", "field_name", "source_field_name", "operator", "expected_value", "actual_value", "reason", "rule_weight")}
            item.update(dsl_id=rule["dsl_id"], included_in_score=not excluded, score=score, result=result, verification="passed" if score else "not_applicable" if excluded else "failed" if detail.get("passed") is False else "unverified", source_pages=rule.get("source_pages", []), source_sections=rule.get("source_sections", []), source_text=rule.get("source_text", ""))
            if different_entity:
                item["reason"] = "已确认物料实体与规则对象不同，不进分母"
            if rule["dsl_id"] in traces:
                item["execution_evidence"] = traces[rule["dsl_id"]]
            details.append(item)
        scores, counts, reasons, evidence = {}, {}, {}, {}
        for dimension in DIMENSIONS:
            checks = [d for d in details if d["quality_type"] == dimension.upper() and d["included_in_score"]]
            denominator = sum(d["rule_weight"] for d in checks)
            score = round(sum(d["rule_weight"] * d["score"] for d in checks) / denominator, 4) if denominator else 0.0
            counts[dimension] = len(checks)
            reasons[dimension] = "按适用规则权重汇总；通过得分，其余计0分" if denominator else "没有适用规则，按数值策略记0分"
            cfg = payload.ml.get(dimension)
            if cfg and cfg.get("enabled"):
                try:
                    ev = ml_evidence(dimension, original, cfg)
                    weight = cfg.get("weight", 0)
                    blended = round(score * (1 - weight) + ev["score"] * weight, 4)
                    # Original accuracy adapter caps ML fusion at the deterministic score.
                    score = min(score, blended) if dimension == "accuracy" else blended
                    evidence[dimension] = {"status": "completed", "weight": weight, "response": ev}
                except Exception as exc:
                    weight = cfg.get("weight", 0)
                    score = round(score * (1 - weight), 4)
                    evidence[dimension] = {"status": "failed", "weight": weight, "score": 0, "reason": "ML证据服务未返回有效且可追溯结果，启用的证据计0分"}
                    if isinstance(exc, MLResponseError):
                        evidence[dimension].update(reason=str(exc), http_status=exc.http_status, raw_response=exc.raw_response)
            scores[dimension] = score
        scores["final"] = round(sum(scores[d] * payload.dimension_weights[d] for d in DIMENSIONS) / sum(payload.dimension_weights.values()), 4)
        result = {"sample_id": str(original.get("sample_id", index + 1)), "material_code": original.get("material_code", ""), "scores_0_to_1": scores, "included_rule_counts": counts, "dimension_reasons": reasons, "ml_evidence": evidence, "details": details}
        results.append(result)
        if on_progress:
            on_progress(results)
    return results
