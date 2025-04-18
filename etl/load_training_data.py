#!/usr/bin/env python3
import os
import re
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
try:
    import gspread
except ImportError:
    sys.exit("ERROR: gspread library not found. Please install: pip install gspread oauth2client")

# Regex to identify block worksheets: numbers and optional comment
BLOCK_SHEET_REGEX = re.compile(r'^(?:B|Block)\s*(\d+)(?:\s*[-–]\s*(.+)|\s*\(([^)]+)\))?$', re.IGNORECASE)

# --------------------------------------------------------------------------------
# 1) Find metadata: Start Date and End Date
# --------------------------------------------------------------------------------
def find_metadata(df):
    """
    Scan the DataFrame for Start Date and End Date metadata rows.
    Returns None if not found or blank.
    """
    start_date = None
    end_date = None
    for _, row in df.iterrows():
        for cell in row:
            if isinstance(cell, str):
                if cell.startswith('Start Date:'):
                    val = cell.split(':', 1)[1].strip()
                    start_date = val or None
                elif cell.startswith('End Date:'):
                    val = cell.split(':', 1)[1].strip()
                    end_date = val or None
        if start_date or end_date:
            break
    return start_date, end_date

# --------------------------------------------------------------------------------
# 2) Load worksheets matching training blocks from Google Sheets
# --------------------------------------------------------------------------------
def get_block_sheets():
    creds_path = os.getenv('GOOGLE_CREDS')
    sheet_id = os.getenv('SHEET_ID') or open(os.getenv('SHEET_ID_FILE')).read().strip()
    if not creds_path or not sheet_id:
        sys.exit("ERROR: Set GOOGLE_CREDS and SHEET_ID(_FILE) environment variables.")
    client = gspread.service_account(filename=creds_path)
    spreadsheet = client.open_by_key(sheet_id)
    block_sheets = []
    for ws in spreadsheet.worksheets():
        title = ws.title.strip()
        m = BLOCK_SHEET_REGEX.match(title)
        if m:
            block_num = int(m.group(1))
            comment = m.group(2) or m.group(3) or None
            if comment:
                comment = comment.strip()
            block_sheets.append((block_num, comment, ws))
    return sorted(block_sheets, key=lambda x: x[0])

# --------------------------------------------------------------------------------
# 3) Extract training rows from a sheet DataFrame
# --------------------------------------------------------------------------------
def extract_training_data(df):
    day_pattern = re.compile(r'^Day\s*(\d+)', re.IGNORECASE)
    items = []
    i = 0
    while i < len(df):
        row = df.iloc[i].astype(str)
        day_num = None
        for cell in row:
            m = day_pattern.match(cell)
            if m:
                day_num = int(m.group(1))
                break
        if not day_num:
            i += 1
            continue
        header1 = df.iloc[i+1]
        header2 = df.iloc[i+2]
        metric_cols = []
        for col in header1.index:
            name = str(header1[col]).strip()
            setno = str(header2[col]).strip()
            if setno.isdigit() and name in ['Reps', 'RPE', 'Weight']:
                metric_cols.append((col, name.lower(), int(setno)))
        j = i + 3
        order = 1
        while j < len(df):
            if df.iloc[j].isna().all():
                break
            if any(day_pattern.match(str(x)) for x in df.iloc[j].astype(str)):
                break
            ex_col = None
            try:
                ex_col = header1[header1 == 'Exercise'].index[0]
            except:
                pass
            if ex_col is not None and pd.notna(df.iat[j, ex_col]):
                ex_name = str(df.iat[j, ex_col]).strip()
                sets = {}
                for col, metric, s_no in metric_cols:
                    val = df.iat[j, col]
                    if pd.notna(val) and val != '':
                        v = float(val)
                        if metric == 'reps':
                            sets.setdefault(s_no, {})['prescribed_reps'] = int(v)
                        elif metric == 'rpe':
                            sets.setdefault(s_no, {})['prescribed_rpe'] = v
                        elif metric == 'weight':
                            sets.setdefault(s_no, {})['completed_weight'] = v
                sets_list = []
                for s_no in sorted(sets.keys()):
                    s = sets[s_no]
                    s['set_number'] = s_no
                    s.setdefault('completed_reps', s.get('prescribed_reps'))
                    s.setdefault('completed_rpe', s.get('prescribed_rpe'))
                    sets_list.append(s)
                items.append({
                    'day': day_num,
                    'exercise': ex_name,
                    'sets': sets_list,
                    'order': order
                })
                order += 1
            j += 1
        i = j
    return items

# --------------------------------------------------------------------------------
# 4) DB helpers: upsert and insert
# --------------------------------------------------------------------------------
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
    for s in sets_list:
        cur.execute(
            """
            INSERT INTO exercise_sets
              (day_exercise_id, set_number, prescribed_reps, prescribed_rpe,
               completed_weight, completed_reps, completed_rpe)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                day_exercise_id,
                s['set_number'],
                s.get('prescribed_reps'),
                s.get('prescribed_rpe'),
                s.get('completed_weight'),
                s.get('completed_reps'),
                s.get('completed_rpe')
            )
        )

if __name__ == '__main__':
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'db'),
        dbname=os.getenv('DB_NAME', 'mydatabase'),
        user=os.getenv('DB_USER', 'myuser'),
        password=os.getenv('DB_PASSWORD', 'mypassword')
    )
    conn.autocommit = False
    cur = conn.cursor()

    for block_num, comment, ws in get_block_sheets():
        df = pd.DataFrame(ws.get_all_values())
        start_date, end_date = find_metadata(df)
        items = extract_training_data(df)
        blk_id = upsert_block(cur, block_num, comment, start_date, end_date)
        for item in items:
            day_id = upsert_day(cur, blk_id, item['day'])
            ex_id = upsert_exercise(cur, item['exercise'])
            de_id = link_day_exercise(cur, day_id, ex_id, item['order'])
            insert_sets(cur, de_id, item['sets'])

    conn.commit()
    cur.close()
    conn.close()
    print("Import complete")
