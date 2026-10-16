"""Observable failures and normal controls, using minimal synthetic OOXML."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_common import AuditError, Docx, digest
from check_citations import audit as cite, numbers
from inspect_docx import audit as inspect

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def p(text, props='', run_props=''):
    return f'<w:p><w:pPr>{props}</w:pPr><w:r><w:rPr>{run_props}</w:rPr><w:t>{escape(text)}</w:t></w:r></w:p>'


def tbl(content, padding='<w:top w:w="0" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/>'):
    return '<w:tbl><w:tblPr><w:tblCellMar>' + padding + '</w:tblCellMar></w:tblPr><w:tr><w:tc>' + content + '</w:tc></w:tr></w:tbl>'


DEFAULT_STYLES = f'''<w:styles xmlns:w="{W}"><w:docDefaults><w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults></w:styles>'''


def fixture(path, content, styles=DEFAULT_STYLES):
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body>{content}</w:body></w:document>')
        z.writestr('word/styles.xml', styles)
    return Docx(path)


def codes(result):
    return {f['code'] for f in result['findings']}


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = {'selectors': {'body': {'tables': [0]}, 'bibliography': {'tables': [1]}},
                    'citations': {'style': 'sequential'}, 'ledger': {'path': 'ledger.json'}}
        self.sources = []
        for n, title in [(1, '甲.风险研究[J].刊物,2025.'), (2, 'B. Risk[J]. Journal,2024.')]:
            self.sources.append({'id': f's{n}', 'number': n, 'title': title, 'entry': title, 'allowed_use': 'cite',
                                 'required': True, 'evidence': {'metadata': 'verified', 'metadata_locator': 'synthetic:test',
                                 'claim_support': 'checked', 'claims': [{'location': 'synthetic', 'source_locator': 'test passage', 'claim': 'test only'}]}})
        self.save_ledger()

    def tearDown(self):
        self.tmp.cleanup()

    def save_ledger(self):
        (self.base / 'ledger.json').write_text(json.dumps({'sources': self.sources}), encoding='utf-8')

    def doc(self, body='正文[1]。另一观点[2]。再次[1]。', bib=None, props=''):
        bib = bib or ''.join(p(f'[{s["number"]}] {s["entry"]}') for s in self.sources if s.get('number'))
        return fixture(self.base / 'test.docx', tbl(p(body, props)) + tbl(bib))

    def test_normal_repeated_citation_passes(self):
        result = cite(self.doc(), self.cfg, self.base)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['first_occurrence'], [1, 2])

    def test_first_occurrence_wrong(self):
        self.assertIn('first_occurrence_order', codes(cite(self.doc('先[2]再[1]'), self.cfg, self.base)))

    def test_bibliography_not_scanned_as_body(self):
        self.cfg['selectors']['body'] = {'tables': [0]}
        self.assertEqual(cite(self.doc('正文[2]'), self.cfg, self.base)['first_occurrence'], [2])

    def test_overlapping_scope_rejected(self):
        self.cfg['selectors']['body'] = {'tables': [0, 1]}
        with self.assertRaises(AuditError):
            cite(self.doc(), self.cfg, self.base)

    def test_missing_reference(self):
        self.assertIn('missing_reference', codes(cite(self.doc('正文[1-3]'), self.cfg, self.base)))

    def test_duplicate_source(self):
        self.sources[1]['entry'] = self.sources[0]['entry']; self.save_ledger()
        self.assertIn('duplicate_source', codes(cite(self.doc(), self.cfg, self.base)))

    def test_restricted_source(self):
        self.sources[0]['allowed_use'] = 'outline_only'; self.save_ledger()
        self.assertIn('restricted_source_cited', codes(cite(self.doc(), self.cfg, self.base)))

    def test_restricted_source_title_detection(self):
        self.sources.append({'id': 'restricted', 'number': None, 'allowed_use': 'outline_only', 'match_terms': ['甲', '风险研究']})
        self.save_ledger()
        self.assertIn('restricted_material_match', codes(cite(self.doc(), self.cfg, self.base)))

    def test_required_source_omission(self):
        self.sources.append({'id': 'required', 'number': None, 'title': '指定文献', 'required': True})
        self.save_ledger()
        self.assertIn('required_source_unused', codes(cite(self.doc(), self.cfg, self.base)))

    def test_unverified_not_pass(self):
        self.sources[0]['evidence']['metadata'] = 'pending'; self.save_ledger()
        self.assertEqual(cite(self.doc(), self.cfg, self.base)['status'], 'pending')

    def test_fulltext_not_claim_verification(self):
        self.sources[0]['evidence'] = {'metadata': 'verified', 'metadata_locator': 'synthetic', 'access': 'fulltext', 'read': 'fulltext'}
        self.save_ledger()
        self.assertIn('claim_support_unchecked', codes(cite(self.doc(), self.cfg, self.base)))

    def test_claim_checked_without_mapping_stays_pending(self):
        self.sources[0]['evidence']['claims'] = [{}]; self.save_ledger()
        self.assertIn('claim_support_unchecked', codes(cite(self.doc(), self.cfg, self.base)))

    def test_language_groups_optional(self):
        self.assertNotIn('language_group_headings', codes(cite(self.doc(), self.cfg, self.base)))

    def test_language_groups_enforced_when_configured(self):
        self.cfg['citations']['language_groups'] = [{'name': 'zh', 'heading_regex': '^中文文献$', 'entry_regex': '^[\u4e00-\u9fff]'}]
        self.assertIn('language_group_headings', codes(cite(self.doc(), self.cfg, self.base)))

    def test_range_and_fullwidth(self):
        self.assertEqual(numbers('a［1，2–4］b[1]'), [1, 2, 3, 4, 1])

    def test_bad_range_rejected(self):
        with self.assertRaises(AuditError): numbers('[4-2]')

    def test_ambiguous_boundary_rejected(self):
        d = fixture(self.base / 'test.docx', p('正文') + p('正文') + p('参考文献'))
        with self.assertRaises(AuditError): d.select({'start_regex': '^正文$'})

    def test_empty_template_rejected(self):
        with self.assertRaises(AuditError): self.doc().select({})

    def test_scoped_constraints_are_project_parameters(self):
        for token, target in [('限制词甲', 0), ('术语乙', 1), ('ABC', 0)]:
            with self.subTest(token=token, target=target):
                d = fixture(self.base / 'scope.docx', tbl(p(token)) + tbl(p(token)))
                cfg = {'selectors': {'section': {'tables': [target]}}, 'text_rules': [{'id': 'local', 'kind': 'forbidden', 'scope': 'section', 'pattern': token, 'suggestion': '执行当前局部要求'}]}
                hits = [f for f in inspect(d, cfg)['findings'] if f['code'] == 'local']
                self.assertEqual(len(hits), 1)
                self.assertTrue(hits[0]['location'].startswith(f'table[{target}]'))
                self.assertNotIn('local', codes(inspect(d, {'text_rules': []})))

    def test_no_local_constraint_in_other_project(self):
        self.assertNotIn('local', codes(inspect(self.doc('允许的术语'), {'text_rules': []})))

    def test_guidance_review_and_legitimate_limit(self):
        cfg = {'selectors': {'body': {'tables': [0]}}, 'text_rules': [{'id': 'guidance', 'kind': 'review', 'scope': 'body', 'pattern': '内部写作提醒', 'suggestion': '复核句子功能'}]}
        self.assertIn('guidance', codes(inspect(self.doc('内部写作提醒'), cfg)))
        self.assertNotIn('guidance', codes(inspect(self.doc('样本仅覆盖公开披露期间，因此结论限于该期间。'), cfg)))

    def test_required_subheading(self):
        cfg = {'selectors': {'body': {'tables': [0]}}, 'text_rules': [{'id': 'background', 'kind': 'required', 'scope': 'body', 'pattern': '^1.1设计背景$', 'suggestion': '分开背景目的'}]}
        self.assertIn('background', codes(inspect(self.doc('1.1 设计目的'), cfg)))

    def test_spacing_inherited_and_override(self):
        cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'before_pt': 0, 'after_pt': 0, 'line_multiple': 1.5}]}
        self.assertEqual(inspect(self.doc(), cfg)['status'], 'pass')
        bad = inspect(self.doc(props='<w:spacing w:after="120"/>'), cfg)
        self.assertIn('paragraph_spacing', codes(bad))

    def test_auto_spacing_overrides_zero(self):
        cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'after_pt': 0}]}
        self.assertIn('paragraph_spacing', codes(inspect(self.doc(props='<w:spacing w:after="0" w:afterAutospacing="1"/>'), cfg)))

    def test_fixed_line_not_multiple(self):
        cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'line_multiple': 1.5}]}
        self.assertIn('line_spacing', codes(inspect(self.doc(props='<w:spacing w:line="360" w:lineRule="exact"/>'), cfg)))

    def test_style_based_on_resolved(self):
        styles = DEFAULT_STYLES.replace('</w:styles>', '<w:style w:styleId="base" w:type="paragraph"><w:pPr><w:spacing w:after="160"/></w:pPr></w:style><w:style w:styleId="child" w:type="paragraph"><w:basedOn w:val="base"/></w:style></w:styles>')
        d = fixture(self.base / 'style.docx', tbl(p('正文', '<w:pStyle w:val="child"/>')), styles)
        cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'after_pt': 0}]}
        self.assertIn('paragraph_spacing', codes(inspect(d, cfg)))

    def test_cell_padding_independent_of_paragraph_spacing(self):
        d = fixture(self.base / 'padding.docx', tbl(p('正文'), '<w:top w:w="120"/><w:bottom w:w="0"/>'))
        cfg = {'selectors': {'body': {'tables': [0]}}, 'table_padding': {'scope': 'body', 'top_pt': 0, 'bottom_pt': 0}}
        self.assertIn('cell_padding', codes(inspect(d, cfg)))

    def test_font_override(self):
        d = fixture(self.base / 'font.docx', tbl(p('正文abc', run_props='<w:rFonts w:eastAsia="黑体" w:ascii="Arial"/>')))
        cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'fonts': {'eastAsia': '宋体', 'ascii': 'Times New Roman'}}]}
        self.assertIn('font_family', codes(inspect(d, cfg)))

    def test_independent_numbering_starts_one(self):
        cfg = {'selectors': {'list': {'tables': [0]}}, 'numbered_lists': [{'scope': 'list', 'pattern': r'^（(\d+)）', 'start': 1}]}
        self.assertIn('list_sequence', codes(inspect(self.doc('（3）分析'), cfg)))
        self.assertNotIn('list_sequence', codes(inspect(self.doc('（1）分析'), cfg)))

    def test_numbering_start_is_configurable(self):
        for start in (1, 4, 7):
            cfg = {'selectors': {'list': {'tables': [0]}}, 'numbered_lists': [{'scope': 'list', 'pattern': r'^（(\d+)）', 'start': start}]}
            self.assertNotIn('list_sequence', codes(inspect(self.doc(f'（{start}）条目'), cfg)))
            self.assertIn('list_sequence', codes(inspect(self.doc(f'（{start+1}）条目'), cfg)))

    def test_superscript_citation_has_own_font_size(self):
        for body_pt, citation_pt in [(12, 9), (10.5, 7), (14, 10)]:
            props = f'<w:sz w:val="{int(citation_pt*2)}"/>'
            d = fixture(self.base / 'super.docx', tbl(p('[1]', run_props=props+'<w:vertAlign w:val="superscript"/>')))
            cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'font_pt': body_pt, 'citation_font_pt': citation_pt}]}
            self.assertNotIn('font_size', codes(inspect(d, cfg)))
            d = fixture(self.base / 'super.docx', tbl(p('正文', run_props=props)))
            self.assertIn('font_size', codes(inspect(d, cfg)))

    def test_spacing_values_are_parameters(self):
        for multiple, before, after in [(1, 0, 0), (1.25, 3, 6), (2, 8, 4)]:
            props = f'<w:spacing w:before="{before*20}" w:after="{after*20}" w:line="{int(multiple*240)}" w:lineRule="auto"/>'
            cfg = {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'before_pt': before, 'after_pt': after, 'line_multiple': multiple}]}
            self.assertEqual(inspect(self.doc(props=props), cfg)['status'], 'pass')

    def test_numbering_resets_children(self):
        d = fixture(self.base / 'lists.docx', tbl(''.join(p(s) for s in ['1 设计', '1.1 背景', '1.2 目的', '2 方案', '2.1 内容'])))
        cfg = {'selectors': {'list': {'tables': [0]}}, 'numbered_lists': [{'scope': 'list', 'pattern': r'^(\d+(?:\.\d+)*)\s', 'start': 1}]}
        self.assertEqual(inspect(d, cfg)['status'], 'pass')

    def test_visual_qa_never_claimed(self):
        result = inspect(self.doc(), {'selectors': {'body': {'tables': [0]}}, 'formatting': [{'scope': 'body', 'after_pt': 0}]})
        self.assertEqual(result['visual_qa']['status'], 'not_performed')
        self.assertEqual(result['semantic_review']['status'], 'not_performed')

    def test_inputs_unchanged_and_cli_exit_codes(self):
        d = self.doc(); before = digest(d.path)
        cfg_path = self.base / 'config.json'; cfg_path.write_text(json.dumps(self.cfg), encoding='utf-8')
        cmd = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/check_citations.py'), str(d.path), '--config', str(cfg_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.sources[0]['evidence']['metadata'] = 'pending'; self.save_ledger()
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
        self.assertEqual(digest(d.path), before)

    def test_output_never_overwrites_existing_file(self):
        d = self.doc(); cfg_path = self.base / 'config.json'; cfg_path.write_text(json.dumps(self.cfg), encoding='utf-8')
        out = self.base / 'existing.json'; out.write_text('preserve', encoding='utf-8')
        cmd = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/check_citations.py'), str(d.path), '--config', str(cfg_path), '--out', str(out)]
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 1)
        self.assertEqual(out.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
