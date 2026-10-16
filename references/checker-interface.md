# 检查工具接口

Python 3.10+，只用标准库；不需要联网、Word 或 python-docx。`--out` 不覆盖现有文件。引用与结构报告分别输出，返回 0/1/2 对应 pass/fail/pending；引用来源和视觉状态另看分项。

从 `templates/project-config.json` 复制到项目 `thesis-project.json`。空 selector 会拒绝执行，先检查真实文件边界；不能保留空模板后称检查通过。

`selectors` 中的每个值支持：

- `tables: [0, 2]`：按 document.xml 中的表格顺序，从 0 开始，含嵌套表格。单元格段落按 XML 顺序读取，不重复读取合并单元格。
- `outside_tables: true`：仅表外段落。
- `start_regex`、`end_regex`：对移除空白后的段落匹配，必须唯一；起点包含，终点默认不含，`include_end: true` 可包含终点。
- `text_regex`：边界确定后按原段落文本进一步过滤。

范围顺序为：表格筛选→表外筛选→起点→终点→文字筛选。不能跨两个候选段落模糊选择；无匹配、边界不唯一、无正文或正文与参考表重叠时拒绝检查。不要随意更换表格索引；学校模板修改后重新确认。

`body` 是数字引文出现范围；`bibliography` 是文献条目范围。其他名称由规则引用。段落定位 `table[0]/p[1]` 中表格从 0、段落从 1 编号；这是结构位置，不是页码。页码需使用真实导出文件。

## 规则

`text_rules`：`id/kind/scope/pattern/suggestion`。`kind` 为 `required/forbidden/review`，正则匹配去空白文本。review 只要求人工复核，不证明内容错误。

`numbered_lists`：`scope/pattern/start`，pattern 第一捕获组是数字编号，可为 `1` 或 `1.1.1`；每个独立列表使用独立范围。自动 Word 列表未解析显示值，报告待核对。

`formatting`：`scope/before_pt/after_pt/line_multiple/font_pt/fonts/flag_empty`，只设置本项目需要的属性，字体可用 `eastAsia/ascii`。标题和正文应分开选择；上标数字引文可单独配置 `citation_font_pt`，不影响普通正文。处理 docDefaults、basedOn、直接段落及运行格式；复杂表格条件样式和主题字体需复核。

`table_padding`：`scope/top_pt/bottom_pt`；只检查所选范围涉及的表格。`page` 支持 `margins_cm: {top,bottom,left,right}` 和 `size_cm: {w,h}`。

`citations`：`style: sequential`、可选 `minimum_academic`、`language_groups`。每组含 `name/heading_regex/entry_regex`，用于学校明确要求的分组检查；不默认按语言重排。

`ledger.path` 相对配置文件所在目录解析，指向台账模板结构。程序不从中文核验描述猜测“已证实”；历史台账转入时保留原说明，将无法证明的状态记 pending。

顺序引文支持 `[1]`、`［1］`、`[1,3-5]`、区间连接号；普通方括号数字可能被误认为引文，应人工复核。引用样式不支持时不可用它判断通过。只解析主文档，发现脚注、域、文本框或修订将提示补查；页眉页脚、参考管理器内部关系和分页需另查。

结构检查通过意味着“已配置的可解析属性符合要求”，并不证明段落功能、内容深度、参考文献真实性、字号视觉效果或所有排版项目完成。统计仅作核查，不自动修改原文。
