"""Audit sequential numeric citations and a source ledger; never rewrite inputs."""
import re
from pathlib import Path
from audit_common import AuditError, finding, load_json, norm, report, run_cli, selected, unsupported_features

GROUP = re.compile(r'[\[［]([0-9０-９,，、\s\-–—]+)[\]］]')
ENTRY = re.compile(r'^\s*[\[［](\d+)[\]］]\s*(.+)$')


def numbers(text):
    result = []
    for match in GROUP.finditer(text):
        for token in re.split(r'[,，、\s]+', match[1].strip()):
            if not token:
                continue
            parts = re.split(r'[-–—]', token)
            if len(parts) == 1:
                result.append(int(parts[0]))
            elif len(parts) == 2 and all(parts):
                lo, hi = map(int, parts)
                if lo < 1 or hi < lo or hi - lo > 1000:
                    raise AuditError('Invalid citation range: ' + token)
                result.extend(range(lo, hi + 1))
            else:
                raise AuditError('Invalid citation group: ' + match[0])
    return result


def audit(doc, cfg, base=Path('.')):
    body, bib = selected(doc, cfg, 'body'), selected(doc, cfg, 'bibliography')
    if {r['index'] for r in body} & {r['index'] for r in bib}:
        raise AuditError('Body and bibliography overlap; first-occurrence scan would be invalid')
    findings, entries, first, first_loc = [], {}, [], {}
    for row in bib:
        m = ENTRY.match(row['text'])
        if not m:
            continue
        n = int(m[1])
        if n in entries:
            findings.append(finding('duplicate_number', 'error', row['location'], n, '每个文献编号只能对应一个条目'))
        entries[n] = {'text': m[2], 'location': row['location']}
    if not entries:
        raise AuditError('No bibliography entries recognized; numeric [n] style required')
    if list(entries) != list(range(1, len(entries) + 1)):
        findings.append(finding('bibliography_sequence', 'error', 'bibliography', list(entries), '按首次引用顺序连续编号'))
    seen_entries = {}
    for n, entry in entries.items():
        key = norm(entry['text']).casefold()
        if key in seen_entries:
            findings.append(finding('duplicate_source', 'error', entry['location'], [seen_entries[key], n], '同一文献沿用同一编号'))
        seen_entries[key] = n
    for row in body:
        for n in numbers(row['text']):
            if n not in first_loc:
                first_loc[n] = row['location']
                first.append(n)
            if n not in entries:
                findings.append(finding('missing_reference', 'error', row['location'], n, '补齐对应真实文献或修正编号'))
    if not first:
        findings.append(finding('no_citations', 'pending', 'body', '未识别到数字方括号引文', '核对引用样式和正文边界；不据此认定没有引用'))
    if cfg.get('citations', {}).get('style', 'sequential') != 'sequential':
        raise AuditError('Only sequential numeric citation style is supported')
    for expected, actual in enumerate(first, 1):
        if actual != expected:
            findings.append(finding('first_occurrence_order', 'error', first_loc[actual], {'expected': expected, 'actual': actual}, '同步调整正文编号、文献表和台账；重复引用保持一致'))
    for n in entries.keys() - set(first):
        findings.append(finding('uncited_reference', 'review', entries[n]['location'], n, '核对是否漏选正文范围或存在未引用条目'))
    bib_count = len(entries)
    minimum = cfg.get('citations', {}).get('minimum_academic')
    academic_count = sum(bool(re.search(r'\[(?:J|D|C|M)(?:/[^\]]+)?\]', e['text'], re.I)) for e in entries.values())
    if minimum is not None and academic_count < minimum:
        findings.append(finding('reference_count', 'error', 'bibliography', {'academic': academic_count, 'required': minimum}, '补充相关、真实且已引用的学术来源'))
    groups = cfg.get('citations', {}).get('language_groups', [])
    group_names = [g['name'] for g in groups]
    group_hits = []
    for row in bib:
        label = next((g for g in groups if re.fullmatch(g['heading_regex'], norm(row['text']))), None)
        if label:
            group_hits.append(label['name'])
    if groups and group_hits != group_names:
        findings.append(finding('language_group_headings', 'error', 'bibliography', group_hits, '按项目要求设置分组标题；分组不得破坏引用顺序'))
    current = None
    for row in bib:
        group = next((g for g in groups if re.fullmatch(g['heading_regex'], norm(row['text']))), None)
        if group:
            current = group
        m = ENTRY.match(row['text'])
        if m and current and not re.search(current['entry_regex'], m[2]):
            findings.append(finding('language_group_entry', 'error', row['location'], row['text'], '核对该文献所属分组与首次引用顺序，不能单独重排文献表'))
    ledger_cfg = cfg.get('ledger')
    ledger_summary = {'status': 'not_checked'}
    if ledger_cfg:
        ledger_path = (base / ledger_cfg['path']).resolve()
        ledger = load_json(ledger_path)
        sources = ledger['sources']
        stable_ids = [s['id'] for s in sources]
        if len(stable_ids) != len(set(stable_ids)):
            raise AuditError('Duplicate stable source IDs')
        source_map = {}
        for source in sources:
            n = source.get('number')
            if n is not None:
                if type(n) is not int or n in source_map:
                    raise AuditError('Invalid or duplicate source number in ledger')
                source_map[n] = source
            if source.get('required') and n not in entries and not source.get('exclusion_reason'):
                findings.append(finding('required_source_unused', 'pending', source['id'], source['title'], '使用指定材料，或记录有依据的未采用原因'))
        unverified, unsupported, outline_only = [], [], []
        for n, entry in entries.items():
            source = source_map.get(n)
            if source is None:
                findings.append(finding('ledger_missing', 'pending', entry['location'], n, '补齐稳定文献ID与核验记录'))
                continue
            if norm(source.get('entry', '')) != norm(entry['text']):
                findings.append(finding('ledger_entry_mismatch', 'error', entry['location'], source['id'], '文献表与台账同步；编号变化不改变稳定ID'))
            if source.get('allowed_use') not in ('cite', 'data'):
                outline_only.append(source['id'])
                findings.append(finding('restricted_source_cited', 'error', entry['location'], source['id'], '该材料禁止列入引用；按实际许可用途使用'))
            ev = source.get('evidence', {})
            if ev.get('metadata') != 'verified' or not ev.get('metadata_locator'):
                unverified.append(source['id'])
                findings.append(finding('metadata_unverified', 'pending', entry['location'], source['id'], '独立核对书目并记录来源；未命中不等于文献虚假'))
            claims = ev.get('claims', [])
            mapped = (isinstance(claims, list) and bool(claims)
                      and all(isinstance(c, dict) and all(c.get(k) for k in ('location', 'claim', 'source_locator')) for c in claims))
            if ev.get('claim_support') != 'checked' or not mapped:
                unsupported.append(source['id'])
                findings.append(finding('claim_support_unchecked', 'pending', entry['location'], source['id'], '逐处核对论点与原文页码或段落；取得全文也不等于支持引用'))
        for restriction in sources:
            if restriction.get('allowed_use') not in ('outline_only', 'format_only', 'excluded'):
                continue
            tokens = restriction.get('match_terms', [])
            for n, entry in entries.items():
                if tokens and all(norm(token) in norm(entry['text']) for token in tokens):
                    findings.append(finding('restricted_material_match', 'error', entry['location'], restriction['id'], '该材料仅限指定用途，移出参考文献'))
        ledger_summary = {'status': 'checked_records_only', 'sources': len(sources), 'metadata_pending': unverified,
                          'claim_support_pending': unsupported, 'restricted_cited': outline_only,
                          'notice': '读取已有核验记录；本脚本没有联网核验或阅读原文'}
    else:
        findings.append(finding('evidence_not_checked', 'pending', 'ledger', '未配置文献台账', '编号通过也不能宣称文献与论点已核实'))
    unsupported = unsupported_features(doc)
    if unsupported:
        findings.append(finding('unsupported_word_features', 'pending', 'document', unsupported, '用文档工具检查脚注、域或修订等，补足正文范围'))
    return report('citations', doc, findings, first_occurrence=first, bibliography_count=bib_count,
                  academic_count=academic_count, ledger=ledger_summary)


if __name__ == '__main__':
    raise SystemExit(run_cli(audit, __doc__))
