import os
import unittest
from scrapers.base import JobPosting
from processor.deduplicator import JobDeduplicator
from processor.geocoder import UniversityGeocoder
from processor.exporter import JobExporter
from processor.map_generator import MapGenerator
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
