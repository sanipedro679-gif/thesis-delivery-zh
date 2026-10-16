"""Inspect actual DOCX structure and resolved paragraph properties; not visual QA."""
import re
from pathlib import Path
from audit_common import NS, AuditError, finding, norm, report, run_cli, selected, tag, unsupported_features


def audit(doc, cfg, base=Path('.')):
    findings, checks = [], []
    for rule in cfg.get('text_rules', []):
        rows = selected(doc, cfg, rule['scope'])
        if rule['kind'] == 'required':
            matches = [r for r in rows if re.search(rule['pattern'], norm(r['text']))]
            if not matches:
                findings.append(finding(rule['id'], 'error', rule['scope'], rule['pattern'], rule['suggestion']))
        elif rule['kind'] in ('forbidden', 'review'):
            for r in rows:
                if re.search(rule['pattern'], norm(r['text'])):
                    findings.append(finding(rule['id'], 'error' if rule['kind'] == 'forbidden' else 'review', r['location'], r['text'], rule['suggestion']))
        else:
            raise AuditError('Unknown text rule kind')
        checks.append(rule['id'])
    for rule in cfg.get('numbered_lists', []):
        rows = selected(doc, cfg, rule['scope'])
        counts, found = {}, 0
        for r in rows:
            p = r['element']
            if p.find('w:pPr/w:numPr', NS) is not None:
                findings.append(finding('automatic_numbering_pending', 'pending', r['location'], r['text'], '自动编号需检查 numbering.xml、重启及覆盖设置，并在 Word 中查看显示值'))
            m = re.match(rule['pattern'], r['text'])
            if not m:
                continue
            found += 1
            parts = tuple(int(n) for n in m[1].split('.'))
            depth = len(parts)
            # A new parent begins a fresh child sequence; supports 1.1/1.2/2.1 and (1)/(2).
            counts = {k: v for k, v in counts.items() if len(k) <= depth - 1}
            parent = parts[:-1]
            expected = counts.get(parent, rule.get('start', 1) - 1) + 1
            if parts[-1] != expected:
                findings.append(finding('list_sequence', 'error', r['location'], {'actual': m[1], 'expected_last': expected}, '该独立列表从指定起点连续编号；先确认父级与重启边界'))
            counts[parent] = parts[-1]
        if not found:
            findings.append(finding('numbering_not_recognized', 'pending', rule['scope'], rule['pattern'], '核对列表范围与实际编号样式'))
        checks.append('numbering:' + rule['scope'])
    for profile in cfg.get('formatting', []):
        rows = selected(doc, cfg, profile['scope'])
        for r in rows:
            if not r['text'].strip():
                if profile.get('flag_empty'):
                    findings.append(finding('empty_paragraph', 'review', r['location'], '', '确认是否为多余空段；保留学校签字区等必要留白'))
                continue
            p = r['element']
            spacing = doc.properties(p).get('spacing', {})
            for key in ('before', 'after'):
                if key + '_pt' in profile:
                    actual = float(spacing.get(key, 0)) / 20
                    # auto spacing and line-based spacing can override before/after twips.
                    auto = spacing.get(key + 'Autospacing', '0') not in ('0', 'false', 'off')
                    lines = float(spacing.get(key + 'Lines', 0))
                    if abs(actual - profile[key + '_pt']) > .05 or auto or lines:
                        findings.append(finding('paragraph_spacing', 'error', r['location'], {key: actual, 'auto': auto, 'lines': lines}, '按项目配置统一段前段后，并检查继承样式与自动间距'))
            if 'line_multiple' in profile:
                actual = float(spacing.get('line', 240)) / 240
                mode = spacing.get('lineRule', 'auto')
                if mode != 'auto' or abs(actual - profile['line_multiple']) > .001:
                    findings.append(finding('line_spacing', 'error', r['location'], {'line': actual, 'mode': mode}, '使用倍数行距；固定值不等于倍数'))
            for run in p.iter(tag('r')):
                text = ''.join(n.text or '' for n in run.iter(tag('t')))
                if not text.strip():
                    continue
                props = doc.properties(p, 'rPr', run)
                fonts = props.get('rFonts', {})
                for key, regex in [('eastAsia', r'[\u3400-\u9fff]'), ('ascii', r'[A-Za-z0-9]')]:
                    expected = profile.get('fonts', {}).get(key)
                    if expected and re.search(regex, text):
                        if fonts.get(key + 'Theme'):
                            findings.append(finding('theme_font_pending', 'pending', r['location'], fonts, '主题字体需要解析主题并在渲染中确认'))
                        elif fonts.get(key) != expected:
                            findings.append(finding('font_family', 'error' if fonts.get(key) else 'pending', r['location'], {'script': key, 'actual': fonts.get(key), 'expected': expected, 'text': text[:60]}, '核对直接格式、字符样式与段落样式'))
                if 'font_pt' in profile:
                    actual = props.get('sz', {}).get('val')
                    expected_pt = profile['font_pt']
                    if (props.get('vertAlign', {}).get('val') == 'superscript'
                            and re.fullmatch(r'[\[［][0-9０-９,，、\s\-–—]+[\]］]', text.strip())):
                        expected_pt = profile.get('citation_font_pt', expected_pt)
                    if actual is None or abs(float(actual)/2 - expected_pt) > .05:
                        findings.append(finding('font_size', 'error' if actual else 'pending', r['location'], {'actual_half_pt': actual, 'expected_pt': expected_pt}, '按正文、标题或上标引文配置分别设置字号'))
        checks.append('format:' + profile['scope'])
    padding_cfg = cfg.get('table_padding')
    if padding_cfg:
        rows = selected(doc, cfg, padding_cfg['scope'])
        tis = sorted({r['table'] for r in rows if r['table'] is not None})
        for ti in tis:
            tbl = doc.tables[ti]
            ts = tbl.find('w:tblPr/w:tblStyle', NS)
            style_layers = doc.style_chain(ts.get(tag('val'))) if ts is not None else []
            if any(s.find('.//w:tblStylePr', NS) is not None for s in style_layers):
                findings.append(finding('conditional_table_style_pending', 'pending', f'table[{ti}]', '条件表格样式', '边缘/首行等条件格式需人工与页面核对'))
            for side in ('top', 'bottom'):
                expected = padding_cfg.get(side + '_pt')
                if expected is None:
                    continue
                for ci, cell in enumerate(tbl.iter(tag('tc'))):
                    value = None
                    for style in style_layers:
                        node = style.find('w:tblPr/w:tblCellMar/w:' + side, NS)
                        if node is not None:
                            value = node
                    for node in (tbl.find('w:tblPr/w:tblCellMar/w:' + side, NS), cell.find('w:tcPr/w:tcMar/w:' + side, NS)):
                        if node is not None:
                            value = node
                    # Absent padding is not proof of zero: Word defaults/styles can vary.
                    if value is None:
                        findings.append(finding('cell_padding_unknown', 'pending', f'table[{ti}]/cell[{ci}]', side, '缺少明确内边距，需在 Word 中确认'))
                    elif value.get(tag('type'), 'dxa') != 'dxa' or abs(float(value.get(tag('w'), 0))/20 - expected) > .05:
                        findings.append(finding('cell_padding', 'error', f'table[{ti}]/cell[{ci}]', {side: value.attrib}, '按项目要求设置表格及单元格内边距'))
    page = cfg.get('page', {})
    for i, sec in enumerate(doc.root.iter(tag('sectPr'))):
        for group, node_name, scale in [('margins_cm', 'pgMar', 1440/2.54), ('size_cm', 'pgSz', 1440/2.54)]:
            node = sec.find('w:' + node_name, NS)
            for attr, expected in page.get(group, {}).items():
                value = node.get(tag(attr)) if node is not None else None
                if value is None or abs(float(value)/scale - expected) > .02:
                    findings.append(finding('page_geometry', 'error', f'section[{i}]', {attr: value, 'expected_cm': expected}, '按模板检查所有分节的纸张与页边距'))
    if unsupported_features(doc):
        findings.append(finding('unsupported_word_features', 'pending', 'document', unsupported_features(doc), '另行检查脚注、域、文本框和修订显示'))
    if not checks and not padding_cfg and not page:
        findings.append(finding('no_checks_configured', 'pending', 'config', '', '配置实际项目规则；空检查不能作为通过'))
    return report('docx_structure', doc, findings, checks=checks,
                  visual_qa={'status': 'not_performed', 'required': '导出实际文件并逐页查看；本脚本不检查截断、重叠、缺字或分页'},
                  semantic_review={'status': 'not_performed', 'required': '人工核对段落功能、问题成因与方案对应关系'})


if __name__ == '__main__':
    raise SystemExit(run_cli(audit, __doc__))
