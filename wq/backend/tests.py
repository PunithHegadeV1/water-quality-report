import os, tempfile, unittest, sqlite3
from concurrent.futures import ThreadPoolExecutor
import app as A


def mk(station="WSN123", param="P07", desc="Noted by field team", urg="Normal"):
    return {"reporter_name": "Asha", "contact": "9999999999", "station_code": station, "param_code": param, "description": desc, "urgency": urg}


class T(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.f.close()
        A.DB = self.f.name; A.init_db(); self.c = A.app.test_client()

    def tearDown(self): os.unlink(self.f.name)

    def post(self, **k):
        r = self.c.post("/api/reports", json=mk(**k)); return r.status_code, r.get_json()

    def hid(self, name): return next(h["id"] for h in self.c.get("/api/handlers").get_json() if h["name"] == name)

    def test01_valid_formats(self):
        for s, p in [("WSN123", "P07"), ("WSE001", "P99"), ("WSW999", "P00"), ("WSX555", "P50")]:
            v = A.check_ids(s, p); self.assertEqual(v["errors"], [], (s, p))

    def test02_invalid_formats(self):
        for s in ["", "WSN12", "WSN1234", "wsn123", "XSN123", "WS1123", "WSN12A", "WSN123\n", " WSN123"]:
            self.assertFalse(A.check_ids(s, "P07")["station"]["dfa"], s)
        for p in ["", "P7", "P007", "p07", "Q07", "P0A", "P07\n"]:
            self.assertFalse(A.check_ids("WSN123", p)["param"]["dfa"], p)

    def test03_dfa_regex_agree(self):
        import itertools
        pool = ["W", "S", "N", "X", "1", "a", "-", "P", "0", "9", "\n"]
        for n in range(0, 5):
            for t in itertools.product(pool, repeat=n):
                s = "".join(t); self.assertEqual(A.dfa(s, A.STATION_SPEC)[0], bool(A.STATION_RE.fullmatch(s)), repr(s)); self.assertEqual(A.dfa(s, A.PARAM_SPEC)[0], bool(A.PARAM_RE.fullmatch(s)), repr(s))
        for s in ["WSN123", "WSN12", "WSNN123", "WSN1234", "WSX999"]:
            self.assertEqual(A.dfa(s, A.STATION_SPEC)[0], bool(A.STATION_RE.fullmatch(s)))

    def _cat(self, p, exp):
        code, r = self.post(param=p); self.assertEqual(code, 201); self.assertEqual(r["category"], exp)

    def test04_chemical(self): self._cat("P05", "Chemical")
    def test05_biological(self): self._cat("P25", "Biological")
    def test06_physical(self): self._cat("P45", "Physical")
    def test07_pressure(self): self._cat("P65", "Pressure")
    def test08_supply(self): self._cat("P85", "Supply")

    def test09_conflict_priority_rule(self):
        code, r = self.post(param="P45", desc="strong chlorine smell and muddy water")
        self.assertEqual(r["category"], "Chemical"); self.assertIn("Conflict", r["validation_msg"])
        self.assertEqual(self.post(param="P85", desc="sewage with low pressure")[1]["category"], "Biological")

    def test10_unknown_zone_fallback(self):
        code, r = self.post(station="WSX123"); self.assertEqual(code, 201)
        self.assertEqual(r["status"], "Pending"); self.assertIn("CENTRAL_FALLBACK", r["decision"])
        self.assertEqual(self.c.get("/api/routing").get_json()["queue"][0]["kind"], "FALLBACK")
        r2 = self.c.post(f"/api/queue/{r['id']}/route", json={"zone": "S"}).get_json()
        self.assertEqual(r2["status"], "Assigned")

    def test11_invalid_and_unmapped_codes(self):
        code, r = self.post(station="WSN12"); self.assertEqual(code, 422); self.assertEqual(r["status"], "Rejected")
        self.assertIn("Station code", r["errors"][0])
        code, r = self.post(param="P00", desc="chlorine"); self.assertEqual(r["category"], "Unclassified"); self.assertEqual(r["status"], "Pending")
        self.assertIn("correction", r["decision"])
        self.assertEqual(self.c.get("/api/stats").get_json()["rejected"], 1)

    def test12_unavailable_handler_uses_backup(self):
        self.c.put(f"/api/handlers/{self.hid('Team-N')}", json={"available": False})
        code, r = self.post(param="P50"); self.assertEqual(r["handler_name"], "Team-N-B"); self.assertIn("Backup", r["decision"])

    def test13_capacity_overflow_waiting_queue_and_drain(self):
        self.c.put(f"/api/handlers/{self.hid('Central Control')}", json={"available": False})
        res = [self.post(param="P50")[1] for _ in range(6)]
        self.assertEqual([x["status"] for x in res], ["Assigned"] * 5 + ["Pending"])
        self.assertEqual(self.c.get("/api/routing").get_json()["queue"][0]["kind"], "WAITING")
        first = res[0]["id"]
        for s in ("In Progress", "Resolved"): self.c.put(f"/api/reports/{first}/status", json={"status": s})
        self.assertEqual(self.c.get(f"/api/reports/{res[5]['report_code']}").get_json()["status"], "Assigned")

    def test14_escalation_to_central(self):
        for n in ("Team-N", "Team-N-B"): self.c.put(f"/api/handlers/{self.hid(n)}", json={"available": False})
        r = self.post(param="P50")[1]; self.assertEqual(r["handler_name"], "Central Control"); self.assertIn("ESCALATED", r["decision"])

    def test15_emergency_override_and_queue_order(self):
        for n in ("Central Control", "Team-N", "Team-N-B"): self.c.put(f"/api/handlers/{self.hid(n)}", json={"available": False})
        low = self.post(param="P50", urg="Low")[1]; normal = self.post(param="P50")[1]
        emer = self.post(param="P50", urg="Emergency")[1]
        self.assertEqual(emer["priority_label"], "Critical")
        self.assertEqual([q["report_id"] for q in self.c.get("/api/routing").get_json()["queue"]], [emer["id"], normal["id"], low["id"]])
        self.c.put(f"/api/handlers/{self.hid('Team-N')}", json={"available": True, "capacity": 1})
        self.assertEqual(self.c.get(f"/api/reports/{emer['report_code']}").get_json()["status"], "Assigned")
        self.assertEqual(self.c.get(f"/api/reports/{normal['report_code']}").get_json()["status"], "Pending")
        self.assertTrue(self.c.get("/api/routing").get_json()["overrides"])

    def test16_simultaneous_reports_no_duplicates(self):
        def go(i): return A.app.test_client().post("/api/reports", json=mk(param=["P05", "P25", "P50", "P70", "P90"][i % 5], station="WS" + "NSEW"[i % 4] + "100")).status_code
        with ThreadPoolExecutor(8) as ex: codes = list(ex.map(go, range(20)))
        self.assertEqual(set(codes), {201})
        c = sqlite3.connect(A.DB)
        self.assertEqual(c.execute("SELECT COUNT(*), COUNT(DISTINCT report_id) FROM assignments").fetchone()[0], c.execute("SELECT COUNT(DISTINCT report_id) FROM assignments").fetchone()[0])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM reports WHERE status='Assigned'").fetchone()[0], c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0])
        self.assertEqual(c.execute("SELECT SUM(load) FROM handlers").fetchone()[0], c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0])
        self.assertEqual(c.execute("SELECT COUNT(DISTINCT report_code) FROM reports").fetchone()[0], 20)

    def test17_status_workflow_and_persistence(self):
        r = self.post(param="P05")[1]; self.assertEqual(r["handler_name"], "ZQO-N"); self.assertEqual(r["priority_label"], "Critical")
        bad = self.c.put(f"/api/reports/{r['id']}/status", json={"status": "Resolved"}); self.assertEqual(bad.status_code, 400)
        for s in ("In Progress", "Resolved"): self.assertEqual(self.c.put(f"/api/reports/{r['id']}/status", json={"status": s}).status_code, 200)
        c = sqlite3.connect(A.DB)  # fresh connection = persisted
        self.assertEqual(c.execute("SELECT status FROM reports WHERE id=?", (r["id"],)).fetchone()[0], "Resolved")
        self.assertEqual(c.execute("SELECT load FROM handlers WHERE name='ZQO-N'").fetchone()[0], 0)
        self.assertEqual(self.c.get("/api/analytics").get_json()["resolved"], 1)
        self.assertEqual(self.c.get("/api/reports/WQ-nope").status_code, 404)

if __name__ == "__main__": unittest.main()
