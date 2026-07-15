#!/usr/bin/env python3
"""
BadUSB Payload Sync Engine - keeps the local payload DB in sync with
upstream GitHub payload repositories. Uses git for efficient incremental
updates (avoids GitHub API rate limits). Modelled after ir/sync.py.
"""

import os
from datetime import datetime

from modules.base_sync import BaseGitSync


class BadUSBSync(BaseGitSync):
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
        super().__init__(db, repos_dir)

    def clone_or_update(self, repo_info):
        """Clone a repo shallow, or git pull if already cloned. Returns status dict."""
        repo_dir = os.path.join(self.repos_dir, repo_info['dir'])
        state_key = f"sha_{repo_info['name']}"

        if not os.path.isdir(os.path.join(repo_dir, '.git')):
            os.makedirs(self.repos_dir, exist_ok=True)
            success, result = self._clone_repo(
                repo_info['url'], repo_dir)
            if not success:
                return {'success': False, 'error': result,
                        'repo': repo_info['name']}
            sha = result
            self.db.set_sync_state(state_key, sha)
            self.db.set_sync_state(f'last_sync_{repo_info["name"]}',
                                  datetime.now().isoformat())
            return {'success': True, 'action': 'cloned', 'repo': repo_info['name'],
                    'sha': sha}

        # Already cloned — fetch and merge
        action, old_sha, new_sha = self._fetch_and_merge(repo_dir)
        if action == 'up_to_date':
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

        headers = self.db._parse_rem_headers(content)
        fname = os.path.splitext(os.path.basename(filepath))[0]
        # If the filename is generic (payload, Payload) use the parent directory
        if fname.lower() in ('payload', 'inject', 'ducky'):
            parent = os.path.basename(os.path.dirname(filepath))
            if parent and parent.lower() not in ('payloads', 'library', 'directly_ready',
                                                  'configuration_needed', 'windows',
                                                  'linux', 'macos', 'gnu-linux'):
                fname = parent
        name = headers.get('title') or fname
        name = name.replace('_', ' ').replace('-', ' ').strip().title()

        os_slug = self.db._resolve_os(
            headers.get('target', ''),
            os.path.dirname(filepath),
            content
        )
        cat = self.db._resolve_category(
            headers.get('category', ''),
            os.path.dirname(filepath)
        )

        # Scan for companion files (staged .ps1, .sh, .py, .bat, .vbs etc.)
        # in the same directory. Hak5 requires submitters to bundle these.
        companions = {}
        payload_dir = os.path.dirname(full_path)
        companion_exts = ('.ps1', '.sh', '.py', '.bat', '.vbs', '.psm1', '.cmd')
        try:
            for entry in os.listdir(payload_dir):
                if any(entry.lower().endswith(ext) for ext in companion_exts):
                    cpath = os.path.join(payload_dir, entry)
                    if os.path.isfile(cpath) and os.path.getsize(cpath) < 500_000:
                        try:
                            with open(cpath, 'r', encoding='utf-8', errors='replace') as cf:
                                companions[entry] = cf.read()
                        except Exception:
                            pass
        except Exception:
            pass

        import json
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
            companions=json.dumps(companions) if companions else '',
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

        # Determine files to import. Do a full scan when: freshly cloned, git
        # didn't report an old SHA, or the DB was reset (no stored SHA for
        # this repo). Otherwise only import files changed since last sync.
        stored_sha = self.db.get_sync_state(f'sha_{repo_info["name"]}')
        if action == 'cloned' or not status.get('old_sha') or not stored_sha:
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
