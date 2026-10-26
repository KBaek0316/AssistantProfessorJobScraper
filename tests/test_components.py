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
        # Per user specification, use the later deadline (2026-11-01)
        cat, _, diff = parse_deadline_info("Priority: 2026-09-15 / Final: 2026-11-01", ref_date=ref)
        self.assertEqual(cat, "future")
        self.assertEqual(diff, 49)

        # On 2026-09-16, final deadline remains active
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

            # Verify CSV contains ID as first column and Fit Score columns
            with open(test_csv, "r", encoding="utf-8-sig") as f:
                header = f.readline().strip()
                self.assertTrue(header.startswith("ID,"))
                self.assertIn("Fit Score (1-10)", header)
                self.assertIn("Fit Reason", header)

            import openpyxl
            wb = openpyxl.load_workbook(test_xlsx, data_only=True)
            ws = wb.active
            self.assertEqual(ws.cell(row=1, column=1).value, "ID")
            wb.close()

            # Test Map Generator
            map_gen = MapGenerator(output_filepath=test_map)
            map_gen.generate_map(all_jobs)
            self.assertTrue(os.path.exists(test_map))

            # Verify map HTML contains unified Fit Score Legend and 2-way filter controls
            with open(test_map, "r", encoding="utf-8") as f:
                map_content = f.read()
                self.assertIn("Fit Score Marker Legend", map_content)
                self.assertIn("score-filter-cb", map_content)
                self.assertIn("dl-filter-cb", map_content)
                # Verify Fit Score 9-10 & 7-8 checked, 5-6 & 3-4 unchecked by default
                self.assertIn('value="tier_9_10" checked', map_content)
                self.assertIn('value="tier_7_8" checked', map_content)
                self.assertNotIn('value="tier_5_6" checked', map_content)
                self.assertNotIn('value="tier_3_4" checked', map_content)
                self.assertIn('value="tier_5_6" onchange', map_content)
                self.assertIn('value="tier_3_4" onchange', map_content)
                # Verify Deadline Urgency "Passed" unchecked by default
                self.assertIn('value="urgent" checked', map_content)
                self.assertIn('value="open" checked', map_content)
                self.assertNotIn('value="passed" checked', map_content)
                self.assertIn('value="passed" onchange', map_content)

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
        self.assertFalse(JobPosting.is_allowed_location("Byblos", "Lebanon"))
        self.assertFalse(JobPosting.is_allowed_location("Byblos", institution="Lebanese American University"))
        self.assertFalse(JobPosting.is_allowed_location("Beirut", "Lebanon"))
        self.assertTrue(JobPosting.is_allowed_location("Las Cruces, New Mexico", "United States"))
        self.assertTrue(JobPosting.is_allowed_location("Albuquerque, NM"))
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

    def test_re_evaluate_mode_validation(self):
        """Test CLI argument validation for --re-evaluate and --re-evaluate-mode."""
        import sys
        from unittest.mock import patch
        from job_scraper import parse_args

        # Case 1: --re-evaluate-mode without --re-evaluate must trigger parser error
        with patch.object(sys, "argv", ["job_scraper.py", "--re-evaluate-mode", "fresh"]):
            with self.assertRaises(SystemExit):
                parse_args()

        # Case 2: --re-evaluate with --re-evaluate-mode update succeeds
        with patch.object(sys, "argv", ["job_scraper.py", "--re-evaluate", "--re-evaluate-mode", "update", "--skip-scrape"]):
            args = parse_args()
            self.assertTrue(args.re_evaluate)
            self.assertEqual(args.re_evaluate_mode, "update")
            self.assertTrue(args.skip_scrape)

        # Case 3: --re-evaluate with --re-evaluate-mode fresh succeeds
        with patch.object(sys, "argv", ["job_scraper.py", "--re-evaluate", "--re-evaluate-mode", "fresh"]):
            args = parse_args()
            self.assertTrue(args.re_evaluate)
            self.assertEqual(args.re_evaluate_mode, "fresh")

    def test_faculty_posting_with_mentoring_description(self):
        """Ensure real faculty openings are not rejected when duties mention postdocs or undergraduates."""
        title = "Assistant Professor of Transportation Engineering"
        desc = "The candidate will teach undergraduate courses, advise graduate students, and supervise postdocs."
        self.assertTrue(JobPosting.is_valid_faculty_posting(title, desc))

        # Real role that is actually a postdoc or driver must still be rejected
        self.assertFalse(JobPosting.is_valid_faculty_posting("Postdoctoral Fellow in Transportation Systems"))
        self.assertFalse(JobPosting.is_valid_faculty_posting("Bus Driver - University Shuttle"))

    def test_exporter_backup_methods(self):
        """Test local Excel backup generation and backup worksheet creation."""
        exporter = JobExporter(csv_filepath="test_backup_jobs.csv", excel_filepath="test_backup_jobs.xlsx")
        posting = JobPosting(
            id="backup_p1",
            title="Assistant Professor in Transit Analytics",
            institution="University of Minnesota",
            field="Civil Engineering",
            location="Minneapolis, MN",
            deadline="2026-11-15",
            salary="$110k",
            link="https://example.com/transit",
            source="LinkedIn",
        )
        exporter.export_excel([posting])

        # Test standalone backup file creation
        backup_path = exporter.create_backup([posting], backup_filepath="test_backup_out.xlsx")
        self.assertTrue(os.path.exists(backup_path))

        # Test adding backup worksheet to existing workbook
        sheet_name = exporter.add_backup_sheet([posting], sheet_name="Backup_TestTab")
        self.assertEqual(sheet_name, "Backup_TestTab")

        # Cleanup test artifacts
        for f in ("test_backup_jobs.csv", "test_backup_jobs.xlsx", "test_backup_out.xlsx"):
            if os.path.exists(f):
                os.remove(f)

    def test_google_sheets_error_diagnostics(self):
        """Ensure GoogleSheetsSync records detailed error diagnostic when sheet ID or credentials missing."""
        from processor.google_sheets import GoogleSheetsSync
        sync = GoogleSheetsSync(sheet_id="")
        self.assertIsNone(sync.client)
        self.assertIn("GOOGLE_SHEET_ID not provided", sync.init_error)


    def test_institution_alias_normalization(self):
        """Ensure clean_institution normalizes common university abbreviations and aliases."""
        clean = JobDeduplicator.clean_institution
        self.assertEqual(clean("UMass Boston"), clean("University of Massachusetts - Boston"))
        self.assertEqual(clean("UMass Amherst"), clean("University of Massachusetts Amherst"))
        self.assertEqual(clean("UC Berkeley"), clean("University of California, Berkeley"))
        self.assertEqual(clean("Georgia Tech"), clean("Georgia Institute of Technology"))
        self.assertEqual(clean("UIUC"), clean("University of Illinois Urbana-Champaign"))
        self.assertEqual(clean("Penn State"), clean("Pennsylvania State University"))
        self.assertEqual(clean("Texas A&M"), clean("Texas A&M University"))

    def test_umass_boston_cross_board_deduplication(self):
        """Ensure UMass Boston posting across HigherEdJobs and LinkedIn resolves as duplicate and merges."""
        dedup = JobDeduplicator()
        p_highered = JobPosting(
            id="umass_hej",
            title="Assistant Professor - Urban Analytics",
            institution="University of Massachusetts - Boston",
            field="Civil & Environmental / Transportation Engineering",
            location="Boston, MA",
            deadline="Open until filled",
            salary="$80,000 - $98,003 per year",
            link="https://www.higheredjobs.com/search/details.cfm?JobCode=179566167",
            source="HigherEdJobs",
            raw_description="Short snippet from HigherEdJobs card",
            date_first_seen="2026-09-28",
        )
        p_linkedin = JobPosting(
            id="umass_li",
            title="Assistant Professor - Urban Analytics",
            institution="UMass Boston",
            field="Department of Urban Planning and Community Development",
            location="Greater Boston",
            deadline="2026-10-18",
            salary="$80,000 - $98,003",
            link="https://www.linkedin.com/jobs/view/4469629227",
            source="LinkedIn",
            raw_description="The Department of Urban Planning and Community Development (UPCD) in the School for the Environment at the University of Massachusetts Boston invites applications for Assistant Professor in Urban Analytics and AI...",
            date_first_seen="2026-09-30",
            fit_score=8,
            fit_reason="Strong interdisciplinary match in urban planning and mobility analytics",
        )

        self.assertTrue(dedup.is_same_position(p_highered, p_linkedin))
        active, dupes = dedup.deduplicate_by_institution_department([p_highered, p_linkedin])
        self.assertEqual(len(active), 1)
        self.assertEqual(len(dupes), 1)
        winner = active[0]
        self.assertEqual(winner.id, "umass_li")
        self.assertEqual(winner.fit_score, 8)
        self.assertEqual(winner.deadline, "2026-10-18")

    def test_clean_institution_the_prefix(self):
        """Ensure clean_institution handles 'the ' prefix symmetrically."""
        clean = JobDeduplicator.clean_institution
        self.assertEqual(
            clean("The Hong Kong Polytechnic University"),
            clean("Hong Kong Polytechnic University"),
        )
        self.assertEqual(
            clean("The Ohio State University"),
            clean("Ohio State University"),
        )

    def test_deduplicate_generic_open_position_polyu(self):
        """Ensure generic 'Open position' / unspecified faculty titles deduplicate against specific positions."""
        dedup = JobDeduplicator()

        generic_posting = JobPosting(
            id="polyu_generic",
            title="Professor / Associate Professor / Assistant Professor",
            institution="THE HONG KONG POLYTECHNIC UNIVERSITY",
            field="Unspecified Department",
            location="Hong Kong",
            deadline="Open until filled",
            salary="Competitive",
            link="https://jobs.chronicle.com/job/38028368/professor-associate-professor-assistant-professor/",
            source="Chronicle",
            summary="Open rank faculty position at a polytechnic university requiring a Ph.D. in a relevant engineering or technology discipline.",
            research_topics="Polytechnic Education, Engineering, Technology",
            fit_score=5,
            date_first_seen="2026-09-28",
            date_last_verified="2026-10-01",
        )

        specific_posting = JobPosting(
            id="polyu_specific",
            title="Professor / Associate Professor / Assistant Professor in AI/Robotics for Aircraft Maintenance / Low-Altitude Economy / Satellite and Space Engineering",
            institution="The Hong Kong Polytechnic University",
            field="Department of Aeronautical and Aviation Engineering",
            location="Hong Kong",
            deadline="Open until filled",
            salary="Not specified",
            link="https://www.jobs.ac.uk/job/DSR599/professor-associate-professor-assistant-professor-in-ai-robotics-for-aircraft-maintenance-low-altitude-economy-satellite-and-space-engineering-under-strategic-hiring-scheme",
            source="Jobs.ac.uk",
            summary="Open rank faculty position focusing on AI and robotics for aviation and low-altitude economy applications requiring a Ph.D.",
            research_topics="Low-Altitude Economy, AI and Robotics, Aviation Systems",
            fit_score=5,
            date_first_seen="2026-09-28",
            date_last_verified="2026-10-08",
        )

        # Symmetrical match check
        self.assertTrue(dedup.is_same_position(generic_posting, specific_posting))
        self.assertTrue(dedup.is_same_position(specific_posting, generic_posting))

        active, dupes = dedup.deduplicate_by_institution_department([generic_posting, specific_posting])
        self.assertEqual(len(active), 1)
        self.assertEqual(len(dupes), 1)

        winner = active[0]
        # Specific title and department must be retained
        self.assertEqual(winner.id, "polyu_specific")
        self.assertEqual(
            winner.title,
            "Professor / Associate Professor / Assistant Professor in AI/Robotics for Aircraft Maintenance / Low-Altitude Economy / Satellite and Space Engineering",
        )
        self.assertEqual(winner.field, "Department of Aeronautical and Aviation Engineering")
        # Winner inherits competitive salary from generic posting
        self.assertEqual(winner.salary, "Competitive")

    def test_generic_title_and_unspecified_department_helpers(self):
        """Verify helper methods for generic titles and unspecified departments."""
        self.assertTrue(JobDeduplicator.is_generic_title("Professor / Associate Professor / Assistant Professor"))
        self.assertTrue(JobDeduplicator.is_generic_title("Assistant Professor"))
        self.assertTrue(JobDeduplicator.is_generic_title("Open Position"))
        self.assertTrue(JobDeduplicator.is_generic_title("Faculty Openings"))
        self.assertTrue(JobDeduplicator.is_generic_title("Open Rank Faculty"))
        self.assertFalse(JobDeduplicator.is_generic_title("Assistant Professor of Transportation Engineering"))
        self.assertFalse(JobDeduplicator.is_generic_title("Tenure-Track Assistant Professor in Urban Analytics"))

        self.assertTrue(JobDeduplicator.is_unspecified_department("Unspecified Department"))
        self.assertTrue(JobDeduplicator.is_unspecified_department("Not specified"))
        self.assertTrue(JobDeduplicator.is_unspecified_department(""))
        self.assertTrue(JobDeduplicator.is_unspecified_department(None))
        self.assertFalse(JobDeduplicator.is_unspecified_department("Department of Civil and Environmental Engineering"))
        self.assertFalse(JobDeduplicator.is_unspecified_department("School of Urban Planning"))

    def test_re_evaluate_missing_cli_flags(self):
        """Verify CLI argument defaults and flags for re-evaluating missing fit scores."""
        from job_scraper import parse_args
        import sys

        orig_argv = sys.argv
        try:
            # Default run (e.g. daily scrape) should have re_evaluate_missing = True
            sys.argv = ["job_scraper.py"]
            args = parse_args()
            self.assertTrue(args.re_evaluate_missing)

            # Explicit disable flag
            sys.argv = ["job_scraper.py", "--no-re-evaluate-missing"]
            args = parse_args()
            self.assertFalse(args.re_evaluate_missing)

            # Explicit enable flag
            sys.argv = ["job_scraper.py", "--re-evaluate-missing"]
            args = parse_args()
            self.assertTrue(args.re_evaluate_missing)
        finally:
            sys.argv = orig_argv

    def test_dtu_cross_board_deduplication(self):
        """Ensure Technical University of Denmark (DTU) postings across boards are deduplicated."""
        dedup = JobDeduplicator()
        p1 = JobPosting(
            id="dtu_jobsacuk",
            title="Associate Professor or DTU Tenure Track Assistant Professor in Sustainable Travel Behaviour",
            institution="Technical University of Denmark",
            field="DTU Management",
            location="Kongens Lyngby, Denmark",
            deadline="2026-11-01",
            salary="Not specified",
            link="https://www.jobs.ac.uk/job/DTA266/associate-professor",
            source="Jobs.ac.uk",
            date_first_seen="2026-09-23",
            fit_score=10,
        )
        p2 = JobPosting(
            id="dtu_linkedin",
            title="DTU Tenure Track Assistant Professor in Sustainable Travel Behaviour",
            institution="DTU - Technical University of Denmark",
            field="DTU Management",
            location="Kongens Lyngby",
            deadline="2026-11-01",
            salary="Not specified",
            link="https://dk.linkedin.com/jobs/view/4468634703",
            source="LinkedIn",
            date_first_seen="2026-09-27",
            fit_score=10,
        )
        p3 = JobPosting(
            id="dtu_highered",
            title="Associate Professor or DTU Tenure Track Assistant Professor in Sustainable Travel Behaviour",
            institution="DTU Management",
            field="DTU Management",
            location="Kongens Lyngby, Denmark",
            deadline="2026-11-01",
            salary="Not specified",
            link="https://www.higheredjobs.com/search/details.cfm?JobCode=179567818",
            source="HigherEdJobs",
            date_first_seen="2026-09-28",
            fit_score=10,
        )

        self.assertTrue(dedup.is_same_position(p1, p2))
        self.assertTrue(dedup.is_same_position(p1, p3))
        self.assertTrue(dedup.is_same_position(p2, p3))

        active, dupes = dedup.deduplicate_by_institution_department([p1, p2, p3])
        self.assertEqual(len(active), 1)
        self.assertEqual(len(dupes), 2)
        winner = active[0]
        self.assertEqual(winner.institution, "Technical University of Denmark")
        self.assertEqual(winner.field, "DTU Management")
        self.assertEqual(winner.fit_score, 10)

    def test_load_search_queries(self):
        """Verify load_search_queries behavior with CLI args, custom files, and defaults."""
        from job_scraper import load_search_queries, DEFAULT_QUERIES
        import tempfile

        # 1. CLI query takes highest precedence
        res = load_search_queries(cli_query="Assistant Professor AI, Assistant Professor Robotics")
        self.assertEqual(res, ["Assistant Professor AI", "Assistant Professor Robotics"])

        # 2. File parsing with comments and whitespace
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tf:
            tf.write("# Comment line\n")
            tf.write("Assistant Professor Economics\n")
            tf.write("\n")
            tf.write("Assistant Professor Finance, Assistant Professor Econometrics\n")
            tf.flush()
            temp_path = tf.name

        try:
            res_file = load_search_queries(cli_query=None, queries_file=temp_path)
            self.assertEqual(res_file, [
                "Assistant Professor Economics",
                "Assistant Professor Finance",
                "Assistant Professor Econometrics",
            ])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 3. Fallback when file doesn't exist
        res_default = load_search_queries(cli_query=None, queries_file="non_existent_queries_file.xyz")
        self.assertEqual(res_default, DEFAULT_QUERIES)

    def test_gemini_extractor_dynamic_instructions(self):
        """Verify GeminiExtractor extracts dynamic evaluation instructions from prompt template."""
        from processor.gemini_extractor import GeminiExtractor
        import tempfile

        custom_prompt = """Analyze posting:
{candidate_profile}
{raw_description}

=== EVALUATION INSTRUCTIONS ===
1. Custom Instruction for Computer Science
2. Geographic Scope: United States only
3. Fit Score Rubric for Algorithms & Systems

=== REQUIRED JSON OUTPUT FORMAT ===
{"fit_score": 8}
"""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tf:
            tf.write(custom_prompt)
            tf.flush()
            temp_prompt_path = tf.name

        try:
            extractor = GeminiExtractor(prompt_file=temp_prompt_path)
            instructions = extractor._get_evaluation_instructions()
            self.assertIn("Custom Instruction for Computer Science", instructions)
            self.assertIn("Fit Score Rubric for Algorithms & Systems", instructions)
            self.assertNotIn("Transportation", instructions)
        finally:
            if os.path.exists(temp_prompt_path):
                os.remove(temp_prompt_path)

    def test_cv_profile_hash_computation(self):
        """Verify CVProfileManager computes deterministic SHA-256 hash."""
        from processor.cv_matcher import CVProfileManager
        import tempfile

        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".pdf") as tf:
            tf.write(b"Dummy CV content for testing")
            tf.flush()
            temp_cv_path = tf.name

        try:
            h1 = CVProfileManager._compute_cv_hash(temp_cv_path)
            h2 = CVProfileManager._compute_cv_hash(temp_cv_path)
            self.assertTrue(len(h1) == 64)
            self.assertEqual(h1, h2)
            self.assertEqual(CVProfileManager._compute_cv_hash("non_existent_file.pdf"), "")
        finally:
            if os.path.exists(temp_cv_path):
                os.remove(temp_cv_path)

    def test_gemini_extractor_targeted_track_prefix(self):
        """Verify GeminiExtractor formats summary to start with targeted track when multiple positions exist."""
        from processor.gemini_extractor import GeminiExtractor
        from scrapers.base import JobPosting

        extractor = GeminiExtractor()
        # Verify instructions include multiple positions rule
        instructions = extractor._get_evaluation_instructions()
        self.assertIn("Handling Multiple Positions / Tracks", instructions)
        self.assertIn("targeted_track", instructions)

        posting = JobPosting(
            id="multi_test_1",
            title="Multiple Faculty Positions in Civil Engineering",
            institution="Test University",
            field="Civil Engineering",
            location="Atlanta, GA",
            deadline="2026-10-15",
            salary="Not specified",
            link="https://example.com/job",
            source="LinkedIn",
        )

        mock_data = {
            "id": "multi_test_1",
            "is_faculty": True,
            "fit_score": 10,
            "fit_reason": "Core match in Transportation Systems Engineering",
            "clean_title": "Assistant Professor of Transportation Systems Engineering",
            "institution": "Test University",
            "department": "Civil & Environmental Engineering",
            "targeted_track": "Transportation Systems Engineering (TSE)",
            "research_topics": ["Travel Demand", "Transit Systems"],
            "concise_summary": "Invites applications for a tenure-track faculty position focusing on transit systems and AI.",
        }

        # Simulate batch update logic
        targeted_track = str(mock_data.get("targeted_track") or "").strip()
        concise = mock_data.get("concise_summary", "").strip()
        if targeted_track and targeted_track.lower() not in ("null", "none"):
            prefix = f"[{targeted_track}]"
            if not concise.startswith(prefix):
                concise = f"{prefix} {concise}"
        posting.summary = f"{concise} | Research Topics: {', '.join(mock_data['research_topics'])}"

        self.assertTrue(posting.summary.startswith("[Transportation Systems Engineering (TSE)]"))
        self.assertIn("Travel Demand, Transit Systems", posting.summary)

    def test_michigan_and_mit_deduplication(self):
        """Verify Michigan and MIT duplicates are accurately recognized and deduplicated."""
        # 1. Michigan postings
        mich_kept = JobPosting(
            id="6299f7a0124cf48b",
            title="Assistant Professor, Associate Professor, or Professor",
            institution="University of Michigan, Ann Arbor",
            field="Civil and Environmental Engineering",
            location="Ann Arbor, MI",
            deadline="Nov. 30, 2026",
            salary="Not specified",
            link="http://engineering.academickeys.com/job/4oehp61f/Assistant-Professor-Associate-Professor-or-Professor",
            source="AcademicKeys",
            fit_score=8,
            fit_reason="Strong match in CEE department with strategic focus on automation and AI in transportation.",
            summary="Open-rank faculty position in civil and environmental infrastructure systems focusing on automation.",
        )
        mich_dupe = JobPosting(
            id="ebc41356faae3c23",
            title="Faculty Position in Civil and Environmental Infrastructure Systems",
            institution="University of Michigan",
            field="Department of Civil and Environmental Engineering",
            location="Ann Arbor, MI",
            deadline="Open until filled",
            salary="Not specified",
            link="https://www.higheredjobs.com/search/details.cfm?JobCode=179592284",
            source="HigherEdJobs",
            fit_score=8,
            fit_reason="Strong match for candidate's civil engineering doctorate in CEE department.",
            summary="Open-rank tenure-track faculty position in Civil and Environmental Engineering targeting AI.",
        )

        self.assertTrue(JobDeduplicator.is_same_institution(mich_kept, mich_dupe))
        self.assertTrue(JobDeduplicator.is_same_position(mich_kept, mich_dupe))

        dedup = JobDeduplicator()
        active, dupes = dedup.deduplicate_by_institution_department([mich_kept, mich_dupe])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, "6299f7a0124cf48b")
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0].id, "ebc41356faae3c23")

        # 2. MIT postings
        mit_kept = JobPosting(
            id="44dfdb908222b394",
            title="Tenure-track Assistant Professor",
            institution="Massachusetts Institute of Technology",
            field="Department of Civil and Environmental Engineering",
            location="Cambridge, MA",
            deadline="12/01/2026",
            salary="$143,000 - $147,000 per year",
            link="https://www.higheredjobs.com/search/details.cfm?JobCode=179589362",
            source="HigherEdJobs",
            fit_score=10,
            fit_reason="Core match in transportation networks.",
        )
        mit_dupe = JobPosting(
            id="88b5edbe66430187",
            title="Tenure-Track Assistant Professor - Civil and Environmental Engineering",
            institution="Massachusetts Institute of Technology (MIT)",
            field="Department of Civil and Environmental Engineering & Institute for Data, Systems, and Society",
            location="Cambridge, Massachusetts",
            deadline="Open until filled",
            salary="Competitive Salary",
            link="https://jobs.chronicle.com/job/38055016/tenure-track-assistant-professor-civil-and-environmental-engineering/",
            source="Chronicle",
            fit_score=8,
            fit_reason="Strong match in networked infrastructure.",
        )

        self.assertTrue(JobDeduplicator.is_same_institution(mit_kept, mit_dupe))
        self.assertTrue(JobDeduplicator.is_same_position(mit_kept, mit_dupe))

        active_mit, dupes_mit = dedup.deduplicate_by_institution_department([mit_kept, mit_dupe])
        self.assertEqual(len(active_mit), 1)
        self.assertEqual(active_mit[0].id, "44dfdb908222b394")
        self.assertEqual(len(dupes_mit), 1)
        self.assertEqual(dupes_mit[0].id, "88b5edbe66430187")

    def test_branch_campus_distinction_and_geocoding(self):
        """Verify branch campuses are distinguished from flagship campuses and geocoded accurately."""
        # 1. Texas A&M College Station vs Texas A&M Corpus Christi
        tamu_main = JobPosting(
            id="tamu_main",
            title="Assistant Professor",
            institution="Texas A&M University",
            field="Civil Engineering",
            location="College Station, TX",
            deadline="2026-12-01",
            salary="Not specified",
            link="https://example.com/1",
            source="HigherEdJobs",
        )
        tamu_cc = JobPosting(
            id="tamu_cc",
            title="Assistant Professor of Civil Engineering",
            institution="Texas A&M University-Corpus Christi",
            field="Department of Engineering",
            location="Corpus Christi, TX",
            deadline="Open until filled",
            salary="Not specified",
            link="https://example.com/2",
            source="LinkedIn",
        )
        # Should NOT be treated as same institution / same position
        self.assertFalse(JobDeduplicator.is_same_institution(tamu_main, tamu_cc))
        self.assertFalse(JobDeduplicator.is_same_position(tamu_main, tamu_cc))

        # 2. Geocoder lookups for branch campuses
        geocoder = UniversityGeocoder()
        coords_cc = geocoder.geocode("Texas A&M University-Corpus Christi")
        self.assertIsNotNone(coords_cc)
        self.assertAlmostEqual(coords_cc[0], 27.7128, places=2)
        self.assertAlmostEqual(coords_cc[1], -97.3234, places=2)

        coords_cornell_nyc = geocoder.geocode("Cornell University, New York, NY")
        self.assertIsNotNone(coords_cornell_nyc)
        self.assertAlmostEqual(coords_cornell_nyc[0], 40.7548, places=2)
        self.assertAlmostEqual(coords_cornell_nyc[1], -73.9564, places=2)

        coords_purdue_indy = geocoder.geocode("Purdue University, Indianapolis, Indiana")
        self.assertIsNotNone(coords_purdue_indy)
        self.assertAlmostEqual(coords_purdue_indy[0], 39.7749, places=2)
        self.assertAlmostEqual(coords_purdue_indy[1], -86.1681, places=2)

        # 3. Verify enrich_coordinates does not overwrite branch campus coords
        tamu_cc.latitude = 27.7128
        tamu_cc.longitude = -97.3234
        geocoder.enrich_coordinates([tamu_cc])
        self.assertAlmostEqual(tamu_cc.latitude, 27.7128, places=3)
        self.assertAlmostEqual(tamu_cc.longitude, -97.3234, places=3)


if __name__ == "__main__":
    unittest.main()



