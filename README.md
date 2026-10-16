# thesis-delivery-zh

面向中文论文、毕业设计、文献综述和开题报告的 **Codex Skill**。围绕学校要求、材料用途、证据、正文与引用一致性、Word 检查和交付验收组织工作，并将反馈归纳为可验证的共性规则。

[![CI](https://github.com/sanipedro679-gif/thesis-delivery-zh/actions/workflows/ci.yml/badge.svg)](https://github.com/sanipedro679-gif/thesis-delivery-zh/actions/workflows/ci.yml)

版本：**1.0.1**。检查脚本需要 **Python 3.10+**，仅使用标准库。Skill 需要支持本地技能的 Codex 环境；Word 页面渲染另需可用的文档引擎。

## 可以做什么

| 能力 | 处理方式 |
| --- | --- |
| 要求管理 | 为要求记录来源、范围与生效条件；学校规定按项目配置 |
| 材料管理 | 区分引用、数据、结构参考和格式参考，记录采用与排除依据 |
| 文献与证据 | 分开记录书目核对、资料取得、实际阅读和逐处论点支持 |
| 引文检查 | 检查数字顺序编码的首次引用、重引、缺项、重复条目和台账一致性 |
| 写作审核 | 检查章节功能、论证衔接、计划与结果的区别及正式表达 |
| Word 检查 | 读取实际 DOCX 的段落、继承样式、字体、字号、表格内边距及页面参数 |
| 经验维护 | 记录反馈、定位机制、验证规则、重新加载及保存可恢复版本 |

通用的是方法。**题目、学校、章数、术语限制、文献数量和格式值均由当前项目输入**，不继承上一篇论文的答案。完整规则见 [共性原则](references/general-principles.md)。

## 安装

### 安装到一个项目

在目标项目目录执行：

```bash
git clone https://github.com/sanipedro679-gif/thesis-delivery-zh.git .agents/skills/thesis-delivery-zh
```

安装后目录应为 `.agents/skills/thesis-delivery-zh/SKILL.md`。如果目标目录已有技能，先检查和备份，不直接覆盖。

### 安装为个人全局技能

PowerShell：

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
git clone https://github.com/sanipedro679-gif/thesis-delivery-zh.git (Join-Path $skillRoot 'thesis-delivery-zh')
```

macOS / Linux：

```bash
git clone https://github.com/sanipedro679-gif/thesis-delivery-zh.git "${CODEX_HOME:-$HOME/.codex}/skills/thesis-delivery-zh"
```

重新打开项目或新建 Codex 会话后，使用 `$thesis-delivery-zh` 调用。也可以下载本仓库 ZIP，解压至相同目录；最终必须直接看到上述 `SKILL.md`，避免多套一层文件夹。

## 使用示例

```text
用 $thesis-delivery-zh，先阅读学校模板、原稿和老师反馈，
建立本项目要求，再完成这次开题报告修改。
分别说明正文、引用核验、结构检查和页面查看的状态。
```

```text
用 $thesis-delivery-zh，审核这份毕业设计。
按位置、原文或证据、影响、修改建议和待核实项给出意见，先不改原稿。
```

```text
用 $thesis-delivery-zh，复盘这次出现的问题。
先提炼根因、适用条件与例外，再补正常对照并验证改进。
仅更新当前授权的本地技能资源，不提交论文或发布外部内容。
```

已有 `research-writing-skill`、`literature-review`、`scientific-critical-thinking`、`humanizer-zh` 或 documents/pdf 技能时，可按需组合。本仓库不打包这些第三方技能，也不把它们列为检查脚本的必需依赖。

## 项目配置与命令行检查

在**论文项目自己的目录**建立配置，不把真实论文材料放进此技能仓库：

1. 复制 [项目配置模板](templates/project-config.json) 为 `thesis-project.json`。
2. 复制 [来源台账模板](templates/source-ledger.json) 为 `source-ledger.json`，用真实条目替换模板内容。
3. 根据实际 Word 文件设置正文、书目等范围，以及本项目要求的检查规则。

模板的空范围会使检查拒绝执行。`tables` 索引从 0 开始；边界正则必须唯一。完整字段与覆盖限制见 [检查工具接口](references/checker-interface.md)。

以下命令在已安装的技能目录执行；将路径替换为实际项目路径：

```bash
python scripts/check_citations.py /path/to/report.docx --config /path/to/thesis-project.json --out /path/to/citations_R01.json
python scripts/inspect_docx.py /path/to/report.docx --config /path/to/thesis-project.json --out /path/to/structure_R01.json
```

Windows 可将 `python` 换成 `py -3.12 -X utf8`。脚本默认只读原稿，报告文件不能覆盖已有文件。

| 退出码 | 含义 |
| --- | --- |
| `0` | 已配置且被支持的检查通过 |
| `1` | 发现错误，或无法安全执行检查 |
| `2` | 尚有待核验项目或需要人工复核 |

引用脚本读取台账状态，**不会联网验证文献，也不会自动阅读全文**。结构检查不会判断页面是否截断、重叠或缺字；页面验收需要真实导出并逐页查看，参见 [文档验收](references/document-acceptance.md)。

## 经验如何持续更新

执行任务时按以下流程维护本地经验：

**反馈 → 根因 → 共性机制 → 条件与例外 → 不同参数及正常对照 → 验证 → 更新。**

项目特有要求保留在项目，通用库保存脱敏机制。候选规则不自动成为硬约束；资源改变后，原验证状态会失效并要求重新验证。

```bash
python scripts/evolve.py list
python scripts/evolve.py record --issue /path/to/sanitized-issue.json
python scripts/evolve.py transition --id ISS-ID --status pending_validation --note "修复说明"
python scripts/evolve.py transition --id ISS-ID --status active --note "验证结论"
python scripts/evolve.py release --version 1.0.2 --note "本次已验证的改进"
python scripts/evolve.py rollback --version 1.0.1
```

问题字段见 [问题模板](templates/issue.json)，流程见 [经验维护](references/evolution-policy.md)。`active` 需要实际回归通过；`release` 会运行本地测试并保存受管资源快照。只能恢复**本地确已保存的版本**，首次安装不会自动带有恢复快照。恢复先在隔离副本中演练。

这是一套运行任务时维护文件的机制，没有后台训练或无人值守自我修改服务。维护范围遵循当前用户与项目授权。新安装的仓库不携带作者的本地问题日志、个人路径、运行状态或论文案例。

## 测试与适用范围

在仓库根目录运行：

```bash
python -m unittest discover -s tests -v
```

发布前本地 **43 项自动测试通过**。测试覆盖失败输入、正常对照及术语、范围、编号起点、字号和间距参数变化；GitHub Actions 会在 Python 3.10 / 3.12 上重复运行。

这些测试证明对应机制在所测输入上的行为，不能证明所有学科或学校都已验证。以下内容仍需实际来源、文档工具或人工复核：

- 文献真实性、原文是否支持具体论点，以及数据口径和因果解释。
- 段落与章节的实际功能、论证深度、方案可行性。
- 自动编号显示值、复杂条件样式、主题字体、分页和页面观感。
- 脚注、文本框、修订与域等超出当前主文档解析范围的内容。

不提供未经真实检测的查重率或 AIGC 分数；不以改写保证通过检测。原件保留，修改稿使用独立版本，缺少证据的项目准确报告状态。

## 仓库结构

```text
SKILL.md              技能入口
agents/               Codex 展示元数据
references/           按需加载的共性规则与操作流程
templates/            项目配置、来源台账、问题记录模板
scripts/              只读检查与本地经验维护工具
tests/                合成 OOXML 与隔离副本测试
.github/workflows/    自动测试
```

`.gitignore` 排除了真实文稿、项目配置、来源台账、运行日志、恢复快照和凭证文件。提交前仍须人工检查待提交内容，不能把忽略规则当作隐私审核的替代。
