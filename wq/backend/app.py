import os, re, sqlite3, datetime as dt
from contextlib import contextmanager
from flask import Flask, jsonify, request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("WQ_DB", os.path.join(BASE, "..", "database", "wq.db"))
app = Flask(__name__, static_folder=os.path.join(BASE, "..", "frontend", "static"), static_url_path="/static")

ZONES = ["N", "S", "E", "W"]
URG = ["Low", "Normal", "High", "Emergency"]
PLABEL = {1: "Critical", 2: "High", 3: "Normal", 4: "Low"}
# Documented priority rule: if several patterns match, the earliest in this list wins.
CAT_ORDER = ["Chemical", "Biological", "Physical", "Pressure", "Supply"]
RANGES = [(1, 20, "Chemical"), (21, 40, "Biological"), (41, 60, "Physical"), (61, 80, "Pressure"), (81, 99, "Supply")]
KEYWORDS = {
    "Chemical": ["chlorine", "chemical", "oil", "petrol", "pesticide", "smell", "odour", "odor", "acid", "bleach"],
    "Biological": ["bacteria", "sewage", "sick", "diarrhea", "worms", "algae", "ecoli", "cholera"],
    "Physical": ["muddy", "turbid", "cloudy", "colour", "color", "sediment", "rust", "dirty", "particles"],
    "Pressure": ["pressure", "trickle", "weak"],
    "Supply": ["no water", "interruption", "outage", "dry"],
}

# ---------------- Part A: DFA + regex ----------------
UP = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIG = "0123456789"
eq = lambda x: (lambda c: c == x)
STATION_SPEC = [eq("W"), eq("S"), lambda c: c in UP, lambda c: c in DIG, lambda c: c in DIG, lambda c: c in DIG]
PARAM_SPEC = [eq("P"), lambda c: c in DIG, lambda c: c in DIG]
STATION_RE = re.compile(r"WS[A-Z][0-9]{3}")
PARAM_RE = re.compile(r"P[0-9]{2}")


def dfa(s, spec):
    """Deterministic DFA: state i = i chars matched; len(spec) = accepting; anything else -> dead state."""
    if not s:
        return False, "Value is required"
    st = 0
    for ch in s:
        if st < len(spec) and spec[st](ch):
            st += 1
        else:
            return False, f"Rejected at '{ch}' (position {st + 1}, state q{st})" if st < len(spec) else f"Rejected: extra character '{ch}' after complete identifier"
    if st == len(spec):
        return True, "Valid"
    return False, f"Incomplete: stopped in state q{st}, needs {len(spec) - st} more character(s)"


def check_ids(station, param):
    out, errors = {}, []
    for key, val, spec, rx, label in (("station", station, STATION_SPEC, STATION_RE, "Station code (WS+zone letter+3 digits, e.g. WSN123)"),
                                      ("param", param, PARAM_SPEC, PARAM_RE, "Parameter code (P+2 digits, e.g. P07)")):
        ok, msg = dfa(val, spec)
        rok = bool(rx.fullmatch(val))
        out[key] = {"dfa": ok, "regex": rok, "agree": ok == rok, "message": msg}
        if not ok:
            errors.append(f"{label}: {msg}")
    out["errors"] = errors
    return out


def classify(param, desc):
    """Returns (category, note). Unmapped code (P00) is never silently given a category."""
    n = int(param[1:])
    code_cat = next((c for lo, hi, c in RANGES if lo <= n <= hi), None)
    if code_cat is None:
        return "Unclassified", "Unmapped parameter code P00 -> correction queue"
    text = (desc or "").lower()
    kw = {c for c, ws in KEYWORDS.items() if any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in ws)}
    found = {code_cat} | kw
    win = min(found, key=CAT_ORDER.index)
    if len(found) > 1:
        return win, f"Conflict {sorted(found, key=CAT_ORDER.index)} -> {win} wins by priority rule Chemical>Biological>Physical>Pressure>Supply"
    return win, f"Code {param} maps to {win}"


def prio(cat, urg):
    p = {"Emergency": 1, "High": 2, "Normal": 3, "Low": 4}[urg]
    return 1 if cat in ("Chemical", "Biological") else p


# ---------------- DB ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS handlers(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, zone TEXT, capacity INT, load INT DEFAULT 0, available INT DEFAULT 1, backup_id INT);
CREATE TABLE IF NOT EXISTS routing_table(zone TEXT PRIMARY KEY, branch TEXT, depot TEXT, field_handler_id INT, zqo_handler_id INT);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, report_code TEXT UNIQUE, reporter_name TEXT, contact TEXT, station_code TEXT, param_code TEXT, description TEXT, urgency TEXT, zone TEXT, category TEXT, priority INT, override INT DEFAULT 0, valid INT, validation_msg TEXT, status TEXT, handler_id INT, decision TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, report_id INT UNIQUE, handler_id INT, decision TEXT, timestamp TEXT);
CREATE TABLE IF NOT EXISTS queue(report_id INT PRIMARY KEY, kind TEXT, priority INT, override INT, queued_at TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, report_id INT, decision TEXT, priority INT, timestamp TEXT);
"""


def now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")


@contextmanager
def tx():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def rows(sql, args=()):
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def init_db():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM handlers").fetchone():
        names = {"N": "North", "S": "South", "E": "East", "W": "West"}
        ins = lambda *a: c.execute("INSERT INTO handlers(name,type,zone,capacity,backup_id) VALUES(?,?,?,?,?)", a).lastrowid
        for z in ZONES:
            zq_dep = ins(f"ZQO-{z}-Deputy", "ZQO", z, 2, None)
            zq = ins(f"ZQO-{z}", "ZQO", z, 3, zq_dep)
            tb = ins(f"Team-{z}-B", "FIELD", z, 2, None)
            t = ins(f"Team-{z}", "FIELD", z, 3, tb)
            c.execute("INSERT INTO routing_table VALUES(?,?,?,?,?)", (z, f"Branch-{names[z]}", f"Depot-{names[z]}", t, zq))
        c.execute("INSERT INTO handlers(name,type,zone,capacity) VALUES('Central Control','CENTRAL','*',20)")
    c.commit()
    c.close()


# ---------------- Part B: dispatch ----------------
def log(c, rid, text, p):
    c.execute("INSERT INTO log(report_id,decision,priority,timestamp) VALUES(?,?,?,?)", (rid, text, p, now()))


def chain(c, zone, cat):
    rt = c.execute("SELECT * FROM routing_table WHERE zone=?", (zone,)).fetchone()
    hid = rt["zqo_handler_id"] if cat in ("Chemical", "Biological") else rt["field_handler_id"]
    out, seen = [], set()
    while hid and hid not in seen:
        seen.add(hid)
        h = c.execute("SELECT * FROM handlers WHERE id=?", (hid,)).fetchone()
        out.append(h)
        hid = h["backup_id"]
    out.append(c.execute("SELECT * FROM handlers WHERE type='CENTRAL'").fetchone())
    return out


def try_assign(c, rid):
    r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    if c.execute("SELECT 1 FROM assignments WHERE report_id=?", (rid,)).fetchone():
        return False  # no duplicate assignment
    for i, h in enumerate(chain(c, r["zone"], r["category"])):
        if h["available"] and h["load"] < h["capacity"]:
            if h["type"] == "CENTRAL":
                d = f"ESCALATED to {h['name']} (zone handlers unavailable/full)"
            elif i == 0:
                d = f"Routed to {h['name']} (primary for zone {r['zone']}, {r['category']})"
            else:
                d = f"Backup {h['name']} selected (primary unavailable/at capacity)"
            if r["override"]:
                d += " | PRIORITY OVERRIDE (Emergency)"
            ts = now()
            c.execute("INSERT INTO assignments(report_id,handler_id,decision,timestamp) VALUES(?,?,?,?)", (rid, h["id"], d, ts))
            c.execute("UPDATE handlers SET load=load+1 WHERE id=?", (h["id"],))
            c.execute("UPDATE reports SET status='Assigned',handler_id=?,decision=?,updated_at=? WHERE id=?", (h["id"], d, ts, rid))
            c.execute("DELETE FROM queue WHERE report_id=?", (rid,))
            log(c, rid, d, r["priority"])
            return True
    return False


def drain(c):
    """Deterministic queue order: priority, emergency override first, arrival time, report id."""
    for q in c.execute("SELECT report_id FROM queue WHERE kind='WAITING' ORDER BY priority, override DESC, queued_at, report_id").fetchall():
        try_assign(c, q["report_id"])


def enqueue(c, rid, kind, p, ov, reason):
    c.execute("INSERT OR REPLACE INTO queue VALUES(?,?,?,?,?,?)", (rid, kind, p, ov, now(), reason))
    log(c, rid, f"[{kind}] {reason}", p)
    c.execute("UPDATE reports SET decision=? WHERE id=?", (reason, rid))


def out(r):
    r = dict(r)
    r["priority_label"] = PLABEL.get(r.get("priority"))
    return r


def full_report(where, args):
    return [out(r) for r in rows("SELECT r.*, h.name AS handler_name FROM reports r LEFT JOIN handlers h ON h.id=r.handler_id " + where, args)]


# ---------------- API ----------------
@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/validate")
def validate():
    d = request.get_json(silent=True) or {}
    st, pc = str(d.get("station_code") or "").strip(), str(d.get("param_code") or "").strip()
    v = check_ids(st, pc)
    if st and pc and not v["errors"]:
        v["category"], v["note"] = classify(pc, str(d.get("description") or ""))
        v["zone"] = st[2]
        v["zone_known"] = st[2] in ZONES
    return jsonify(v)


@app.post("/api/reports")
def submit():
    d = request.get_json(silent=True) or {}
    g = lambda k: str(d.get(k) or "").strip()
    name, contact, st, pc, desc, urg = g("reporter_name"), g("contact"), g("station_code"), g("param_code"), g("description"), g("urgency") or "Normal"
    errs = []
    if not name: errs.append("Reporter name is required")
    if not desc: errs.append("Description is required")
    if urg not in URG: errs.append(f"Urgency must be one of {URG}")
    errs += check_ids(st, pc)["errors"]
    with tx() as c:
        rid = c.execute("SELECT COALESCE(MAX(id),0)+1 FROM reports").fetchone()[0]
        code = f"WQ-{dt.datetime.now().strftime('%Y%m%d')}-{rid:04d}"
        ts = now()
        if errs:
            c.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,NULL,?,?,?)",
                      (rid, code, name, contact, st, pc, desc, urg, None, None, None, "; ".join(errs), "Rejected", "Rejected before dispatch: " + "; ".join(errs), ts, ts))
            log(c, rid, "Rejected before dispatch: " + "; ".join(errs), None)
            return jsonify({"report_code": code, "status": "Rejected", "errors": errs}), 422
        zone = st[2]
        cat, note = classify(pc, desc)
        p, ov = prio(cat, urg), int(urg == "Emergency")
        c.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,NULL,NULL,?,?)",
                  (rid, code, name, contact, st, pc, desc, urg, zone, cat, p, ov, note, "Pending", ts, ts))
        if ov:
            log(c, rid, "PRIORITY OVERRIDE: Emergency -> Critical, moved to front of queue", p)
        if cat == "Unclassified":
            enqueue(c, rid, "CORRECTION", p, ov, "Unmapped parameter code -> correction queue")
        elif zone not in ZONES:
            enqueue(c, rid, "FALLBACK", p, ov, f"Unknown zone '{zone}' -> CENTRAL_FALLBACK queue")
        else:
            enqueue(c, rid, "WAITING", p, ov, "Waiting for handler")
            drain(c)
    return jsonify(full_report("WHERE r.id=?", (rid,))[0]), 201


@app.get("/api/reports")
def list_reports():
    return jsonify(full_report("ORDER BY r.id DESC LIMIT 200", ()))


@app.get("/api/reports/<code>")
def get_report(code):
    r = full_report("WHERE r.report_code=?", (code.strip(),))
    return (jsonify(r[0]), 200) if r else (jsonify({"error": "Report not found"}), 404)


@app.get("/api/stats")
def stats():
    n = lambda w: rows(f"SELECT COUNT(*) n FROM reports WHERE {w}")[0]["n"]
    return jsonify({"total": n("1=1"), "pending": n("status='Pending'"), "assigned": n("status='Assigned'"),
                    "in_progress": n("status='In Progress'"), "resolved": n("status='Resolved'"), "rejected": n("status='Rejected'")})


@app.put("/api/reports/<int:rid>/status")
def set_status(rid):
    new = (request.get_json(silent=True) or {}).get("status")
    nxt = {"Assigned": "In Progress", "In Progress": "Resolved"}
    with tx() as c:
        r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        if not r: return jsonify({"error": "Report not found"}), 404
        if nxt.get(r["status"]) != new:
            return jsonify({"error": f"Invalid transition {r['status']} -> {new}. Allowed: Assigned -> In Progress -> Resolved"}), 400
        c.execute("UPDATE reports SET status=?,updated_at=? WHERE id=?", (new, now(), rid))
        log(c, rid, f"Status {r['status']} -> {new}", r["priority"])
        if new == "Resolved":
            c.execute("UPDATE handlers SET load=MAX(load-1,0) WHERE id=?", (r["handler_id"],))
            drain(c)
    return jsonify(full_report("WHERE r.id=?", (rid,))[0])


@app.get("/api/handlers")
def handlers():
    return jsonify(rows("SELECT h.*, b.name AS backup_name FROM handlers h LEFT JOIN handlers b ON b.id=h.backup_id ORDER BY h.id"))


@app.get("/api/handlers/<int:hid>/reports")
def handler_reports(hid):
    return jsonify(full_report("WHERE r.handler_id=? ORDER BY r.priority, r.created_at", (hid,)))


@app.put("/api/handlers/<int:hid>")
def update_handler(hid):
    d = request.get_json(silent=True) or {}
    with tx() as c:
        if not c.execute("SELECT 1 FROM handlers WHERE id=?", (hid,)).fetchone():
            return jsonify({"error": "Handler not found"}), 404
        if "available" in d:
            c.execute("UPDATE handlers SET available=? WHERE id=?", (int(bool(d["available"])), hid))
        if "capacity" in d:
            try: cap = int(d["capacity"])
            except (TypeError, ValueError): return jsonify({"error": "Capacity must be an integer"}), 400
            if cap < 0: return jsonify({"error": "Capacity must be >= 0"}), 400
            c.execute("UPDATE handlers SET capacity=? WHERE id=?", (cap, hid))
        drain(c)
    return jsonify([h for h in rows("SELECT * FROM handlers WHERE id=?", (hid,))][0])


@app.get("/api/routing")
def routing():
    rt = rows("""SELECT t.zone, t.branch, t.depot, f.name field_team, z.name quality_officer
                 FROM routing_table t JOIN handlers f ON f.id=t.field_handler_id JOIN handlers z ON z.id=t.zqo_handler_id""")
    queue = rows("""SELECT q.kind, q.reason, q.priority, q.override, q.queued_at, r.id report_id, r.report_code, r.category, r.zone
                    FROM queue q JOIN reports r ON r.id=q.report_id ORDER BY q.priority, q.override DESC, q.queued_at, q.report_id""")
    lg = rows("SELECT l.*, r.report_code FROM log l LEFT JOIN reports r ON r.id=l.report_id ORDER BY l.id DESC LIMIT 100")
    return jsonify({"routing_table": rt, "handlers": handlers().get_json(), "queue": queue,
                    "escalations": [x for x in lg if "ESCALATED" in x["decision"]],
                    "overrides": [x for x in lg if "OVERRIDE" in x["decision"]], "log": lg})


@app.post("/api/queue/<int:rid>/route")
def manual_route(rid):
    """Operator fixes a report sitting in the fallback/correction queue."""
    d = request.get_json(silent=True) or {}
    zone, cat = str(d.get("zone") or "").upper(), d.get("category")
    with tx() as c:
        q = c.execute("SELECT * FROM queue WHERE report_id=? AND kind IN ('FALLBACK','CORRECTION')", (rid,)).fetchone()
        r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        if not q: return jsonify({"error": "Report is not in the fallback/correction queue"}), 404
        if zone not in ZONES: return jsonify({"error": f"Zone must be one of {ZONES}"}), 400
        cat = cat or r["category"]
        if cat not in CAT_ORDER: return jsonify({"error": f"Category must be one of {CAT_ORDER}"}), 400
        p = prio(cat, r["urgency"])
        c.execute("UPDATE reports SET zone=?,category=?,priority=? WHERE id=?", (zone, cat, p, rid))
        c.execute("UPDATE queue SET kind='WAITING',priority=?,reason='Manually corrected by operator' WHERE report_id=?", (p, rid))
        log(c, rid, f"Operator corrected -> zone {zone}, {cat}", p)
        drain(c)
    return jsonify(full_report("WHERE r.id=?", (rid,))[0])


@app.get("/api/analytics")
def analytics():
    ok = "valid=1"
    return jsonify({
        "by_zone": rows(f"SELECT zone label, COUNT(*) n FROM reports WHERE {ok} GROUP BY zone ORDER BY zone"),
        "by_category": rows(f"SELECT category label, COUNT(*) n FROM reports WHERE {ok} GROUP BY category ORDER BY n DESC"),
        "by_status": rows("SELECT status label, COUNT(*) n FROM reports GROUP BY status"),
        "resolved": rows("SELECT COUNT(*) n FROM reports WHERE status='Resolved'")[0]["n"],
        "unresolved": rows("SELECT COUNT(*) n FROM reports WHERE status IN ('Pending','Assigned','In Progress')")[0]["n"],
    })


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
