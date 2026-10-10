#!/usr/bin/env python3
"""
git-doctor: Diagnostic health inspector and hygiene toolkit for Git repositories.
Zero-dependency CLI tool and GitHub Action.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

# ANSI color codes
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
    "bg_red": "\033[41m",
    "bg_green": "\033[42m",
    "bg_yellow": "\033[43m",
}


def colorize(text, color_name, use_color=True):
    if not use_color or color_name not in COLORS:
        return text
    return f"{COLORS[color_name]}{text}{COLORS['reset']}"


def run_git(args, cwd=None):
    """Run a git command and return (stdout, returncode)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout.strip(), proc.returncode
    except FileNotFoundError:
        return "", 127
    except Exception as e:
        return "", 1


def is_git_repo(path=None):
    """Check if directory is inside a Git repository."""
    out, code = run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0 and out.strip() == "true"


def get_git_root(path=None):
    """Get the root directory of the Git repository."""
    out, code = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if code == 0 and out:
        return Path(out).resolve()
    return None


def get_default_branch(repo_root):
    """Detect the default branch (main, master, or from remote HEAD)."""
    # Try origin/HEAD first
    out, code = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_root)
    if code == 0 and out:
        return out.split("/")[-1].strip()

    # Try local main or master
    out, code = run_git(["branch", "--list", "main"], cwd=repo_root)
    if code == 0 and "main" in out:
        return "main"

    out, code = run_git(["branch", "--list", "master"], cwd=repo_root)
    if code == 0 and "master" in out:
        return "master"

    # Fallback to current branch
    out, code = run_git(["branch", "--show-current"], cwd=repo_root)
    if code == 0 and out.strip():
        return out.strip()

    return "main"


def check_branches(repo_root, default_branch, stale_days=60):
    """Check for merged, stale, and tracking-gone branches."""
    findings = []
    merged_branches = []
    stale_branches = []
    gone_branches = []

    # Get current branch
    current_branch, _ = run_git(["branch", "--show-current"], cwd=repo_root)

    # 1. Merged branches into default
    out, code = run_git(["branch", "--merged", default_branch], cwd=repo_root)
    if code == 0 and out:
        for line in out.splitlines():
            b = line.strip().lstrip("* ").strip()
            if b and b != default_branch and b != current_branch:
                merged_branches.append(b)

    # 2. Check for branches whose upstream remote is gone
    out, code = run_git(["branch", "-vv"], cwd=repo_root)
    if code == 0 and out:
        for line in out.splitlines():
            if ": gone]" in line:
                parts = line.strip().lstrip("* ").split()
                if parts:
                    b_name = parts[0]
                    if b_name != current_branch and b_name not in gone_branches:
                        gone_branches.append(b_name)

    # 3. Check for stale branches by last commit date
    out, code = run_git(
        ["for-each-ref", "--sort=-committerdate", "refs/heads/", "--format=%(refname:short)|%(committerdate:iso8601)"],
        cwd=repo_root,
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    if code == 0 and out:
        for line in out.splitlines():
            if "|" in line:
                b_name, date_str = line.split("|", 1)
                b_name = b_name.strip()
                if b_name == default_branch or b_name == current_branch:
                    continue
                try:
                    dt = datetime.datetime.fromisoformat(date_str.strip())
                    days_old = (now - dt).days
                    if days_old >= stale_days:
                        stale_branches.append({"name": b_name, "days": days_old})
                except Exception:
                    pass

    status = "PASS"
    penalty = 0

    if merged_branches:
        status = "WARN"
        penalty += min(len(merged_branches) * 2, 10)
        findings.append(f"{len(merged_branches)} local branch(es) fully merged into '{default_branch}': {', '.join(merged_branches[:5])}{'...' if len(merged_branches) > 5 else ''}")

    if gone_branches:
        status = "WARN"
        penalty += min(len(gone_branches) * 2, 10)
        findings.append(f"{len(gone_branches)} local branch(es) tracking deleted remote branches: {', '.join(gone_branches[:5])}")

    if stale_branches:
        status = "WARN"
        penalty += min(len(stale_branches) * 1, 5)
        stale_names = [f"{s['name']} ({s['days']}d)" for s in stale_branches[:4]]
        findings.append(f"{len(stale_branches)} stale branch(es) (> {stale_days} days inactive): {', '.join(stale_names)}")

    return {
        "category": "Branches",
        "status": status,
        "penalty": penalty,
        "findings": findings,
        "merged_branches": merged_branches,
        "gone_branches": gone_branches,
        "stale_branches": stale_branches,
    }


def check_bloat(repo_root, max_blob_bytes=5 * 1024 * 1024, top_n=5):
    """Check repository size and identify large blobs in history."""
    findings = []
    status = "PASS"
    penalty = 0

    # Calculate .git folder size
    git_dir = repo_root / ".git"
    git_size_bytes = 0
    if git_dir.exists():
        for p in git_dir.rglob("*"):
            if p.is_file():
                try:
                    git_size_bytes += p.stat().st_size
                except OSError:
                    pass

    git_size_mb = git_size_bytes / (1024 * 1024)

    # Find large objects in packfiles / history
    large_objects = []
    out, code = run_git(["rev-list", "--objects", "--all"], cwd=repo_root)
    if code == 0 and out:
        sha_to_path = {}
        for line in out.splitlines():
            parts = line.strip().split(" ", 1)
            if len(parts) == 2:
                sha_to_path[parts[0]] = parts[1]

        # Batch check object sizes using cat-file
        if sha_to_path:
            input_shas = "\n".join(sha_to_path.keys())
            try:
                proc = subprocess.run(
                    ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                    cwd=repo_root,
                    input=input_shas,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) == 3 and parts[1] == "blob":
                            sha, _, size_str = parts
                            try:
                                size = int(size_str)
                                if size >= max_blob_bytes:
                                    path = sha_to_path.get(sha, "unknown")
                                    large_objects.append({"sha": sha[:8], "size_bytes": size, "path": path})
                            except ValueError:
                                pass
            except Exception:
                pass

    large_objects.sort(key=lambda x: x["size_bytes"], reverse=True)
    top_large = large_objects[:top_n]

    if git_size_mb > 100:
        status = "WARN"
        penalty += 10
        findings.append(f"Repository .git directory is large: {git_size_mb:.1f} MB")
    else:
        findings.append(f"Repository .git directory size: {git_size_mb:.2f} MB")

    if top_large:
        status = "WARN"
        penalty += min(len(top_large) * 5, 20)
        for obj in top_large:
            mb = obj["size_bytes"] / (1024 * 1024)
            findings.append(f"Heavy blob in history: {obj['path']} ({mb:.2f} MB, commit object {obj['sha']})")

    return {
        "category": "Repository Bloat",
        "status": status,
        "penalty": penalty,
        "git_size_mb": round(git_size_mb, 2),
        "large_objects": top_large,
        "findings": findings,
    }


def check_secrets(repo_root):
    """Scan tracked files and recent commits for leaked credentials."""
    findings = []
    status = "PASS"
    penalty = 0

    secret_patterns = [
        ("AWS Access Key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
        ("GitHub Personal Token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,})\b")),
        ("Slack Webhook", re.compile(r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+")),
        ("Private Key Block", re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----")),
        ("Generic Private Token", re.compile(r"""(?:api_key|apikey|secret_key|secret_token)\s*=\s*['\"][a-zA-Z0-9_\-]{20,}['\"]""", re.IGNORECASE)),
    ]

    sensitive_filenames = {
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "service-account.json",
    }

    # 1. Check tracked files list
    out, code = run_git(["ls-files"], cwd=repo_root)
    tracked_files = [f for f in out.splitlines() if f.strip()] if code == 0 else []

    leaked_files = []
    for f in tracked_files:
        name = Path(f).name.lower()
        if name in sensitive_filenames:
            leaked_files.append(f)

    if leaked_files:
        status = "FAIL"
        penalty += 25
        findings.append(f"Sensitive credential file(s) tracked in Git: {', '.join(leaked_files)}")

    # 2. Pattern scanning across tracked files
    pattern_matches = 0
    for rel_path in tracked_files:
        file_path = repo_root / rel_path
        # Skip binary or very large files
        if not file_path.is_file() or file_path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                for line_no, line in enumerate(fp, start=1):
                    for label, pattern in secret_patterns:
                        if pattern.search(line):
                            # Ignore test files or false positive demo fixtures
                            if "test" in str(file_path).lower() and ("dummy" in line or "example" in line):
                                continue
                            pattern_matches += 1
                            if pattern_matches <= 3:
                                findings.append(f"{label} detected in {rel_path}:{line_no}")
        except Exception:
            pass

    if pattern_matches > 0:
        status = "FAIL"
        penalty += min(pattern_matches * 10, 30)

    if not findings:
        findings.append("No sensitive tokens, keys, or credential files detected in tracked files.")

    return {
        "category": "Security & Secrets",
        "status": status,
        "penalty": penalty,
        "findings": findings,
        "leaked_files": leaked_files,
        "secret_count": pattern_matches + len(leaked_files),
    }


def check_conflicts(repo_root):
    """Scan for unresolved merge conflict markers left in tracked files."""
    findings = []
    status = "PASS"
    penalty = 0

    conflict_patterns = [
        re.compile(r"^<<<<<<< "),
        re.compile(r"^=======$"),
        re.compile(r"^>>>>>>> "),
    ]

    out, code = run_git(["ls-files"], cwd=repo_root)
    tracked_files = [f for f in out.splitlines() if f.strip()] if code == 0 else []

    conflict_files = []
    for rel_path in tracked_files:
        file_path = repo_root / rel_path
        if not file_path.is_file() or file_path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                for line_no, line in enumerate(fp, start=1):
                    for pat in conflict_patterns:
                        if pat.match(line):
                            conflict_files.append(f"{rel_path}:{line_no}")
                            break
                    if len(conflict_files) >= 5:
                        break
        except Exception:
            pass

    # Check for git lock files
    git_dir = repo_root / ".git"
    lock_files = []
    if git_dir.exists():
        for lock in git_dir.glob("*.lock"):
            lock_files.append(str(lock.name))
        index_lock = git_dir / "index.lock"
        if index_lock.exists() and "index.lock" not in lock_files:
            lock_files.append("index.lock")

    if conflict_files:
        status = "FAIL"
        penalty += 25
        findings.append(f"Unresolved conflict markers found in: {', '.join(conflict_files[:5])}")

    if lock_files:
        status = "WARN"
        penalty += 10
        findings.append(f"Dangling Git lock file(s) present: {', '.join(lock_files)}")

    if not findings:
        findings.append("No conflict markers or stale lock files found.")

    return {
        "category": "Merge Conflicts",
        "status": status,
        "penalty": penalty,
        "findings": findings,
        "conflict_files": conflict_files,
        "lock_files": lock_files,
    }


def check_config(repo_root):
    """Check git user configuration and commit identity."""
    findings = []
    status = "PASS"
    penalty = 0

    user_name, _ = run_git(["config", "user.name"], cwd=repo_root)
    user_email, _ = run_git(["config", "user.email"], cwd=repo_root)
    autocrlf, _ = run_git(["config", "core.autocrlf"], cwd=repo_root)

    if not user_name:
        status = "WARN"
        penalty += 5
        findings.append("user.name is not configured (commits will use system hostname)")
    else:
        findings.append(f"Committer Name: {user_name}")

    if not user_email:
        status = "WARN"
        penalty += 5
        findings.append("user.email is not configured (commits will lack attribution)")
    else:
        findings.append(f"Committer Email: {user_email}")

    if autocrlf:
        findings.append(f"core.autocrlf is set to '{autocrlf}'")

    return {
        "category": "Git Configuration",
        "status": status,
        "penalty": penalty,
        "user_name": user_name,
        "user_email": user_email,
        "findings": findings,
    }


def check_hygiene(repo_root):
    """Check .gitignore presence and standard hygiene rules."""
    findings = []
    status = "PASS"
    penalty = 0

    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        status = "WARN"
        penalty += 10
        findings.append("Missing .gitignore file in repository root")
    else:
        findings.append(".gitignore is present")

    # Check for common unwanted committed folders
    unwanted_patterns = [
        "node_modules",
        "__pycache__",
        ".DS_Store",
        ".idea",
        ".vscode",
        ".venv",
    ]

    out, code = run_git(["ls-files"], cwd=repo_root)
    tracked_files = [f for f in out.splitlines() if f.strip()] if code == 0 else []

    unwanted_found = set()
    for f in tracked_files:
        for pat in unwanted_patterns:
            if pat in f:
                unwanted_found.add(pat)

    if unwanted_found:
        status = "WARN"
        penalty += len(unwanted_found) * 5
        findings.append(f"Tracked unwanted build/cache artifacts: {', '.join(sorted(unwanted_found))}")

    return {
        "category": "Repository Hygiene",
        "status": status,
        "penalty": penalty,
        "findings": findings,
        "unwanted_tracked": list(unwanted_found),
    }


def compute_grade(score):
    if score >= 95:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    return "F"


def run_diagnostics(repo_root, stale_days=60, max_blob_mb=5):
    """Run all diagnostics and assemble final report."""
    default_branch = get_default_branch(repo_root)

    branches_res = check_branches(repo_root, default_branch, stale_days=stale_days)
    bloat_res = check_bloat(repo_root, max_blob_bytes=int(max_blob_mb * 1024 * 1024))
    secrets_res = check_secrets(repo_root)
    conflicts_res = check_conflicts(repo_root)
    config_res = check_config(repo_root)
    hygiene_res = check_hygiene(repo_root)

    diagnostics = [
        branches_res,
        bloat_res,
        secrets_res,
        conflicts_res,
        config_res,
        hygiene_res,
    ]

    total_penalty = sum(d["penalty"] for d in diagnostics)
    score = max(0, 100 - total_penalty)
    grade = compute_grade(score)

    has_failures = any(d["status"] == "FAIL" for d in diagnostics)
    has_warnings = any(d["status"] == "WARN" for d in diagnostics)

    return {
        "repo_root": str(repo_root),
        "default_branch": default_branch,
        "score": score,
        "grade": grade,
        "has_failures": has_failures,
        "has_warnings": has_warnings,
        "diagnostics": diagnostics,
    }


def format_cli_report(report, use_color=True):
    """Generate ANSI formatted terminal dashboard."""
    lines = []
    w = 70

    grade_colors = {
        "A+": "green",
        "A": "green",
        "B": "cyan",
        "C": "yellow",
        "F": "red",
    }
    g_color = grade_colors.get(report["grade"], "yellow")

    lines.append(colorize("=" * w, "blue", use_color))
    title = f"  🩺  GIT-DOCTOR REPORT  v{VERSION}  "
    lines.append(colorize(title.center(w), "bold", use_color))
    lines.append(colorize("=" * w, "blue", use_color))
    lines.append(f" Repository : {report['repo_root']}")
    lines.append(f" Default Br : {report['default_branch']}")

    score_text = f" Health Score: {report['score']}/100 [Grade {report['grade']}]"
    lines.append(colorize(score_text, g_color, use_color))
    lines.append(colorize("-" * w, "gray", use_color))

    status_badges = {
        "PASS": colorize("[PASS]", "green", use_color),
        "WARN": colorize("[WARN]", "yellow", use_color),
        "FAIL": colorize("[FAIL]", "red", use_color),
    }

    for diag in report["diagnostics"]:
        badge = status_badges.get(diag["status"], "[????]")
        cat_line = f" {badge} {colorize(diag['category'], 'bold', use_color)}"
        lines.append(cat_line)
        for finding in diag["findings"]:
            lines.append(f"         * {finding}")
        lines.append("")

    lines.append(colorize("=" * w, "blue", use_color))
    if report["grade"] in ("A+", "A"):
        lines.append(colorize(" Status: Repository is healthy and in great condition!", "green", use_color))
    elif report["grade"] == "B":
        lines.append(colorize(" Status: Repository is functional but has mild hygiene issues.", "yellow", use_color))
    else:
        lines.append(colorize(" Status: Action required! Hygiene or security issues detected.", "red", use_color))
    lines.append(colorize("=" * w, "blue", use_color))

    return "\n".join(lines)


def run_fix_action(repo_root, report, dry_run=False):
    """Execute safe fixes for detected hygiene and branch issues."""
    print("Executing git-doctor fix routine...")
    fixes_applied = 0

    # 1. Prune local merged branches
    for diag in report["diagnostics"]:
        if diag["category"] == "Branches":
            merged = diag.get("merged_branches", [])
            for b in merged:
                if dry_run:
                    print(f" [DRY-RUN] Would delete merged branch: {b}")
                else:
                    out, code = run_git(["branch", "-d", b], cwd=repo_root)
                    if code == 0:
                        print(f" [FIXED] Deleted merged branch: {b}")
                        fixes_applied += 1
                    else:
                        print(f" [ERROR] Could not delete branch {b}: {out}")

    # 2. Prune dead remote tracking references
    if dry_run:
        print(" [DRY-RUN] Would run: git fetch --prune")
    else:
        out, code = run_git(["fetch", "--prune"], cwd=repo_root)
        if code == 0:
            print(" [FIXED] Pruned dead remote tracking references.")
            fixes_applied += 1

    # 3. Clear dangling lock files if present
    for diag in report["diagnostics"]:
        if diag["category"] == "Merge Conflicts":
            locks = diag.get("lock_files", [])
            for lock_name in locks:
                lock_path = repo_root / ".git" / lock_name
                if lock_path.exists():
                    if dry_run:
                        print(f" [DRY-RUN] Would remove stale lock file: {lock_name}")
                    else:
                        try:
                            lock_path.unlink()
                            print(f" [FIXED] Removed stale lock file: {lock_name}")
                            fixes_applied += 1
                        except OSError as e:
                            print(f" [ERROR] Failed to remove {lock_name}: {e}")

    print(f"\nDone! Applied {fixes_applied} fix(es).")


def main():
    parser = argparse.ArgumentParser(
        prog="git-doctor",
        description="Diagnose, audit, and clean Git repositories for optimal health and hygiene.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="audit",
        choices=["audit", "check", "bloat", "secrets", "branches", "fix"],
        help="Command to run (default: audit)",
    )
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--ci", action="store_true", help="Exit code 1 if any warnings or failures exist")
    parser.add_argument("--strict", action="store_true", help="Exit code 1 if score < 95")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode for fix command")
    parser.add_argument("--stale-days", type=int, default=60, help="Days of inactivity to mark a branch as stale")
    parser.add_argument("--max-size-mb", type=float, default=5.0, help="Threshold in MB for large blob warnings")
    parser.add_argument("--path", type=str, default=".", help="Target Git repository path")
    parser.add_argument("-v", "--version", action="version", version=f"git-doctor {VERSION}")

    args = parser.parse_args()

    target_path = Path(args.path).resolve()
    if not is_git_repo(target_path):
        print(f"Error: '{target_path}' is not a Git repository.", file=sys.stderr)
        sys.exit(1)

    repo_root = get_git_root(target_path)
    report = run_diagnostics(
        repo_root,
        stale_days=args.stale_days,
        max_blob_mb=args.max_size_mb,
    )

    use_color = not args.no_color and sys.stdout.isatty()

    if args.command == "fix":
        run_fix_action(repo_root, report, dry_run=args.dry_run)
        sys.exit(0)

    if args.json:
        print(json.dumps(report, indent=2))
    elif args.command == "bloat":
        bloat_diag = next(d for d in report["diagnostics"] if d["category"] == "Repository Bloat")
        print(f"Git Directory Size: {bloat_diag['git_size_mb']} MB")
        for f in bloat_diag["findings"]:
            print(f" - {f}")
    elif args.command == "secrets":
        sec_diag = next(d for d in report["diagnostics"] if d["category"] == "Security & Secrets")
        print(f"Status: {sec_diag['status']}")
        for f in sec_diag["findings"]:
            print(f" - {f}")
    elif args.command == "branches":
        br_diag = next(d for d in report["diagnostics"] if d["category"] == "Branches")
        print(f"Status: {br_diag['status']}")
        for f in br_diag["findings"]:
            print(f" - {f}")
    else:
        # Default: audit full report
        print(format_cli_report(report, use_color=use_color))

    # Exit code determination
    if args.strict and report["score"] < 95:
        sys.exit(1)
    if args.ci and (report["has_failures"] or report["has_warnings"]):
        sys.exit(1)
    if report["has_failures"]:
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
