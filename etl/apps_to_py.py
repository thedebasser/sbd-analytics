# -*- coding: utf-8 -*-
"""
Standalone module to mirror the Apps Script `extractWorkoutData` logic in Python.
Provides `extract_all_workout_data(ws)` which scans a worksheet for all W#D# anchors
and returns a list of dicts representing each set entry.
"""
import re
from typing import List, Dict

# Regex to identify week-day anchors like 'W7D1', case-insensitive
week_day_regex = re.compile(r'^W\d+D\d+$', re.IGNORECASE)

# Fixed column offsets relative to the "Exercise" column
OFFSETS = {
    'prescribed_reps': 3,
    'prescribed_rpe': 6,
    'completed_weight': 10,
    'completed_reps': 11,
    'completed_rpe': 12,
}


def extract_all_workout_data(ws) -> List[Dict]:
    """
    Extracts all workout data from a Google Sheets worksheet `ws`,
    mirroring the Apps Script for each week-day anchor.

    Returns:
        A list of dicts with keys:
        - 'week_day', 'exercise', 'set_number',
        - 'prescribed_reps', 'prescribed_rpe',
        - 'completed_weight', 'completed_reps', 'completed_rpe',
        - 'notes'
    """
    # 1) Fetch merge metadata
    metadata = ws.spreadsheet.fetch_sheet_metadata()
    sheet_meta = next(s for s in metadata['sheets']
                      if s['properties']['sheetId'] == ws.id)
    merges = sheet_meta.get('merges', [])
    merge_ranges = []
    for m in merges:
        merge_ranges.append({
            'row': m['startRowIndex'] + 1,
            'col': m['startColumnIndex'] + 1,
            'num_rows': m['endRowIndex'] - m['startRowIndex'],
            'num_cols': m['endColumnIndex'] - m['startColumnIndex'],
        })

    # 2) Fetch all cell values
    values = ws.get_all_values()
    results: List[Dict] = []

    # 3) Find each W#D# anchor
    for i, row in enumerate(values):
        for j, cell in enumerate(row):
            if week_day_regex.fullmatch(cell.strip()):
                week_day = cell.strip()
                # find merge covering anchor
                anchor = next((mr for mr in merge_ranges
                               if mr['row'] <= i+1 <= mr['row'] + mr['num_rows'] - 1
                               and mr['col'] <= j+1 <= mr['col'] + mr['num_cols'] - 1), None)
                if anchor:
                    sr = anchor['row']
                    sc = anchor['col']
                    height = anchor['num_rows']
                else:
                    sr = i+1
                    sc = j+1
                    height = 1

                # 4) Locate "Exercise" header
                ex_col = None
                for mr in merge_ranges:
                    top = mr['row']
                    bot = top + mr['num_rows'] - 1
                    if top <= sr <= bot and mr['col'] > sc:
                        if values[top-1][mr['col']-1].strip() == 'Exercise':
                            ex_col = mr['col']
                            break
                if ex_col is None:
                    for c in range(sc, len(values[0])):
                        if values[sr-1][c].strip() == 'Exercise':
                            ex_col = c + 1
                            break
                if ex_col is None:
                    raise ValueError(f"Could not find 'Exercise' for {week_day}")

                # 5) Locate "Notes" header
                notes_col = None
                for mr in merge_ranges:
                    r_idx = mr['row'] - 1
                    c_idx = mr['col'] - 1
                    if mr['col'] > sc and r_idx < len(values) and c_idx < len(values[r_idx]):
                        if values[r_idx][c_idx].strip() == 'Notes':
                            notes_col = mr['col']
                            break
                if notes_col is None:
                    for c in range(len(values[0]) - 1, sc - 1, -1):
                        if c < len(values[sr-1]) and values[sr-1][c].strip() == 'Notes':
                            notes_col = c + 1
                            break
                if notes_col is None:
                    raise ValueError(f"Could not find 'Notes' for {week_day}")

                # 6) Prep data rows (skip two header lines) (skip two header lines)
                data_rows = []
                start_idx = sr - 1 + 2
                end_idx = sr - 1 + height
                for r in range(start_idx, end_idx):
                    if r < len(values):
                        data_rows.append(values[r])

                # 7) Build spans to backfill exercise names
                spans = []
                for mr in merge_ranges:
                    if mr['col'] == ex_col and mr['row'] <= sr + height - 1 and (mr['row'] + mr['num_rows'] - 1) >= sr + 2:
                        row_idx = mr['row'] - 1
                        col_idx = ex_col - 1
                        # guard against out-of-bounds
                        if row_idx < len(values) and col_idx < len(values[row_idx]):
                            name = values[row_idx][col_idx].strip()
                        else:
                            name = ''
                        if name:
                            spans.append({'name': name, 'from': mr['row'], 'to': mr['row'] + mr['num_rows'] - 1})

                # 8) Extract sets) Extract sets
                prev_ex = None
                counter = 1
                for idx, row_vals in enumerate(data_rows):
                    abs_row = sr + 2 + idx
                    ex = row_vals[ex_col-1].strip()
                    if not ex:
                        for span in spans:
                            if span['from'] <= abs_row <= span['to']:
                                ex = span['name']
                                break
                    # collect metrics
                    metrics = {}
                    for key, offset in OFFSETS.items():
                        col_idx = ex_col - 1 + offset
                        metrics[key] = row_vals[col_idx] if col_idx < len(row_vals) else ''
                    notes = row_vals[notes_col-1] if notes_col-1 < len(row_vals) else ''
                    # skip blank rows
                    if not any(str(v).strip() for v in list(metrics.values()) + [notes]):
                        continue
                    # reset counter on new exercise
                    if ex != prev_ex:
                        counter = 1
                        prev_ex = ex
                    results.append({
                        'week_day': week_day,
                        'exercise': ex,
                        'set_number': counter,
                        **metrics,
                        'notes': notes
                    })
                    counter += 1

    return results
