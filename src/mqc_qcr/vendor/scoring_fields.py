"""Confirmed scoring aliases shared by Excel ingestion and MQC.

Unknown database names and revision suffixes require explicit selection.
"""

FIELD_ALIASES = {
    "编码": (
        "编码", "material_code", "material_no", "物料号", "物料编码",
        "spare_part_code", "备件代码", "备件编码", "spare_part_id", "备件ID",
    ),
    "物料描述": (
        "物料描述", "cn_description", "description_cn", "中文描述", "中文名称",
        "part_name", "物料名称",
    ),
    "采购订单文本（中文）": (
        "采购订单文本（中文）", "采购订单文本", "采购文本", "中文采购订单文本",
        "中文代购订单文本", "cn_po_text", "chinese_procurement_order_text",
        "purchase_text", "purchase_order_text_cn",
    ),
    "英文描述": ("英文描述", "en_description", "description_en"),
    "采购订单文本（英文）": (
        "采购订单文本（英文）", "英文采购订单文本", "en_po_text",
        "english_procurement_order_text", "purchase_order_text_en",
    ),
    "制造商": (
        "制造商", "制造厂", "制造厂名称", "manufacturer_name", "manufacturer",
    ),
    "制造厂编码": (
        "制造厂编码", "制造厂代码", "制造商编码", "manufacturer_code",
        "manufacturer_id", "manufacturer_no", "mfr_code", "vendor_code",
    ),
    "无代码制造商名称": (
        "无代码制造商名称", "no_code_mfr_name", "no_code_manufacturer_name",
    ),
    "成套供应商编码": (
        "成套供应商编码", "成套供应商", "成套商", "package_vendor_code",
        "package_supplier_code",
    ),
    "成套供应商名称": (
        "成套供应商名称", "成套商名称", "package_vendor_name",
        "package_supplier_name",
    ),
    "参考号": (
        "参考号", "制造厂参考号", "制造商参考号", "manufacturer_reference_no",
        "mfr_ref_no", "reference_no", "reference_number",
    ),
    "制造商零件编号": (
        "制造商零件编号", "制造厂零件编号", "制造厂零件号", "厂家零件编号",
        "manufacturer_part_no", "mfr_part_no", "part_no",
    ),
    "图纸号": (
        "图纸号", "制造厂图号", "电厂制造厂图号", "电站图号", "电站图纸号",
        "drawing_no", "mfr_drawing_no", "manufacturer_drawing_no",
        "plant_mfr_drawing_no", "plant_drawing_no", "power_station_drawing_no",
    ),
    "图项号": (
        "图项号", "制造厂图项号", "制造厂项号", "电厂制造厂图项号",
        "drawing_item_no", "mfr_drawing_item", "mfr_item_no",
        "manufacturer_drawing_item_no", "plant_mfr_drawing_item",
    ),
    "制造厂图号": (
        "制造厂图号", "mfr_drawing_no", "manufacturer_drawing_no",
    ),
    "制造厂图项号": (
        "制造厂图项号", "制造厂项号", "mfr_drawing_item", "mfr_item_no",
        "manufacturer_drawing_item_no",
    ),
    "电厂制造厂图号": (
        "电厂制造厂图号", "plant_mfr_drawing_no",
    ),
    "电厂制造厂图项号": (
        "电厂制造厂图项号", "plant_mfr_drawing_item",
    ),
    "电站图号": (
        "电站图号", "电站图纸号", "plant_drawing_no", "power_station_drawing_no",
    ),
    "EOMM手册号": ("EOMM手册号", "eomm_manual_no"),
    "规格型号": (
        "规格型号", "型号", "model", "spec_model", "specification_model", "规格",
    ),
    "型号": (
        "型号", "规格型号", "model", "spec_model", "specification_model", "规格",
    ),
    "材质": ("材质", "material", "material_texture", "material_text"),
    # 分类层级：当前四张评分编码表字段结构中明确存在
    # material_category（物资类别）与 level3_category（三级分类）。
    # level2 在当前四表中不是固定列，但保留 API/其他来源的兼容别名。
    "物资分类": (
        "物资分类", "物料分类", "物资类别", "material_category", "category_name",
    ),
    "一级分类": (
        "一级分类", "一级物资分类", "一级物料分类", "物资类别", "物资分类",
        "material_category", "level1_category", "category_level1", "classifi1",
    ),
    "二级分类": (
        "二级分类", "二级物资分类", "二级物料分类",
        "level2_category", "category_level2", "classifi2",
    ),
    "三级分类": (
        "三级分类", "三级物资分类", "三级物料分类",
        "level3_category", "classifi3", "category_level3",
    ),
    "基本计量单位": ("基本计量单位", "base_unit"),
    "系统": ("系统", "system", "system_code", "system_name"),
    "内部批注": (
        "内部批注", "internal_remark", "internal_comment", "internal_remarks",
        "remark", "备注",
    ),
    "检验文本": ("检验文本", "inspection_text", "inspection_description"),
    "基本物料": ("基本物料", "base_material", "basic_material"),
    "阀体材料": (
        "阀体材料", "valve_body_material", "body_material", "material_texture", "材质",
    ),
    "RIN码": ("RIN码", "RIN 码", "rin", "rin_code", "RIN"),
    "额定电压": ("额定电压", "rated_voltage", "voltage", "ratedVoltage"),
    "控制单编号": (
        "控制单编号", "质量单编号", "控制单", "kzd", "KZD", "rule_id",
        "qc_order_no", "mqc_rule_id",
    ),
}


# Workbook v1.0 names plus legacy DSL spellings. Do not equate original
# manufacturer with current manufacturer, or drive mode with an inclusion flag.
FIELD_ALIASES["关键识别参数"] = (
    "关键识别参数", "key_parameters", "key_parameter", "identity_parameters",
)
FIELD_ALIASES["物料描述"] += ("description", "description_zh")
FIELD_ALIASES["材质"] += ("材质及要求",)
FIELD_ALIASES.update({
    "质保等级": ("质保等级", "质量等级", "quality_grade", "qa_level"),
    "标准号": ("标准号", "标准", "standard", "standard_no"),
    "寿期": ("寿期", "service_life", "life"),
    "NNSA监管": ("NNSA监管", "NNSA 监管", "是否核安全局监管备件", "是否核安全局监管",
                 "is_ns_regulated", "is_nnsa_supervised", "nnsa_supervision"),
    "原制造商": ("原制造商", "原制造厂", "original_manufacturer", "original_mfr"),
})


def field_state(row, canonical, aliases=None):
    aliases = aliases or FIELD_ALIASES.get(canonical, (canonical,))
    selected = (row.get('_field_selection') or {}).get(canonical)
    if not selected:
        # 型号/规格型号 share a physical field; one explicit selection covers both.
        selected = next(((row.get('_field_selection') or {}).get(name)
                         for name in aliases if (row.get('_field_selection') or {}).get(name)), None)
    names = [selected] if selected else [name for name in aliases if name in row]
    if selected and selected not in row:
        return {'state':'mapping_pending', 'source_field':selected, 'candidates':[], 'value':None}
    if not names:
        return {'state':'missing_column', 'source_field':'', 'candidates':[], 'value':None}
    filled = [name for name in names if row[name] not in (None, '')]
    distinct = {(type(row[name]).__name__, str(row[name]).strip()) for name in filled}
    if len(distinct) > 1:
        return {'state':'mapping_pending', 'source_field':'', 'candidates':names, 'value':None}
    source = (filled or names)[0]
    return {'state':'present' if filled else 'empty', 'source_field':source,
            'candidates':names, 'value':row[source]}
