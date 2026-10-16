"""Maintain local issues and tested, reversible skill releases. No background service."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
MANAGED = ('SKILL.md', 'agents', 'references', 'scripts', 'templates', 'tests')
VALID_STATES = ('pending_analysis', 'pending_validation', 'active', 'deprecated')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(temp, path)
    finally:
        if Path(temp).exists():
            Path(temp).unlink()


def append_event(root, event):
    path = root / 'evolution/issues.jsonl'
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    atomic(path, old + json.dumps(event, ensure_ascii=False) + '\n')


def current_issues(root):
    path = root / 'evolution/issues.jsonl'
    out = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            issue = json.loads(line)
            out[issue['id']] = issue
    for issue in out.values():
        issue['effective_status'] = issue['status']
        if issue['status'] == 'active':
            manifest = issue.get('validated_resources', {})
            if not manifest or any(not (root / name).is_file() or hashlib.sha256((root / name).read_bytes()).hexdigest() != value for name, value in manifest.items()):
                issue['effective_status'] = 'pending_validation'
    return list(out.values())


def record(root, issue):
    required = {'trigger', 'failure', 'root_cause', 'scope', 'remedy', 'exceptions', 'check', 'regression_test'}
    if set(issue) != required or any(not isinstance(v, str) or not v.strip() or len(v) > 1800 for v in issue.values()):
        raise ValueError('Issue requires exactly: ' + ', '.join(sorted(required)) + '; use short sanitized strings')
    if issue['scope'] not in ('project', 'user_preference', 'general'):
        raise ValueError('Invalid issue scope')
    serialized = json.dumps(issue, ensure_ascii=False)
    if re.search(r'(?:sk-[A-Za-z0-9]{12,}|-----BEGIN .*PRIVATE KEY|(?:api[_-]?key|password|token)\s*[=:]\s*\S+)', serialized, re.I):
        raise ValueError('Possible secret; remove private information before recording')
    fingerprint = hashlib.sha256(('\n'.join(issue[k].strip() for k in ('trigger', 'failure', 'scope'))).encode()).hexdigest()
    duplicate = next((i for i in current_issues(root) if i.get('fingerprint') == fingerprint), None)
    if duplicate:
        return {'duplicate': duplicate['id'], 'action': 'Investigate why the existing rule did not prevent recurrence; do not append duplicates'}
    event = dict(issue, id='ISS-' + fingerprint[:12], fingerprint=fingerprint,
                 status='pending_analysis', timestamp=stamp(), validation=None,
                 associated_version=read_version(root))
    append_event(root, event)
    return event


def package_files(root):
    files = []
    for item in MANAGED:
        path = root / item
        for f in ([path] if path.is_file() else path.rglob('*') if path.exists() else []):
            if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc':
                if not f.resolve().is_relative_to(root.resolve()):
                    raise ValueError('Managed resource escapes skill root')
                files.append(f)
    return sorted(files)


def read_version(root):
    state = root / 'evolution/state.json'
    if state.exists():
        return json.loads(state.read_text(encoding='utf-8'))['version']
    match = re.search(r'^\s+version:\s*["\']?([0-9.]+)', (root / 'SKILL.md').read_text(encoding='utf-8'), re.M)
    return match[1] if match else 'unreleased'


def resource_hashes(root):
    return {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in package_files(root)}


def test_package(root):
    proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                          cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=180)
    text = proc.stdout + proc.stderr
    if proc.returncode or not re.search(r'Ran [1-9]\d* tests?', text):
        raise ValueError('Regression failed or no tests ran:\n' + text[-7000:])
    # Check entrypoint and local links too; full creator validation remains a release acceptance step.
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    if not skill.startswith('---\nname: thesis-delivery-zh\n') or '[TODO:' in skill:
        raise ValueError('Invalid skill entrypoint')
    for target in re.findall(r'\]\(([^)]+)\)', skill):
        if not target.startswith(('http:', 'https:')) and not (root / target).is_file():
            raise ValueError('Broken resource link: ' + target)
    return {'status': 'pass', 'command': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
            'output': text, 'timestamp': stamp()}


def release(root, version, note='本地已验证修改；具体原因见问题记录'):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric x.y.z version')
    archive = root / 'evolution/releases' / (version + '.zip')
    if archive.exists():
        raise ValueError('Version already exists; never overwrite a release')
    test = test_package(root)
    files = package_files(root)
    manifest = {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(root).as_posix())
        z.writestr('_manifest.json', json.dumps(manifest))
    state = {'version': version, 'timestamp': stamp(), 'note': note, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
             'manifest': manifest, 'regression': test}
    atomic(root / 'evolution/releases' / (version + '.json'), json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    atomic(root / 'evolution/state.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    log = root / 'evolution/changes.md'
    old = log.read_text(encoding='utf-8') if log.exists() else '# 技能版本记录\n'
    atomic(log, old + f'\n- {stamp()}：发布 {version}，{note}；回归通过，{len(files)} 个文件已保存可恢复快照。\n')
    return {'version': version, 'status': 'released', 'files': len(files), 'test_output': test['output']}


def rollback(root, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid version')
    archive = root / 'evolution/releases' / (version + '.zip')
    state = json.loads((archive.with_suffix('.json')).read_text(encoding='utf-8'))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != state['archive_sha256']:
        raise ValueError('Release archive checksum mismatch')
    # Preserve the entire current managed tree before changing anything.
    backup = root / 'evolution/backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.zip')
    backup.parent.mkdir(parents=True, exist_ok=True)
    current = package_files(root)
    with ZipFile(backup, 'x', compression=ZIP_DEFLATED) as z:
        for f in current:
            z.write(f, f.relative_to(root).as_posix())
    with ZipFile(archive) as z:
        manifest = json.loads(z.read('_manifest.json'))
        for name, expected in manifest.items():
            dest = (root / name).resolve()
            if not dest.is_relative_to(root.resolve()) or Path(name).parts[0] not in MANAGED:
                raise ValueError('Unsafe snapshot path')
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise ValueError('Snapshot file checksum mismatch')
        for f in current:
            if f.relative_to(root).as_posix() not in manifest:
                f.unlink()  # verified descendant file, already backed up; never recursive delete
        for name in manifest:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    test = test_package(root)
    atomic(root / 'evolution/state.json', json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    log = root / 'evolution/changes.md'
    atomic(log, log.read_text(encoding='utf-8') + f'\n- {stamp()}：恢复 {version}，回归通过；恢复前文件备份 {backup.name}。\n')
    return {'status': 'restored', 'version': version, 'backup': str(backup), 'regression': test['status']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('list')
    p = subs.add_parser('record'); p.add_argument('--issue', required=True)
    p = subs.add_parser('transition'); p.add_argument('--id', required=True); p.add_argument('--status', choices=VALID_STATES, required=True); p.add_argument('--note', required=True)
    p = subs.add_parser('release'); p.add_argument('--version', required=True); p.add_argument('--note', default='本地已验证修改；具体原因见问题记录')
    p = subs.add_parser('rollback'); p.add_argument('--version', required=True)
    args = parser.parse_args()
    lock = ROOT / 'evolution/.lock'
    ROOT.joinpath('evolution').mkdir(exist_ok=True)
    handle = None
    try:
        if args.command != 'list':
            handle = lock.open('x', encoding='utf-8')
            handle.write(str(os.getpid())); handle.flush()
        if args.command == 'record':
            result = record(ROOT, json.loads(Path(args.issue).read_text(encoding='utf-8-sig')))
        elif args.command == 'list':
            result = current_issues(ROOT)
        elif args.command == 'transition':
            issue = next((i for i in current_issues(ROOT) if i['id'] == args.id), None)
            if issue is None:
                raise ValueError('Unknown issue')
            validation = None
            if args.status == 'active':
                named = (ROOT / issue['regression_test']).resolve()
                if not named.is_relative_to((ROOT / 'tests').resolve()) or not named.is_file():
                    raise ValueError('Active rule needs an existing local regression test')
                validation = test_package(ROOT)
            result = dict(issue, status=args.status, timestamp=stamp(), note=args.note, validation=validation)
            result.pop('effective_status', None)
            if args.status == 'active':
                result['associated_version'] = read_version(ROOT)
                result['validated_resources'] = resource_hashes(ROOT)
            append_event(ROOT, result)
        elif args.command == 'release':
            result = release(ROOT, args.version, args.note)
        else:
            result = rollback(ROOT, args.version)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False))
        return 1
    finally:
        if handle is not None:
            handle.close(); lock.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
