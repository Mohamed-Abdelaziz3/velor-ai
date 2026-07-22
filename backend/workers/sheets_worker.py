"""
workers/sheets_worker.py — RQ worker for Google Sheets sync
============================================================
Issue #9 — replaces asyncio.create_task (fire-and-forget, unreliable).

Usage:
  Start worker:   rq worker adam-sheets --url redis://localhost:6379/0

brain.py enqueues a job via enqueue_sheets_log(); this module is
the actual worker code that runs in a separate process.
"""

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("velor.sheets_worker")

GOOGLE_CREDS_FILE = os.path.join(os.path.dirname(__file__), "..", "google_keys.json")


def sync_lead_to_sheets(name: str, phone: str, interest: str, company_id: str = "default") -> dict:
    """
    Called by the RQ worker process.
    Each company gets its own sheet tab (worksheet) inside "VELOR Leads" spreadsheet.
    Returns {"status": "ok"} or raises on hard failure (RQ will retry).
    """
    if os.getenv("ENABLE_GOOGLE_SHEETS_EXPORT", "false").strip().casefold() != "true":
        log.info("Google Sheets export is disabled")
        return {"status": "skipped", "reason": "export_disabled"}

    if not os.path.exists(GOOGLE_CREDS_FILE):
        log.info("google_keys.json not found — skipping Sheets sync")
        return {"status": "skipped", "reason": "no_creds_file"}

    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open("VELOR Leads")

        # Phase 4: Per-company worksheet — each company gets its own tab
        sheet_title = f"company_{company_id}"
        try:
            sheet = spreadsheet.worksheet(sheet_title)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=sheet_title, rows=1000, cols=5)
            sheet.append_row(["الاسم", "الهاتف", "الاهتمام", "التاريخ"])
            log.info("Created new worksheet for company=%s", company_id)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Step A: Search the Google Sheet for the specific clean_phone (Column B / 2)
        try:
            phones = sheet.col_values(2)  # 1-based index for column B

            if phone in phones:
                # Step B: Phone number EXISTS, UPDATE that specific row
                row_index = phones.index(phone) + 1  # list index is 0-based, sheet rows are 1-based
                # Update cells A:D for the found row
                sheet.update(values=[[name, phone, interest, timestamp]], range_name=f"A{row_index}:D{row_index}")
                log.info("Sheets sync update completed for company=%s", company_id)
            else:
                # Step C: Phone DOES NOT EXIST, APPEND a new row
                sheet.append_row([name, phone, interest, timestamp])
                log.info("Sheets sync append completed for company=%s", company_id)

        except Exception as sheet_err:
            log.error("Sheets upsert operation failed for company=%s (%s)", company_id, type(sheet_err).__name__)
            raise

        return {"status": "ok"}
    except Exception as exc:
        log.error("Sheets sync failed for company=%s (%s)", company_id, type(exc).__name__)
        raise  # RQ will retry the job (default: 3 attempts)
