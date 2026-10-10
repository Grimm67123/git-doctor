# 🩺 git-doctor

> The missing diagnostic health inspector and hygiene toolkit for Git repositories.

[![CI](https://github.com/Grimm67123/git-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/Grimm67123/git-doctor/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen.svg)](#features)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Grimm67123/git-doctor/pulls)

Just like `brew doctor` inspects your Homebrew environment and `flutter doctor` audits your mobile SDKs, **`git-doctor`** audits your Git repository across 6 critical dimensions: bloated historical objects, leaked credentials, dead branch clutter, unresolved merge conflicts, configuration drift, and hygiene violations.

Zero external dependencies. Works out of the box on Linux, macOS, and Windows. Run locally in your terminal or enforce in CI via GitHub Actions.

---

```text
======================================================================
                   🩺  GIT-DOCTOR REPORT  v1.0.0                      
======================================================================
 Repository : /home/developer/workspace/project
 Default Br : main
 Health Score: 95/100 [Grade A+]
----------------------------------------------------------------------
 [PASS] Branches
         * No unmerged or stale branches detected
 [PASS] Repository Bloat
         * Repository .git directory size: 4.12 MB
 [PASS] Security & Secrets
         * No sensitive tokens, keys, or credential files detected
 [PASS] Merge Conflicts
         * No conflict markers or stale lock files found
 [PASS] Git Configuration
         * Committer Name: Developer
         * Committer Email: dev@example.com
 [PASS] Repository Hygiene
         * .gitignore is present
======================================================================
 Status: Repository is healthy and in great condition!
======================================================================
```

---

## ⚡ Quick Start

### Option 1: Run directly (Zero install)

Drop the standalone script into your PATH:

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/Grimm67123/git-doctor/main/git_doctor.py -o /usr/local/bin/git-doctor
chmod +x /usr/local/bin/git-doctor

# Run anywhere
git-doctor
```

Because of Git's built-in subcommand discovery, placing `git-doctor` in your `PATH` lets you invoke it natively:

```bash
git doctor
```

### Option 2: Install via pip

```bash
pip install git-doctor
```

### Option 3: Run with Python

```bash
git clone https://github.com/Grimm67123/git-doctor.git
python3 git-doctor/git_doctor.py
```

---

## 🔍 What git-doctor Audits

### 1. 🌿 Branch Hygiene & Ghost Branches
* **Merged Branch Detection:** Finds local branches already merged into `main`/`master` that can safely be deleted.
* **Upstream Gone Detection:** Detects local branches tracking remote branches deleted after PR merges.
* **Stale Branch Alerts:** Flags branches with no commits in over 60 days.
* **Safe Pruning:** `git-doctor fix` automatically prunes merged and gone branches.

### 2. 🪨 Historical Bloat & Oversized Blobs
* Measures overall `.git` directory disk footprint.
* Inspects packfiles and commits to find the heaviest blobs ever committed across repository history.
* Flags binaries, media files, and archives inflating clone times.

### 3. 🛡️ Security & Secret Leak Scanner
* Scans tracked files for committed secrets:
  * AWS Access Key IDs (`AKIA...`)
  * GitHub Personal Access Tokens (`ghp_...`, `gho_...`)
  * Slack Webhook URLs
  * Private key certificates (`BEGIN RSA/OPENSSH PRIVATE KEY`)
  * Generic API keys & high-entropy tokens
  * Leaked sensitive files (`.env`, `.env.local`, `id_rsa`, `credentials.json`)

### 4. ⚔️ Merge Conflict & Lock Detection
* Scans tracked files for lingering conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
* Identifies stale lock files (`.git/index.lock`, `*.lock`) blocking operations after interrupted commands.

### 5. ⚙️ Committer Configuration
* Verifies `user.name` and `user.email` are set so your commits receive proper attribution.
* Checks cross-platform line ending configurations (`core.autocrlf`).

### 6. 🧹 Repository Hygiene
* Verifies presence of `.gitignore`.
* Detects accidentally tracked build artifacts and caches (`node_modules`, `__pycache__`, `.DS_Store`, `.venv`).

---

## 🛠️ Usage & Commands

```bash
# Run full diagnostic health check
git-doctor

# Run specific diagnostics
git-doctor bloat       # Scan largest objects in Git history
git-doctor secrets     # Audit for secrets and sensitive files
git-doctor branches    # Audit merged, gone, and stale branches

# Automatically fix merged branches and clear stale locks
git-doctor fix

# Preview fixes without modifying anything
git-doctor fix --dry-run

# Output raw JSON for scripts or dashboards
git-doctor --json

# CI/CD mode (exits with code 1 on warnings or failures)
git-doctor --ci
```

### CLI Flags

| Flag | Description | Default |
| :--- | :--- | :--- |
| `command` | Subcommand: `audit`, `bloat`, `secrets`, `branches`, `fix` | `audit` |
| `--ci` | Exit with status code `1` if warnings or errors are found | `False` |
| `--strict` | Exit with status code `1` if health score is under `95` | `False` |
| `--json` | Output full diagnostic payload as JSON | `False` |
| `--no-color` | Disable ANSI terminal color codes | `False` |
| `--dry-run` | Preview actions in `fix` mode without making changes | `False` |
| `--stale-days` | Number of days before an inactive branch is marked stale | `60` |
| `--max-size-mb` | Size threshold in MB for heavy blob warnings | `5.0` |
| `--path` | Target repository path | `.` |

---

## 🚀 GitHub Actions Integration

Add `git-doctor` to your CI pipeline to prevent repository rot and catch leaked credentials on every pull request.

Create `.github/workflows/git-doctor.yml`:

```yaml
name: Git Health Audit

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run git-doctor Action
        uses: Grimm67123/git-doctor@v1
        with:
          ci: true
          strict: false
```

---

## 💡 Health Score Calculation

`git-doctor` calculates a baseline score of 100 points, deducting weighted penalties based on issue severity:

| Severity | Deductions | Issues |
| :--- | :--- | :--- |
| **Critical** | -25 to -30 pts | Tracked credentials, private keys, merge conflict markers |
| **High** | -10 to -20 pts | Heavy packfile blobs (>5MB), repo size >100MB, stale lock files |
| **Medium** | -5 to -10 pts | Missing `.gitignore`, tracked cache folders (`node_modules`), merged branches |
| **Low** | -1 to -5 pts | Stale branches (>60 days inactive), unconfigured author email |

### Letter Grades
* **A+** : 95 – 100 (Flawless repository health)
* **A**  : 85 – 94  (Healthy with minor observations)
* **B**  : 70 – 84  (Functional with mild hygiene backlog)
* **C**  : 50 – 69  (Degraded; cleanup recommended)
* **F**  : < 50     (Immediate action required)

---

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/improvement`)
3. Run the test suite: `python -m unittest discover tests`
4. Commit your changes (`git commit -m 'Add improvement'`)
5. Push to the branch (`git push origin feature/improvement`)
6. Open a Pull Request

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).
