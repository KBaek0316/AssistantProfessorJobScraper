import os
import unittest
from datetime import date
from scrapers.base import JobPosting
from processor.deduplicator import JobDeduplicator
from processor.geocoder import UniversityGeocoder
from processor.exporter import JobExporter
from processor.map_generator import MapGenerator, get_fit_marker_color, parse_deadline_info
from processor.cv_matcher import CVProfileManager


class TestComponents(unittest.TestCase):

    def setUp(self):
        self.sample_posting = JobPosting(
            id=JobPosting.generate_id("test", "job123"),
            title="Assistant Professor in Transportation Systems",
            institution="Purdue University",
            field="Civil Engineering",
            location="West Lafayette, IN",
            deadline="2026-12-01",
            salary="$95,000 - $110,000",
            link="https://example.com/job/123",
            source="TestSite",
            raw_description="Looking for an Assistant Professor in sustainable transportation systems.",
            summary="Focuses on sustainable transportation infrastructure and next-generation mobility.",
            fit_score=9,
            fit_reason="Core match in transit systems and transportation infrastructure",
            tenure_track="Tenure-Track",
        )

    def test_job_id_generation(self):
        id1 = JobPosting.generate_id("higheredjobs", "12345")
        id2 = JobPosting.generate_id("higheredjobs", "12345")
        id3 = JobPosting.generate_id("higheredjobs", "54321")
        self.assertEqual(id1, id2)
        self.assertNotEqual(id1, id3)

    def test_cv_matcher_profile(self):
        manager = CVProfileManager()
        profile = manager.profile
        self.assertIn("candidate_name", profile)
        self.assertIn("primary_field", profile)
        self.assertIn("research_specialties", profile)
        prompt_ctx = manager.get_prompt_context()
        self.assertIn("Transportation", prompt_ctx)

    def test_geocoder(self):
        geocoder = UniversityGeocoder()
        coords = geocoder.geocode("Purdue University")
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords[0], 40.4237, places=2)
        self.assertAlmostEqual(coords[1], -86.9212, places=2)

    def test_map_marker_colors_and_deadline_parser(self):
        # Color mapping tests
        self.assertEqual(get_fit_marker_color(10), "darkgreen")
        self.assertEqual(get_fit_marker_color(9), "darkgreen")
        self.assertEqual(get_fit_marker_color(8), "green")
        self.assertEqual(get_fit_marker_color(7), "green")
        self.assertEqual(get_fit_marker_color(6), "orange")
        self.assertEqual(get_fit_marker_color(5), "orange")
        self.assertEqual(get_fit_marker_color(4), "lightred")
        self.assertEqual(get_fit_marker_color(3), "lightred")
        self.assertEqual(get_fit_marker_color(2), "gray")
        self.assertEqual(get_fit_marker_color(1), "gray")
        self.assertEqual(get_fit_marker_color(None), "blue")

        # Deadline categorization tests against a reference date
        ref = date(2026, 9, 13)
        cat, _, diff = parse_deadline_info("2026-11-01", ref_date=ref)
        self.assertEqual(cat, "future")
        self.assertEqual(diff, 49)

        cat, _, diff = parse_deadline_info("2026-08-31", ref_date=ref)
        self.assertEqual(cat, "passed")
        self.assertEqual(diff, -13)

        cat, _, diff = parse_deadline_info("2026-09-18", ref_date=ref)
        self.assertEqual(cat, "urgent")
        self.assertEqual(diff, 5)

        cat, _, diff = parse_deadline_info("2026-10-01", ref_date=ref)
        self.assertEqual(cat, "closing_soon")
        self.assertEqual(diff, 18)

        cat, _, _ = parse_deadline_info("Open until filled", ref_date=ref)
        self.assertEqual(cat, "open")

        cat, _, _ = parse_deadline_info("Not specified", ref_date=ref)
        self.assertEqual(cat, "open")

        # Test yearless format (e.g. Loyola Marymount: "September 30")
        cat, _, diff = parse_deadline_info("September 30", ref_date=ref)
        self.assertEqual(cat, "closing_soon")
        self.assertEqual(diff, 17)

        cat, _, diff = parse_deadline_info("Nov 1", ref_date=ref)
        self.assertEqual(cat, "future")
        self.assertEqual(diff, 49)

        # Test dual deadlines (e.g. UCLA: Priority Sep 15 / Final Nov 1)
        cat, _, diff = parse_deadline_info("Priority: 2026-09-15 / Final: 2026-11-01", ref_date=ref)
        self.assertEqual(cat, "urgent")
        self.assertEqual(diff, 2)

        # Once priority passes, verify it transitions to final deadline instead of 'passed'
        cat2, _, diff2 = parse_deadline_info("Priority: 2026-09-15 / Final: 2026-11-01", ref_date=date(2026, 9, 16))
        self.assertEqual(cat2, "future")
        self.assertEqual(diff2, 46)

    def test_exporter_and_deduplicator(self):
        test_csv = "test_jobs.csv"
        test_xlsx = "test_jobs.xlsx"
        test_map = "test_map.html"

        try:
            # Test Deduplication
            dedup = JobDeduplicator(csv_filepath=test_csv)
            new_jobs, all_jobs = dedup.process_incoming([self.sample_posting])
            self.assertEqual(len(new_jobs), 1)
            self.assertEqual(len(all_jobs), 1)
            self.assertEqual(all_jobs[0].fit_score, 9)
            self.assertEqual(all_jobs[0].fit_reason, "Core match in transit systems and transportation infrastructure")

            # Enrich coordinates
            geocoder = UniversityGeocoder()
            geocoder.enrich_coordinates(all_jobs)
            self.assertIsNotNone(all_jobs[0].latitude)

            # Test Exporter with Fit Score & Fit Reason
            exporter = JobExporter(csv_filepath=test_csv, excel_filepath=test_xlsx)
            exporter.export_csv(all_jobs)
            exporter.export_excel(all_jobs)

            self.assertTrue(os.path.exists(test_csv))
            self.assertTrue(os.path.exists(test_xlsx))

            # Verify CSV contains Fit Score column
            with open(test_csv, "r", encoding="utf-8-sig") as f:
                header = f.readline()
                self.assertIn("Fit Score (1-10)", header)
                self.assertIn("Fit Reason", header)

            # Test Map Generator
            map_gen = MapGenerator(output_filepath=test_map)
            map_gen.generate_map(all_jobs)
            self.assertTrue(os.path.exists(test_map))

            # Verify map HTML contains legend and deadline feature group controls (without marker clustering)
            with open(test_map, "r", encoding="utf-8") as f:
                map_content = f.read()
                self.assertIn("Fit Score Marker Legend", map_content)
                self.assertIn("feature_group", map_content)

            # Run deduplicator a second time with the same posting -> should have 0 new jobs
            dedup2 = JobDeduplicator(csv_filepath=test_csv)
            new_jobs2, all_jobs2 = dedup2.process_incoming([self.sample_posting])
            self.assertEqual(len(new_jobs2), 0)
            self.assertEqual(len(all_jobs2), 1)

        finally:
            import gc, time
            gc.collect()
            for f in (test_csv, test_xlsx, test_map):
                if os.path.exists(f):
                    for _ in range(5):
                        try:
                            os.remove(f)
                            break
                        except PermissionError:
                            time.sleep(0.1)

    def test_location_filtering(self):
        # Allowed target locations: US & Canada
        self.assertTrue(JobPosting.is_allowed_location("Austin, TX", "United States"))
        self.assertTrue(JobPosting.is_allowed_location("Toronto, ON", "Canada"))
        self.assertTrue(JobPosting.is_allowed_location("Vancouver", "Canada"))
        self.assertTrue(JobPosting.is_allowed_location("Montreal, QC"))
        self.assertTrue(JobPosting.is_allowed_location("Waterloo, Ontario"))

        # Allowed: Europe
        self.assertTrue(JobPosting.is_allowed_location("London", "United Kingdom"))
        self.assertTrue(JobPosting.is_allowed_location("Munich", "Germany"))
        self.assertTrue(JobPosting.is_allowed_location("Delft", "Netherlands"))
        self.assertTrue(JobPosting.is_allowed_location("Zurich", "Switzerland"))

        # Allowed: Asia
        self.assertTrue(JobPosting.is_allowed_location("Singapore", "Singapore"))
        self.assertTrue(JobPosting.is_allowed_location("Taipei", "Taiwan"))
        self.assertTrue(JobPosting.is_allowed_location("Hong Kong", "Hong Kong"))
        self.assertTrue(JobPosting.is_allowed_location("Hong Kong, China"))  # Must preserve HK!
        self.assertTrue(JobPosting.is_allowed_location("Tokyo", "Japan"))
        self.assertTrue(JobPosting.is_allowed_location("Seoul", "South Korea"))

        # Excluded locations: Mainland China
        self.assertFalse(JobPosting.is_allowed_location("Beijing", "China"))
        self.assertFalse(JobPosting.is_allowed_location("Shanghai", "PRC"))
        self.assertFalse(JobPosting.is_allowed_location("Shenzhen", "Mainland China"))
        self.assertFalse(JobPosting.is_allowed_location("Hangzhou, China"))

        # Excluded other non-target regions
        self.assertFalse(JobPosting.is_allowed_location("Dubai", "UAE"))
        self.assertFalse(JobPosting.is_allowed_location("Riyadh", "Saudi Arabia"))
        self.assertFalse(JobPosting.is_allowed_location("Mumbai", "India"))
        self.assertFalse(JobPosting.is_allowed_location("São Paulo", "Brazil"))

    def test_institution_department_deduplication(self):
        dedup = JobDeduplicator()
        job_older = JobPosting(
            id="job_old",
            title="Assistant Professor / Associate Professor in Maritime Studies",
            institution="Nanyang Technological University",
            field="School of Civil and Environmental Engineering",
            location="Singapore",
            deadline="Open until filled",
            salary="Not specified",
            link="https://example.com/job/old",
            source="AcademicKeys",
            date_first_seen="2026-09-12",
            date_last_verified="2026-09-13",
            fit_score=5,
        )
        job_newer = JobPosting(
            id="job_new",
            title="Assistant Professor / Associate Professor (Tenure-Track) in Civil and Environmental Engineering",
            institution="Nanyang Technological University",
            field="Department of Civil and Environmental Engineering",
            location="Singapore",
            deadline="Open until filled",
            salary="Not specified",
            link="https://example.com/job/new",
            source="AcademicKeys",
            date_first_seen="2026-09-13",
            date_last_verified="2026-09-13",
            fit_score=7,
        )
        job_unrelated = JobPosting(
            id="job_unrelated",
            title="Assistant Professor of Transportation",
            institution="Purdue University",
            field="Civil Engineering",
            location="West Lafayette, IN",
            deadline="2026-12-01",
            salary="$100k",
            link="https://example.com/job/purdue",
            source="AcademicKeys",
            date_first_seen="2026-09-11",
            date_last_verified="2026-09-13",
            fit_score=9,
        )

        active, dupes = dedup.deduplicate_by_institution_department([job_older, job_newer, job_unrelated])
        self.assertEqual(len(active), 2)
        self.assertEqual(len(dupes), 1)
        active_ids = [j.id for j in active]
        self.assertIn("job_new", active_ids)
        self.assertIn("job_unrelated", active_ids)
        self.assertNotIn("job_old", active_ids)
        self.assertEqual(dupes[0].id, "job_old")

        # Test Wisconsin-Madison cross-board duplicate resolution
        wisc_1 = JobPosting(
            id="wisc_chronicle",
            title="Assistant Professor of Public Policy (Market-Based Solutions to Societal Challenges)",
            institution="University of Wisconsin-Madison",
            field="Department of Public Policy / La Follette School of Public Affairs",
            location="Madison, WI",
            deadline="Open until filled",
            salary="Competitive",
            link="https://jobs.chronicle.com/wisc",
            source="Chronicle",
            date_first_seen="2026-09-12",
        )
        wisc_2 = JobPosting(
            id="wisc_linkedin",
            title="Assistant Professor of Public Policy (Market-Based Solutions to Societal Challenges)",
            institution="University of Wisconsin-Madison",
            field="La Follette School of Public Affairs, College of Letters & Science",
            location="Madison, WI",
            deadline="Open until filled",
            salary="Competitive",
            link="https://www.linkedin.com/wisc",
            source="LinkedIn",
            date_first_seen="2026-09-13",
        )
        wisc_active, wisc_dupes = dedup.deduplicate_by_institution_department([wisc_1, wisc_2])
        self.assertEqual(len(wisc_active), 1)
        self.assertEqual(wisc_active[0].id, "wisc_linkedin")

        # Test UIC cross-board variations
        uic_1 = JobPosting(
            id="uic_chronicle",
            title="Assistant Professor of Operations Management",
            institution="University of Illinois - Chicago",
            field="Information and Decision Sciences (IDS) Department",
            location="Chicago, IL",
            deadline="Open until filled",
            salary="Competitive",
            link="https://jobs.chronicle.com/uic",
            source="Chronicle",
            date_first_seen="2026-09-13",
        )
        uic_2 = JobPosting(
            id="uic_highered",
            title="Assistant Professor of Information and Decision Sciences (Supply Chain & Operations Management)",
            institution="University of Illinois Chicago",
            field="Information and Decision Sciences (IDS)",
            location="Chicago, IL",
            deadline="Open until filled",
            salary="Competitive",
            link="https://www.higheredjobs.com/uic",
            source="HigherEdJobs",
            date_first_seen="2026-09-12",
        )
        uic_active, uic_dupes = dedup.deduplicate_by_institution_department([uic_1, uic_2])
        self.assertEqual(len(uic_active), 1)
        self.assertEqual(uic_active[0].id, "uic_chronicle")


if __name__ == "__main__":
    unittest.main()
