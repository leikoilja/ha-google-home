#!/usr/bin/env python3
"""Update manifest.json and create new Github Release."""
from __future__ import annotations

import json
import os
import sys

from github import Github
from github.ContentFile import ContentFile
from github.GitRelease import GitRelease
from github.Repository import Repository


def main() -> int:
    """Main function"""
    github_token = os.environ.get("GITHUB_TOKEN")
    print("Fetching draft release...")
    github = Github(github_token)
    repo = github.get_repo("leikoilja/ha-google-home")
    release = repo.get_releases()[0]
    if not release.draft:
        print("The latest release is not a draft!")
        return 1
    version = release.title.split()[-1].lstrip("v")
    update_version(repo, version)
    publish_release(release)
    return 0


def update_version(repo: Repository, version: str) -> None:
    """Update manifest.json with the new version"""
    print("Updating manifest.json...")
    manifest = repo.get_contents("custom_components/google_home/manifest.json")
    assert isinstance(manifest, ContentFile)
    manifest_json = json.loads(manifest.decoded_content)
    manifest_json["version"] = version
    updated_manifest = json.dumps(manifest_json, indent=2) + "\n"
    branch = repo.get_branch("master")
    # Disable branch protection before commit
    branch.remove_admin_enforcement()
    repo.update_file(
        path=manifest.path,
        message=f"Release v{version}",
        content=updated_manifest,
        sha=manifest.sha,
    )
    # Re-enable branch protection
    branch.set_admin_enforcement()


def publish_release(release: GitRelease) -> None:
    """Publish draft release"""
    print("Publishing new release...")
    release.update_release(
        name=release.title.split()[-1],
        message=release.body,
        draft=False,
    )


if __name__ == "__main__":
    sys.exit(main())
