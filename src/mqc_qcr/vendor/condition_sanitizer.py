import os
import re


RUNTIME_FIELD_TOKENS = (
    "型号", "规格型号", "图纸号", "图号", "图项号", "参考号",
    "制造商零件编号", "厂家零件编号", "RIN码", "RIN 码",
    "物料描述", "采购订单文本", "采购文本", "检验文本",
    "编码", "物料编码",
)

SCOPE_CONDITION_MARKERS = (
    "备件制造商", "制造商为", "制造厂为", "厂家为", "供应商为",
    "备件类别", "备件类型", "编码分类", "编码类别", "更换情况",
    "更换类别", "重要a类", "重要A类", "重要b类", "重要B类",
    "易损件", "整阀条件", "专用类字段", "生产准备期间", "替代场景",
)


def _extra_scope_markers() -> tuple[str, ...]:
    """厂商等业务专有 marker 从环境变量 MQC_SCOPE_CONDITION_EXTRA_MARKERS (逗号分隔) 读取。"""
    raw = os.environ.get("MQC_SCOPE_CONDITION_EXTRA_MARKERS", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def compact_text(value):
    return re.sub(r"[\s:：=＝\-_/（）()，,。；;]+", "", str(value or "")).lower()


def split_condition_segments(condition_text):
    return [
        segment.strip()
        for segment in re.split(r"[；;\n]+", str(condition_text or ""))
        if segment.strip()
    ]


def parse_assignment(text):
    text = str(text or "").strip()
    match = re.match(r"^\s*([^=＝:：]{1,30})\s*[=＝:：]\s*(.+?)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(r"^\s*(.{1,20}?)(?:为|是)([^，。；;]+)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", ""


def is_scope_condition(segment, material_entity=""):
    text = str(segment or "").strip()
    compact = compact_text(text)
    entity = compact_text(material_entity)
    key, value = parse_assignment(text)
    key_compact = compact_text(key)
    value_compact = compact_text(value)

    if any(compact_text(marker) in compact for marker in SCOPE_CONDITION_MARKERS + _extra_scope_markers()):
        return True

    if value_compact and len(value_compact) >= 2 and entity and value_compact in entity:
        return True

    if key_compact and entity and key_compact in {"对象", "实体", "适用对象", "物料实体"}:
        return True

    return False


def is_runtime_condition(segment):
    text = str(segment or "")
    compact = compact_text(text)
    has_field = any(compact_text(token) in compact for token in RUNTIME_FIELD_TOKENS)
    has_compare = bool(re.search(r"(=|＝|:|：|为|是|包含|前缀|后缀|为空|缺少|存在|填写)", text))
    return has_field and has_compare


def sanitize_runtime_condition(condition_text, material_entity="", return_removed=False):
    kept = []
    removed = []

    for segment in split_condition_segments(condition_text):
        if is_scope_condition(segment, material_entity=material_entity):
            removed.append(segment)
            continue
        if not is_runtime_condition(segment):
            removed.append(segment)
            continue
        kept.append(segment)

    condition = "；".join(kept)
    if return_removed:
        return condition, removed
    return condition
