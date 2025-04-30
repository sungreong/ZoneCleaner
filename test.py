import sys, os
import sqlite3

sys.path.append(os.path.dirname(os.getcwd()))
# from app import load_vacation_data

from app import generate_schedule

DB_FILE = "vacation_data.db"
TABLE_NAME = "vacation_days"
session_state = {}
session_state["start_of_month"] = "2024-09-30"
session_state["end_of_month"] = "2024-11-02"


# Load all vacation data from the database
def load_vacation_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # c.execute(f"SELECT date, worker FROM {TABLE_NAME}")
    start_of_month = session_state["start_of_month"]
    end_of_month = session_state["end_of_month"]
    query = f"SELECT date, worker FROM {TABLE_NAME} WHERE date BETWEEN ? AND ?"

    c.execute(query, (start_of_month, end_of_month))

    result = c.fetchall()
    conn.close()
    vacation_days = {}
    for date, worker in result:
        if date not in vacation_days:
            vacation_days[date] = []
        vacation_days[date].append(worker)

    return vacation_days


vacation_data = load_vacation_data()
from datetime import datetime

workers = ["다솔", "다혜", "민지", "혜정", "한울"]
start_date = session_state["start_of_month"]

start_date = datetime.strptime(session_state["start_of_month"], "%Y-%m-%d").date()
end_date = datetime.strptime(session_state["end_of_month"], "%Y-%m-%d").date()

schedule = generate_schedule(start_date, end_date, workers)

from opt_clean_schedule import solve_cleaning_schedule_logic

# from opt_clean_schedule import solve_cleaning_schedule_v2

output_schedule = solve_cleaning_schedule_logic(schedule=schedule, workers=workers, vacation_days=vacation_data)
print(output_schedule)
print(vacation_data)

results = []
for day in sorted(output_schedule.keys()):
    results.append(
        {
            "날짜": day,
            "근무자": output_schedule[day]["workers"],
            "1구역(A)": output_schedule[day]["zone_A"],
            "2구역(B)": output_schedule[day]["zone_B"],
        }
    )
import pandas as pd

df = pd.DataFrame(results)
print(df)

stats = {}
for worker in workers:
    stats[worker] = {
        "1구역(A) 총 횟수": df["1구역(A)"].str.contains(worker).sum(),
        "2구역(B) 총 횟수": df["2구역(B)"].str.contains(worker).sum(),
        "2구역(B) 혼자": df[df["2구역(B)"].str.split(", ").str.len() == 1]["2구역(B)"].str.contains(worker).sum(),
        "2구역(B) 2명 이상": df[df["2구역(B)"].str.split(", ").str.len() > 1]["2구역(B)"].str.contains(worker).sum(),
    }

stats_df = pd.DataFrame(stats).T
print(stats_df)
