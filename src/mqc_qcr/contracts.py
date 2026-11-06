from typing import Any, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

DIMENSIONS = ("necessity", "completeness", "accuracy", "uniqueness")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Endpoint(Strict):
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = ""
    timeout_seconds: float = Field(default=90, ge=1, le=600)
    retries: int = Field(default=2, ge=0, le=5)
    max_tokens: int = Field(default=8192, ge=32, le=131072)

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        value = value.strip().rstrip("/")
        if value:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("API 地址须为 http(s) URL，不允许 URL 内凭据、查询参数或片段")
        return value

    def public(self):
        data = self.model_dump(exclude={"api_key"})
        data["key_configured"] = bool(self.api_key.get_secret_value())
        return data


class ModelConfig(Strict):
    ocr: Endpoint = Field(default_factory=Endpoint)
    text: Endpoint = Field(default_factory=Endpoint)


class Rule(Strict):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    quality_type: Literal["NECESSITY", "COMPLETENESS", "ACCURACY", "UNIQUENESS"]
    rule_title: str = Field(min_length=1)
    rule_text: str = Field(min_length=1)
    material_entity: str = ""
    condition_text: str = ""
    source_sections: list[str] = Field(min_length=1)
    source_pages: list[int] = Field(min_length=1)
    weight: float = Field(default=1, gt=0, le=1000)
    enabled: bool = True
    source_type: Literal["extracted", "manual", "replay"] = "extracted"
    checks: list[dict[str, Any]] = Field(default_factory=list)


class ScoreInput(Strict):
    materials: list[dict[str, Any]] = Field(min_length=1, max_length=2000)
    catalog: dict[str, Any] = Field(default_factory=dict)
    dimension_weights: dict[str, float] = Field(default_factory=lambda: dict.fromkeys(DIMENSIONS, 1.0))
    # Evidence services must be separately configured and actually called; disabled by default.
    ml: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def weights(self):
        import math
        if set(self.dimension_weights) != set(DIMENSIONS) or any(not math.isfinite(v) or v < 0 for v in self.dimension_weights.values()) or not sum(self.dimension_weights.values()):
            raise ValueError("四性权重必须齐全、非负且至少一项大于0")
        if "completeness" in self.ml:
            raise ValueError("完整性禁止接入机器学习")
        if set(self.ml) - {"necessity", "accuracy", "uniqueness"}:
            raise ValueError("未知的机器学习维度")
        for cfg in self.ml.values():
            weight = cfg.get("weight", 0)
            if not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 <= weight <= 1:
                raise ValueError("ML权重必须在0到1之间")
        return self
