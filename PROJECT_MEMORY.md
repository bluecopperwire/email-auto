# Project Memory: Email Merge Automation

## Overview
A Python-based mail merge automation script that reads company/contact information from a CSV file, validates email addresses, filters out duplicate contacts, and sends personalized internship application emails with a resume attachment using a Gmail account via SMTP.

---

## Todo List
- [x] Create `implementation_plan.md` and get user approval
- [x] Setup project structure (e.g., config templates, project structure)
- [x] Implement configuration loader (load `.env` / configuration values)
- [x] Implement CSV parser with dynamic header detection
- [x] Implement email validator and duplicate protection
- [x] Implement email builder (MIME constructor with attachment and conditional greeting)
- [x] Implement SMTP sender with error handling, logging (`email_log.csv`), and random delays
- [x] Create testing instructions and dry run verification
- [x] Create user documentation (README.md) with Gmail App Password instructions and run instructions

---

## Log & Decisions
- **2026-07-06**: Initial analysis of workspace, CSV headers, and requirement specifications. Initiated project memory tracking.
- **2026-07-06**: Implementation plan approved. Developed `send_emails.py` with zero dependencies, robust logging, cross-run duplicate protection, and dynamic header search. Verified functionality using dry run simulations. Documented setup in `README.md`.
- **2026-07-06**: Added blacklist filtering functionality to allow skipping of specific companies or email addresses loaded from `blacklist.txt`. Verified that blacklisted items are successfully skipped and logged under the status `SKIPPED_BLACKLISTED`.

