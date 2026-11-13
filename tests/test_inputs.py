"""Reading the jobs list (.txt, .csv, .json). No network.

    python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signalcheck.inputs import InputError, job_id, load_jobs  # noqa: E402

A = "https://job-boards.greenhouse.io/acme/jobs/4000000001"
B = "https://jobs.lever.co/umbrella/7314a1a4-0000-4000-8000-000000000002"


class Inputs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def file(self, name, text):
        p = Path(self.dir.name) / name
        p.write_text(text)
        return p

    def test_txt_one_url_per_line(self):
        jobs, _ = load_jobs(self.file("jobs.txt", f"# my list\n{A}\n\n  {B}  \n{A}\n"))
        self.assertEqual([j["url"] for j in jobs], [A, B])  # comment, blank and duplicate skipped
        self.assertEqual(jobs[0], {"id": job_id(A), "company": "", "title": "", "url": A})

    def test_ids_are_stable(self):
        self.assertEqual(job_id(A), job_id(A))
        self.assertNotEqual(job_id(A), job_id(B))

    def test_csv_with_any_column_order_and_case(self):
        text = f"Title,Company,Notes,URL\nStaff Designer,Acme,applied?,{A}\n,,,\nDesign Lead,Umbrella,,{B}\n"
        jobs, _ = load_jobs(self.file("jobs.csv", text))
        self.assertEqual([(j["company"], j["title"]) for j in jobs], [("Acme", "Staff Designer"), ("Umbrella", "Design Lead")])

    def test_csv_link_column_and_excel_bom(self):
        jobs, _ = load_jobs(self.file("jobs.csv", f"﻿company,link\nAcme,{A}\n"))
        self.assertEqual(jobs[0]["url"], A)

    def test_csv_without_url_column(self):
        with self.assertRaisesRegex(InputError, "'url' column"):
            load_jobs(self.file("jobs.csv", f"company,page\nAcme,{A}\n"))

    def test_json_list_and_jobs_object(self):
        rows = [{"url": A, "company": "Acme", "title": "Staff Designer", "id": "acme-1"}, {"url": B}]
        for doc in (rows, {"jobs": rows}):
            jobs, _ = load_jobs(self.file("jobs.json", json.dumps(doc)))
            self.assertEqual(jobs[0]["id"], "acme-1")
            self.assertEqual(jobs[1]["id"], job_id(B))

    def test_plain_errors(self):
        cases = [
            ("jobs.txt", "", "no job URLs"),
            ("jobs.txt", "careers.example.com/jobs/1\n", "not a web address"),
            ("jobs.json", "{not json", "not valid JSON"),
            ("jobs.json", '{"rows": []}', "must be a list"),
            ("jobs.xlsx", A, "use a .txt, .csv or .json"),
            ("jobs.json", json.dumps([{"url": A, "id": "x"}, {"url": B, "id": "x"}]), "used twice"),
        ]
        for name, text, msg in cases:
            with self.subTest(name=name, msg=msg):
                with self.assertRaisesRegex(InputError, msg):
                    load_jobs(self.file(name, text))

    def test_missing_file(self):
        with self.assertRaisesRegex(InputError, "file not found"):
            load_jobs(Path(self.dir.name) / "nope.txt")


if __name__ == "__main__":
    unittest.main()
