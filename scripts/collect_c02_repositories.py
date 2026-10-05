#!/usr/bin/env python3
"""Frozen C-02 repository metadata census; never invokes circuit tools or installs packages."""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request

PROCEDURE_SHA = 'e80a51f6fad213109497080441b8dcd2dc4d9cc9f91416f4f09937e59e5ba9f4'
CUTOFF = '2025-01-01T00:00:00+00:00'
ROOT = Path(__file__).resolve().parents[1]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def mask_comments_and_strings(source):
    """Keep positions/newlines, masking comment and string contents before declaration scan."""
    result = list(source)
    index = 0
    while index < len(source):
        start = index
        if source.startswith('//', index):
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
        elif source.startswith('/*', index):
            end = source.find('*/', index + 2)
            if end < 0:
                raise ValueError('unterminated_block_comment')
            index = end + 2
        elif source[index] == '"':
            index += 1
            while index < len(source):
                if source[index] == '\\':
                    index += 2
                elif source[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            else:
                raise ValueError('unterminated_string')
        else:
            index += 1
            continue
        for position in range(start, min(index, len(source))):
            if result[position] != '\n':
                result[position] = ' '
    return ''.join(result)


def main_declarations(source):
    masked = mask_comments_and_strings(source)
    pattern = r'\bcomponent\s+main\s*(?:\{[^{}]*\}\s*)?=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\('
    return [{'line': source.count('\n', 0, match.start()) + 1, 'template': match.group(1)}
            for match in re.finditer(pattern, masked)]


def path_roles(path):
    parts = Path(path).parts
    lowered = [part.lower() for part in parts]
    roles = []
    if any('test' in part for part in lowered):
        roles.append('test')
    if any('example' in part or 'demo' in part for part in lowered):
        roles.append('example')
    if any(part in {'node_modules', 'vendor', 'third_party', 'external'} for part in lowered):
        roles.append('vendor_or_dependency')
    return roles or ['unclassified']


def merge_sources(base):
    catalog = json.loads((base / 'catalog_sources.json').read_text())
    repos = {}
    for page in (1, 2):
        path = base / f'github-search-page-{page}-network.json'
        data = json.loads(path.read_text())
        if data.get('incomplete_results') or len(data.get('items', [])) != 100:
            raise ValueError('frozen GitHub200 search incomplete; do not silently shrink census')
        for offset, item in enumerate(data['items']):
            key = item['full_name'].casefold()
            row = repos.setdefault(key, {'full_name': item['full_name'], 'url': item['html_url'],
                                        'source_memberships': [], 'source_spellings': [], 'github_ranks': []})
            if 'github_top200' not in row['source_memberships']:
                row['source_memberships'].append('github_top200')
            row['source_spellings'].append(item['full_name'])
            row['github_ranks'].append((page - 1) * 100 + offset + 1)
            row['search_metadata'] = item
            row['search_source'] = {'path': str(path.relative_to(ROOT)), 'sha256': digest(path.read_bytes())}
    for item in catalog['projects']:
        key = item['full_name'].casefold()
        row = repos.setdefault(key, {'full_name': item['full_name'], 'url': item['url'],
                                    'source_memberships': [], 'source_spellings': [], 'github_ranks': []})
        row['source_spellings'].append(item['full_name'])
        for source in item['source_memberships']:
            if source not in row['source_memberships']:
                row['source_memberships'].append(source)
        row['circom_source_memberships'] = item['circom_source_memberships']
    dev = {item['full_name'].casefold() for item in catalog['development_exposure']['projects']}
    prior = {item['full_name'].casefold() for item in catalog['development_exposure']['prior_exposure_metadata']}
    uncertain = {repo.casefold() for family in catalog['development_exposure']['uncertain_families']
                 for repo in family['repositories']}
    for key, row in repos.items():
        known = bool(set(row['source_memberships']) & {'zkbugs', 'sok_2026'})
        row['exposure'] = {'development_used': key in dev, 'known_bug_listed': known,
                           'prior_exposure_listed': key in prior, 'family_boundary_uncertain': key in uncertain,
                           'stratum': ('development_used' if key in dev else 'known_bug_listed' if known
                                       else 'unknown' if key in prior or key in uncertain else 'unexposed_by_lists')}
    return list(repos.values())


def git_command(args, logdir, label, cwd=None, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/usr/bin/false',
               GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1', GIT_LFS_SKIP_SMUDGE='1')
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'submodule.recurse=false',
               '-c', 'protocol.file.allow=never'] + args
    started = time.monotonic()
    stdout_path = logdir / f'{label}.stdout'
    stderr_path = logdir / f'{label}.stderr'
    with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
    result = {'command': command, 'cwd': str(cwd) if cwd else None, 'returncode': returncode,
              'timed_out': timed_out, 'wall_seconds': time.monotonic() - started,
              'stdout_path': str(stdout_path.relative_to(ROOT)), 'stderr_path': str(stderr_path.relative_to(ROOT))}
    result['status'] = 'timeout' if timed_out else 'ok' if returncode == 0 else 'failed'
    atomic_json(logdir / f'{label}.json', result)
    return result, stdout_path.read_bytes()


def license_evidence(clone, tree, api_license):
    evidence = []
    if api_license:
        evidence.append({'kind': 'github_metadata', 'spdx_id': api_license.get('spdx_id'),
                         'name': api_license.get('name')})
    for path in tree:
        p = Path(path)
        if len(p.parts) == 1 and re.match(r'(?i)^(licen[sc]e|copying|unlicense)(?:[.\-_].*)?$', p.name):
            target = clone / p
            if target.is_file() and not target.is_symlink():
                data = target.read_bytes()
                evidence.append({'kind': 'root_license_file', 'path': path, 'sha256': digest(data),
                                 'bytes': len(data), 'nonempty': bool(data.strip())})
    package = clone / 'package.json'
    if package.is_file() and not package.is_symlink():
        try:
            data = json.loads(package.read_text())
            if data.get('license'):
                evidence.append({'kind': 'root_package_license', 'path': 'package.json',
                                 'declaration': data['license'], 'sha256': digest(package.read_bytes())})
        except (ValueError, UnicodeError):
            pass
    for path in tree:
        if len(Path(path).parts) == 1 and Path(path).name.lower().startswith('readme'):
            target = clone / path
            if not target.is_file() or target.is_symlink():
                continue
            data = target.read_bytes()
            content = data.decode('utf-8', errors='replace')
            declarations = re.findall(r'(?im)^.*\b(?:licensed under|license:|licen[sc]e\s*[-:]\s*)[^\n]{0,220}', content)
            for line in declarations:
                evidence.append({'kind': 'root_readme_statement', 'path': path,
                                 'sha256': digest(data), 'statement': line[:300]})
    explicit = any((item['kind'] == 'github_metadata' and item.get('spdx_id') not in (None, 'NOASSERTION'))
                   or (item['kind'] == 'root_license_file' and item['nonempty'])
                   or (item['kind'] == 'root_package_license' and str(item['declaration']).strip().upper()
                       not in {'UNLICENSED', 'NONE', ''})
                   or (item['kind'] == 'root_readme_statement' and
                       re.search(r'(?i)^(?:this (?:project|repository|repo|software|code) is |licensed under|licen[sc]e\s*:)\s*.*\b(?:MIT|Apache|GPL|LGPL|AGPL|BSD|MPL|CC0|Unlicense|ISC|Creative Commons)\b', item['statement'].strip()))
                   for item in evidence)
    if explicit:
        return {'status': 'declared', 'evidence': evidence}
    if evidence:
        return {'status': 'unknown', 'reason': 'ambiguous_or_unlicensed_root_declaration', 'evidence': evidence}
    return {'status': 'absent', 'reason': 'no_api_or_root_license_package_readme_declaration', 'evidence': []}


def collect_one(seed, base):
    folder = base / 'repositories' / seed['full_name'].replace('/', '__')
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / 'metadata.json'
    if final.exists():
        return json.loads(final.read_text())
    logs = folder / 'logs'
    logs.mkdir(exist_ok=True)
    clone = folder / 'clone'
    row = {key: value for key, value in seed.items() if key != 'search_metadata'}
    row.update({'schema_version': 1, 'owner': 'miiz', 'started_at': now(), 'procedure_sha256': PROCEDURE_SHA,
                'clone_path': str(clone.relative_to(ROOT)), 'commands': [], 'errors': [], 'entrypoints': [],
                'manual_intervention_count': 0, 'commit_sha': None, 'commit_committer_date': None,
                'license': {'status': 'unknown', 'reason': 'not_inspected'},
                'entrypoint_inventory': {'status': 'not_inspected', 'reason': 'not_started'},
                'inclusion': {'status': 'unknown', 'reasons': []}})
    metadata = seed.get('search_metadata')
    if metadata is None:
        url = f"https://api.github.com/repos/{seed['full_name']}"
        retrieved = {'url': url, 'started_at': now()}
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'c02-repository-census'})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            (logs / 'github-repository.json').write_bytes(data)
            metadata = json.loads(data)
            retrieved.update({'status': 'ok', 'sha256': digest(data),
                              'path': str((logs / 'github-repository.json').relative_to(ROOT))})
        except (OSError, ValueError) as exc:
            retrieved.update({'status': 'unknown', 'reason': str(exc)})
        retrieved['finished_at'] = now()
        row['repository_api'] = retrieved
    metadata = metadata or {}
    canonical = metadata.get('full_name', seed['full_name'])
    row['canonical_full_name'] = canonical
    row['canonical_resolution'] = 'github_metadata' if metadata else 'unresolved_requested_url'
    row['canonical_redirect'] = canonical.casefold() != seed['full_name'].casefold()
    row['lineage'] = {key: metadata.get(key) for key in ('fork', 'archived', 'default_branch')}
    row['lineage']['parent'] = (metadata.get('parent') or {}).get('full_name')
    row['lineage']['source'] = (metadata.get('source') or {}).get('full_name')
    if (row['canonical_redirect'] or row['lineage']['fork'] is True) and row['exposure']['stratum'] == 'unexposed_by_lists':
        row['exposure']['stratum'] = 'unknown'
        row['exposure']['identity_or_fork_uncertain'] = True
    try:
        command, _ = git_command(['clone', '--depth', '1', '--filter=blob:none', '--no-checkout',
                                  '--single-branch', '--no-tags', f'https://github.com/{canonical}.git', str(clone)], logs, 'clone')
        row['commands'].append(command)
        if command['status'] != 'ok':
            raise RuntimeError('clone_' + command['status'])
        command, out = git_command(['show', '-s', '--format=%H%n%cI', 'HEAD'], logs, 'head', cwd=clone)
        row['commands'].append(command)
        if command['status'] != 'ok':
            raise RuntimeError('head_metadata_' + command['status'])
        sha, date = out.decode().strip().splitlines()[:2]
        row['commit_sha'], row['commit_committer_date'] = sha, date
        recent = dt.datetime.fromisoformat(date) >= dt.datetime.fromisoformat(CUTOFF)
        row['recent_commit'] = recent
        if not recent:
            row['inclusion'] = {'status': 'excluded', 'reasons': ['head_committer_date_before_2025_01_01']}
            row['entrypoint_inventory'] = {'status': 'not_inspected', 'reason': 'date_condition_failed'}
            return finish(row, final)
        command, out = git_command(['ls-tree', '-rz', sha], logs, 'tree', cwd=clone)
        row['commands'].append(command)
        if command['status'] != 'ok':
            raise RuntimeError('tree_' + command['status'])
        tree = {}
        submodules = []
        for entry in out.split(b'\0'):
            if not entry:
                continue
            head, path = entry.split(b'\t', 1)
            mode, kind, object_id = head.decode().split()
            name = path.decode('utf-8', errors='surrogateescape')
            tree[name] = {'mode': mode, 'kind': kind, 'git_object': object_id}
            if kind == 'commit':
                submodules.append(name)
        circom = [path for path in tree if path.endswith('.circom')]
        row['circom_file_count'] = len(circom)
        row['uninitialized_submodule_paths'] = submodules
        if not circom:
            row['inclusion'] = {'status': 'excluded', 'reasons': ['no_circom_files_in_pinned_tree']}
            row['entrypoint_inventory'] = {'status': 'complete', 'circom_file_count': 0, 'entrypoint_count': 0,
                                           'scope': 'pinned_repository_tree_no_submodule_recursion'}
            return finish(row, final)
        command, _ = git_command(['checkout', '--detach', sha], logs, 'checkout', cwd=clone)
        row['commands'].append(command)
        if command['status'] != 'ok':
            raise RuntimeError('checkout_' + command['status'])
        row['source_preparation_exposure'] = {'timestamp': now(), 'scope': 'checked_out_pinned_source; component-main declarations and root licensing only'}
        row['license'] = license_evidence(clone, tree, metadata.get('license'))
        parse_errors = []
        for path in circom:
            p = clone / path
            if tree[path]['mode'] == '120000' or p.is_symlink():
                parse_errors.append({'path': path, 'reason': 'circom_symlink_not_followed'})
                continue
            try:
                data = p.read_bytes()
                declarations = main_declarations(data.decode('utf-8'))
                for declaration in declarations:
                    row['entrypoints'].append({'path': path, **declaration, 'sha256': digest(data),
                                                'git_blob': tree[path]['git_object'], 'path_roles': path_roles(path)})
            except (OSError, ValueError, UnicodeError) as exc:
                parse_errors.append({'path': path, 'reason': str(exc)})
        row['entrypoint_inventory'] = {'status': 'incomplete' if parse_errors else 'complete',
                                       'circom_file_count': len(circom), 'entrypoint_count': len(row['entrypoints']),
                                       'errors': parse_errors, 'scope': 'pinned_repository_tree_no_submodule_recursion'}
        reasons = []
        if not row['entrypoints']:
            reasons.append('main_declaration_unresolved' if parse_errors else 'no_component_main_declaration')
        if row['license']['status'] != 'declared':
            reasons.append('license_' + row['license']['status'])
        if parse_errors:
            reasons.append('entrypoint_inventory_incomplete')
        if not reasons:
            status = 'included'
        elif 'license_absent' in reasons or 'no_component_main_declaration' in reasons:
            status = 'excluded'
        else:
            status = 'unknown'
        row['inclusion'] = {'status': status, 'reasons': reasons}
    except (OSError, ValueError, RuntimeError) as exc:
        row['errors'].append({'stage': row['commands'][-1]['command'] if row['commands'] else 'initialization', 'reason': str(exc)})
        row['inclusion'] = {'status': 'unknown', 'reasons': [str(exc)]}
    return finish(row, final)


def finish(row, final):
    row['finished_at'] = now()
    row['metadata_path'] = str(final.relative_to(ROOT))
    atomic_json(final, row)
    print(json.dumps({'repo': row['full_name'], 'status': row['inclusion']['status'],
                      'entrypoints': len(row['entrypoints']), 'reasons': row['inclusion']['reasons']}), flush=True)
    return row



def refined_metadata(original, metadata_path):
    """Keep first census record intact; correct inclusion without selecting by build results."""
    row = copy.deepcopy(original)
    changes = []
    inventory = row['entrypoint_inventory']
    submodules = row.get('uninitialized_submodule_paths', [])
    if submodules and row.get('recent_commit') is True:
        inventory['potential_unenumerated_submodule_entrypoints'] = True
        inventory['status'] = 'incomplete'
        changes.append('uninitialized_submodules_keep_unknown_additional_main_denominator')
    if row.get('recent_commit') is True and row.get('commit_sha') and not row['errors']:
        if row['license']['status'] == 'unknown' and row['license'].get('evidence'):
            for item in row['license']['evidence']:
                if item['kind'] == 'root_readme_statement' and re.search(
                        r'(?i)^(?:this (?:project|repository|repo|software|code) is |licensed under|licen[sc]e\s*:)\s*.*\b(?:MIT|Apache|GPL|LGPL|AGPL|BSD|MPL|CC0|Unlicense|ISC|Creative Commons)\b',
                        item['statement'].strip()):
                    row['license']['status'] = 'declared'
                    row['license'].pop('reason', None)
                    changes.append('explicit_repository_license_declaration_accepted')
        if row['entrypoints'] and row['license']['status'] == 'declared':
            if row['inclusion']['status'] != 'included':
                row['inclusion'] = {'status': 'included', 'reasons': []}
                changes.append('at_least_one_verified_main_is_sufficient_despite_other_inventory_errors')
        elif not row['entrypoints'] and submodules:
            previous = row['inclusion']['status']
            if row['license']['status'] != 'absent':
                row['inclusion'] = {'status': 'unknown', 'reasons': ['main_in_uninitialized_submodules_unknown']}
            else:
                row['inclusion'] = {'status': 'excluded', 'reasons': ['license_absent'],
                                    'additional_unknown_reasons': ['main_in_uninitialized_submodules_unknown']}
            if previous != row['inclusion']['status']:
                changes.append('missing_submodule_main_not_treated_as_verified_absence')
    if not changes:
        return None
    row['schema_version'] = 2
    row['supersedes'] = {'path': str(metadata_path.relative_to(ROOT)), 'sha256': digest(metadata_path.read_bytes())}
    row['corrections'] = changes
    row['refined_at'] = now()
    row['metadata_path'] = str(metadata_path.with_name('metadata.v2.json').relative_to(ROOT))
    return row


def refine_collection(base):
    original_path = base / 'repositories.json'
    original = json.loads(original_path.read_text())
    refined = copy.deepcopy(original)
    changes = []
    for index, old in enumerate(original['repositories']):
        path = ROOT / old['metadata_path']
        row = refined_metadata(old, path)
        if row is not None:
            target = path.with_name('metadata.v2.json')
            if target.exists():
                row = json.loads(target.read_text())
            else:
                atomic_json(target, row)
            refined['repositories'][index] = row
            changes.append({'full_name': row['full_name'], 'before': old['inclusion'],
                            'after': row['inclusion'], 'path': row['metadata_path'], 'corrections': row['corrections']})
    refined['schema_version'] = 2
    refined['supersedes'] = {'path': str(original_path.relative_to(ROOT)), 'sha256': digest(original_path.read_bytes())}
    refined['refined_at'] = now()
    refined['corrections'] = changes
    target = base / 'repositories-v2.json'
    if target.exists():
        raise FileExistsError('Preserve existing repositories-v2.json; use a new version.')
    atomic_json(target, refined)
    print(json.dumps({'refinement_complete': True, 'changed_rows': changes}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT / 'runs/c02-corpus-2026-10-02')
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 5))
    parser.add_argument('--refine-existing', action='store_true')
    args = parser.parse_args()
    base = args.root.resolve()
    actual = digest((ROOT / 'docs/c02_corpus_procedure_2026-10-02.md').read_bytes())
    if actual != PROCEDURE_SHA:
        raise SystemExit('Procedure hash changed; census refused.')
    if args.refine_existing:
        refine_collection(base)
        return
    seeds = merge_sources(base)
    atomic_json(base / 'repository-census-inputs.json', {'procedure_sha256': PROCEDURE_SHA,
                'count': len(seeds), 'repositories': [{k: v for k, v in s.items() if k != 'search_metadata'} for s in seeds]})
    started = now()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        rows = list(executor.map(lambda seed: collect_one(seed, base), seeds))
    canonical_groups = {}
    for row in rows:
        canonical_groups.setdefault(row['canonical_full_name'].casefold(), []).append(row['full_name'])
    result = {'schema_version': 1, 'owner': 'miiz', 'procedure_sha256': PROCEDURE_SHA,
              'started_at': started, 'finished_at': now(), 'source_repository_count': len(seeds),
              'canonical_repository_count': len(canonical_groups), 'canonical_groups': canonical_groups,
              'repositories': rows, 'manual_intervention_count': 0,
              'scope': 'source and license census only; no circuit tools, dependency installs, or fuzzing'}
    atomic_json(base / 'repositories.json', result)
    print(json.dumps({'complete': True, 'repository_count': len(rows)}), flush=True)


if __name__ == '__main__':
    main()
