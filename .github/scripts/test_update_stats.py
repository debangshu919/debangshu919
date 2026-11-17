#!/usr/bin/env python3
"""Unit tests for the public stat badge updater."""

import unittest
from datetime import date, timedelta

import update_stats


class SplitDatesTest(unittest.TestCase):
    def test_two_day_range_splits_into_single_days(self):
        left, right = update_stats.split_dates(date(2026, 1, 1), date(2026, 1, 2))
        self.assertEqual(left, (date(2026, 1, 1), date(2026, 1, 1)))
        self.assertEqual(right, (date(2026, 1, 2), date(2026, 1, 2)))

    def test_split_has_no_gap(self):
        start, end = date(2026, 1, 1), date(2026, 4, 30)
        left, right = update_stats.split_dates(start, end)
        self.assertEqual(left[0], start)
        self.assertEqual(right[1], end)
        self.assertEqual(left[1] + timedelta(days=1), right[0])

    def test_single_day_cannot_split(self):
        with self.assertRaises(ValueError):
            update_stats.split_dates(date(2026, 1, 1), date(2026, 1, 1))


class CountTest(unittest.TestCase):
    def test_year_query_is_one_request_under_the_cap(self):
        calls = []

        def fetch(path, query):
            calls.append((path, query))
            return 412, False

        got = update_stats.bounded_count(
            fetch,
            "commits",
            "author:u",
            "author-date",
            date(2026, 1, 1),
            date(2026, 12, 31),
        )
        self.assertEqual(got, 412)
        self.assertEqual(
            calls,
            [("commits", "author:u author-date:2026-01-01..2026-12-31")],
        )

    def test_capped_range_sums_both_sides(self):
        def fetch(path, query):
            if query.endswith("2026-01-01..2026-01-02"):
                return 1000, False
            if query.endswith("2026-01-01..2026-01-01"):
                return 2, False
            if query.endswith("2026-01-02..2026-01-02"):
                return 3, False
            raise AssertionError(query)

        got = update_stats.bounded_count(
            fetch,
            "commits",
            "author:u",
            "author-date",
            date(2026, 1, 1),
            date(2026, 1, 2),
        )
        self.assertEqual(got, 5)

    def test_incomplete_result_is_not_trusted(self):
        def fetch(path, query):
            if query.endswith("2026-01-01..2026-01-03"):
                return 9, True
            if query.endswith("2026-01-01..2026-01-02"):
                return 3, False
            if query.endswith("2026-01-03..2026-01-03"):
                return 1, False
            raise AssertionError(query)

        got = update_stats.bounded_count(
            fetch,
            "commits",
            "author:u",
            "author-date",
            date(2026, 1, 1),
            date(2026, 1, 3),
        )
        self.assertEqual(got, 4)

    def test_day_splits_cover_each_day_once(self):
        def fetch(path, query):
            start_s, end_s = query.split("author-date:")[1].split("..")
            start = date.fromisoformat(start_s)
            end = date.fromisoformat(end_s)
            if start == end:
                return 1, False
            return 0, True

        got = update_stats.bounded_count(
            fetch,
            "commits",
            "author:u",
            "author-date",
            date(2026, 1, 1),
            date(2026, 1, 8),
        )
        self.assertEqual(got, 8)

    def test_single_capped_day_raises(self):
        def fetch(path, query):
            return 1000, False

        with self.assertRaises(RuntimeError):
            update_stats.bounded_count(
                fetch,
                "commits",
                "author:u",
                "author-date",
                date(2026, 1, 1),
                date(2026, 1, 1),
            )

    def test_plain_query_skips_date_splits(self):
        calls = []

        def fetch(path, query):
            calls.append(query)
            return 838, False

        got = update_stats.count_exact(fetch, "commits", "author:u", "author-date")
        self.assertEqual(got, 838)
        self.assertEqual(calls, ["author:u"])

    def test_capped_plain_query_adds_outside_dates(self):
        def fetch(path, query):
            if query == "author:u":
                return 1000, True
            if "author-date:<" in query or "author-date:>" in query:
                return 1, False
            return 2, False

        got = update_stats.count_exact(fetch, "commits", "author:u", "author-date")
        self.assertEqual(got, 4)

    def test_request_budget_stops_a_runaway_split(self):
        def fetch(path, query):
            return 1000, True

        budget = {"used": 0, "limit": 3}
        with self.assertRaises(RuntimeError):
            update_stats.bounded_count(
                fetch,
                "commits",
                "author:u",
                "author-date",
                date(2026, 1, 1),
                date(2026, 12, 31),
                budget,
            )


class BadgeTest(unittest.TestCase):
    def test_badge_links_to_the_same_search(self):
        line = update_stats.badge_line(
            "issues opened",
            "D1242F",
            12,
            "author:debangshu919 is:issue",
            "issues",
        )
        self.assertEqual(
            line,
            "[![issues opened](https://img.shields.io/badge/issues_opened-12-D1242F"
            "?style=flat-square&logo=github&logoColor=white)]"
            "(https://github.com/search?q=author%3Adebangshu919+is%3Aissue&type=issues)",
        )

    def test_render_uses_requested_labels_in_order(self):
        body = update_stats.render_badges(
            {
                "commits_2026": 412,
                "commits_all": 838,
                "prs": 43,
                "merged": 37,
                "issues": 12,
            },
            "debangshu919",
        )
        labels = [
            "2026 public commits",
            "all time public commits",
            "public PRs",
            "merged PRs",
            "issues opened",
        ]
        positions = [body.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("2026_public_commits-412-2DA44E", body)
        self.assertIn("all_time_public_commits-838-0969DA", body)
        self.assertIn("public_PRs-43-8250DF", body)
        self.assertIn("merged_PRs-37-1A7F37", body)
        self.assertIn("issues_opened-12-D1242F", body)
        self.assertIn("type=commits", body)
        self.assertIn("type=pullrequests", body)
        self.assertIn("is%3Amerged", body)

    def test_replace_keeps_the_activity_section(self):
        content = (
            "intro\n"
            "<!--START_SECTION:stats-->\nold\n<!--END_SECTION:stats-->\n"
            "<!--START_SECTION:activity-->\nkeep\n<!--END_SECTION:activity-->\n"
        )
        updated = update_stats.replace_section(content, "new badge")
        self.assertIn("new badge", updated)
        self.assertNotIn("old", updated)
        self.assertIn("keep", updated)

    def test_missing_markers_fail(self):
        with self.assertRaises(SystemExit):
            update_stats.replace_section("no markers", "x")


if __name__ == "__main__":
    unittest.main()
