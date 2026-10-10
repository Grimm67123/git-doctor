#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import git_doctor


class TestGitDoctor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        # Initialize a temporary git repo
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test Committer"], cwd=self.repo_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_path, check=True)

        # Create an initial commit
        readme = self.repo_path / "README.md"
        readme.write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo_path, check=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_git_repo(self):
        self.assertTrue(git_doctor.is_git_repo(self.repo_path))
        non_repo = tempfile.mkdtemp()
        try:
            self.assertFalse(git_doctor.is_git_repo(Path(non_repo)))
        finally:
            shutil.rmtree(non_repo, ignore_errors=True)

    def test_default_branch_detection(self):
        branch = git_doctor.get_default_branch(self.repo_path)
        self.assertEqual(branch, "main")

    def test_clean_repo_diagnostics(self):
        report = git_doctor.run_diagnostics(self.repo_path)
        self.assertEqual(report["default_branch"], "main")
        self.assertIn(report["grade"], ["A+", "A", "B"])
        self.assertFalse(report["has_failures"])

    def test_merged_branch_detection(self):
        # Create a branch, commit, merge to main
        subprocess.run(["git", "checkout", "-b", "feature/login"], cwd=self.repo_path, check=True, capture_output=True)
        feat_file = self.repo_path / "feature.txt"
        feat_file.write_text("feature content", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=self.repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "add feature"], cwd=self.repo_path, check=True)

        subprocess.run(["git", "checkout", "main"], cwd=self.repo_path, check=True, capture_output=True)
        subprocess.run(["git", "merge", "feature/login"], cwd=self.repo_path, check=True, capture_output=True)

        res = git_doctor.check_branches(self.repo_path, "main")
        self.assertEqual(res["status"], "WARN")
        self.assertIn("feature/login", res["merged_branches"])

    def test_secret_detection(self):
        # Add an .env file
        env_file = self.repo_path / ".env"
        env_file.write_text("DATABASE_URL=postgres://localhost\n", encoding="utf-8")
        subprocess.run(["git", "add", ".env"], cwd=self.repo_path, check=True)

        res = git_doctor.check_secrets(self.repo_path)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn(".env", res["leaked_files"])

    def test_conflict_marker_detection(self):
        conflict_file = self.repo_path / "conflict.txt"
        conflict_file.write_text("<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\n", encoding="utf-8")
        subprocess.run(["git", "add", "conflict.txt"], cwd=self.repo_path, check=True)

        res = git_doctor.check_conflicts(self.repo_path)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("conflict.txt" in f for f in res["conflict_files"]))

    def test_json_output(self):
        report = git_doctor.run_diagnostics(self.repo_path)
        json_str = json.dumps(report)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["repo_root"], str(self.repo_path))
        self.assertIn("score", parsed)
        self.assertIn("grade", parsed)

    def test_compute_grade(self):
        self.assertEqual(git_doctor.compute_grade(98), "A+")
        self.assertEqual(git_doctor.compute_grade(88), "A")
        self.assertEqual(git_doctor.compute_grade(75), "B")
        self.assertEqual(git_doctor.compute_grade(60), "C")
        self.assertEqual(git_doctor.compute_grade(40), "F")


if __name__ == "__main__":
    unittest.main()
