#!/usr/bin/env python3
"""
Email Merge Automation Script
Author: Dominic Christian Isais / Antigravity

This script automates sending personalized internship application emails using a Gmail SMTP server.
It features:
- Dynamic CSV header parsing (skips metadata lines automatically)
- Zero external package requirements (optional python-dotenv support)
- Robust email validation and duplicate email address protection
- Resumes sending by scanning previous email logs to avoid sending twice
- Random delays between 10-20 seconds to prevent spam flags
- Resume attachment verification (fails fast if file is missing)
- Log generation (email_log.csv) with detailed execution metrics
- Dry-run mode for safe execution testing
"""

import os
import sys
import csv
import re
import time
import random
import smtplib
import ssl
import argparse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

# Try to import dotenv for convenience; otherwise fallback to custom .env parser
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

# Regex pattern for basic email validation (standards-compliant, no extra packages)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def load_env_fallback(dotenv_path=".env"):
    """
    Fallback .env loader that parses key-value pairs manually.
    Avoids requiring third-party libraries for basic operations.
    """
    if not os.path.exists(dotenv_path):
        return False
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip surrounding quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key] = val
        return True
    except Exception as e:
        print(f"Warning: Failed to parse .env file via fallback loader: {e}", file=sys.stderr)
        return False


def get_config():
    """
    Loads, sanitizes, and returns the configuration settings.
    Prioritizes OS environment variables, then loaded .env variables.
    """
    # Attempt to load configuration
    if HAS_DOTENV:
        load_dotenv()
    else:
        load_env_fallback()

    config = {
        "GMAIL_ADDRESS": os.getenv("GMAIL_ADDRESS"),
        "GMAIL_APP_PASSWORD": os.getenv("GMAIL_APP_PASSWORD"),
        "SMTP_SERVER": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "SMTP_PORT": os.getenv("SMTP_PORT", "465"),
        "CSV_FILE_PATH": os.getenv("CSV_FILE_PATH"),
        "RESUME_PATH": os.getenv("RESUME_PATH", "attachments/Resume.pdf"),
        "MIN_DELAY": os.getenv("MIN_DELAY", "10"),
        "MAX_DELAY": os.getenv("MAX_DELAY", "20"),
        "DRY_RUN": os.getenv("DRY_RUN", "True").lower() in ("true", "1", "yes"),
        "BLACKLIST_FILE_PATH": os.getenv("BLACKLIST_FILE_PATH", "blacklist.txt")
    }

    return config


def validate_config(config):
    """
    Validates that essential configuration variables are present and of the correct type.
    Exits the script if critical parameters are missing.
    """
    errors = []

    # Required fields
    required_keys = ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CSV_FILE_PATH", "RESUME_PATH"]
    for key in required_keys:
        if not config[key]:
            errors.append(f"Missing required configuration key: {key}")

    # Numeric validations
    try:
        config["SMTP_PORT"] = int(config["SMTP_PORT"])
    except ValueError:
        errors.append(f"SMTP_PORT must be an integer (got: {config['SMTP_PORT']})")

    try:
        config["MIN_DELAY"] = float(config["MIN_DELAY"])
    except ValueError:
        errors.append(f"MIN_DELAY must be a number (got: {config['MIN_DELAY']})")

    try:
        config["MAX_DELAY"] = float(config["MAX_DELAY"])
    except ValueError:
        errors.append(f"MAX_DELAY must be a number (got: {config['MAX_DELAY']})")

    if config["MIN_DELAY"] < 0 or config["MAX_DELAY"] < 0:
        errors.append("Delays must be non-negative values.")

    if config["MIN_DELAY"] > config["MAX_DELAY"]:
        errors.append("MIN_DELAY cannot be greater than MAX_DELAY.")

    if errors:
        print("\n=== Configuration Configuration Error ===", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print("\nPlease create a '.env' file based on '.env.template' and specify all parameters.", file=sys.stderr)
        sys.exit(1)

    return config


def parse_csv_file(csv_path):
    """
    Parses a CSV file containing company and contact data.
    Dynamically scans for the header row containing 'COMPANY'S NAME' and 'EMAIL ADDRESS'.
    """
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at path: {csv_path}", file=sys.stderr)
        sys.exit(1)

    records = []
    header_indices = {}
    header_found = False

    # Open with utf-8-sig to automatically handle UTF-8 BOM
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        for row_idx, row in enumerate(reader):
            # Skip completely empty rows
            if not row or all(cell.strip() == "" for cell in row):
                continue

            if not header_found:
                # Standardize values for comparison
                row_clean = [col.strip().upper() for col in row]
                # Look for a row containing both Company's Name and Email Address columns
                if "COMPANY'S NAME" in row_clean and "EMAIL ADDRESS" in row_clean:
                    header_found = True
                    # Retrieve the specific columns required
                    for col_name in ["COMPANY'S NAME", "CONTACT PERSON", "EMAIL ADDRESS"]:
                        try:
                            header_indices[col_name] = row_clean.index(col_name)
                        except ValueError:
                            if col_name == "CONTACT PERSON":
                                # Contact person is optional; handle gracefully if not present
                                header_indices[col_name] = -1
                            else:
                                print(f"Error: Required column '{col_name}' was not found in CSV header.", file=sys.stderr)
                                sys.exit(1)
                    continue
            else:
                # Ensure the row has enough columns corresponding to indices
                max_idx = max(header_indices.values())
                if len(row) <= max_idx:
                    # Pad row with empty cells
                    row += [''] * (max_idx - len(row) + 1)

                company = row[header_indices["COMPANY'S NAME"]].strip()
                contact = ""
                if header_indices["CONTACT PERSON"] != -1:
                    contact = row[header_indices["CONTACT PERSON"]].strip()
                email = row[header_indices["EMAIL ADDRESS"]].strip()

                # Skip completely blank data rows (e.g. metadata trailing rows)
                if not company and not contact and not email:
                    continue

                records.append({
                    "company": company,
                    "contact": contact,
                    "email": email,
                    "line_number": row_idx + 1
                })

    if not header_found:
        print(f"Error: Could not locate header row in CSV file '{csv_path}'.", file=sys.stderr)
        print("Ensure the CSV has column headers labeled \"COMPANY'S NAME\" and \"EMAIL ADDRESS\".", file=sys.stderr)
        sys.exit(1)

    return records


def is_valid_email(email):
    """
    Validates an email address using a standard regex.
    """
    if not email:
        return False
    return bool(EMAIL_REGEX.match(email))


def load_sent_emails(log_path="email_log.csv"):
    """
    Scans the CSV log file to find email addresses that have already been sent successfully.
    This protects against duplicates across multiple executions of the script.
    """
    sent_emails = set()
    if not os.path.exists(log_path):
        return sent_emails

    try:
        with open(log_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Verify columns exist
            if not reader.fieldnames or "Email Address" not in reader.fieldnames or "Status" not in reader.fieldnames:
                return sent_emails
            
            for row in reader:
                status = row.get("Status", "").strip().upper()
                email = row.get("Email Address", "").strip().lower()
                if status == "SENT" and email:
                    sent_emails.add(email)
    except Exception as e:
        print(f"Warning: Could not parse previous run logs in '{log_path}' for duplicates: {e}", file=sys.stderr)
    
    return sent_emails


def load_blacklist(blacklist_path):
    """
    Loads blacklisted company names and email addresses from a text file.
    Each line can be a company name or an email address.
    """
    blacklist = set()
    if not blacklist_path or not os.path.exists(blacklist_path):
        return blacklist
    try:
        with open(blacklist_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                blacklist.add(line)
    except Exception as e:
        print(f"Warning: Could not parse blacklist file '{blacklist_path}': {e}", file=sys.stderr)
    return blacklist


def write_log(log_path, company, contact, email, status, error_msg=""):
    """
    Appends execution result for a single row to the CSV log file.
    Creates the log file with header if it doesn't already exist.
    """
    file_exists = os.path.exists(log_path)
    try:
        with open(log_path, mode='a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "Company Name", "Contact Person", "Email Address", "Status", "Error Message"])
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([timestamp, company, contact, email, status, error_msg])
    except Exception as e:
        print(f"Error writing to log file '{log_path}': {e}", file=sys.stderr)


def get_smtp_connection(server, port, address, password):
    """
    Establishes and returns an authenticated SMTP connection.
    Supports standard SSL (port 465) and STARTTLS (port 587).
    """
    if port == 465:
        context = ssl.create_default_context()
        conn = smtplib.SMTP_SSL(server, port, context=context)
    else:
        conn = smtplib.SMTP(server, port)
        conn.ehlo()
        conn.starttls()
        conn.ehlo()
    conn.login(address, password)
    return conn


def send_application_email(smtp_conn, sender, recipient_email, company_name, contact_person, resume_path):
    """
    Constructs and sends the internship application email.
    """
    # 1. Subject line
    subject = "RE: Internship Application (200 hrs) - Computer Science"

    # 2. Compute Greeting
    if not contact_person:
        greeting = "Dear Hiring Manager,"
    else:
        greeting = f"Dear {contact_person},"

    # 3. Email Body text
    body_text = f"""{greeting}

I hope this email finds you well.

I am Dominic Christian Isais, a Bachelor of Science in Computer Science student from the Polytechnic University of the Philippines.

I am writing to express my interest in applying for an internship opportunity with your company as part of my required 200-hour internship.

Please find my resume attached for your review.

I would greatly appreciate the opportunity to be considered for any available internship position. Thank you for your time and consideration. I look forward to hearing from you.

Sincerely,

Dominic Christian Isais
Bachelor of Science in Computer Science
Polytechnic University of the Philippines"""

    # 4. Construct MIME Multipart message
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = recipient_email
    msg['Subject'] = subject

    # Attach text body
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    # Attach PDF resume file
    resume_file = Path(resume_path)
    with open(resume_file, "rb") as attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{resume_file.name}"'
        )
        msg.attach(part)

    # 5. Send email via active SMTP connection
    smtp_conn.sendmail(sender, recipient_email, msg.as_string())


def main():
    parser = argparse.ArgumentParser(description="Mail Merge Internship Application Script")
    parser.add_argument("--dry-run", action="store_true", help="Force dry run mode (no emails sent)")
    parser.add_argument("--no-dry-run", action="store_true", help="Force active send mode (emails will be sent)")
    parser.add_argument("--csv", type=str, help="Override CSV file path configuration")
    args = parser.parse_args()

    # Load config
    config = get_config()

    # Apply command-line overrides
    if args.csv:
        config["CSV_FILE_PATH"] = args.csv
    if args.dry_run:
        config["DRY_RUN"] = True
    elif args.no_dry_run:
        config["DRY_RUN"] = False

    # Validate configuration
    config = validate_config(config)

    # Output run configuration header
    print("=" * 60)
    print("           INTERNSHIP APPLICATION MAIL MERGE AUTOMATION")
    print("=" * 60)
    print(f"Gmail Address : {config['GMAIL_ADDRESS']}")
    print(f"CSV File Path : {config['CSV_FILE_PATH']}")
    print(f"Resume Path   : {config['RESUME_PATH']}")
    print(f"SMTP Server   : {config['SMTP_SERVER']}:{config['SMTP_PORT']}")
    print(f"Delays        : Random wait between {config['MIN_DELAY']}s and {config['MAX_DELAY']}s")
    print(f"Execution Mode: {'DRY RUN (Simulated)' if config['DRY_RUN'] else 'LIVE SEND (Active)'}")
    print("=" * 60)

    # Fail fast if Resume doesn't exist
    if not os.path.exists(config["RESUME_PATH"]):
        print(f"\nCRITICAL ERROR: Resume PDF not found at path: {config['RESUME_PATH']}", file=sys.stderr)
        print("Please check your configuration or make sure the file exists.", file=sys.stderr)
        sys.exit(1)

    # Parse CSV file
    print("Parsing CSV rows...")
    records = parse_csv_file(config["CSV_FILE_PATH"])
    total_records = len(records)
    print(f"Successfully loaded {total_records} rows from CSV.\n")

    # Load existing logs for cross-run duplicate checking
    log_file = "email_log.csv"
    seen_emails = load_sent_emails(log_file)
    if seen_emails:
        print(f"Loaded {len(seen_emails)} previously sent emails from '{log_file}' to prevent duplicates.")

    # Load blacklist
    blacklist_file = config["BLACKLIST_FILE_PATH"]
    blacklist = load_blacklist(blacklist_file)
    if blacklist:
        print(f"Loaded {len(blacklist)} blacklisted companies/emails from '{blacklist_file}'.")

    # Initialize SMTP variables
    smtp_conn = None
    sent_count = 0
    failed_count = 0
    skipped_dup_count = 0
    skipped_inv_count = 0
    skipped_blacklist_count = 0

    # Live connection setup (if not Dry Run)
    if not config["DRY_RUN"]:
        print("Connecting and logging into SMTP Server...")
        try:
            smtp_conn = get_smtp_connection(
                config["SMTP_SERVER"],
                config["SMTP_PORT"],
                config["GMAIL_ADDRESS"],
                config["GMAIL_APP_PASSWORD"]
            )
            print("SMTP login successful.\n")
        except Exception as e:
            print(f"CRITICAL ERROR: Could not connect to SMTP server: {e}", file=sys.stderr)
            print("Verify your Gmail App Password, network connection, or SMTP settings.", file=sys.stderr)
            sys.exit(1)

    print("Beginning email processing...")
    print("-" * 60)

    try:
        for idx, record in enumerate(records):
            comp = record["company"]
            cont = record["contact"]
            email = record["email"]
            line = record["line_number"]

            print(f"[{idx+1}/{total_records}] Line {line}: {comp} | {cont or '(No Contact)'} | {email}")

            # 1. Blacklist Check
            comp_lower = comp.lower()
            email_lower = email.lower()
            if comp_lower in blacklist or email_lower in blacklist:
                print(f"  --> SKIP: Company '{comp}' or Email '{email}' is in the blacklist.")
                write_log(log_file, comp, cont, email, "SKIPPED_BLACKLISTED", "Blacklisted in config file")
                skipped_blacklist_count += 1
                continue

            # 2. Validation Check
            if not email:
                print(f"  --> SKIP: Email address is empty.")
                write_log(log_file, comp, cont, email, "SKIPPED_INVALID_EMAIL", "Email address is empty")
                skipped_inv_count += 1
                continue

            if not is_valid_email(email):
                print(f"  --> SKIP: Email address '{email}' is invalid.")
                write_log(log_file, comp, cont, email, "SKIPPED_INVALID_EMAIL", "Invalid email format")
                skipped_inv_count += 1
                continue

            # 2. Duplicate Check (case-insensitive)
            email_lower = email.lower()
            if email_lower in seen_emails:
                print(f"  --> SKIP: Email address '{email}' already received a send (Duplicate protection).")
                write_log(log_file, comp, cont, email, "SKIPPED_DUPLICATE", "Already sent in this or a previous run")
                skipped_dup_count += 1
                continue

            # 3. Add delay if this is NOT the first email sent in this execution
            # Delay is added prior to sending to space out operations
            if sent_count > 0 or failed_count > 0:
                sleep_time = random.uniform(config["MIN_DELAY"], config["MAX_DELAY"])
                print(f"  --> Delaying for {sleep_time:.2f} seconds before sending...")
                if not config["DRY_RUN"]:
                    time.sleep(sleep_time)

            # 4. Perform Sending
            if config["DRY_RUN"]:
                print(f"  --> [DRY RUN] Would send email to: {email}")
                write_log(log_file, comp, cont, email, "SENT", "Dry run send simulation")
                # Add to seen emails set to simulate duplicate protection for subsequent rows in this dry run
                seen_emails.add(email_lower)
                sent_count += 1
            else:
                send_success = False
                error_details = ""
                # Attempt sending, with automatic reconnection try if SMTP connection fails
                for attempt in range(2):
                    try:
                        send_application_email(
                            smtp_conn,
                            config["GMAIL_ADDRESS"],
                            email,
                            comp,
                            cont,
                            config["RESUME_PATH"]
                        )
                        send_success = True
                        break
                    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as conn_err:
                        print(f"  --> SMTP Connection lost on attempt {attempt+1}. Attempting reconnection...")
                        try:
                            smtp_conn = get_smtp_connection(
                                config["SMTP_SERVER"],
                                config["SMTP_PORT"],
                                config["GMAIL_ADDRESS"],
                                config["GMAIL_APP_PASSWORD"]
                            )
                        except Exception as reconnect_err:
                            error_details = f"Reconnection failed: {reconnect_err}"
                            break
                    except Exception as e:
                        error_details = str(e)
                        break

                if send_success:
                    print(f"  --> SENT successfully.")
                    write_log(log_file, comp, cont, email, "SENT")
                    seen_emails.add(email_lower)
                    sent_count += 1
                else:
                    print(f"  --> FAILED: {error_details}")
                    write_log(log_file, comp, cont, email, "FAILED", error_details)
                    failed_count += 1

    finally:
        # Gracefully terminate the SMTP session
        if smtp_conn:
            try:
                smtp_conn.quit()
                print("\nSMTP connection closed.")
            except Exception:
                pass

    print("-" * 60)
    print("Execution Finished Summary:")
    print(f"Total processed rows : {total_records}")
    print(f"Successfully Sent    : {sent_count}")
    print(f"Failed               : {failed_count}")
    print(f"Skipped Duplicates   : {skipped_dup_count}")
    print(f"Skipped Invalid      : {skipped_inv_count}")
    print(f"Skipped Blacklisted  : {skipped_blacklist_count}")
    print(f"Details written to   : {os.path.abspath(log_file)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
