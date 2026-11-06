# 待确认的发布信息

本地软件、启动入口、依赖锁定、测试、来源差异及JSON契约已准备。尚未推送、创建公开仓库、打正式发行标签或选择项目许可证。

GitHub连接检查：能读取当前账户资料；可访问仓库列表为空。未成功读取用户指定仓库，因此不能报告目标仓库授权已经验证。父工作区无可用远程目标。

发布前最少需要权利人确认：

1. 目标GitHub owner/repository与可见性（private/public），或允许创建的目标名称。
2. 可公开范围：本包中的来源代码适配、提示词、脱敏控制单、合成物料与合成参考库是否全部获准公开。
3. 项目许可证及正式版本号。未决定前保持本地审查状态；先审核依赖自身许可证。

真实服务验收只需复现人员在Demo填写OCR和文本模型的base URL、model、api key（不要在聊天或仓库提交密钥），按VALIDATION.md运行并保存新任务JSON。如需ML，还需真实模型证据服务与模型版本；没有这些信息不影响纯规则/确定性路径运行。

## 论文Code metadata回填草案

| 项目 | 当前值 |
| --- | --- |
| Software name | MQC-OCR-QCR |
| Formal version | Pending; package build identifier 0.0.0.dev0 only |
| Repository URL | Not published; local review repository |
| Permanent code identifier | Local Git commit in delivery report; no archived DOI |
| Legal code license | Pending rights-holder selection |
| Language | Python, JavaScript, HTML/CSS |
| Requirements | Python 3.11+, declared locked dependencies; optional configurable model APIs |
| Documentation | README.md, docs/CONTRACTS.md, docs/VALIDATION.md |
| Support contact | To be supplied by author; no inferred address |

不得把本地开发标识写成已发布版本，不得把模拟HTTP验收写成真实Qwen运行或工业准确率结果。
