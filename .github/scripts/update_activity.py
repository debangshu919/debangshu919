#!/usr/bin/env python3
"""Replace the recent-activity block in README.md with pull requests and releases."""

import json
import os
import re
import urllib.request

USER = os.environ.get("GH_USERNAME", "debangshu919")
MAX_LINES = int(os.environ.get("MAX_LINES", "5"))
README = os.environ.get("README_PATH", "README.md")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

START = "<!--START_SECTION:activity-->"
END = "<!--END_SECTION:activity-->"
PR_ACTIONS = {"opened": "Opened", "closed": "Closed", "merged": "Merged"}


def fetch_events():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "debangshu919-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    events = []
    for page in range(1, 4):
        request = urllib.request.Request(
            f"https://api.github.com/users/{USER}/events/public?per_page=100&page={page}",
            headers=headers,
        )
        with urllib.request.urlopen(request) as response:
            batch = json.load(response)
        if not batch:
            break
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


def activity_line(event):
    repo = event["repo"]["name"]
    repo_url = f"https://github.com/{repo}"
    payload = event.get("payload") or {}
    kind = event["type"]

    if kind == "PullRequestEvent":
        action = payload.get("action")
        verb = PR_ACTIONS.get(action)
        number = (payload.get("pull_request") or {}).get("number") or payload.get("number")
        if not verb or not number:
            return None
        url = f"{repo_url}/pull/{number}"
        return f"{verb} PR [#{number}]({url}) in [{repo}]({repo_url})"

    if kind == "ReleaseEvent" and payload.get("action") == "published":
        release = payload.get("release") or {}
        tag = release.get("tag_name")
        url = release.get("html_url")
        if not tag or not url:
            return None
        return f"Published [{tag}]({url}) in [{repo}]({repo_url})"

    return None


def main():
    lines = []
    for event in fetch_events():
        text = activity_line(event)
        if text is None:
            continue
        lines.append(text)
        if len(lines) >= MAX_LINES:
            break

    body = (
        "\n".join(f"{index}. {text}" for index, text in enumerate(lines, 1))
        if lines
        else "No recent pull requests or releases."
    )
    block = f"{START}\n{body}\n{END}"

    with open(README, encoding="utf-8", newline="") as handle:
        content = handle.read()

    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if pattern.search(content) is None:
        raise SystemExit("activity markers missing from README")

    updated = pattern.sub(lambda _match: block, content, count=1)
    if updated == content:
        print("README unchanged")
        return

    with open(README, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    print(f"README updated with {len(lines)} lines")


if __name__ == "__main__":
    main()
