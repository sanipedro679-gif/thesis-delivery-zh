"""Read-only OOXML helpers. Standard library only; locations follow XML order."""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def tag(name):
    return '{' + NS['w'] + '}' + name


def norm(text):
    return re.sub(r'\s+', '', text)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class AuditError(ValueError):
    pass


class Docx:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.sha256 = digest(self.path)
        with ZipFile(path) as z:
            if z.testzip():
                raise AuditError('DOCX ZIP integrity failed')
            self.root = ET.fromstring(z.read('word/document.xml'))
            self.styles = ET.fromstring(z.read('word/styles.xml')) if 'word/styles.xml' in z.namelist() else ET.Element('styles')
            self.numbering = ET.fromstring(z.read('word/numbering.xml')) if 'word/numbering.xml' in z.namelist() else ET.Element('numbering')
        self.parent = {c: p for p in self.root.iter() for c in p}
        self.tables = list(self.root.iter(tag('tbl')))
        self.records = []
        counts = {}
        for p in self.root.find('w:body', NS).iter(tag('p')):
            ancestors, cur = [], p
            while cur in self.parent:
                cur = self.parent[cur]
                ancestors.append(cur)
            tbl = next((a for a in ancestors if a.tag == tag('tbl')), None)
            ti = self.tables.index(tbl) if tbl is not None else None
            key = f'table[{ti}]' if ti is not None else 'body'
            counts[key] = counts.get(key, 0) + 1
            text = ''.join(n.text or '' for n in p.iter(tag('t')))
            self.records.append({'index': len(self.records), 'location': f'{key}/p[{counts[key]}]',
                                 'table': ti, 'text': text, 'element': p})
        self.style_map = {s.get(tag('styleId')): s for s in self.styles.findall('w:style', NS)}
        self.default_style = next((s.get(tag('styleId')) for s in self.style_map.values()
                                   if s.get(tag('type')) == 'paragraph' and s.get(tag('default')) == '1'), None)

    def select(self, spec):
        if not isinstance(spec, dict) or not spec:
            raise AuditError('Empty selector; inspect the document and configure its boundaries')
        unknown = set(spec) - {'tables', 'outside_tables', 'start_regex', 'end_regex', 'include_end', 'text_regex'}
        if unknown:
            raise AuditError('Unknown selector keys: ' + ', '.join(sorted(unknown)))
        rows = list(self.records)
        if 'tables' in spec:
            if not spec['tables'] or any(type(t) is not int or t < 0 or t >= len(self.tables) for t in spec['tables']):
                raise AuditError('Invalid or missing table index')
            rows = [r for r in rows if r['table'] in spec['tables']]
        if spec.get('outside_tables'):
            rows = [r for r in rows if r['table'] is None]
        for boundary in ('start_regex', 'end_regex'):
            if boundary not in spec:
                continue
            hits = [i for i, r in enumerate(rows) if re.search(spec[boundary], norm(r['text']))]
            if len(hits) != 1:
                raise AuditError(f'{boundary}: expected one boundary, got {len(hits)}')
            i = hits[0]
            rows = rows[i:] if boundary == 'start_regex' else rows[:i + int(spec.get('include_end', False))]
        if 'text_regex' in spec:
            rows = [r for r in rows if re.search(spec['text_regex'], r['text'])]
        if not any(r['text'].strip() for r in rows):
            raise AuditError('Selector matched no nonempty paragraphs')
        return rows

    def style_chain(self, style_id):
        seen, chain = set(), []
        while style_id:
            if style_id in seen:
                raise AuditError('Cyclic style inheritance')
            seen.add(style_id)
            s = self.style_map.get(style_id)
            if s is None:
                break
            chain.append(s)
            b = s.find('w:basedOn', NS)
            style_id = b.get(tag('val')) if b is not None else None
        return list(reversed(chain))

    def properties(self, p, kind='pPr', run=None):
        """Cascade attributes: defaults -> paragraph styles -> run styles -> direct."""
        out = {}
        def merge(node):
            if node is not None:
                for c in node:
                    out.setdefault(c.tag.rsplit('}', 1)[-1], {}).update({k.rsplit('}', 1)[-1]: v for k, v in c.attrib.items()})
        merge(self.styles.find(f'w:docDefaults/w:{kind}Default/w:{kind}', NS))
        ps = p.find('w:pPr/w:pStyle', NS)
        sid = ps.get(tag('val')) if ps is not None else self.default_style
        for s in self.style_chain(sid):
            merge(s.find('w:' + kind, NS))
        if run is not None:
            rs = run.find('w:rPr/w:rStyle', NS)
            if rs is not None:
                for s in self.style_chain(rs.get(tag('val'))):
                    merge(s.find('w:rPr', NS))
            merge(run.find('w:rPr', NS))
        else:
            merge(p.find('w:' + kind, NS))
        return out


def finding(code, level, location, evidence, suggestion):
    return dict(code=code, level=level, location=location, evidence=evidence, suggestion=suggestion)


def report(kind, doc, findings, **details):
    state = 'fail' if any(f['level'] == 'error' for f in findings) else 'pending' if findings else 'pass'
    return dict(kind=kind, status=state, input=str(doc.path), sha256=doc.sha256,
                scope='document.xml only; headers, footnotes, textboxes, fields and tracked changes need review',
                findings=findings, **details)


def emit(result, output=None):
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        dest = Path(output)
        if dest.exists():
            raise AuditError('Output exists; choose a new versioned report path')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text + '\n', encoding='utf-8')
    print(text)
    return {'pass': 0, 'fail': 1, 'pending': 2}[result['status']]


def run_cli(function, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('docx')
    parser.add_argument('--config', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    try:
        doc = Docx(args.docx)
        if args.out and Path(args.out).resolve() in {doc.path, Path(args.config).resolve()}:
            raise AuditError('Report cannot overwrite an input')
        cfg_path = Path(args.config).resolve()
        cfg = load_json(cfg_path)
        result = function(doc, cfg, cfg_path.parent)
        if digest(doc.path) != doc.sha256:
            raise AuditError('Input changed during audit')
        return emit(result, args.out)
    except (AuditError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'fail', 'error': str(exc)}, ensure_ascii=False))
        return 1


def selected(doc, cfg, key):
    try:
        return doc.select(cfg['selectors'][key])
    except KeyError as exc:
        raise AuditError('Missing selector: ' + key) from exc


def unsupported_features(doc):
    features = []
    for name in ('footnoteReference', 'endnoteReference', 'txbxContent', 'del', 'ins', 'fldChar', 'altChunk'):
        if doc.root.find('.//w:' + name, NS) is not None:
            features.append(name)
    return features
