#!/usr/bin/env python3
"""Refresh the public commit, pull request, and issue badges in README.md.

Counts come from GitHub search. A single search total is capped at 1000, so a
capped or incomplete result is split into smaller date ranges and summed.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

USER = os.environ.get("GH_USERNAME", "debangshu919")
README = os.environ.get("README_PATH", "README.md")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
YEAR = 2026
SEARCH_CAP = 1000
REQUEST_BUDGET = 40
EARLIEST = date(1970, 1, 1)
LATEST = date(2099, 12, 31)

START = "<!--START_SECTION:stats-->"
END = "<!--END_SECTION:stats-->"


def split_dates(start, end):
    if start >= end:
        raise ValueError("range cannot be split")
    mid = start + timedelta(days=(end - start).days // 2)
    right_start = mid + timedelta(days=1)
    if right_start > end:
        raise ValueError("split made no progress")
    return (start, mid), (right_start, end)


def bounded_count(fetch, path, base, qualifier, start, end, budget=None):
    """Count matches for base between start and end, inclusive."""
    if end < start:
        return 0
    charge(budget)
    query = f"{base} {qualifier}:{start.isoformat()}..{end.isoformat()}"
    total, incomplete = fetch(path, query)
    if total < SEARCH_CAP and not incomplete:
        return total
    if start >= end:
        raise RuntimeError(f"search slice still capped: {query}")
    left, right = split_dates(start, end)
    return bounded_count(
        fetch, path, base, qualifier, left[0], left[1], budget
    ) + bounded_count(fetch, path, base, qualifier, right[0], right[1], budget)


def count_exact(fetch, path, query, qualifier, budget=None):
    """Return the full public total, splitting past the 1000-result cap."""
    charge(budget)
    total, incomplete = fetch(path, query)
    if total < SEARCH_CAP and not incomplete:
        return total
    window = bounded_count(fetch, path, query, qualifier, EARLIEST, LATEST, budget)
    before = side_count(fetch, path, f"{query} {qualifier}:<{EARLIEST.isoformat()}", budget)
    after = side_count(fetch, path, f"{query} {qualifier}:>{LATEST.isoformat()}", budget)
    return window + before + after


def side_count(fetch, path, query, budget):
    charge(budget)
    total, incomplete = fetch(path, query)
    if total >= SEARCH_CAP or incomplete:
        raise RuntimeError(f"search slice still capped: {query}")
    return total


def charge(budget):
    if budget is None:
        return
    budget["used"] += 1
    if budget["used"] > budget["limit"]:
        raise RuntimeError("too many search requests")


def year_commit_query(user, year):
    return f"author:{user} author-date:{year}-01-01..{year}-12-31"


def collect_counts(fetch, user, budget=None):
    author = f"author:{user}"
    counts = {
        "commits_2026": bounded_count(
            fetch,
            "commits",
            author,
            "author-date",
            date(YEAR, 1, 1),
            date(YEAR, 12, 31),
            budget,
        ),
        "commits_all": count_exact(fetch, "commits", author, "author-date", budget),
        "prs": count_exact(fetch, "issues", f"{author} is:pr", "created", budget),
        "merged": count_exact(
            fetch, "issues", f"{author} is:pr is:merged", "created", budget
        ),
        "issues": count_exact(fetch, "issues", f"{author} is:issue", "created", budget),
    }
    for key, value in counts.items():
        if not isinstance(value, int) or value < 0:
            raise RuntimeError(f"bad count for {key}: {value}")
    return counts


def search_link(query, kind):
    return "https://github.com/search?" + urllib.parse.urlencode(
        [("q", query), ("type", kind)]
    )


def badge_line(label, color, value, query, kind):
    slug = label.replace(" ", "_")
    image = (
        f"https://img.shields.io/badge/{slug}-{value}-{color}"
        "?style=flat-square&logo=github&logoColor=white"
    )
    return f"[![{label}]({image})]({search_link(query, kind)})"


def render_badges(counts, user):
    author = f"author:{user}"
    specs = [
        (
            "2026 public commits",
            "2DA44E",
            counts["commits_2026"],
            year_commit_query(user, YEAR),
            "commits",
        ),
        (
            "all time public commits",
            "0969DA",
            counts["commits_all"],
            author,
            "commits",
        ),
        ("public prs", "8250DF", counts["prs"], f"{author} is:pr", "pullrequests"),
        (
            "merged prs",
            "1A7F37",
            counts["merged"],
            f"{author} is:pr is:merged",
            "pullrequests",
        ),
        (
            "issues opened",
            "D1242F",
            counts["issues"],
            f"{author} is:issue",
            "issues",
        ),
    ]
    return "\n".join(badge_line(*spec) for spec in specs)


def replace_section(content, body):
    block = f"{START}\n{body}\n{END}"
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if pattern.search(content) is None:
        raise SystemExit("stats markers missing from README")
    return pattern.sub(lambda _match: block, content, count=1)


def github_json(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "debangshu919-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"GitHub API {err.code}: {detail}") from err


def live_fetch(path, query):
    url = (
        "https://api.github.com/search/"
        + path
        + "?q="
        + urllib.parse.quote_plus(query)
        + "&per_page=1"
    )
    data = github_json(url)
    if "total_count" not in data:
        message = data.get("message", "missing total_count")
        raise RuntimeError(message)
    return data["total_count"], bool(data.get("incomplete_results"))


def update_readme(body):
    with open(README, encoding="utf-8", newline="") as handle:
        content = handle.read()
    updated = replace_section(content, body)
    if updated == content:
        print("README stats unchanged")
        return
    with open(README, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    print("README stats updated")


def main():
    budget = {"used": 0, "limit": REQUEST_BUDGET}
    counts = collect_counts(live_fetch, USER, budget)
    update_readme(render_badges(counts, USER))
    print(
        "counts:",
        ", ".join(f"{key}={value}" for key, value in counts.items()),
    )


if __name__ == "__main__":
    main()
