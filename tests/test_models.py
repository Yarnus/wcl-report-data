from __future__ import annotations

import unittest

from wcl_raid_coach.errors import InputError
from wcl_raid_coach.models import ReportRef


class ReportRefTests(unittest.TestCase):
    def test_parses_fragment_and_preserves_source_as_hint(self) -> None:
        ref = ReportRef.parse(
            "https://www.warcraftlogs.com/reports/AbC123#fight=12&source=34&type=damage-done"
        )

        self.assertEqual(ref.code, "AbC123")
        self.assertEqual(ref.fight, 12)
        self.assertEqual(ref.source_hint, 34)

    def test_fragment_parameters_override_query_parameters(self) -> None:
        ref = ReportRef.parse(
            "https://warcraftlogs.com/reports/AbC123?fight=1&source=2#fight=last&source=3"
        )

        self.assertEqual(ref.fight, "last")
        self.assertEqual(ref.source_hint, 3)

    def test_parses_cn_report_url(self) -> None:
        ref = ReportRef.parse("https://cn.warcraftlogs.com/reports/AbC123#fight=9")

        self.assertEqual(ref.code, "AbC123")
        self.assertEqual(ref.fight, 9)
        self.assertEqual(ref.canonical_url(), "https://www.warcraftlogs.com/reports/AbC123#fight=9")

    def test_rejects_classic_and_non_report_urls(self) -> None:
        invalid = (
            "https://classic.warcraftlogs.com/reports/AbC123",
            "https://example.com/reports/AbC123",
            "https://www.warcraftlogs.com/character/id/1",
        )

        for value in invalid:
            with self.subTest(value=value), self.assertRaises(InputError):
                ReportRef.parse(value)

    def test_rejects_invalid_fight(self) -> None:
        with self.assertRaises(InputError):
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=zero")

    def test_rejects_url_user_information_instead_of_persisting_it(self) -> None:
        with self.assertRaises(InputError):
            ReportRef.parse("https://secret@example.com@www.warcraftlogs.com/reports/AbC123")


if __name__ == "__main__":
    unittest.main()
