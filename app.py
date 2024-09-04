import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
import json
import streamlit.components.v1 as components
import holidays, io
from ortools.sat.python import cp_model
import sqlite3
from flask import Flask, request, jsonify
import chardet
from threading import Thread
from opt_clean_schedule import solve_cleaning_schedule
from collections import defaultdict
from datetime import datetime
import atexit

# Streamlit 페이지 설정을 wide 모드로 변경
st.set_page_config(layout="wide")

local_host_ip = "127.0.0.1"
# 한국의 공휴일 정보를 가져옵니다.
kr_holidays = holidays.KR()


def is_workday(date):
    return date.weekday() < 6 and date not in kr_holidays


from copy import deepcopy


def generate_schedule(start_date, end_date, workers):
    schedule = {}
    temp_current_date = deepcopy(start_date)
    while temp_current_date <= end_date:
        if is_workday(temp_current_date):
            schedule[temp_current_date] = workers.copy()
        temp_current_date += timedelta(days=1)
    return schedule


def parse_csv_vacations(csv_contents):
    vacations = {}
    df = pd.read_csv(io.StringIO(csv_contents.decode("utf-8")))
    for _, row in df.iterrows():
        date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
        worker = row["Worker"]
        if date not in vacations:
            vacations[date] = []
        vacations[date].append(worker)
    return vacations


def create_interactive_calendar_html(year, month, schedule, vacations, workers):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    html = f"""
    <div class="calendar" id="calendar-{year}-{month}">
        <h2>{month_name} {year}</h2>
        <table>
            <tr><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr>
    """

    for week in cal:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td></td>"
            else:
                date = datetime(year, month, day).date()
                date_str = date.strftime("%Y-%m-%d")
                if date in schedule:
                    zone_a = schedule[date]["zone_A"]
                    zone_b = schedule[date]["zone_B"]
                    vacation_workers = vacations.get(date, [])
                    html += f"""
                    <td class="day" data-date="{date_str}">
                        <div class="date">{day}</div>
                        <div class="zone-a">A: {zone_a}</div>
                        <div class="zone-b">B: {zone_b}</div>
                    </td>
                    """
                else:
                    html += f"<td class='day' data-date='{date_str}'><div class='date'>{day}</div></td>"
        html += "</tr>"

    html += """
        </table>
    </div>
    """

    return html


def create_vacation_calendar_html(year, month, worker, vacations):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    html = f"""
    <div class="calendar" id="calendar-{worker}-{year}-{month}">
        <h3>{worker} - {month_name} {year}</h3>
        <table>
            <tr><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr>
    """

    for week in cal:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td></td>"
            else:
                date = datetime(year, month, day).date()
                date_str = date.strftime("%Y-%m-%d")
                is_vacation = worker in vacations.get(date, [])
                html += f"""
                <td class="day {'vacation' if is_vacation else ''}" data-date="{date_str}" data-worker="{worker}">
                    <div class="date">{day}</div>
                </td>
                """
        html += "</tr>"

    html += """
        </table>
    </div>
    """

    return html


# Database file
DB_FILE = st.secrets["database"]["file_path"]
TABLE_NAME = st.secrets["database"]["table_name"]


# Initialize the SQLite database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            worker TEXT NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()


def save_vacation_data(date, worker):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    print("save...", date, worker)
    # Check if the record already exists
    query = f"SELECT * FROM {TABLE_NAME} WHERE date = ? AND worker = ?"
    c.execute(query, (date, worker))

    existing_record = c.fetchone()  # Fetch one matching record, if any

    # Only insert if no matching record is found
    if existing_record is None:
        query = f"INSERT INTO {TABLE_NAME} (date, worker) VALUES (?, ?)"
        c.execute(query, (date, worker))
        conn.commit()
    else:
        print("exist...", existing_record)
    conn.close()


# Remove vacation data from the database
def remove_vacation_data(date, worker):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = f"DELETE FROM {TABLE_NAME} WHERE date = ? AND worker = ?"
    c.execute(query, (date, worker))
    conn.commit()
    conn.close()


# Load all vacation data from the database
def load_vacation_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # c.execute(f"SELECT date, worker FROM {TABLE_NAME}")
    start_of_month = st.session_state["start_of_month"]
    end_of_month = st.session_state["end_of_month"]
    query = f"SELECT date, worker FROM {TABLE_NAME} WHERE date BETWEEN ? AND ?"
    print(start_of_month, end_of_month)
    c.execute(query, (start_of_month, end_of_month))

    result = c.fetchall()
    conn.close()
    vacation_days = {}
    for date, worker in result:
        if date not in vacation_days:
            vacation_days[date] = []
        vacation_days[date].append(worker)

    return vacation_days


# Flask application
app = Flask(__name__)
from flask_cors import CORS

# CORS(app, resources={r"/*": {"origins": [f"http://{local_host_ip}:3000", f"http://{local_host_ip}:8501", "https://zonecleaner.streamlit.app"]}})
# CORS(app, resources={r"/*": {"origins": "*"}})
# CORS(app, resources={r"/*": {"origins": "*"}})
CORS(app, resources={r"/*": {"origins": ["http://127.0.0.1:8501", "http://localhost:8501"]}})

# CORS(app)  # Enable CORS to allow cross-origin requests within the same machine


@app.route("/save-vacation", methods=["POST"])
def save_vacation_route():
    data = request.json
    date = data.get("date")
    worker = data.get("worker")
    action = data.get("action")  # 'add' or 'remove'
    if action == "add":
        save_vacation_data(date, worker)
    elif action == "remove":
        remove_vacation_data(date, worker)
    return jsonify({"status": "success", "message": f"Vacation data updated({action})"}), 200


@app.route("/get-vacation-data", methods=["GET"])
def get_vacation_data_route():
    vacation_data = load_vacation_data()
    print(vacation_data)
    return jsonify(vacation_data), 200


@app.route("/reset-vacation-data", methods=["POST"])
def reset_vacation_data_route():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"DELETE FROM {TABLE_NAME}")
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Vacation data reset"}), 200


import socket


# Function to check if port is in use
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


# Function to run Flask server
def run_flask():
    app.run(host=local_host_ip, port=8000, debug=True, use_reloader=False)


# Helper function to get the first and last day of the month
def get_month_start_end(year, month):
    # First day of the month
    start_of_month = datetime(year, month, 1)

    # Last day of the month
    if month == 12:
        end_of_month = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_of_month = datetime(year, month + 1, 1) - timedelta(days=1)

    return start_of_month, end_of_month


workers = st.secrets["workers"]

# 사이드바에 CSV 파일 업로드 기능 추가


# Initialize session state variables
if "file_uploaded" not in st.session_state:
    st.session_state.file_uploaded = False

if "file_processed" not in st.session_state:
    st.session_state.file_processed = False


# Reset button to allow re-uploading and reprocessing the file
def reset_file_upload():
    st.session_state.file_uploaded = False
    st.session_state.file_processed = False
    st.session_state.file_uploader = None  # Reset the file uploader widget


def read_csv_file(file):
    # Read the file content
    file_content = file.read()

    # Detect the file encoding
    result = chardet.detect(file_content)
    encoding = result["encoding"]

    # Try reading the CSV file with the detected encoding
    try:
        df = pd.read_csv(io.StringIO(file_content.decode(encoding)))
    except UnicodeDecodeError:
        # If the detected encoding fails, try with utf-8
        try:
            df = pd.read_csv(io.StringIO(file_content.decode("utf-8")))
        except UnicodeDecodeError:
            # If utf-8 fails, fall back to cp949
            df = pd.read_csv(io.StringIO(file_content.decode("cp949")))

    return df


def check_vacation_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"SELECT * FROM {TABLE_NAME}")
    rows = c.fetchall()
    conn.close()
    st.sidebar.write(rows)


if "previous_vacation_days" not in st.session_state:
    st.session_state.previous_vacation_days = {}

import time


def check_vacation_data_updates():
    check_container = st.empty()
    while True:
        current_vacation_data = load_vacation_data()
        if "previous_vacation_days" not in st.session_state:
            st.session_state.previous_vacation_days = {}

        if current_vacation_data != st.session_state.previous_vacation_days:
            print("Vacation data updated:", current_vacation_data)
            st.session_state.previous_vacation_days = current_vacation_data.copy()
            st.rerun()
        else:
            # print("... np update", current_vacation_data , st.session_state.previous_vacation_days)
            pass
        # 현재 시간 표시 (옵션)
        check_container.text(f"Last checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(1)


def remove_all_vacation_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # This will delete all rows from the vacation_days table
    c.execute(f"DELETE FROM {TABLE_NAME}")
    conn.commit()
    conn.close()


def create_vacation_calendar_html(year, month, worker, vacations):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    html = f"""
    <div class="calendar" id="calendar-{worker}-{year}-{month}">
        <h3>{worker} - {month_name} {year}</h3>
        <table>
            <tr><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th></tr>
    """

    for week in cal:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td></td>"
            else:
                date = datetime(year, month, day).date()
                date_str = date.strftime("%Y-%m-%d")
                is_vacation = worker in vacations.get(date, [])
                html += f"""
                <td class="day {'vacation' if is_vacation else ''}" data-date="{date_str}" data-worker="{worker}">
                    <div class="date">{day}</div>
                </td>
                """
        html += "</tr>"

    html += """
        </table>
    </div>
    """

    return html


def sidebar():

    if st.sidebar.toggle("휴가 일정 업로드"):
        uploaded_file = st.sidebar.file_uploader("CSV 파일 업로드", type="csv")
        if uploaded_file is not None and not st.session_state.file_processed:
            try:
                # Read and process the CSV file
                df = read_csv_file(uploaded_file)

                # Validate the CSV format (should have 'Date' and 'Worker' columns)
                if set(df.columns) != {"Date", "Worker"}:
                    raise ValueError("CSV 파일은 'Date'와 'Worker' 열을 포함해야 합니다.")

                # Extract vacation data from each row and save
                for _, row in df.iterrows():
                    date = row["Date"]
                    worker = row["Worker"]
                    save_vacation_data(date, worker)

                # Update session state after successful upload and processing
                st.session_state.file_uploaded = True
                st.session_state.file_processed = True

                # Success message
                st.sidebar.success("휴가 일정이 성공적으로 업로드되었습니다.")

            except Exception as e:
                # Error handling
                st.sidebar.error(f"파일 처리 중 오류가 발생했습니다: {e}")

        # Show an info message and reset option if the file has been processed
        if st.session_state.file_processed:
            st.sidebar.info("파일 업로드 및 처리가 완료되었습니다.")
            st.sidebar.button("다시 업로드", on_click=reset_file_upload)
    height = st.sidebar.number_input("캘린더 높이", min_value=0, max_value=2000, value=400)
    st.session_state.calendar_height = height

    st.sidebar.subheader("현재 휴가 일정")

    # 이전 상태와 비교
    # if 'previous_vacation_days' not in st.session_state:
    #     st.session_state.previous_vacation_days = {}
    # 휴가 일정 표시
    vacation_data = load_vacation_data()

    # 날짜를 기준으로 정렬
    # sorted_dates = sorted(vacation_data.keys(), key=lambda x: datetime.strptime(x, '%Y-%m-%d'))

    # for date in sorted_dates:
    #     workers_on_vacation = vacation_data[date]

    #     st.sidebar.write(f"{date}: {', '.join(workers_on_vacation)}")

    # 근로자별 휴가 정보 정리
    worker_vacations = defaultdict(list)
    for date, _workers in vacation_data.items():
        for worker in _workers:
            worker_vacations[worker].append(date)

    # 근로자 목록 (알파벳 순으로 정렬)
    sorted_workers = sorted(worker_vacations.keys())
    # Add vacation functionality
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    for worker in sorted_workers:
        sorted_dates = sorted(worker_vacations[worker], key=lambda x: datetime.strptime(x, "%Y-%m-%d"))
        with st.sidebar.expander(f"{worker}의 휴가 ({len(sorted_dates)}일)", expanded=False):
            if worker_vacations[worker]:
                for date in sorted_dates:
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        day_of_week = weekdays[datetime.strptime(date, "%Y-%m-%d").weekday()]
                        st.write(f"• {date} ({day_of_week})")
                    with col2:
                        if st.button("삭제", key=f"delete_{worker}_{date}"):
                            remove_vacation_data(date, worker)
                            st.rerun()
            else:
                st.write("예정된 휴가 없음")

    if st.sidebar.button("RERUN"):
        st.rerun()

    if st.sidebar.button("휴가일정 전부 삭제"):
        remove_all_vacation_data()
        st.rerun()

    if st.sidebar.button("show"):
        check_vacation_data()


def create_app():

    # Get the current date
    today = datetime.today()
    current_year = today.year
    current_month = today.month
    if is_port_in_use(8000):
        print("Port 8000 is already in use")
    else:
        # Start Flask server in a new thread
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()

    # Streamlit app starts here
    st.title("청소 스케줄 최적화")

    # User selects the year and month
    col1, col2 = st.columns(2)

    with col1:
        selected_year = st.number_input("년도 선택", min_value=2000, max_value=2100, value=current_year)

    with col2:
        selected_month = st.selectbox("월 선택", list(range(1, 13)), index=current_month - 1)

    start_of_month, end_of_month = get_month_start_end(selected_year, selected_month)

    # Create two columns for the date inputs
    col1, col2 = st.columns(2)

    with col1:
        start_date = st.date_input("시작 날짜", start_of_month)

    with col2:
        end_date = st.date_input("종료 날짜", end_of_month)
    st.session_state["start_of_month"] = start_date.strftime("%Y-%m-%d")
    st.session_state["end_of_month"] = end_date.strftime("%Y-%m-%d")
    sidebar()

    # 휴가 캘린더 HTML 생성
    start_month = start_date
    end_month = end_date
    vacation_calendars_html = "<div class='calendar-container'>"
    current_month = start_month
    init_vacation_data = load_vacation_data()
    init_vacation_data_dict = {
        datetime.strptime(date, "%Y-%m-%d").date(): workers for date, workers in init_vacation_data.items()
    }
    while current_month <= end_month:
        vacation_calendars_html += "<div class='month-row'>"
        for worker in workers:
            vacation_calendars_html += create_vacation_calendar_html(
                current_month.year, current_month.month, worker, init_vacation_data_dict
            )
        vacation_calendars_html += "</div>"
        current_month += timedelta(days=32)
        current_month = current_month.replace(day=1)
    vacation_calendars_html += "</div>"
    # CSS와 JavaScript를 포함한 HTML 렌더링
    components.html(
        f"""
    <style>
        .calendar-container {{
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            max-height: 80vh;
        }}
        .month-row {{
            display: flex;
            flex-wrap: nowrap;
            overflow-x: auto;
        }}
        .calendar {{
            font-family: Arial, sans-serif;
            margin: 0 10px 20px 0;
            flex: 0 0 auto;
        }}
        .calendar table {{
            border-collapse: collapse;
        }}
        .calendar th, .calendar td {{
            border: 1px solid #ddd;
            padding: 5px;
            text-align: center;
        }}
        .calendar .date {{
            font-weight: bold;
        }}
        .calendar .vacation {{
            background-color: #ffcccb;
        }}
        .calendar .day {{
            cursor: pointer;
        }}
        #update-button {{
            margin-top: 10px;
            padding: 5px 10px;
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
        }}
        #reset-button {{
            margin-top: 10px;
            margin-left: 10px;
            padding: 5px 10px;
            background-color: #f44336;
            color: white;
            border: none;
            cursor: pointer;
        }}
    </style>
    <div id="calendar-root">{vacation_calendars_html}</div>
    <button id="update-button">휴가 일정 업데이트</button>
    <button id="reset-button">DB 초기화</button>
    <script>
        let vacationData = {{}};
        
        function toggleVacation(element) {{
            const date = element.dataset.date;
            const worker = element.dataset.worker;
            const action = element.classList.contains('vacation') ? 'remove' : 'add';
            
            fetch('http://127.0.0.1:8000/save-vacation', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ date: date, worker: worker, action: action }}),
                credentials: 'omit'
            }})
            .then(response => response.json())
            .then(data => {{
                console.log("---")
                console.log('toggle update Success:', data);
                console.log("---")
                element.classList.toggle('vacation');
            }})
            .catch((error) => console.error('Error:', error));
        }}
        
        function initializeCalendars() {{
            document.querySelectorAll('.day').forEach(day => {{
                day.addEventListener('click', function() {{
                    toggleVacation(this);
                }});
            }});
        }}
        
        function adjustHeight() {{
            const container = document.querySelector('.calendar-container');
            if (container) {{
                const actualHeight = container.scrollHeight;
                window.parent.postMessage({{
                    type: "streamlit:setFrameHeight",
                    height: actualHeight + 50
                }}, "*");
            }}
        }}
        
        function updateVacationData() {{
            fetch('http://127.0.0.1:8000/get-vacation-data')
            .then(response => response.json())
            .then(data => {{
                vacationData = data;
                console.log("api-get-vacation-data")
                console.log("Vacation data updated:", vacationData);
                // 여기에 캘린더 UI 업데이트 로직 추가
            }})
            .catch((error) => console.error('Error:', error));
        }}
        
        function resetVacationData() {{
            if (confirm('정말로 모든 휴가 데이터를 초기화하시겠습니까?')) {{
                fetch('http://127.0.0.1:8000/reset-vacation-data', {{
                    method: 'POST',
                }})
                .then(response => response.json())
                .then(data => {{
                    console.log('Reset success:', data);
                    updateVacationData();  // 데이터 초기화 후 UI 업데이트
                    alert('휴가 데이터가 초기화되었습니다.');
                }})
                .catch((error) => {{
                    console.error('Error:', error);
                    alert('데이터 초기화 중 오류가 발생했습니다.');
                }});
            }}
        }}
        function adjustIframeHeight() {{
            const calendarContainer = document.querySelector('.calendar-container');
            if (calendarContainer) {{
                const actualHeight = calendarContainer.scrollHeight;
                // Send the height back to Streamlit using postMessage
                window.parent.postMessage({{
                    type: "streamlit:setFrameHeight",
                    height: actualHeight + 50  // Add padding to avoid cutting content
                }}, "*");
            }}
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            adjustIframeHeight();
        }});
        function init() {{
            initializeCalendars();
            adjustHeight();
            adjustIframeSize();
            updateVacationData();
            
            const updateButton = document.getElementById('update-button');
            if (updateButton) {{
                updateButton.addEventListener('click', updateVacationData);
            }}
            
            const resetButton = document.getElementById('reset-button');
            if (resetButton) {{
                resetButton.addEventListener('click', resetVacationData);
            }}
            
            // MutationObserver 설정
            const observer = new MutationObserver(() => {{
                adjustHeight();
                adjustIframeHeight();
                window.parent.postMessage({{
                    type: "streamlit:componentReady",
                    value: true
                }}, "*");
            }});
            
            const calendarRoot = document.getElementById('calendar-root');
            if (calendarRoot) {{
                observer.observe(calendarRoot, {{ childList: true, subtree: true }});
                observer.observe(document.body, {{ childList: true, subtree: true }});
            }}
            // 페이지 로드 후 초기 크기 조정
            
            
        }}
        
        // DOMContentLoaded 이벤트를 사용하여 페이지 로드 완료 후 초기화
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', init);
        }} else {{
            init();
        }}
        
    </script>
    """,
        height=st.session_state.calendar_height,
    )

    # if st.button('Vacation Data 출력'):
    #     st.rerun()
    # st.write("Vacation Data:", vacation_data)
    vacation_data = load_vacation_data()

    # 스케줄 최적화 버튼
    if st.button("스케줄 최적화"):
        # 스케줄 생성
        schedule = generate_schedule(start_date, end_date, workers)
        # 최적화 실행
        try:
            output_schedule = solve_cleaning_schedule(schedule, workers, vacation_data)
        except Exception as e:
            st.error(f"스케줄 생성 실패... 휴가일 조정이 필요해보입니다... {e}")

        if output_schedule is None:
            st.error("스케줄 생성 실패... 휴가일 조정이 필요해보입니다...")
        if output_schedule:
            st.success("스케줄 생성 성공!")
            # 결과를 DataFrame으로 변환
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
            df = pd.DataFrame(results)

            # 결과 표시
            with st.expander("최적화된 청소 스케줄"):
                st.dataframe(df, height=400, use_container_width=True)  # DataFrame 크기 조정
                # CSV 다운로드 버튼
                csv = df.to_csv(index=False)
                st.download_button(
                    label="CSV 다운로드",
                    data=csv,
                    file_name="cleaning_schedule.csv",
                    mime="text/csv",
                )

            # 청소 횟수 통계 표시
            with st.expander("청소 횟수 통계"):

                stats = {}
                for worker in workers:
                    stats[worker] = {
                        "1구역(A) 총 횟수": df["1구역(A)"].str.contains(worker).sum(),
                        "2구역(B) 총 횟수": df["2구역(B)"].str.contains(worker).sum(),
                        "2구역(B) 혼자": df[df["2구역(B)"].str.split(", ").str.len() == 1]["2구역(B)"]
                        .str.contains(worker)
                        .sum(),
                        "2구역(B) 2명 이상": df[df["2구역(B)"].str.split(", ").str.len() > 1]["2구역(B)"]
                        .str.contains(worker)
                        .sum(),
                    }

                stats_df = pd.DataFrame(stats).T
                st.dataframe(stats_df, height=300, use_container_width=True)  # 통계 DataFrame 크기 조정

            # 달력 표시
            st.header("달력 형식의 청소 스케줄")

            # 시작 월과 종료 월 계산

            current_month = start_month
            while current_month <= end_month:
                calendar_html = create_interactive_calendar_html(
                    current_month.year, current_month.month, output_schedule, vacation_data, workers
                )

                # CSS, JavaScript, 그리고 달력 HTML을 함께 렌더링
                components.html(
                    f"""
                <style>
                    .calendar {{
                        font-family: Arial, sans-serif;
                        max-width: 800px;
                        margin: 0 auto;
                    }}
                    .calendar table {{
                        width: 100%;
                        border-collapse: collapse;
                    }}
                    .calendar th, .calendar td {{
                        border: 1px solid #ddd;
                        padding: 5px;
                        text-align: center;
                    }}
                    .calendar .date {{
                        font-weight: bold;
                    }}
                    .calendar .zone-a {{
                        color: #4CAF50;
                    }}
                    .calendar .zone-b {{
                        color: #2196F3;
                    }}
                    .calendar .vacation-select {{
                        font-size: 0.8em;
                    }}
                    .calendar .vacation-select label {{
                        display: block;
                    }}
                </style>
                <script>
                    let vacationData = {json.dumps(vacation_data)};
                    
                    function updateVacation(date, worker, isChecked) {{
                        if (!vacationData[date]) {{
                            vacationData[date] = [];
                        }}
                        if (isChecked) {{
                            if (!vacationData[date].includes(worker)) {{
                                vacationData[date].push(worker);
                            }}
                        }} else {{
                            vacationData[date] = vacationData[date].filter(w => w !== worker);
                        }}
                        
                        // Streamlit에 데이터 전송
                        window.parent.postMessage({{
                            type: "streamlit:setComponentValue",
                            value: JSON.stringify({{
                                vacation_days: vacationData
                            }})
                        }}, "*");
                    }}
                    
                    function initializeCheckboxes() {{
                        document.querySelectorAll('.vacation-select input[type="checkbox"]').forEach(checkbox => {{
                            checkbox.addEventListener('change', (e) => {{
                                const date = e.target.closest('.day').dataset.date;
                                const worker = e.target.value;
                                updateVacation(date, worker, e.target.checked);
                            }});
                        }});
                    }}
                    
                    // DOMContentLoaded 이벤트를 사용하여 페이지 로드 완료 후 초기화
                    document.addEventListener('DOMContentLoaded', initializeCheckboxes);
                    
                    // 변경사항이 있을 때마다 Streamlit에 알림
                    new MutationObserver(() => {{
                        window.parent.postMessage({{
                            type: "streamlit:componentReady",
                            value: true
                        }}, "*");
                    }}).observe(document.body, {{subtree: true, childList: true}});
                </script>
                {calendar_html}
                """,
                    height=600,
                )

                current_month += timedelta(days=32)
                current_month = current_month.replace(day=1)

    check_vacation_data_updates()


if __name__ == "__main__":
    # Initialize session state for password check
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False  # Set default to False

    if not st.session_state.authenticated:
        # Show the password input field if not authenticated
        password = st.text_input("Enter Key", type="password")
        st.markdown(
            """
            <div style="text-align: center;">
                <img src="https://github.com/sungreong/ZoneCleaner/blob/f9a51ca21a61604dfcf844efa6182dbed93d8350/imgs/uandi.jpg" alt="image" style="width: 90%; max-width: 800px;">
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Check if the entered password matches the stored secret
        if password == st.secrets["password"]["enter_key"]:
            st.session_state.authenticated = True  # Set authenticated to True
            st.success("키를 입력하셨습니다.")
            init_db()  # Initialize the database
            create_app()  # Run the main app
        else:
            if password:  # Only show the error if a password was entered
                st.error("잘못된 키를 입력하셨습니다.")
    else:
        # If already authenticated, just run the app without showing the password input
        init_db()
        create_app()

    # Cleanup function
    def cleanup():
        print("Cleaning up...")

        # Add any cleanup code here (e.g., closing database connections)

    # Register the cleanup function
    atexit.register(cleanup)
