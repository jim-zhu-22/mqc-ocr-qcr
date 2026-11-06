# 待确认的发布信息

本地软件、启动入口、依赖锁定、测试、来源差异及JSON契约已准备。按用户要求同步到私有GitHub仓库；未创建公开仓库、打正式发行标签或选择项目许可证。

远程仓库：https://github.com/jim-zhu-22/mqc-ocr-qcr 。使用当前已登录账号创建，private=true，默认分支main。运行数据、密钥、虚拟环境及测试临时输出不纳入Git。

今后公开发布前需要权利人确认：

1. 是否将当前私有仓库改为公开。
2. 可公开范围：本包中的来源代码适配、提示词、脱敏控制单、合成物料与合成参考库是否全部获准公开。
3. 项目许可证及正式版本号。未决定前保持私有开发状态；先审核依赖自身许可证。

真实服务验收只需复现人员在Demo填写OCR和文本模型的base URL、model、api key（不要在聊天或仓库提交密钥），按VALIDATION.md运行并保存新任务JSON。如需ML，还需真实模型证据服务与模型版本；没有这些信息不影响纯规则/确定性路径运行。

## 论文Code metadata回填草案

| 项目 | 当前值 |
| --- | --- |
| Software name | MQC-OCR-QCR |
| Formal version | Pending; package build identifier 0.0.0.dev0 only |
| Repository URL | https://github.com/jim-zhu-22/mqc-ocr-qcr (private) |
| Permanent code identifier | Local Git commit in delivery report; no archived DOI |
| Legal code license | Pending rights-holder selection |
| Language | Python, JavaScript, HTML/CSS |
| Requirements | Python 3.11+, declared locked dependencies; optional configurable model APIs |
| Documentation | README.md, docs/CONTRACTS.md, docs/VALIDATION.md |
| Support contact | To be supplied by author; no inferred address |

不得把本地开发标识写成已发布版本，不得把模拟HTTP验收写成真实Qwen运行或工业准确率结果。
