import pytest
from mqc_qcr.contracts import ScoreInput
from mqc_qcr.scoring import score_records
from mqc_qcr.semantic import identity_check
from mqc_qcr.rules import normalize_checks


def rule(**extra):
    return {"dsl_id":"R1.1", "rule_id":"DOC", "source_rule_id":"R1", "quality_type":"NECESSITY", "rule_title":"编码必填", "field_name":"material_code", "operator":"required", "expected_value":"true", "material_entity":"", "condition_text":"", "rule_weight":1, **extra}


def test_fail_unverified_zero_excluded_removed_and_weights():
    rules=[rule(),rule(dsl_id="R2.1",material_entity="Other",rule_weight=100),rule(dsl_id="R3.1",operator="UNKNOWN",rule_weight=3)]
    result=score_records(rules,ScoreInput(materials=[{"kzd":"DOC","material_code":"A","material_entity":"Equipment"}]))[0]
    assert result["scores_0_to_1"]["necessity"]==0.25
    assert result["scores_0_to_1"]["final"]==0.0625
    assert [d["result"] for d in result["details"]]==["PASS","EXCLUDED","ZERO"]
    assert all(type(v) is float for v in result["scores_0_to_1"].values())


def test_identity_determinacy_is_not_cross_record_code_dedup():
    cfg={"model_fields":["model","spec_model"],"parameter_fields":["size","range"]}
    catalog={"references":[{"model":"M1","canonical_manufacturer":"A","key_parameters":{"size":1,"range":2}}]}
    material={"model":"M1","material_code":"DUPLICATE"}
    assert identity_check(material,catalog,cfg,True)[0] is True
    assert identity_check({"key_parameters":{"size":1}},catalog,cfg)[0] is False
    assert identity_check({"key_parameters":{"size":1,"range":2}},catalog,cfg,True)[0] is True
    assert identity_check({"model":"M1","spec_model":"M2"},catalog,cfg,True)[0] is None
    assert identity_check(material,{},cfg,True)[0] is None


def test_completeness_never_calls_model_and_ml_rejected():
    checks=normalize_checks([{"field_name":"model","operator":"semantic_assertion"}],"COMPLETENESS")
    assert checks[0]["operator"]=="UNKNOWN"
    class Client:
        def call(self,*args,**kwargs):
            raise AssertionError("must not call")
    result=score_records([rule(quality_type="COMPLETENESS",operator="semantic_assertion")],ScoreInput(materials=[{"kzd":"DOC"}]),Client())
    assert result[0]["scores_0_to_1"]["completeness"]==0
    with pytest.raises(ValueError):
        ScoreInput(materials=[{}],ml={"completeness":{"enabled":True}})


def test_enabled_ml_evidence_is_weighted_and_failure_not_invented(monkeypatch):
    monkeypatch.setattr("mqc_qcr.scoring.ml_evidence",lambda *args:{"score":0.5,"model_version":"test-only","evidence":{"x":1}})
    payload=ScoreInput(materials=[{"kzd":"DOC","material_code":"A"}],ml={"necessity":{"enabled":True,"weight":0.4}})
    r=score_records([rule()],payload)[0]
    assert r["scores_0_to_1"]["necessity"]==0.8
    def fail(*args):
        raise RuntimeError("service unavailable")
    monkeypatch.setattr("mqc_qcr.scoring.ml_evidence",fail)
    r=score_records([rule()],payload)[0]
    assert r["scores_0_to_1"]["necessity"]==0.6 and r["ml_evidence"]["necessity"]["status"]=="failed"
