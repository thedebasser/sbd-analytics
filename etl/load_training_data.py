#!/usr/bin/env python3
import os
import re
import sys
import logging
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from apps_to_py import extract_all_workout_data

# ----------------- CONFIGURE LOGGING -----------------
LOG_PATH = os.getenv('ETL_LOG_FILE', 'etl_debug.log')
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logging.debug("=== Starting ETL run ===")

# Default bodyweight for BW entries (kg)
DEFAULT_BODYWEIGHT = float(os.getenv('DEFAULT_BODYWEIGHT', '100'))

try:
    import gspread
except ImportError:
    logging.error("gspread library not found")
    sys.exit("ERROR: gspread library not found. Please install: pip install gspread oauth2client")

# Regex to identify Block sheets: number and optional comment
BLOCK_SHEET_REGEX = re.compile(
    r'^(?:B|Block)\s*(?P<number>\d+)'           # Block prefix and number
    r'(?:'                                       # optional comment
      r'\s*[-–]\s*(?P<comment>[^()]+?)'         # - comment text
    r'|\s*\((?P<comment2>[^)]+)\)'             # or (comment text)
    r')?$',
    re.IGNORECASE
)

# Helper: parse numeric cell, handling ranges, BW, and percent adjustments
def parse_numeric_cell(raw, previous_rpe=None):
    s = str(raw).strip()
    # 1) Empty → None
    if not s:
        return None

    # 2) RPE‐percent adjustments
    if s.endswith('%'):
        if previous_rpe is None:
            return None  # or choose a sensible default
        pct = float(s.rstrip('%'))
        if abs(pct) >= 7:
            return previous_rpe - 2
        elif abs(pct) >= 5:
            return previous_rpe - 1
        else:
            return previous_rpe

    # 3) Range like “8-12”
    m = re.match(r'^(\d+)\s*-\s*\d+', s)
    if m:
        return float(m.group(1))

    # 4) Body-weight placeholder
    if s.upper() == 'BW':
        return DEFAULT_BODYWEIGHT

    # 5) Fallback
    try:
        return float(s)
    except ValueError:
        return None

# --------------------------------------------------------------------------------
# 1) Find metadata: Start Date and End Date
# --------------------------------------------------------------------------------
def find_metadata(df):
    start_date = None
    end_date   = None
    for _, row in df.iterrows():
        for cell in row:
            if isinstance(cell, str) and cell.startswith('Start Date:'):
                start_date = cell.split(':', 1)[1].strip() or None
            if isinstance(cell, str) and cell.startswith('End Date:'):
                end_date = cell.split(':', 1)[1].strip() or None
        if start_date or end_date:
            break
    logging.debug(f"Found metadata: start_date={start_date}, end_date={end_date}")
    return start_date, end_date

# --------------------------------------------------------------------------------
# 2) Load worksheets matching training blocks from Google Sheets
# --------------------------------------------------------------------------------
def get_block_sheets():
    creds_path = os.getenv('GOOGLE_CREDS')
    sheet_id   = os.getenv('SHEET_ID') or open(os.getenv('SHEET_ID_FILE')).read().strip()
    if not creds_path or not sheet_id:
        logging.error("Missing GOOGLE_CREDS and/or SHEET_ID")
        sys.exit("ERROR: Set GOOGLE_CREDS and SHEET_ID(_FILE) environment variables.")
    client      = gspread.service_account(filename=creds_path)
    spreadsheet = client.open_by_key(sheet_id)
    block_sheets = []

    for ws in spreadsheet.worksheets():
        title = ws.title.strip()
        m     = BLOCK_SHEET_REGEX.match(title)
        if not m:
            continue
        block_num = int(m.group('number'))
        comment   = m.group('comment') or m.group('comment2')
        if comment:
            comment = comment.strip()
        logging.info(f"Starting import for Block {block_num}{f' – {comment}' if comment else ''}")
        print(f"Starting import for Block {block_num}{f' – {comment}' if comment else ''}...")
        block_sheets.append((block_num, comment, ws))

    return sorted(block_sheets, key=lambda x: x[0])

# --------------------------------------------------------------------------------
# 3) DB helpers: upsert and insert
# --------------------------------------------------------------------------------
# (upsert_block, upsert_day, upsert_exercise, link_day_exercise, insert_sets unchanged)

def upsert_block(cur, block_num, comment=None, start_date=None, end_date=None):
    name = f"Block {block_num}"
    cur.execute(
        """
        INSERT INTO training_blocks (name, start_date, end_date, notes)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE
          SET start_date = EXCLUDED.start_date,
              end_date   = EXCLUDED.end_date,
              notes      = EXCLUDED.notes
        RETURNING block_id
        """, (name, start_date, end_date, comment)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT block_id FROM training_blocks WHERE name = %s", (name,))
    return cur.fetchone()[0]


def upsert_day(cur, block_id, day_number):
    cur.execute(
        """
        INSERT INTO training_days (block_id, day_number)
        VALUES (%s, %s)
        ON CONFLICT (block_id, day_number) DO NOTHING
        RETURNING day_id
        """, (block_id, day_number)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "SELECT day_id FROM training_days WHERE block_id = %s AND day_number = %s",
        (block_id, day_number)
    )
    return cur.fetchone()[0]


def upsert_exercise(cur, name):
    cur.execute(
        """
        INSERT INTO exercises (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING exercise_id
        """, (name,)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT exercise_id FROM exercises WHERE name = %s", (name,))
    return cur.fetchone()[0]


def link_day_exercise(cur, day_id, exercise_id, order):
    cur.execute(
        """
        INSERT INTO day_exercises (day_id, exercise_id, exercise_order)
        VALUES (%s, %s, %s)
        ON CONFLICT (day_id, exercise_order) DO NOTHING
        RETURNING day_exercise_id
        """, (day_id, exercise_id, order)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "SELECT day_exercise_id FROM day_exercises WHERE day_id = %s AND exercise_order = %s",
        (day_id, order)
    )
    return cur.fetchone()[0]


def insert_sets(cur, day_exercise_id, sets_list):
    """
    Bulk-insert all sets for a given day_exercise_id, skipping any
    (day_exercise_id, set_number) pairs that already exist.
    Returns the number of rows actually inserted.
    """
    if not sets_list:
        return 0

    records = [
        (
            day_exercise_id,
            s['set_number'],
            s.get('prescribed_reps'),
            s.get('prescribed_rpe'),
            s.get('completed_weight'),
            s.get('completed_reps'),
            s.get('completed_rpe'),
        )
        for s in sets_list
    ]

    sql = """
    INSERT INTO exercise_sets
      (day_exercise_id, set_number, prescribed_reps, prescribed_rpe,
       completed_weight, completed_reps, completed_rpe)
    VALUES %s
    ON CONFLICT (day_exercise_id, set_number) DO NOTHING
    """

    execute_values(cur, sql, records)
    # cur.rowcount will be the number of rows inserted (conflicts are ignored)
    return cur.rowcount

# --------------------------------------------------------------------------------
# Main ETL flow: per-block transactions
# --------------------------------------------------------------------------------
def main():
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'db'),
        dbname=os.getenv('DB_NAME', 'mydatabase'),
        user=os.getenv('DB_USER', 'myuser'),
        password=os.getenv('DB_PASSWORD', 'mypassword')
    )
    conn.autocommit = False
    cur = conn.cursor()

    for block_num, comment, ws in get_block_sheets():
        # Pull block‐level metadata once
        df = pd.DataFrame(ws.get_all_values())
        start_date, end_date = find_metadata(df)

        # Grab all the rows for the block in one go
        rows = extract_all_workout_data(ws)
        if not rows:
            print(f"No data found in Block {block_num}, skipping.")
            continue

        # Upsert block header once
        blk_id = upsert_block(cur, block_num, comment, start_date, end_date)
        print(f"Block {block_num}: metadata upserted (ID={blk_id})")

        # OPTIONAL: clear out any old days/sets for this block to avoid duplicates
        cur.execute("""
            DELETE FROM exercise_sets
            WHERE day_exercise_id IN (
            SELECT day_exercise_id FROM day_exercises
                WHERE day_id IN (
                SELECT day_id FROM training_days WHERE block_id = %s
                )
            )""", (blk_id,))
        cur.execute("DELETE FROM day_exercises WHERE day_id IN (SELECT day_id FROM training_days WHERE block_id = %s)", (blk_id,))
        cur.execute("DELETE FROM training_days WHERE block_id = %s", (blk_id,))

        # Group rows by week_day
        from collections import defaultdict
        days = defaultdict(list)
        for r in rows:
            days[r['week_day']].append(r)

        # Process each day as its own transaction
        for week_day, day_rows in days.items():
            try:
                # Start a sub‐transaction
                logging.info(f"  → Processing {week_day}")
                # Upsert the day
                day_num = int(re.search(r'D(\d+)', week_day).group(1))
                day_id = upsert_day(cur, blk_id, day_num)

                # Track exercise order per day
                exercise_order = {}
                for r in day_rows:
                    ex = r['exercise']
                    if ex not in exercise_order:
                        exercise_order[ex] = len(exercise_order) + 1
                    order = exercise_order[ex]

                    ex_id = upsert_exercise(cur, ex)
                    de_id = link_day_exercise(cur, day_id, ex_id, order)

                    # Insert all sets for this exercise
                    for s in r.get('sets', [r]):
                        # if your row dict already has metrics, wrap them in a list named 'sets'
                        insert_sets(cur, de_id, [dict(
                            set_number    = s['set_number'],
                            prescribed_reps   = parse_numeric_cell(s['prescribed_reps']),
                            prescribed_rpe    = parse_numeric_cell(s['prescribed_rpe']),
                            completed_weight  = parse_numeric_cell(s['completed_weight']),
                            completed_reps    = parse_numeric_cell(s['completed_reps']),
                            completed_rpe     = parse_numeric_cell(s['completed_rpe']),
                        )])
                conn.commit()
                print(f"  ✔ {week_day} committed")
            except Exception as e:
                conn.rollback()
                logging.error(f"  ✖ {week_day} failed: {e}")
                print(f"  ✖ {week_day} failed: {e}")

    cur.close()
    conn.close()

    logging.info("=== ETL run complete ===")
    print("ETL run complete.")

if __name__ == '__main__':
    main()
