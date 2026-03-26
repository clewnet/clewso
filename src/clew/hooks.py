"""
Git hook management for clewso.

Installs/uninstalls shell scripts that run ``clewso review`` as part of
the git commit or push workflow.  Existing hooks are preserved by
chaining: the clewso hook calls the original hook before running review.
"""

import logging
import os
import stat
import subprocess

logger = logging.getLogger("clew.hooks")

_MARKER = "# --- clewso-hook ---"

_HOOK_TEMPLATES: dict[str, str] = {
    "pre-commit": f"""\
#!/usr/bin/env bash
{_MARKER}
# Installed by: clewso hooks install
# Run graph-aware review on staged changes before committing.
# To remove: clewso hooks uninstall

# Chain with previous hook if it exists
if [ -x "$0.pre-clewso" ]; then
    "$0.pre-clewso" "$@" || exit $?
fi

if command -v clewso >/dev/null 2>&1; then
    clewso review --staged --dry-run --output json
    STATUS=$?
    if [ $STATUS -eq 1 ]; then
        echo ""
        echo "clewso: blocking policy violation detected. Commit aborted."
        echo "Run 'clewso review --staged' for details, or commit with --no-verify to skip."
        exit 1
    fi
fi
""",
    "pre-push": f"""\
#!/usr/bin/env bash
{_MARKER}
# Installed by: clewso hooks install
# Run graph-aware review on the push diff before pushing.
# To remove: clewso hooks uninstall

# Chain with previous hook if it exists
if [ -x "$0.pre-clewso" ]; then
    "$0.pre-clewso" "$@" || exit $?
fi

if command -v clewso >/dev/null 2>&1; then
    clewso review --pr --dry-run --output json
    STATUS=$?
    if [ $STATUS -eq 1 ]; then
        echo ""
        echo "clewso: blocking policy violation detected. Push aborted."
        echo "Run 'clewso review --pr' for details, or push with --no-verify to skip."
        exit 1
    fi
fi
""",
}

_SUPPORTED_HOOKS = list(_HOOK_TEMPLATES.keys())


def _find_hooks_dir() -> str:
    """Find the git hooks directory for the current repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("Not a git repository") from None

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    return hooks_dir


def _is_clewso_hook(path: str) -> bool:
    """Check if a hook file was installed by clewso."""
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            return _MARKER in f.read(500)
    except Exception:
        return False


def install(hook_types: list[str] | None = None) -> list[str]:
    """Install clewso git hooks. Returns list of installed hook names."""
    hooks_dir = _find_hooks_dir()
    types = hook_types or ["pre-commit"]
    installed = []

    for hook_type in types:
        if hook_type not in _HOOK_TEMPLATES:
            logger.warning("Unknown hook type: %s (supported: %s)", hook_type, _SUPPORTED_HOOKS)
            continue

        hook_path = os.path.join(hooks_dir, hook_type)
        backup_path = hook_path + ".pre-clewso"

        # Back up existing non-clewso hook
        if os.path.exists(hook_path) and not _is_clewso_hook(hook_path):
            os.rename(hook_path, backup_path)
            logger.info("Backed up existing %s to %s.pre-clewso", hook_type, hook_type)

        with open(hook_path, "w") as f:
            f.write(_HOOK_TEMPLATES[hook_type])

        # Make executable
        st = os.stat(hook_path)
        os.chmod(hook_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        installed.append(hook_type)
        logger.info("Installed %s hook", hook_type)

    return installed


def uninstall(hook_types: list[str] | None = None) -> list[str]:
    """Remove clewso git hooks. Restores backups if they exist. Returns removed names."""
    hooks_dir = _find_hooks_dir()
    types = hook_types or _SUPPORTED_HOOKS
    removed = []

    for hook_type in types:
        hook_path = os.path.join(hooks_dir, hook_type)
        backup_path = hook_path + ".pre-clewso"

        if not _is_clewso_hook(hook_path):
            continue

        os.remove(hook_path)

        # Restore backup
        if os.path.exists(backup_path):
            os.rename(backup_path, hook_path)
            logger.info("Restored original %s hook", hook_type)
        else:
            logger.info("Removed %s hook", hook_type)

        removed.append(hook_type)

    return removed


def status() -> dict[str, str]:
    """Check hook installation status. Returns {hook_type: status_string}."""
    hooks_dir = _find_hooks_dir()
    result = {}

    for hook_type in _SUPPORTED_HOOKS:
        hook_path = os.path.join(hooks_dir, hook_type)
        if _is_clewso_hook(hook_path):
            backup_path = hook_path + ".pre-clewso"
            if os.path.exists(backup_path):
                result[hook_type] = "installed (chained with existing hook)"
            else:
                result[hook_type] = "installed"
        elif os.path.exists(hook_path):
            result[hook_type] = "other hook present (not clewso)"
        else:
            result[hook_type] = "not installed"

    return result
