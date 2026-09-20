import os
import unittest
from datetime import date
from scrapers.base import JobPosting
from scrapers.jobsacuk import JobsAcUkScraper
from scrapers.linkedin import LinkedInScraper
from processor.deduplicator import JobDeduplicator
from processor.map_generator import MapGenerator, parse_deadline_info, get_fit_score_tier


class TestDeadlineAndStatus(unittest.TestCase):

    def test_parse_deadline_info_past_due(self):
        ref = date(2026, 9, 19)

        # > 30 days in the past -> past_due
        cat, label, diff = parse_deadline_info("2026-08-01", ref_date=ref)
        self.assertEqual(cat, "past_due")
        self.assertIn("Past Due", label)
        self.assertTrue(diff < -30)

        # Exactly 31 days in the past -> past_due
        cat, label, diff = parse_deadline_info("2026-08-19", ref_date=ref)
        self.assertEqual(cat, "past_due")
        self.assertEqual(diff, -31)

        # 15 days in the past -> passed (within 30 days)
        cat, label, diff = parse_deadline_info("2026-09-04", ref_date=ref)
        self.assertEqual(cat, "passed")
        self.assertIn("Passed", label)
        self.assertEqual(diff, -15)

        # Future deadlines
        cat, _, diff = parse_deadline_info("2026-09-22", ref_date=ref)
        self.assertEqual(cat, "urgent")
        self.assertEqual(diff, 3)

        cat, _, diff = parse_deadline_info("2026-10-10", ref_date=ref)
        self.assertEqual(cat, "closing_soon")
        self.assertEqual(diff, 21)

        cat, _, diff = parse_deadline_info("2026-11-15", ref_date=ref)
        self.assertEqual(cat, "future")
        self.assertTrue(diff > 30)

    def test_job_posting_extract_deadline_from_text(self):
        ref = date(2026, 9, 19)

        # LSU New Orleans example text
        lsu_text = (
            "Application review will begin on October 1, 2026 and the review will continue until the position is filled. "
            "For full consideration, all required materials should be submitted in the University's application portal by September 30, 2026."
        )
        dl = JobPosting.extract_deadline_from_text(lsu_text, ref_date=ref)
        self.assertIsNotNone(dl)
        self.assertIn("2026-09-30", dl)

        # European / UK style date
        uk_text = "The closing date for applications is 15 October 2026."
        dl_uk = JobPosting.extract_deadline_from_text(uk_text, ref_date=ref)
        self.assertEqual(dl_uk, "2026-10-15")

        # Month and Day without year
        card_text = "Closes 05 Oct"
        dl_card = JobPosting.extract_deadline_from_text(card_text, ref_date=ref)
        self.assertEqual(dl_card, "2026-10-05")

        # Open until filled
        open_text = "Applications are accepted on a rolling basis. Open until filled."
        dl_open = JobPosting.extract_deadline_from_text(open_text, ref_date=ref)
        self.assertEqual(dl_open, "Open until filled")

    def test_refresh_deadline_status(self):
        ref = date(2026, 9, 19)

        # Job with deadline > 30 days in the past
        past_job = JobPosting(
            id="job_past",
            title="Assistant Professor",
            institution="Old University",
            field="Civil Engineering",
            location="Chicago, IL",
            deadline="2026-07-15",
            salary="Not specified",
            link="https://example.com/past",
            source="Test",
            status="Active",
        )
        JobDeduplicator.refresh_deadline_status(past_job, ref_date=ref)
        self.assertEqual(past_job.status, "Past Due")

        # Job with active future deadline
        future_job = JobPosting(
            id="job_future",
            title="Assistant Professor",
            institution="Future University",
            field="Civil Engineering",
            location="Austin, TX",
            deadline="2026-11-01",
            salary="Not specified",
            link="https://example.com/future",
            source="Test",
            status="Active",
        )
        JobDeduplicator.refresh_deadline_status(future_job, ref_date=ref)
        self.assertEqual(future_job.status, "Active")

        # Job previously Past Due whose deadline is rolling -> restored to Active
        renewed_job = JobPosting(
            id="job_renewed",
            title="Assistant Professor",
            institution="Renewed University",
            field="Civil Engineering",
            location="Seattle, WA",
            deadline="Open until filled",
            salary="Not specified",
            link="https://example.com/renewed",
            source="Test",
            status="Past Due",
        )
        JobDeduplicator.refresh_deadline_status(renewed_job, ref_date=ref)
        self.assertEqual(renewed_job.status, "Active")

        # Filtered jobs must retain filtered status
        filtered_job = JobPosting(
            id="job_filtered",
            title="Bus Driver",
            institution="Transit Co",
            field="Operations",
            location="Denver, CO",
            deadline="2026-05-01",
            salary="Not specified",
            link="https://example.com/filtered",
            source="Test",
            status="Filtered (Non-Faculty)",
        )
        JobDeduplicator.refresh_deadline_status(filtered_job, ref_date=ref)
        self.assertEqual(filtered_job.status, "Filtered (Non-Faculty)")

    def test_fit_score_tier_exclusions(self):
        # 9-10 -> tier_9_10
        self.assertEqual(get_fit_score_tier(10), "tier_9_10")
        self.assertEqual(get_fit_score_tier(9), "tier_9_10")
        # 7-8 -> tier_7_8
        self.assertEqual(get_fit_score_tier(8), "tier_7_8")
        self.assertEqual(get_fit_score_tier(7), "tier_7_8")
        # 5-6 -> tier_5_6
        self.assertEqual(get_fit_score_tier(6), "tier_5_6")
        self.assertEqual(get_fit_score_tier(5), "tier_5_6")
        # 3-4 -> tier_3_4
        self.assertEqual(get_fit_score_tier(4), "tier_3_4")
        self.assertEqual(get_fit_score_tier(3), "tier_3_4")
        # 1-2 and None -> excluded (None)
        self.assertIsNone(get_fit_score_tier(2))
        self.assertIsNone(get_fit_score_tier(1))
        self.assertIsNone(get_fit_score_tier(None))

    def test_map_generator_excludes_past_due_and_unscored(self):
        test_map_path = "test_map_out.html"

        postings = [
            # Valid active posting
            JobPosting(
                id="active_1",
                title="Assistant Professor Transportation",
                institution="Active University",
                field="Civil Engineering",
                location="Minneapolis, MN",
                deadline="2026-11-01",
                salary="$100,000",
                link="https://example.com/active",
                source="Chronicle",
                fit_score=8,
                latitude=44.9778,
                longitude=-93.2650,
                status="Active",
            ),
            # Past due posting (> 30 days past)
            JobPosting(
                id="past_due_1",
                title="Old Professor Job",
                institution="Past University",
                field="Civil Engineering",
                location="Chicago, IL",
                deadline="2026-06-01",
                salary="$90,000",
                link="https://example.com/past",
                source="Chronicle",
                fit_score=8,
                latitude=41.8781,
                longitude=-87.6298,
                status="Past Due",
            ),
            # Unscored / low score posting (score 2) -> excluded from map
            JobPosting(
                id="low_score_1",
                title="Irrelevant Job",
                institution="Other University",
                field="Civil Engineering",
                location="Dallas, TX",
                deadline="2026-11-01",
                salary="$80,000",
                link="https://example.com/low",
                source="Chronicle",
                fit_score=2,
                latitude=32.7767,
                longitude=-96.7970,
                status="Active",
            ),
        ]

        mg = MapGenerator(test_map_path)
        mg.generate_map(postings)

        self.assertTrue(os.path.exists(test_map_path))
        with open(test_map_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Active university should be present
        self.assertIn("Active University", html_content)
        # Past due university should be excluded
        self.assertNotIn("Past University", html_content)
        # Low score university should be excluded
        self.assertNotIn("Other University", html_content)
        # Google Sheets link should be present
        self.assertIn("docs.google.com/spreadsheets", html_content)
        # 2-way filter elements should be present
        self.assertIn("score-filter-cb", html_content)
        self.assertIn("dl-filter-cb", html_content)

        if os.path.exists(test_map_path):
            os.remove(test_map_path)

    def test_scrapers_configuration(self):
        # Jobs.ac.uk scraper initialization
        uk_scraper = JobsAcUkScraper()
        self.assertEqual(uk_scraper.name, "JobsAcUk")
        self.assertIn("jobs.ac.uk", uk_scraper.SEARCH_URL)

        # LinkedIn multi-location target list
        li_scraper = LinkedInScraper()
        self.assertIn("United States", li_scraper.TARGET_LOCATIONS)
        self.assertIn("Canada", li_scraper.TARGET_LOCATIONS)
        self.assertIn("Europe", li_scraper.TARGET_LOCATIONS)
        self.assertIn("South Korea", li_scraper.TARGET_LOCATIONS)
        self.assertIn("Japan", li_scraper.TARGET_LOCATIONS)
        self.assertIn("Singapore", li_scraper.TARGET_LOCATIONS)
        self.assertIn("Hong Kong", li_scraper.TARGET_LOCATIONS)

    def test_seniority_and_adjunct_filters(self):
        # Senior-only roles must be rejected
        self.assertFalse(JobPosting.is_valid_faculty_posting("Professor & Department Chair"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Associate Professor of Civil Engineering"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Full Professor of Transportation Engineering"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Dean of the College of Engineering"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Endowed Chair in Civil Infrastructure"))

        # Adjunct and continuing education roles must be rejected
        self.assertFalse(JobPosting.is_valid_faculty_posting("Adjunct Faculty - Transportation Engineering"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Lecturer - Continuing Education"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Instructor of Adult Education"))

        # Valid Assistant Professor and Open Rank roles must be accepted
        self.assertTrue(JobPosting.is_valid_faculty_posting("Assistant Professor of Civil Engineering"))
        self.assertTrue(JobPosting.is_valid_faculty_posting("Assistant/Associate Professor of Civil Engineering"))
        self.assertTrue(JobPosting.is_valid_faculty_posting("Assistant/Associate/Full Professor, Transportation Engineering"))
        self.assertTrue(JobPosting.is_valid_faculty_posting("Open Rank Lecturer in Discipline or Senior Lecturer in Discipline"))
        self.assertTrue(JobPosting.is_valid_faculty_posting("Assistant Professor of Teaching of Urban Planning"))

    def test_canadian_locations(self):
        self.assertTrue(JobPosting.is_allowed_location("Toronto, Canada"))
        self.assertTrue(JobPosting.is_allowed_location("Vancouver, BC"))
        self.assertTrue(JobPosting.is_allowed_location("Montreal, Quebec"))
        self.assertTrue(JobPosting.is_allowed_location("Edmonton, Alberta"))
        self.assertTrue(JobPosting.is_allowed_location("Waterloo, Ontario"))

    def test_extract_latest_deadline_date_multiple_deadlines(self):
        ref = date(2026, 9, 19)

        # UCLA multiple deadlines: Priority: 2026-09-15 / Final: 2026-11-01 -> later date is 2026-11-01
        ucla_dl = "Priority: 2026-09-15 / Final: 2026-11-01"
        ucla_norm = JobPosting.extract_latest_deadline_date(ucla_dl, ref_date=ref)
        self.assertEqual(ucla_norm, "2026-11-01")

        # LSU New Orleans: Priority: 2026-09-30 / Review: 2026-10-01 -> later date is 2026-10-01
        lsu_dl = "Priority: 2026-09-30 / Review: 2026-10-01"
        lsu_norm = JobPosting.extract_latest_deadline_date(lsu_dl, ref_date=ref)
        self.assertEqual(lsu_norm, "2026-10-01")

        # Single ISO date
        self.assertEqual(JobPosting.extract_latest_deadline_date("2026-10-15", ref_date=ref), "2026-10-15")

        # Natural text date
        self.assertEqual(JobPosting.extract_latest_deadline_date("October 15, 2026", ref_date=ref), "2026-10-15")

        # UK style date
        self.assertEqual(JobPosting.extract_latest_deadline_date("15 October 2026", ref_date=ref), "2026-10-15")

        # Open until filled / rolling -> empty string
        self.assertEqual(JobPosting.extract_latest_deadline_date("Open until filled", ref_date=ref), "")
        self.assertEqual(JobPosting.extract_latest_deadline_date("Rolling", ref_date=ref), "")

        # Not specified -> empty string
        self.assertEqual(JobPosting.extract_latest_deadline_date("Not specified", ref_date=ref), "")
        self.assertEqual(JobPosting.extract_latest_deadline_date("", ref_date=ref), "")

    def test_job_posting_auto_deadline_date(self):
        ref = date(2026, 9, 19)
        ucla_job = JobPosting(
            id="ucla_job_1",
            title="Assistant Professor in Transportation",
            institution="University of California, Los Angeles",
            field="Civil Engineering",
            location="Los Angeles, CA",
            deadline="Priority: 2026-09-15 / Final: 2026-11-01",
            salary="Not specified",
            link="https://recruit.apo.ucla.edu/JPF09796",
            source="AcademicKeys",
        )
        # Should auto-populate deadline_date with the later deadline
        self.assertEqual(ucla_job.deadline_date, "2026-11-01")

    def test_four_tier_deadline_sorting(self):
        from scrapers.base import sort_postings_by_deadline
        ref = date(2026, 9, 19)

        # Tier 1a: urgent future (2026-09-22)
        p1 = JobPosting(
            id="p1", title="Urgent Job", institution="A University", field="CE",
            location="City, ST", deadline="2026-09-22", salary="", link="https://a.edu", source="Test", fit_score=8
        )
        # Tier 1b: distant future (2026-11-01) - UCLA example
        p2 = JobPosting(
            id="p2", title="Distant Job", institution="B University", field="CE",
            location="City, ST", deadline="Priority: 2026-09-15 / Final: 2026-11-01", salary="", link="https://b.edu", source="Test", fit_score=9
        )
        # Tier 2: Open until filled
        p3 = JobPosting(
            id="p3", title="Rolling Job", institution="C University", field="CE",
            location="City, ST", deadline="Open until filled", salary="", link="https://c.edu", source="Test", fit_score=7
        )
        # Tier 3: Not specified
        p4 = JobPosting(
            id="p4", title="Unspecified Job", institution="D University", field="CE",
            location="City, ST", deadline="Not specified", salary="", link="https://d.edu", source="Test", fit_score=6
        )
        # Tier 4: Past deadline (2026-08-01)
        p5 = JobPosting(
            id="p5", title="Expired Job", institution="E University", field="CE",
            location="City, ST", deadline="2026-08-01", salary="", link="https://e.edu", source="Test", fit_score=8
        )

        shuffled = [p4, p2, p5, p1, p3]
        sorted_postings = sort_postings_by_deadline(shuffled, ref_date=ref)

        expected_order = [p1, p2, p3, p4, p5]
        self.assertEqual([p.id for p in sorted_postings], [p.id for p in expected_order])

    def test_map_filter_position_upper_right(self):
        test_map_path = "test_map_ur.html"
        postings = [
            JobPosting(
                id="act_1",
                title="Active Professor",
                institution="Active University",
                field="Civil Engineering",
                location="Minneapolis, MN",
                deadline="2026-10-15",
                salary="$100,000",
                link="https://example.com/active",
                source="Chronicle",
                fit_score=9,
                latitude=44.9778,
                longitude=-93.2650,
                status="Active",
            )
        ]
        mg = MapGenerator(test_map_path)
        mg.generate_map(postings)

        with open(test_map_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Check filter panel is in upper-right: top: 25px; right: 25px;
        self.assertIn("top: 25px;", html_content)
        self.assertIn("right: 25px;", html_content)
        # Check LayerControl is positioned bottomleft
        self.assertIn("bottomleft", html_content)

        if os.path.exists(test_map_path):
            os.remove(test_map_path)

    def test_exporter_and_sheets_columns(self):
        from processor.exporter import JobExporter
        from processor.google_sheets import GoogleSheetsSync

        # JobExporter COLUMNS check
        col_keys = [k for k, _ in JobExporter.COLUMNS]
        self.assertIn("deadline", col_keys)
        self.assertIn("deadline_date", col_keys)
        dl_idx = col_keys.index("deadline")
        dl_date_idx = col_keys.index("deadline_date")
        self.assertEqual(dl_date_idx, dl_idx + 1)

        # GoogleSheetsSync COLUMNS check
        gs_cols = GoogleSheetsSync.COLUMNS
        self.assertIn("Deadline", gs_cols)
        self.assertIn("Deadline Date", gs_cols)
        gs_dl_idx = gs_cols.index("Deadline")
        gs_dl_date_idx = gs_cols.index("Deadline Date")
        self.assertEqual(gs_dl_date_idx, gs_dl_idx + 1)


if __name__ == "__main__":
    unittest.main()

