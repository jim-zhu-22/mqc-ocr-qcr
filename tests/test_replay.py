from mqc_qcr.contracts import ModelConfig, ScoreInput
from mqc_qcr.pipeline import Pipeline, read_sample, sample_input
from mqc_qcr.store import Store
from mqc_qcr.sections import split_sections


def test_50_records_650_checks_250_numeric_scores(tmp_path):
    store = Store(tmp_path)
    rid = store.create("replay", "DOC-A-0001", {})
    pipeline = Pipeline(store, rid, ModelConfig())
    pipeline.run(b"", ".pdf", "replay")
    assert store.read(rid, "run.json")["status"] == "completed"
    pipeline.score(ScoreInput.model_validate(sample_input()), "verify", 1)
    result = store.read(rid, "scores-verify.json")["data"]
    assert result["summary"] == {"records": 50, "rule_checks": 650, "numeric_scores": 250, "ml_enabled": []}
    for actual, expected in zip(result["results"], read_sample("expected_scores.json")):
        assert actual["scores_0_to_1"] == expected["scores_0_to_1"]
        for a, e in zip(actual["details"], expected["details"]):
            for key in ("result", "score", "included_in_score", "source_rule_id", "rule_weight"):
                assert a[key] == e[key]
            assert a["source_pages"]
    assert not list(store.directory(rid).glob("*calls*"))


def test_section_regressions_preserve_lists_fractions_and_42():
    parsed = split_sections(read_sample("ocr.json")["pages"])
    sections = {s["section"]: s for s in parsed["sections"]}
    assert set(sections) == {"front", "1", "2", "3", "4", "4.1", "4.2", "4.3", "5", "6", "7"}
    assert "1. 完整的型号信息" in sections["4.2"]["content"]
    assert "2. 或提供所有的参数信息" in sections["4.2"]["content"]
    assert "Process connection 1/2 NPT" in sections["4.3"]["content"]
    assert sections["4"]["content"] == ""
    assert sections["4.2"]["pages"] == [3]
    assert sections["4.3"]["pages"] == [3]
    assert sections["5"]["pages"] == [4]
    assert all("1/2" not in row["text"] for row in parsed["removed_lines"])
