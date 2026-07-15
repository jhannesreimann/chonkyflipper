"""
Base class for git-based repository sync engines.
Provides shared git command execution, clone-or-update, and SHA comparison.
Subclasses implement file parsing and import logic.
"""

import os
import subprocess
from datetime import datetime


class BaseGitSync:
    """Shared git sync infrastructure for payload repos (IR, BadUSB)."""

    def __init__(self, db, repos_dir):
        self.db = db
        self.repos_dir = repos_dir

    def _run_git(self, repo_dir, *args, timeout=120):
        """Run a git command in repo_dir. Returns (stdout, stderr, returncode)."""
        cmd = ['git', '-C', repo_dir] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1

    def _get_head_sha(self, repo_dir, short=True):
        """Get the current HEAD SHA of a repo."""
        args = ['rev-parse', '--short', 'HEAD'] if short else ['rev-parse', 'HEAD']
        stdout, _, rc = self._run_git(repo_dir, *args)
        return stdout if rc == 0 else None

    def _clone_repo(self, url, repo_dir, branch='main'):
        """Shallow clone a repo. Returns (success, sha_or_error)."""
        os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
        stdout, stderr, rc = self._run_git(
            os.path.dirname(repo_dir), 'clone', '--depth', '1',
            '-b', branch, url, os.path.basename(repo_dir),
        )
        if rc != 0:
            # Try without explicit branch (some repos use master)
            stdout, stderr, rc = self._run_git(
                os.path.dirname(repo_dir), 'clone', '--depth', '1',
                url, os.path.basename(repo_dir),
            )
        if rc != 0:
            return False, f'Clone failed: {stderr[:300]}'
        return True, self._get_head_sha(repo_dir)

    def _fetch_and_merge(self, repo_dir):
        """Fetch and ff-merge origin/main (falls back to origin/master).
        Returns (action, old_sha, new_sha) where action is 'updated' or 'up_to_date'."""
        old_sha = self._get_head_sha(repo_dir)
        self._run_git(repo_dir, 'fetch', 'origin', 'main')
        self._run_git(repo_dir, 'fetch', 'origin', 'master')
        _, _, merge_rc = self._run_git(repo_dir, 'merge', 'origin/main', '--ff-only')
        if merge_rc != 0:
            self._run_git(repo_dir, 'merge', 'origin/master', '--ff-only')
        new_sha = self._get_head_sha(repo_dir)
        if old_sha == new_sha:
            return 'up_to_date', old_sha, new_sha
        return 'updated', old_sha, new_sha

    def _count_new_commits(self, repo_dir, old_sha, new_sha):
        """Count commits between two SHAs."""
        stdout, _, rc = self._run_git(
            repo_dir, 'rev-list', '--count', f'{old_sha}..{new_sha}')
        try:
            return int(stdout) if rc == 0 and stdout else 0
        except ValueError:
            return 0

    def _get_changed_files(self, repo_dir, old_sha, new_sha):
        """Return list of changed file paths between two SHAs."""
        stdout, _, rc = self._run_git(
            repo_dir, 'diff', '--name-only', old_sha, new_sha)
        if rc == 0 and stdout:
            return [f for f in stdout.split('\n') if f.strip()]
        return []

    def _record_sync(self, state_key_prefix, sha):
        """Record sync state in the DB."""
        self.db.set_sync_state(f'{state_key_prefix}_sha', sha)
        self.db.set_sync_state(f'{state_key_prefix}_synced_at',
                               datetime.now().isoformat())
