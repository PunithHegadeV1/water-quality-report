# P10 Water Quality Incident Reporter
Run:  pip install -r requirements.txt && python app.py   -> open http://localhost:5000
Tests: python -m unittest tests -v   (17 tests)
Sample inputs: station WSN123 / param P07 (Chemical), WSE200 / P25 (Biological), WSX123 (unknown zone -> fallback), P00 (correction queue), WSN12 (rejected)
