# JSON与执行契约

所有文本UTF-8，时间戳ISO8601 UTC，界面记录显示原值。所有阶段文件使用：

```json
{"schema_version":"1","run_id":"32位hex","stage":"ocr","status":"completed","created_at":"2026-11-06T17:00:00+00:00","data":{},"error":null}
```

`run.json` 是任务索引，含mode、status、当前stage、revision、compiled_revision、scores数组、无密钥配置快照。mode=`live|replay`；运行状态=`queued|running|completed|failed|interrupted`。阶段可为partial。重启会将正在执行的任务标为interrupted，保留已有文件；不自动续调API或重算。

## 产物

| 产物 | data |
| --- | --- |
| input | 控制单编号、模式、文件类型、输入哈希 |
| model_calls | calls数组：tag、attempt、model、实际prompt、image_attached、raw_response、HTTP状态、耗时、error。图片正文不写入调用JSON，按page-N.png存储。 |
| ocr | pages数组：page_num、text_content、live的raw_output、图像/提示词哈希、执行状态 |
| sections | sections数组：section、title、content、pages、lines；removed_lines记录页眉过滤。 |
| rules-raw | 尚未解析的提取输出，非法JSON也保留。 |
| rules-vN | rules数组、排除项或parent_revision |
| ir-vN | 每规则source_rule_id、semantic_items、source_pages |
| dsl-vN | DSL数组、编译errors；source_rule_id、dsl_id、来源章节/页码、操作符、权重、execution_status |
| compile-calls-vN | 本次编译实际模型调用 |
| score-input-ID | 规则版本和评分输入快照，敏感键脱敏 |
| score-calls-ID | 实际语义评分调用；无模型调用时不生成 |
| scores-ID | 规则版本、results、summary；每条记录五项数值、每规则结果/原因/来源及ML证据 |
| STAGE-error | code、可理解message、已保留前序产物标记 |

逐页文件和整体产物会在执行中增量写入，JSON替换为原子写。每次评分ID、规则版本不同，历史文件不覆盖。一个任务同时只允许一次修改或评分操作。

## 规则编辑

```json
[{"id":"R0001","quality_type":"NECESSITY","rule_title":"设备需要编码","rule_text":"评分字段：material_code；检查要求：必须存在；原文依据：第3节","material_entity":"Equipment A","condition_text":"","source_sections":["3"],"source_pages":[3],"weight":1,"enabled":true,"source_type":"manual","checks":[{"field_name":"material_code","operator":"required","expected_value":"true","semantic":"编码必填"}]}]
```

PUT `/api/runs/{id}/rules` 保存并自动更新IR/DSL；source_pages由服务重建。checks为空时调用文本模型编译，非空时按人工确定的检查构建DSL。ID唯一，只允许英文字母/数字/点/下划线/连字符。可删除数组元素或设enabled=false。照片规则禁止启用。

支持required、exists、equals、contains、starts_with、ends_with、regex、required_any、required_all、regex_any、source_consistent、semantic_assertion、identification_complete、identity_unique、UNKNOWN。规则默认绑定当前控制单，物料 `kzd` 应匹配控制单编号。实体字段可用 `material_entity` 或 `level3_category` 明确指定；同时保留描述以供原引擎适用性核对。无法确认适用并不自动排除，而是待核实0分。

完整性禁止semantic_assertion模型判断；编译阶段将其转UNKNOWN。identity操作符的expected_value对象指定model_fields、parameter_fields。参考库references提供model、canonical_manufacturer、key_parameters。多个型号冲突或型号/完整参数指向不同对象时待核实0分。

## 物料与评分

```json
{"materials":[{"sample_id":"M1","material_code":"SYN-1","kzd":"DOC-A-0001","level3_category":"Equipment A","cn_description":"Equipment A [M1]","model":"M1","source_evidence":[{"source":"handbook","fields":{"manufacturer":"Manufacturer A"}}]}],"catalog":{"references":[{"reference_id":"REF1","model":"M1","canonical_manufacturer":"MFR1","key_parameters":{"size":"150 mm"}}]},"dimension_weights":{"necessity":1,"completeness":1,"accuracy":1,"uniqueness":1},"ml":{}}
```

POST `/api/runs/{id}/score` 才触发评分。input可导入上述对象或在Demo导入物料数组（自动封装为materials）。参考证据必须实际提供，source_consistent不从模型常识补全。合成样例中reference_links仅用于显式构造测试外部证据，不作为模型特征；部分样例故意不给证据。

results每项含 `scores_0_to_1` 的necessity/completeness/accuracy/uniqueness/final数值、included_rule_counts、dimension_reasons、details。details含PASS/ZERO/EXCLUDED、verification、score、included_in_score、reason、dsl_id、source_rule_id、source_text、source_sections/source_pages。零分不省略原因。

## 可选真实ML证据服务桥接

默认ml={}。此软件不复制原训练器或模型，不会自行训练或伪造模型分数。已有经过授权部署的训练模型可提供HTTP接口。配置示例（不要保存真实密钥到共享JSON）：

```json
{"necessity":{"enabled":true,"weight":0.4,"endpoint":{"base_url":"http://127.0.0.1:9001/predict","api_key":"","timeout_seconds":30}}}
```

服务接收 `{"dimension":"necessity","material":{...}}`，返回 `{"score":0.8,"model_version":"实际模型版本","evidence":{"实际证据":"..."}}`。score必须0–1有限数值；模型版本和evidence不能为空。唯一性还必须返回 `"semantics":"identity_determinacy"`。不调用OpenAI格式ML接口，这是独立的已训练模型证据契约；需复现人员按自己的真实模型包装。

启用时按 `DSL*(1-weight)+ML*weight` 融合，准确性额外取min(DSL,融合值)，与原accuracy_ml策略相符。服务错误、无证据或语义不符的启用项以ML=0计入，并保存失败状态。未启用不调用、不伪造结果；完整性配置ML即报错。该桥接单独请求不重试，超时可配置；OCR/文本模型调用有重试。

## 端点与安全

GET `/api/runs` 列表；GET `/api/runs/{id}` 产物索引；GET `.../artifacts/{name}` 预览，`?download=true`下载；GET `.../export` 全JSON ZIP；GET `.../pages/{n}` 页图。PUT `/api/config` 整体替换内存配置（空密钥会清空，刷新页面不会回显密钥）。POST `/api/config/check/ocr|text` 发起真实连接检查。

接口仅同源本机使用。URL不允许嵌入认证/查询参数；HTTP重定向不跟随，避免凭据被转送。默认不使用系统代理环境变量。401/403不重试；408/429/常见5xx和连接/超时错误按配置重试；输出截断、非法格式报错并保留原始响应。返回模型JSON需符合当前契约，兼容外层Markdown代码围栏；不从任意文本猜测JSON。
