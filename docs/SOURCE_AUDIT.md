# 来源与差异审查

日期：2026-11-07（Asia/Shanghai）。以“来源材料 A”为基准，使用独立仓库维护适配版本；原始材料保持只读。“来源材料 A”为脱敏标识，仅用于区分材料，不包含原始名称、位置或背景信息。

## 选择方法

按调用链检查OCR提示词→章节清洗/标题/拆分→规则提取→编译→IR/DSL→字段执行引擎→计分聚合。对被复用的文件计算SHA256，并对已认可证据包的相关源快照做字节比较。具体记录在 `source_manifest.json`。没有根据文件时间批量合并archive、update_backup或其他旧补丁；未声称有可验证的“10月22日Git提交”，因为未提供该正式源码版本。现有文件中的此前更新只在所选调用链内核对采用。

## 复用

`legacy_common`是用于分发的来源包名别名，不代表原始包实际改名。清单中保留原文件SHA256及目标路径，便于授权审查时核对来源。

| 来源标识（部分使用中性别名） | 处理 |
| --- | --- |
| mqc_service/quality_rule/scoring/rule_engine.py | 复用字段别名、条件、required/来源一致性等执行行为；改相对导入、注入语义执行器，错误文案改为待核实0分。原aggregate_scores仍作为来源代码保留但本软件不调用，数值策略由新scoring.py实现。 |
| mqc_service/quality_rule/scoring/rule_scope.py | 复用控制单及实体适用性逻辑，改包内导入。新计分层仅将已明确对象不同/条件为false排出分母，未确认仍计0。 |
| mqc_service/quality_rule/scoring/field_mapping.py | 复用字段映射。 |
| mqc_service/quality_rule/condition_sanitizer.py | 复用运行时条件清理。 |
| legacy_common/scoring_fields.py | 复用字段状态和别名。 |
| mqc_service/core/prompt.py 的 MQC_PROMPT | AST读取常量原文，作为ocr_original.txt；无凭据或配置模块加载。 |
| mqc_service/quality_rule/prompt_v2.py 的 QUALITY_RULE_PROMPT | 原常量只供审查，不作为新运行的提取提示词。 |
| 脱敏证据包 reproduction/semantic_adapter.py | 保留为synthetic_identity.py，仅明确重放v1使用。 |

## 修复与适配

1. **章节**：原cleaner使用 `.*\d+/\d+.*` 一类宽匹配，会删除含1/2的工程参数；改为首部带标签的页码匹配。第4.2节下1./2.列表不再成为顶层标题；保留无正文父节4。页码标记前的页眉作为单独移除审计，不能把下一页页眉归到上一节。正文行带原页/原行号。样例恢复10个编号章节，另保留front前置信息。非连续/无编号标题仍保存在正文，这是一项已知限制。
2. **唯一性**：原提取prompt_v2与compiler有跨记录查重的强制边界，且会将多类唯一性检查自动转成cross_record_unique。这与用户确认的第4.2节身份确定性不符。新提示词与identity_unique执行器遵循型号/完整参数识别语义，不运行那段自动转换。
3. **数值策略**：原aggregate_scores会排除passed=None或返回None。本软件按最新要求把待核实纳入分母计0，明确不适用才排除，所有五个分数均为数值。规则和维度权重可配置，保留每项原因。
4. **可复现部署**：原API与任务服务依赖数据库、内部配置和训练器路径。新建本地FastAPI服务、内存配置、JSON文件存储和无构建前端，未迁移Excel后端。
5. **模型接口**：原调用客户端未复制；以显式配置的Chat Completions HTTP客户端替代，分离OCR/文本参数，保留每次尝试、原始响应和错误。没有读取原API密钥。
6. **ML**：审查coding_necessity_ml、accuracy_ml、duplicate_model_adapter及aggregator。原必要性融合可用0.60/0.40，准确性存在min(DSL, blended)上限；新桥接按显式权重调用外部训练模型证据服务，准确性保留上限。完整性ML路径按用户要求禁用。原判重模型并不等同于身份确定性，未暗中接入。没有迁移或运行原训练模型，不能将HTTP桥接测试写成原模型已验证。

## 不在本包范围

原系统运行环境、非分发数据与模型资产、历史版本及论文资料不包含在本包。当前程序是可独立运行的软件适配。来源代码和脱敏样例的公开许可仍需权利人确认。
