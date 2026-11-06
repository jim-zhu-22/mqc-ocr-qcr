# 提示词版本与修改理由

| 文件 | 执行状态 | 契约/理由 |
| --- | --- | --- |
| ocr_original.txt | live逐页使用 | 原MQC_PROMPT常量完全保留。每次仅一页图像，输出纯文本，不要求OCR输出JSON；程序负责封装。每页记录提示词SHA256。 |
| extraction_original.txt | 仅审查，不执行 | 记录当前原QUALITY_RULE_PROMPT，保留其{condition_semantic_guide}/{content}模板。 |
| extract_v1.txt | live使用 | portable-extraction-v1。保留对象/字段/动作/依据分离；将唯一性从“只允许跨记录查重”修订为按控制单身份确定性；排除照片；输出原章节引用。 |
| compile_v1.txt | live及需模型的人工修订使用 | portable-compiler-v1。不使用原编译器强制转查重分支；新增确定性identification_complete/identity_unique；完整性禁止语义模型评分；不支持的检查保留UNKNOWN。 |

这两份文本提示词属于明确修订，不能描述成“原提示词未修改”。运行中实际发送的完整提示词、模型名及原始响应保存在model_calls或compile-calls/score-calls JSON。原始响应仅对已配置密钥及敏感键脱敏，不作语义改写。

截图来源信息与源页号来自软件解析和引用校验，不信任模型自行生成页码。人工规则来源页码同样根据source_sections计算。
