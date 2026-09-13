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

            # Verify map HTML contains legend and deadline subgroup controls
            with open(test_map, "r", encoding="utf-8") as f:
                map_content = f.read()
                self.assertIn("Fit Score Marker Legend", map_content)
                self.assertIn("feature_group_sub_group", map_content)

            # Run deduplicator a second time with the same posting -> should have 0 new jobs
            dedup2 = JobDeduplicator(csv_filepath=test_csv)
            new_jobs2, all_jobs2 = dedup2.process_incoming([self.sample_posting])
            self.assertEqual(len(new_jobs2), 0)
            self.assertEqual(len(all_jobs2), 1)

        finally:
            for f in (test_csv, test_xlsx, test_map):
                if os.path.exists(f):
                    os.remove(f)


if __name__ == "__main__":
    unittest.main()
