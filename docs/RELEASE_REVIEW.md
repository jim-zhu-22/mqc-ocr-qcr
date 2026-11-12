# 分发与送审说明

本包提供可审查的源码、启动入口、依赖声明、测试和JSON契约。本文不记录维护者个人账号或仓库地址。项目许可证及正式版本号仍待权利人确定；开发标识不代表正式发行版本。

运行数据、密钥、虚拟环境及测试临时输出不纳入Git。模型API密钥通过本地配置界面写入服务进程内存，重启后需重新配置。

## 匿名分发边界

源码内容中移除账号和项目背景，不会消除公开托管账号、Git历史、既有下载包或外部引用中的身份线索。双盲送审应使用不含.git历史、身份链接及旧截图的独立材料，并按会议或期刊要求检查分发渠道。当前包不宣称已达到完整双盲匿名要求。

来源代码、提示词和样例的使用许可，以及项目许可证，仍需由权利人确认。别名化PDF保留部分原有表格结构与脚注，不能等同于完全合成的匿名版式。

## 论文Code metadata回填草案

| 项目 | 当前值 |
| --- | --- |
| Software name | MQC-OCR-QCR |
| Formal version | Pending; package build identifier 0.0.0.dev0 only |
| Repository URL | Omitted from this distribution document |
| Permanent code identifier | Not assigned |
| Legal code license | Pending rights-holder selection |
| Language | Python, JavaScript, HTML/CSS |
| Requirements | Python 3.11+, declared locked dependencies; optional configurable model APIs |
| Documentation | README.md, docs/CONTRACTS.md, docs/VALIDATION.md |
| Support contact | Omitted from this distribution document |

真实服务验收见VALIDATION.md。不能将模拟HTTP测试写成真实供应商模型验收，也不能将合成样例质量分数写成模型准确率。
