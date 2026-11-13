# 💧 Water Quality Incident Reporter

**Submission:** 106_163_P10  
**Problem Statement:** P10  
**Subjects:** BCS503 – Automata Theory and Computability | BCS502 – Computer Networks

## 📌 Project Overview

The **Water Quality Incident Reporter** is a web-based application designed to help water-supply field teams receive, validate, classify, dispatch, and track water quality complaints.

The system uses a **Deterministic Finite Automaton (DFA)** and an equivalent Regular Expression (Regex) to validate complaint identifiers. Each valid report is assigned to exactly one of five categories and routed to the appropriate handler using a two-tier routing mechanism.

The application also manages handler availability, workload capacity, emergency priorities, waiting queues, and report status updates.

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, HTML, CSS, JavaScript |
| Backend | Python, Flask REST API |
| Database | SQLite |
| Testing | Python unittest |
| Validation | DFA and Regular Expressions |

## 📂 Project Structure

```text
wq/
├── backend/
│   ├── app.py
│   └── tests.py
├── frontend/
│   ├── static/
│   │   └── index.html
│   ├── requirements.txt
│   └── README.md
└── database/
    └── wq.db
```

## ✨ Key Features

### 1. Automata Theory (BCS503)

**DFA and Regex Validation**

- Validates station codes in the format `WS[ZONE][3-digit]`.
- Validates parameter codes in the format `P[2-digit]`.
- Uses a hand-built DFA and an equivalent Regex.
- Both validation methods produce identical results.
- Displays validation results live with the position of the first error.

**Five-Category Classification**

Each accepted report is classified into exactly one category.

| Parameter Code | Category |
|---|---|
| P01 – P20 | Chemical |
| P21 – P40 | Biological |
| P41 – P60 | Physical |
| P61 – P80 | Pressure |
| P81 – P99 | Supply |
| P00 | Unmapped |

**Special Cases**

- Incomplete or malformed identifiers are rejected.
- Unmapped parameter codes are sent to the correction queue.
- Conflicting keywords follow the priority rule: Chemical > Biological > Physical > Pressure > Supply.
- Validation results and classifications are stored in the database.

### 2. Computer Networks (BCS502)

**Two-Tier Routing Mechanism**

Reports are routed according to their validated zone and category.

- Chemical and Biological reports are assigned to the Zonal Quality Officer.
- Physical, Pressure, and Supply reports are assigned to the respective Field Team.

| Zone | Branch | Depot | Field Team | Quality Officer |
|---|---|---|---|---|
| N | Branch-North | Depot-North | Team-N | ZQO-N |
| S | Branch-South | Depot-South | Team-S | ZQO-S |
| E | Branch-East | Depot-East | Team-E | ZQO-E |
| W | Branch-West | Depot-West | Team-W | ZQO-W |

**Dispatch Algorithm**

Before assigning a report, the system checks:

- Handler availability.
- Current workload.
- Maximum capacity.

Fallback order:

1. Primary Handler
2. Backup Handler
3. Central Control (Escalation)
4. Waiting Queue

**Priority Management**

- Chemical and Biological reports are always Critical.
- Other reports follow their selected urgency.
- Emergency reports receive Critical priority and jump the queue.
- Reports are processed using a deterministic ordering based on priority, emergency override, arrival time, and report ID.

**Report Status Tracking**

Reports move through the following stages:

`Pending → Assigned → In Progress → Resolved`

When a report is resolved, the handler's available capacity is updated and the next waiting report is automatically assigned.

### 3. Web Application

The application contains five main pages.

| Page | Features |
|---|---|
| Submit Report | Complaint submission, live validation, category detection, priority selection, unique report ID |
| User Dashboard | Total reports, pending reports, assigned reports, resolved reports, and report search |
| Handler Dashboard | Assigned reports, status updates, availability and capacity controls |
| Routing Management | Routing table, handler loads, backups, waiting queue, escalations, priority overrides, and decision logs |
| Analytics | Zone-wise reports, category-wise reports, resolved vs unresolved charts |

### 4. Automated Testing

The project includes **17 automated test cases** using Python's `unittest` framework.

Tests cover:

- Valid and invalid identifier formats.
- DFA and Regex agreement.
- All five categories.
- Conflicting classification patterns.
- Unknown zones.
- Invalid and unmapped parameter codes.
- Handler availability and capacity.
- Fallback and escalation mechanisms.
- Emergency priority override.
- Simultaneous report handling.
- Status updates.
- Database persistence.

## 🚀 Installation and Setup

### Prerequisites

- Python 3.9 or above.
- pip package manager.
- Internet connection (React is loaded through a CDN).

### Step 1: Clone the Repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

### Step 2: Navigate to the Backend

```bash
cd wq/backend
```

### Step 3: Install Dependencies

```bash
pip install -r ../frontend/requirements.txt
```

### Step 4: Run the Application

```bash
python app.py
```

### Step 5: Open in Browser

Visit:

```text
http://localhost:5000
```

Keep the terminal running while using the application.

## 🧪 Running Automated Tests

Navigate to the backend directory and execute:

```bash
python -m unittest tests -v
```

The test suite contains 17 automated tests covering validation, classification, routing, dispatching, priority handling, and database operations.

## 📡 REST API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/validate` | Validate and classify a report |
| POST | `/api/reports` | Submit and dispatch a report |
| GET | `/api/reports` | Retrieve recent reports |
| GET | `/api/reports/<code>` | Get report status and handler |
| PUT | `/api/reports/<id>/status` | Update report status |
| GET | `/api/stats` | Retrieve report statistics |
| GET | `/api/handlers` | Get handler loads and capacity |
| GET | `/api/handlers/<id>/reports` | Get reports assigned to a handler |
| PUT | `/api/handlers/<id>` | Update handler availability or capacity |
| GET | `/api/routing` | Retrieve routing information and queue |
| POST | `/api/queue/<id>/route` | Manually route a queued report |
| GET | `/api/analytics` | Retrieve analytics data |

## 📝 Sample Demo Inputs

| Station Code | Parameter | Description | Expected Result |
|---|---|---|---|
| WSN123 | P07 | Strong chlorine smell | Chemical, Critical, ZQO-N |
| WSE204 | P25 | Bacteria suspected | Biological, Critical, ZQO-E |
| WSS310 | P45 | Water is muddy | Physical, Team-S |
| WSS220 | P45 | Chlorine smell and muddy water | Chemical wins conflict |
| WSN12 | P07 | Any | Rejected: incomplete station code |
| WSN123 | P00 | Any | Unclassified, correction queue |
| WSX123 | P50 | Any | Unknown zone, CENTRAL_FALLBACK |

## ⚙️ Important Implementation Details

- DFA and Regex validation are used together to verify identifier formats.
- Every accepted report receives exactly one category.
- Routing decisions are based only on validated report information.
- Handler availability and capacity are checked before assignment.
- Database transactions and UNIQUE constraints help prevent duplicate assignments.
- Emergency reports receive priority over normal waiting reports.
- Manual correction is supported for fallback and unmapped reports.
- SQLite stores reports, classifications, assignments, and status information.

## ⚠️ Limitations

- No user authentication or login system.
- No email, SMS, or push notifications.
- No multi-language support.
- Zone identification is based on station codes rather than GPS.
- Uses a local SQLite database, making it suitable as a prototype rather than a production deployment.

## 🎯 Learning Outcomes

This project demonstrates the practical application of two academic subjects:

**BCS503 – Automata Theory and Computability**
- Designing and implementing a DFA.
- Understanding Regular Expressions.
- Validating input strings using finite automata.
- Applying formal language concepts to a real-world problem.

**BCS502 – Computer Networks**
- Understanding routing tables and routing decisions.
- Implementing two-tier routing.
- Managing queues and priority-based dispatching.
- Handling availability, capacity, fallback, and escalation.

## 👨‍💻 Project Information

**Project Name:** Water Quality Incident Reporter  
**Submission ID:** 106_163_P10  
**Problem Statement:** P10  
**Subjects:** BCS503 and BCS502

---

*This project combines Automata Theory and Computer Networks concepts into a practical web-based water quality complaint management system.*
