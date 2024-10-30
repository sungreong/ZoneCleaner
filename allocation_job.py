import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
import sqlite3
import holidays
import io
from collections import defaultdict

# 한국의 공휴일 정보를 가져옵니다.
kr_holidays = holidays.KR()

TEAM_MEMBERS = ["다솔", "다혜", "민지", "혜정", "한울"]

DB_FILE = "allocation_data.db"
TABLE_NAME = "allocation_days"


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
    # 먼저 해당 날짜와 작업자의 조합이 이미 존재하는지 확인
    c.execute(f"SELECT * FROM {TABLE_NAME} WHERE date = ? AND worker = ?", (date, worker))
    if c.fetchone() is None:
        # 존재하지 않는 경우에만 새로운 데이터 삽입
        c.execute(f"INSERT INTO {TABLE_NAME} (date, worker) VALUES (?, ?)", (date, worker))
        conn.commit()
    conn.close()


def load_vacation_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"SELECT date, worker FROM {TABLE_NAME}")
    result = c.fetchall()
    conn.close()
    vacation_days = {}
    for date, worker in result:
        if date not in vacation_days:
            vacation_days[date] = []
        vacation_days[date].append(worker)
    return vacation_days


def get_kr_holidays(start_date, end_date):
    holiday_list = []
    for date in kr_holidays[start_date:end_date]:
        holiday_list.append((date, kr_holidays.get(date)))
    return holiday_list


def is_workday(date, selected_holidays=[]):
    # 월요일(0)부터 토요일(5)까지를 근무일로 설정
    # 선택된 휴일만 제외하고, 다른 공휴일은 근무일로 처리
    return date.weekday() < 6 and date not in selected_holidays


TASK_TYPES = {"카톡": "chat", "해피콜/리뷰": "happy_call", "마감/어플": "closing"}

# 인원별 업무 할당 규칙
ALLOCATION_RULES = {
    3: {"chat": 1, "happy_call": 1, "closing": 1},
    4: {"chat": 2, "happy_call": 1, "closing": 1},
    5: {"chat": 2, "happy_call": 2, "closing": 1},
}


def solve_environment_team_schedule(start_date, end_date, team_members, vacation_data, selected_holidays):
    num_days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(num_days)]
    workdays = [date for date in dates if is_workday(date, selected_holidays)]

    # 각 멤버별 근무 가능일 계산
    available_days = {member: 0 for member in team_members}
    for date in workdays:
        date_str = date.strftime("%Y-%m-%d")
        for member in team_members:
            if member not in vacation_data.get(date_str, []):
                available_days[member] += 1

    schedule = {date: {"tasks": {}} for date in workdays}
    member_task_counts = {member: {task: 0 for task in TASK_TYPES.values()} for member in team_members}

    # 각 멤버별 목표 업무량 계산
    total_available_days = sum(available_days.values())
    target_ratios = {member: days / total_available_days for member, days in available_days.items()}

    for date in workdays:
        date_str = date.strftime("%Y-%m-%d")
        available_members = [m for m in team_members if m not in vacation_data.get(date_str, [])]
        num_available = len(available_members)

        if num_available < 3:
            continue

        rule = ALLOCATION_RULES.get(min(num_available, 5))
        daily_assignments = {task: [] for task in TASK_TYPES.values()}

        # 업무 타입별 할당 우선순위 계산
        task_priorities = {}
        for task_type in TASK_TYPES.values():
            for member in available_members:
                if member not in task_priorities:
                    task_priorities[member] = {}

                # 업무 타입별 할당 비율
                task_ratio = (
                    member_task_counts[member][task_type] / available_days[member]
                    if available_days[member] > 0
                    else float("inf")
                )
                # 전체 업무 할당 비율
                total_ratio = (
                    sum(member_task_counts[member].values()) / available_days[member]
                    if available_days[member] > 0
                    else float("inf")
                )

                # 우선순위 점수 계산 (낮을수록 높은 우선순위)
                task_priorities[member][task_type] = (
                    task_ratio,  # 해당 업무 할당 비율
                    total_ratio,  # 전체 업무 할당 비율
                    member_task_counts[member][task_type],  # 해당 업무 수행 횟수
                )

        # 각 업무 타입별로 할당
        remaining_members = available_members.copy()
        for task_type, count in rule.items():
            for _ in range(count):
                if not remaining_members:
                    break

                # 현재 업무에 가장 적합한 멤버 선택
                selected_member = min(
                    remaining_members,
                    key=lambda m: (
                        task_priorities[m][task_type][0],  # 해당 업무 할당 비율
                        task_priorities[m][task_type][1],  # 전체 업무 할당 비율
                        task_priorities[m][task_type][2],  # 해당 업무 수행 횟수
                        sum(
                            1 for t in TASK_TYPES.values() if member_task_counts[m][t] == 0
                        ),  # 아직 수행하지 않은 업무 수
                    ),
                )

                remaining_members.remove(selected_member)
                daily_assignments[task_type].append(selected_member)
                member_task_counts[selected_member][task_type] += 1

        schedule[date]["tasks"] = daily_assignments

    return schedule, member_task_counts


def parse_csv_vacations(csv_contents):
    try:
        # UTF-8로 시도
        df = pd.read_csv(io.StringIO(csv_contents.decode("utf-8")))
    except UnicodeDecodeError:
        try:
            # CP949(EUC-KR)로 시도
            df = pd.read_csv(io.StringIO(csv_contents.decode("cp949")))
        except UnicodeDecodeError:
            try:
                # UTF-16으로 시도
                df = pd.read_csv(io.StringIO(csv_contents.decode("utf-16")))
            except UnicodeDecodeError:
                # 마지막으로 ANSI로 시도
                df = pd.read_csv(io.BytesIO(csv_contents), encoding="ansi")

    vacations = {}
    for _, row in df.iterrows():
        date = datetime.strptime(str(row["Date"]), "%Y-%m-%d").date()
        worker = row["Worker"]
        date_str = date.strftime("%Y-%m-%d")
        if date_str not in vacations:
            vacations[date_str] = []
        vacations[date_str].append(worker)
    return vacations


def save_vacation_data_from_csv(vacations):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for date_str, workers in vacations.items():
        for worker in workers:
            # 먼저 해당 날짜와 작업자의 조합이 이미 존재하는지 확인
            c.execute(f"SELECT * FROM {TABLE_NAME} WHERE date = ? AND worker = ?", (date_str, worker))
            if c.fetchone() is None:
                # 존재하지 않는 경우에만 새로운 데이터 삽입
                c.execute(f"INSERT INTO {TABLE_NAME} (date, worker) VALUES (?, ?)", (date_str, worker))
    conn.commit()
    conn.close()


def calculate_work_stats(start_date, end_date, team_members, vacation_data, selected_holidays):
    # 날짜 범위 내의 모든 날짜 생성
    date_range = pd.date_range(start_date, end_date)

    # 근무일 계산 (월~토, 선택된 휴일만 제외)
    workdays = []
    for date in date_range:
        # 일요일이 아니고, 선택된 휴일이 아닌 날만 포함
        if date.weekday() < 6 and date.date() not in selected_holidays:
            workdays.append(date)
    print(workdays)
    # 각 멤버별 근무 가능일 계산
    work_stats = {}
    for member in team_members:
        working_days = []
        for date in workdays:
            date_str = date.strftime("%Y-%m-%d")
            # 해당 날짜에 휴가가 없는 경우만 근무일로 카운트
            if member not in vacation_data.get(date_str, []):
                working_days.append(date)

        total_days = len(working_days)
        # 업무별 목표 할당량 (근무일을 3으로 나누어 분배)
        target_per_task = total_days / 3

        work_stats[member] = {
            "total_working_days": total_days,
            "target_allocations": {
                "chat": round(target_per_task, 1),
                "happy_call": round(target_per_task, 1),
                "closing": round(target_per_task, 1),
            },
        }

    return work_stats


def create_vacation_table(start_date, end_date, vacation_data):
    # 날짜 범위 생성
    date_range = pd.date_range(start_date, end_date)
    date_strings = [date.strftime("%Y-%m-%d") for date in date_range]

    # 빈 데이터프레임 생성
    vacation_table = pd.DataFrame(index=TEAM_MEMBERS, columns=date_strings)
    vacation_table = vacation_table.fillna("")

    # 휴가 데이터 채우기
    for date_str, members in vacation_data.items():
        if date_str in vacation_table.columns:
            for member in members:
                if member in vacation_table.index:
                    vacation_table.at[member, date_str] = "●"

    # 일요일과 공휴일 표시 (휴가가 없는 경우에만)
    for date in date_strings:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        if date_obj.weekday() == 6:  # 일요일
            # 해당 날짜에 휴가가 없는 셀에만 'x' 표시
            for member in TEAM_MEMBERS:
                if vacation_table.at[member, date] != "●":
                    vacation_table.at[member, date] = "x"
        elif date_obj in kr_holidays:  # 공휴일
            # 해당 날짜에 휴가가 없는 셀에만 '⚪' 표시
            for member in TEAM_MEMBERS:
                if vacation_table.at[member, date] != "●":
                    vacation_table.at[member, date] = "⚪"

    # 열 이름을 '일(요일)' 형식으로 변경
    vacation_table.columns = [
        f"{datetime.strptime(date, '%Y-%m-%d').strftime('%d')}({['월','화','수','목','금','토','일'][datetime.strptime(date, '%Y-%m-%d').weekday()]})"
        for date in date_strings
    ]

    return vacation_table


def create_calendar_html(start_date, end_date, schedule, vacation_data, selected_holidays):
    year = start_date.year
    month = start_date.month
    cal = calendar.monthcalendar(year, month)

    html = f"""
    <style>
        .calendar {{
            font-family: Arial, sans-serif;
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 20px;
        }}
        .calendar th, .calendar td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: center;
            vertical-align: top;
        }}
        .calendar th {{
            background-color: #f2f2f2;
        }}
        .calendar .date {{
            font-weight: bold;
            margin-bottom: 4px;
        }}
        .calendar .task {{
            font-size: 12px;
            margin: 2px 0;
            text-align: left;
        }}
        .calendar .chat {{
            color: #4CAF50;
        }}
        .calendar .happy_call {{
            color: #2196F3;
        }}
        .calendar .closing {{
            color: #FF5722;
        }}
        .calendar .vacation {{
            background-color: #FFEBEE;
        }}
        .calendar .holiday {{
            background-color: #E8F5E9;
        }}
        .calendar .sunday {{
            background-color: #EEEEEE;
        }}
    </style>
    <table class="calendar">
        <caption>{calendar.month_name[month]} {year}</caption>
        <tr>
            <th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th>
        </tr>
    """

    for week in cal:
        html += "<tr>"
        for day_index, day in enumerate(week):
            if day == 0:
                html += "<td></td>"
            else:
                date = datetime(year, month, day).date()
                date_str = date.strftime("%Y-%m-%d")

                # 셀 클래스 결정
                classes = []
                if date_str in vacation_data:
                    classes.append("vacation")
                if date in kr_holidays:
                    classes.append("holiday")
                if day_index == 6:  # 일요일
                    classes.append("sunday")

                class_str = f'class="{" ".join(classes)}"' if classes else ""

                html += f"<td {class_str}>"
                html += f'<div class="date">{day}</div>'

                # 업무 할당 표시
                if date in schedule and schedule[date]["tasks"]:
                    for task_type, members in schedule[date]["tasks"].items():
                        task_name = next(k for k, v in TASK_TYPES.items() if v == task_type)
                        html += f'<div class="task {task_type}">{task_name}: {", ".join(members)}</div>'

                html += "</td>"
        html += "</tr>"

    html += "</table>"
    return html


def create_daily_assignment_table(schedule, start_date, end_date):
    # 날짜 범위 생성
    date_range = pd.date_range(start_date, end_date)

    # 데이터 프레임용 데이터 준비
    data = []
    for date in date_range:
        if date.weekday() < 6:  # 일요일 제외
            row = {
                "날짜": f"{date.strftime('%m/%d')}({['월','화','수','목','금','토','일'][date.weekday()]})",
                "카톡": "",
                "해피콜/리뷰": "",
                "마감/어플": "",
            }

            if date.date() in schedule and schedule[date.date()]["tasks"]:
                tasks = schedule[date.date()]["tasks"]
                row["카톡"] = ", ".join(tasks.get("chat", []))
                row["해피콜/리뷰"] = ", ".join(tasks.get("happy_call", []))
                row["마감/어플"] = ", ".join(tasks.get("closing", []))

            data.append(row)

    return pd.DataFrame(data)


def get_excel_download_data(df):
    # 엑셀 파일로 변환
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="업무분배표", index=False)

    return output.getvalue()


def main():
    init_db()
    st.title("팀장 업무 분배 시스템")

    # 날짜 선택
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("시작 날짜")
    with col2:
        end_date = st.date_input("종료 날짜")

    # 공휴일 중 실제 휴일 선택
    st.subheader("공휴일 중 실제 휴무일 선택")
    holiday_dates = []
    holiday_names = {}
    for date in pd.date_range(start_date, end_date):
        if date.date() in kr_holidays:
            holiday_dates.append(date.date())
            holiday_names[date.date()] = kr_holidays.get(date.date())

    # 공휴일 선택 옵션
    holiday_options = [f"{date.strftime('%Y-%m-%d')} ({holiday_names[date]})" for date in holiday_dates]
    selected_holiday_strings = st.multiselect(
        "실제 휴무일로 지정할 공휴일을 선택하세요:",
        options=holiday_options,
        default=holiday_options,  # 기본적으로 모든 공휴일 선택
    )

    # 선택된 휴일 날짜 변환
    selected_holidays = [datetime.strptime(h.split(" (")[0], "%Y-%m-%d").date() for h in selected_holiday_strings]
    # 휴가 데이터 입력 섹션
    st.subheader("휴가 정보 입력")

    # CSV 업로드 섹션
    uploaded_file = st.file_uploader("휴가 데이터 CSV 파일 업로드", type="csv")
    if uploaded_file is not None:
        csv_contents = uploaded_file.read()
        try:
            vacations = parse_csv_vacations(csv_contents)
            save_vacation_data_from_csv(vacations)
            st.success("CSV 파일에서 휴가 데이터를 성공적으로 업로드했습니다.")
        except Exception as e:
            st.error(f"CSV 파일 처리 중 오류가 발생했습니다: {str(e)}")

    # 휴가 테이블 표시
    vacation_data = load_vacation_data()
    vacation_table = create_vacation_table(start_date, end_date, vacation_data)

    st.subheader("휴가 현황")
    # CSS 스타일 수정
    table_style = """
    <style>
        .small-table {
            font-size: 11px;
            transform: scale(1.0);
            transform-origin: top left;
        }
        .small-table th, .small-table td {
            padding: 2px 4px;
            text-align: center;
        }
        .small-table td:empty::after {
            content: "-";
            color: #ddd;
        }
    </style>
    """

    # HTML로 테이블 생성 (스타일 적용)
    html_table = vacation_table.style.applymap(
        lambda x: "color: red" if x == "●" else "color: green" if x == "⚪" else ""
    ).to_html()

    # CSS 클래스 추가 및 Streamlit에 표시
    st.markdown(table_style, unsafe_allow_html=True)
    st.markdown(f'<div class="small-table">{html_table}</div>', unsafe_allow_html=True)

    if st.button("업무 분배하기"):
        vacation_data = load_vacation_data()

        # 근무 통계 계산 (선택된 휴일 전달)
        work_stats = calculate_work_stats(start_date, end_date, TEAM_MEMBERS, vacation_data, selected_holidays)

        # 근무 통계 표시
        st.subheader("이번 달 근무 현황")
        stats_table = []
        for member, stats in work_stats.items():
            stats_table.append(
                {
                    "멤버": member,
                    "총 근무일": stats["total_working_days"],
                    "카톡 목표": stats["target_allocations"]["chat"],
                    "해피콜 목표": stats["target_allocations"]["happy_call"],
                    "마감 목표": stats["target_allocations"]["closing"],
                }
            )

        st.table(pd.DataFrame(stats_table))

        # 업무 분배 실행 (선택된 휴일 전달)
        schedule, task_counts = solve_environment_team_schedule(
            start_date, end_date, TEAM_MEMBERS, vacation_data, selected_holidays
        )

        # 캘린더 형식으로 결과 표시 (선택 휴일 전달)
        st.subheader("일일 업무 분배 (캘린더 뷰)")
        calendar_html = create_calendar_html(start_date, end_date, schedule, vacation_data, selected_holidays)
        st.markdown(calendar_html, unsafe_allow_html=True)

        # 실제 할당된 업무 통계
        st.subheader("실제 업무 할당 결과")
        stats_df = pd.DataFrame(task_counts).T

        # 목표 대비 실제 할당 비교
        comparison_data = []
        for member in TEAM_MEMBERS:
            row = {
                "멤버": member,
                "카톡 (목표/실제)": f"{work_stats[member]['target_allocations']['chat']}/{task_counts[member]['chat']}",
                "해피콜 (목표/실제)": f"{work_stats[member]['target_allocations']['happy_call']}/{task_counts[member]['happy_call']}",
                "마감 (목표/실제)": f"{work_stats[member]['target_allocations']['closing']}/{task_counts[member]['closing']}",
            }
            comparison_data.append(row)

        st.table(pd.DataFrame(comparison_data))

        # 날짜별 업무 분배 현황 표시
        st.subheader("날짜별 업무 분배 현황")
        daily_assignment_table = create_daily_assignment_table(schedule, start_date, end_date)

        # 테이블 표시
        st.table(daily_assignment_table)

        # 엑셀 다운로드 버튼
        excel_data = get_excel_download_data(daily_assignment_table)

        # 현재 날짜를 파일명에 포함
        current_date = datetime.now().strftime("%Y%m%d")
        filename = f"업무분배표_{current_date}.xlsx"

        st.download_button(
            label="📥 엑셀 파일 다운로드",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
