#!/usr/bin/env python3
"""
BadUSB Payload Sync Engine - keeps the local payload DB in sync with
upstream GitHub payload repositories. Uses git for efficient incremental
updates (avoids GitHub API rate limits). Modelled after ir_sync.py.
"""

import os
import subprocess
import re
import time
from datetime import datetime


class BadUSBSync:
    """Sync engine for GitHub DuckyScript repos -> local SQLite database."""

    REPOS = [
        {
            'url': 'https://github.com/hak5/usbrubberducky-payloads.git',
            'name': 'hak5',
            'dir': 'hak5-payloads',
        },
        {
            'url': 'https://github.com/Starvinci/BadUsb-Library.git',
            'name': 'starvinci',
            'dir': 'starvinci-badusb',
        },
        {
            'url': 'https://github.com/aleff-github/my-flipper-shits.git',
            'name': 'aleff',
            'dir': 'aleff-flipper',
        },
    ]

    def __init__(self, db, repos_dir=None):
        self.db = db
        if repos_dir is None:
            candidates = [
                '/opt/chonkyflipper/data/badusb_repos',
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             '..', 'data', 'badusb_repos'),
            ]
            repos_dir = candidates[0]
            for p in candidates:
                if os.path.isdir(os.path.dirname(p)):
                    repos_dir = p
                    break
        self.repos_dir = repos_dir

    def _run_git(self, repo_dir, *args):
        cmd = ['git', '-C', repo_dir] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1

    def clone_or_update(self, repo_info):
        """Clone a repo shallow, or git pull if already cloned. Returns status dict."""
        repo_dir = os.path.join(self.repos_dir, repo_info['dir'])
        state_key = f"sha_{repo_info['name']}"

        if not os.path.isdir(os.path.join(repo_dir, '.git')):
            os.makedirs(self.repos_dir, exist_ok=True)
            stdout, stderr, rc = self._run_git(
                self.repos_dir, 'clone', '--depth', '1',
                repo_info['url'], repo_info['dir'],
            )
            if rc != 0:
                return {'success': False, 'error': f'Clone failed: {stderr[:300]}',
                        'repo': repo_info['name']}

            # Get current SHA
            sha, _, rc = self._run_git(repo_dir, 'rev-parse', '--short', 'HEAD')
            if rc == 0 and sha:
                self.db.set_sync_state(state_key, sha)
                self.db.set_sync_state(f'last_sync_{repo_info["name"]}',
                                      datetime.now().isoformat())
            return {'success': True, 'action': 'cloned', 'repo': repo_info['name'],
                    'sha': sha}

        # Already cloned — fetch and merge
        old_sha, _, rc = self._run_git(repo_dir, 'rev-parse', '--short', 'HEAD')
        if rc != 0:
            old_sha = ''

        self._run_git(repo_dir, 'fetch', 'origin', 'main')
        self._run_git(repo_dir, 'fetch', 'origin', 'master')
        # Try main first, fall back to master
        merge_out, merge_err, merge_rc = self._run_git(
            repo_dir, 'merge', 'origin/main', '--ff-only',
        )
        if merge_rc != 0:
            merge_out, merge_err, merge_rc = self._run_git(
                repo_dir, 'merge', 'origin/master', '--ff-only',
            )

        new_sha, _, rc = self._run_git(repo_dir, 'rev-parse', '--short', 'HEAD')
        if rc != 0:
            new_sha = old_sha

        if old_sha == new_sha:
            return {'success': True, 'action': 'up_to_date', 'repo': repo_info['name'],
                    'sha': new_sha}

        self.db.set_sync_state(state_key, new_sha)
        self.db.set_sync_state(f'last_sync_{repo_info["name"]}',
                              datetime.now().isoformat())
        return {'success': True, 'action': 'updated', 'repo': repo_info['name'],
                'old_sha': old_sha, 'sha': new_sha}

    def _get_changed_files(self, repo_dir, old_sha, new_sha):
        """Return list of changed .txt files between two commits."""
        stdout, _, rc = self._run_git(
            repo_dir, 'diff', '--name-only', old_sha, new_sha, '--', '*.txt',
        )
        if rc != 0 or not stdout:
            return []
        return [f for f in stdout.split('\n') if f.endswith('.txt')]

    def _find_all_txt_files(self, repo_dir):
        """Walk repo directory for all .txt files."""
        files = []
        for rootdir, _dirs, filenames in os.walk(repo_dir):
            for fname in filenames:
                if fname.endswith('.txt') and '.git' not in rootdir:
                    files.append(os.path.relpath(os.path.join(rootdir, fname), repo_dir))
        return files

    def _parse_rem_headers(self, content):
        """Extract metadata from REM comment headers in DuckyScript."""
        headers = {}
        patterns = {
            'title': r'REM\s+Title:\s*(.+)',
            'author': r'REM\s+Author:\s*(.+)',
            'description': r'REM\s+Description:\s*(.+)',
            'target': r'REM\s+Target:\s*(.+)',
            'category': r'REM\s+Category:\s*(.+)',
            'props': r'REM\s+Props:\s*(.+)',
            'version': r'REM\s+Version:\s*(.+)',
            'layout': r'REM\s+Layout:\s*(.+)',
        }
        for line in content.split('\n'):
            line = line.strip()
            if not line.upper().startswith('REM '):
                if line and not line.upper().startswith('REM'):
                    if headers:
                        break
                continue
            for key, pat in patterns.items():
                m = re.match(pat, line, re.IGNORECASE)
                if m:
                    headers[key] = m.group(1).strip()
        return headers

    def _resolve_os(self, target_text, dirpath=''):
        t = (target_text or '').lower()
        d = dirpath.lower()
        combined = f'{t} {d}'
        if 'windows' in combined or 'win' in t:
            return 'windows'
        if 'linux' in combined or 'ubuntu' in combined or 'debian' in combined or 'kali' in combined:
            return 'linux'
        if 'macos' in combined or 'mac os' in combined or 'osx' in combined or 'mac' in t:
            return 'macos'
        if 'android' in combined:
            return 'android'
        if 'ios' in combined or 'iphone' in combined or 'ipad' in combined:
            return 'ios'
        return 'cross-platform'

    def _resolve_category(self, category_text, dirpath=''):
        if category_text:
            t = category_text.lower().replace(' ', '_').replace('-', '_')
            for cat in self.db.CATEGORIES:
                if cat.lower() in t:
                    return cat.lower().replace(' ', '_')
        if dirpath:
            d = dirpath.lower()
            for cat in self.db.CATEGORIES:
                if cat.lower() in d:
                    return cat.lower().replace(' ', '_')
        return 'general'

    def _import_payload(self, filepath, repo_name, repo_dir):
        """Import a single .txt payload file into the database."""
        full_path = os.path.join(repo_dir, filepath)
        if not os.path.isfile(full_path):
            return None

        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            return None

        if not content.strip():
            return None

        headers = self._parse_rem_headers(content)
        name = headers.get('title') or os.path.splitext(os.path.basename(filepath))[0]
        name = name.replace('_', ' ').replace('-', ' ').strip().title()

        os_slug = self._resolve_os(
            headers.get('target', ''),
            os.path.dirname(filepath)
        )
        cat = self._resolve_category(
            headers.get('category', ''),
            os.path.dirname(filepath)
        )

        payload_id = self.db.insert_payload(
            name=name, content=content, os_slug=os_slug,
            category_slug=cat,
            description=headers.get('description', ''),
            author=headers.get('author', ''),
            target=headers.get('target', ''),
            source_repo=repo_name, source_path=filepath,
            layout=headers.get('layout', 'us'),
            props=headers.get('props', ''),
            payload_version=headers.get('version', ''),
        )
        return {'id': payload_id, 'name': name, 'os': os_slug, 'category': cat}

    def sync_repo(self, repo_info, progress_callback=None):
        """Sync a single repo: clone/update, find changes, import."""
        status = self.clone_or_update(repo_info)
        if not status['success']:
            return status

        repo_dir = os.path.join(self.repos_dir, repo_info['dir'])
        action = status.get('action', 'up_to_date')

        if action == 'up_to_date' and self.db.get_sync_state(f'sha_{repo_info["name"]}'):
            return {'success': True, 'action': 'up_to_date', 'repo': repo_info['name'],
                    'files_added': 0, 'files_updated': 0, 'sha': status.get('sha', '')}

        # Determine files to import
        if action == 'cloned' or not status.get('old_sha'):
            changed = self._find_all_txt_files(repo_dir)
        else:
            changed = self._get_changed_files(
                repo_dir, status['old_sha'], status['sha'])

        if not changed:
            return {'success': True, 'action': action, 'repo': repo_info['name'],
                    'files_added': 0, 'files_updated': 0, 'sha': status.get('sha', '')}

        added = 0
        updated = 0
        skipped = 0
        total = len(changed)

        for idx, rel_path in enumerate(changed):
            # Skip non-payload directories like languages/, extensions/, .github/
            parts = rel_path.replace('\\', '/').split('/')
            if parts[0] in ('languages', 'extensions', '.github', 'README.md', 'LICENSE'):
                skipped += 1
                continue

            # Check if already imported (only for non-clone actions)
            if action != 'cloned':
                existing = self.db._find_by_source(repo_info['name'], rel_path)
                if existing:
                    updated += 1  # Will be re-inserted via INSERT OR REPLACE
                else:
                    added += 1
            else:
                added += 1

            result = self._import_payload(rel_path, repo_info['name'], repo_dir)
            if result is None:
                skipped += 1

            if progress_callback:
                progress_callback(idx + 1, total, repo_info['name'])

        return {'success': True, 'action': action, 'repo': repo_info['name'],
                'files_added': added, 'files_updated': updated,
                'skipped': skipped, 'sha': status.get('sha', ''),
                'total': total}

    def sync(self, progress_callback=None):
        """Sync all configured repos."""
        results = []
        for repo_info in self.REPOS:
            try:
                result = self.sync_repo(repo_info, progress_callback)
                results.append(result)
            except Exception as e:
                results.append({'success': False, 'repo': repo_info['name'],
                               'error': str(e)})

        # Also seed from local filesystem on first sync
        local = self.db.seed_from_filesystem('/opt/chonkyflipper/payloads')
        if local.get('imported', 0) > 0:
            results.append({'success': True, 'action': 'local_seed',
                           'repo': 'filesystem', 'files_added': local['imported'],
                           'skipped': local.get('skipped', 0)})

        self.db.set_sync_state('last_sync_at', datetime.now().isoformat())
        return {'success': True, 'repos': results}

    def check_for_updates(self):
        """Quick check: are there new commits in any repo?"""
        updates = {}
        for repo_info in self.REPOS:
            repo_dir = os.path.join(self.repos_dir, repo_info['dir'])
            if not os.path.isdir(os.path.join(repo_dir, '.git')):
                updates[repo_info['name']] = {
                    'status': 'not_cloned', 'message': 'Repo not cloned yet'}
                continue

            old_sha, _, _ = self._run_git(repo_dir, 'rev-parse', '--short', 'HEAD')
            self._run_git(repo_dir, 'fetch', 'origin', 'main')
            self._run_git(repo_dir, 'fetch', 'origin', 'master')
            new_sha_main, _, _ = self._run_git(
                repo_dir, 'rev-parse', '--short', 'origin/main')
            new_sha_master, _, _ = self._run_git(
                repo_dir, 'rev-parse', '--short', 'origin/master')

            new_sha = new_sha_main if new_sha_main else new_sha_master
            if old_sha and new_sha and old_sha != new_sha:
                count_out, _, _ = self._run_git(
                    repo_dir, 'rev-list', '--count', f'{old_sha}..{new_sha}')
                try:
                    count = int(count_out.strip()) if count_out else 0
                except ValueError:
                    count = 0
                updates[repo_info['name']] = {
                    'status': 'updates_available', 'new_commits': count,
                    'old_sha': old_sha, 'new_sha': new_sha}
            else:
                updates[repo_info['name']] = {
                    'status': 'up_to_date', 'sha': old_sha or new_sha}

        return {'success': True, 'repos': updates}
