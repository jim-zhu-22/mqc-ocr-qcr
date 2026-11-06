"""Verify portable replay without OCR/LLM/network. Prints one machine-readable result."""
import json
import tempfile
from mqc_qcr.contracts import ModelConfig, ScoreInput
from mqc_qcr.pipeline import Pipeline, read_sample, sample_input
from mqc_qcr.store import Store


def main():
    with tempfile.TemporaryDirectory(prefix="mqc-qcr-reproduce-") as directory:
        store = Store(directory)
        rid = store.create("replay", "DOC-A-0001", {})
        worker = Pipeline(store, rid, ModelConfig())
        worker.run(b"", ".pdf", "replay")
        worker.score(ScoreInput.model_validate(sample_input()), "verify", 1)
        output = store.read(rid, "scores-verify.json")["data"]
        expected = read_sample("expected_scores.json")
        assert len(output["results"]) == len(expected) == 50
        for a, e in zip(output["results"], expected):
            assert a["scores_0_to_1"] == e["scores_0_to_1"]
            assert [(d["result"],d["score"],d["included_in_score"]) for d in a["details"]] == [(d["result"],d["score"],d["included_in_score"]) for d in e["details"]]
        print(json.dumps({"status":"verified", "mode":"offline replay", **output["summary"]}))


if __name__ == "__main__":
    main()
