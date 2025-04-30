import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import calendar
import sqlite3
import holidays
import io
from collections import defaultdict
import re

# 한국의 공휴일 정보를 가져옵니다.
kr_holidays = holidays.KR()

TEAM_MEMBERS = ["다솔", "다혜", "민지", "한울", "설화"]

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


# 업무 타입 정의 (5가지 업무)
TASK_TYPES = {"카톡": "chat", "어플": "app", "리뷰": "review", "해피콜": "happy_call", "마감": "closing"}

# 인원별 업무 할당 규칙 (인원 수에 따라 업무 조합 변경)
ALLOCATION_RULES = {
    2: {
        "combined_tasks": [
            {"name": "카톡/어플/리뷰", "tasks": ["chat", "app", "review"]},
            {"name": "해피콜/마감", "tasks": ["happy_call", "closing"]},
        ]
    },
    3: {
        "combined_tasks": [
            {"name": "카톡/리뷰", "tasks": ["chat", "review"]},
            {"name": "해피콜", "tasks": ["happy_call"]},
            {"name": "마감/어플", "tasks": ["closing", "app"]},
        ]
    },
    4: {
        "combined_tasks": [
            {"name": "카톡/어플", "tasks": ["chat", "app"]},
            {"name": "해피콜", "tasks": ["happy_call"]},
            {"name": "마감", "tasks": ["closing"]},
            {"name": "리뷰", "tasks": ["review"]},
        ]
    },
    5: {
        "combined_tasks": [
            {"name": "리뷰", "tasks": ["review"]},
            {"name": "마감", "tasks": ["closing"]},
            {"name": "카톡/어플", "tasks": ["chat", "app"]},
            {"name": "해피콜1", "tasks": ["happy_call"]},
            {"name": "해피콜2", "tasks": ["happy_call"]},
        ]
    },
}


def remove_trailing_numbers(task_name):
    """업무 이름 끝에 붙은 숫자를 제거합니다."""
    return re.sub(r"(\D+)\d+$", r"\1", task_name)


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

    # 각 업무별 카운트를 추적하기 위한 딕셔너리 초기화
    member_task_counts = {member: {task: 0 for task in TASK_TYPES.values()} for member in team_members}
    # 조합된 업무 추적을 위한 딕셔너리 추가
    member_combined_task_counts = {member: {} for member in team_members}

    # 각 멤버별 목표 업무량 계산
    total_available_days = sum(available_days.values())
    target_ratios = {member: days / total_available_days for member, days in available_days.items()}

    for date in workdays:
        date_str = date.strftime("%Y-%m-%d")
        available_members = [m for m in team_members if m not in vacation_data.get(date_str, [])]
        num_available = len(available_members)

        if num_available < 2:
            continue  # 최소 2명 이상 필요

        # 인원 수에 맞는 규칙 선택 (2, 3, 4명 중 가능한 최대 인원으로)
        rule_key = min(num_available, max(ALLOCATION_RULES.keys()))
        rule = ALLOCATION_RULES.get(rule_key)

        if not rule:
            continue

        combined_tasks = rule["combined_tasks"]
        daily_assignments = {task: [] for task in TASK_TYPES.values()}

        # 각 멤버별 조합된 업무 우선순위 계산
        task_priorities = {}
        for member in available_members:
            task_priorities[member] = {}

            # 각 조합된 업무에 대한 우선순위 계산
            for i, combined_task in enumerate(combined_tasks):
                combined_name = combined_task["name"]
                task_types = combined_task["tasks"]

                # 우선순위 계산에 사용할 키 - 업무 타입을 기준으로 함
                # 해피콜1과 해피콜2는 모두 happy_call이라는 같은 타입
                priority_key = ",".join(sorted(task_types))

                # 이 업무 타입들을 수행한 횟수 계산
                type_count = sum(member_task_counts[member][task_type] for task_type in task_types)

                # 전체 업무 할당 비율
                total_tasks = sum(member_task_counts[member].values())
                total_ratio = total_tasks / available_days[member] if available_days[member] > 0 else float("inf")

                # 우선순위 점수 계산 (낮을수록 높은 우선순위)
                # 1. 해당 업무 타입 수행 횟수
                # 2. 전체 업무 할당 비율
                # 3. 전체 업무 수행 횟수
                task_priorities[member][combined_name] = (
                    type_count,  # 해당 업무 타입 수행 횟수
                    total_ratio,  # 전체 업무 할당 비율
                    total_tasks,  # 전체 업무 수행 횟수
                )

        # 조합된 업무 할당
        remaining_members = available_members.copy()
        assigned_combined_tasks = {}

        # 가능한 모든 조합된 업무 할당
        for i, combined_task in enumerate(combined_tasks):
            if not remaining_members:
                break

            combined_name = combined_task["name"]
            task_types = combined_task["tasks"]

            # 현재 조합된 업무에 가장 적합한 멤버 선택
            selected_member = min(
                remaining_members,
                key=lambda m: (
                    task_priorities[m][combined_name][0],  # 해당 업무 타입 수행 횟수
                    task_priorities[m][combined_name][1],  # 전체 업무 할당 비율
                    task_priorities[m][combined_name][2],  # 전체 업무 수행 횟수
                ),
            )

            remaining_members.remove(selected_member)

            # 조합된 업무 카운트 증가
            if combined_name not in member_combined_task_counts[selected_member]:
                member_combined_task_counts[selected_member][combined_name] = 0
            member_combined_task_counts[selected_member][combined_name] += 1

            # 개별 업무 카운트 증가 및 할당
            for task in task_types:
                member_task_counts[selected_member][task] += 1
                daily_assignments[task].append(selected_member)

            # 할당된 조합 업무 저장
            assigned_combined_tasks[combined_name] = selected_member

        # 일일 업무 할당 저장
        schedule[date]["tasks"] = daily_assignments
        # 조합된 업무 할당 정보도 저장
        schedule[date]["combined_tasks"] = assigned_combined_tasks

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

        # 모든 가능한 조합된 업무 목록 생성
        all_combined_tasks = set()
        for rule in ALLOCATION_RULES.values():
            for combined_task in rule["combined_tasks"]:
                all_combined_tasks.add(combined_task["name"])

        # 각 조합된 업무별 목표 할당량 계산
        # 근무일을 조합된 업무 수로 나누어 분배
        target_per_combined_task = total_days / len(all_combined_tasks) if all_combined_tasks else 0

        target_allocations = {}
        for task_name in all_combined_tasks:
            target_allocations[task_name] = round(target_per_combined_task, 1)

        work_stats[member] = {"total_working_days": total_days, "target_allocations": target_allocations}

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
        .calendar .app {{
            color: #9C27B0;
        }}
        .calendar .review {{
            color: #FF9800;
        }}
        .calendar .happy_call {{
            color: #2196F3;
        }}
        .calendar .closing {{
            color: #FF5722;
        }}
        .calendar .combined {{
            color: #000000;
            font-weight: bold;
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

                # 조합된 업무 할당 표시
                if date in schedule and "combined_tasks" in schedule[date]:
                    combined_tasks = schedule[date]["combined_tasks"]
                    for task_name, member in combined_tasks.items():
                        html += f'<div class="task combined">{task_name}: {member}</div>'

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
            }

            # 모든 조합된 업무 열 추가
            all_combined_tasks = set()
            for rule in ALLOCATION_RULES.values():
                for combined_task in rule["combined_tasks"]:
                    all_combined_tasks.add(combined_task["name"])

            # 모든 가능한 조합된 업무에 대한 열 초기화
            for task_name in sorted(all_combined_tasks):
                row[task_name] = ""

            if date.date() in schedule and "combined_tasks" in schedule[date.date()]:
                combined_tasks = schedule[date.date()]["combined_tasks"]
                for task_name, member in combined_tasks.items():
                    row[task_name] = member

            data.append(row)

    return pd.DataFrame(data)


def create_daily_assignment_summary(schedule, start_date, end_date):
    # 날짜 범위 생성
    date_range = pd.date_range(start_date, end_date)

    # 데이터 프레임용 데이터 준비
    data = []
    for date in date_range:
        if date.weekday() < 6:  # 일요일 제외
            date_obj = date.date()

            # 해당 날짜에 근무하는 인원 수 계산
            working_members = set()
            if date_obj in schedule and "combined_tasks" in schedule[date_obj]:
                for member in schedule[date_obj]["combined_tasks"].values():
                    working_members.add(member)

            num_workers = len(working_members)

            # 업무 할당 정보 생성
            task_assignments = []
            if date_obj in schedule and "combined_tasks" in schedule[date_obj]:
                combined_tasks = schedule[date_obj]["combined_tasks"]
                # 업무 이름 순으로 정렬하여 일관된 순서로 표시
                for task_name in sorted(combined_tasks.keys()):
                    member = combined_tasks[task_name]
                    task_assignments.append(f"{task_name}: {member}")

            task_info = " , ".join(task_assignments) if task_assignments else "업무 할당 없음"

            # 날짜 형식 조정 (요일을 한글로 표시)
            weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][date.weekday()]

            row = {
                "날짜": f"{date.strftime('%m/%d')} ({weekday_kr})",
                "근무 인원": f"{num_workers}명",
                "업무 할당": task_info,
            }

            data.append(row)

    return pd.DataFrame(data)


def get_excel_download_data(df, sheet_name="업무분배표"):
    # 엑셀 파일로 변환
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)

        # 워크시트 가져오기
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]

        # 열 너비 자동 조정
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2  # 데이터 길이  # 열 이름 길이  # 여유 공간
            worksheet.set_column(i, i, max_len)

        # 헤더 스타일 설정
        header_format = workbook.add_format(
            {"bold": True, "text_wrap": True, "valign": "top", "fg_color": "#D7E4BC", "border": 1}
        )

        # 헤더 스타일 적용
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)

    return output.getvalue()


def create_calendar_excel_data(schedule, start_date, end_date, vacation_data, selected_holidays):
    # 엑셀 파일 생성
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book

        # 스타일 설정
        header_format = workbook.add_format(
            {"bold": True, "text_wrap": True, "valign": "top", "align": "center", "fg_color": "#D7E4BC", "border": 1}
        )

        date_format = workbook.add_format({"bold": True, "valign": "top", "align": "left", "border": 1})

        task_format = workbook.add_format({"text_wrap": True, "valign": "top", "align": "left", "border": 1})

        weekend_format = workbook.add_format(
            {"bold": True, "valign": "top", "align": "left", "fg_color": "#EEEEEE", "border": 1}
        )

        holiday_format = workbook.add_format(
            {"bold": True, "valign": "top", "align": "left", "fg_color": "#E8F5E9", "border": 1}
        )

        vacation_format = workbook.add_format(
            {"bold": True, "valign": "top", "align": "left", "fg_color": "#FFEBEE", "border": 1}
        )

        title_format = workbook.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"})

        # 시작 날짜부터 종료 날짜까지의 모든 월 처리
        current_date = start_date.replace(day=1)  # 시작 월의 1일
        end_month_date = end_date.replace(day=1)  # 종료 월의 1일

        while current_date <= end_month_date:
            year = current_date.year
            month = current_date.month

            # 해당 월의 마지막 날짜 계산
            _, last_day = calendar.monthrange(year, month)
            month_end_date = current_date.replace(day=last_day)

            # 워크시트 생성 (월별로 시트 분리)
            worksheet = workbook.add_worksheet(f"{year}년 {month}월")

            # 열 너비 설정
            worksheet.set_column(0, 6, 20)  # 모든 요일 열의 너비를 20으로 설정

            # 제목 추가 (병합된 셀)
            worksheet.merge_range("A1:G1", f"{year}년 {month}월 업무 분배 캘린더", title_format)

            # 요일 헤더 추가
            weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
            for i, day in enumerate(weekdays):
                worksheet.write(1, i, day, header_format)

            # 해당 월의 캘린더 데이터 생성
            cal = calendar.monthcalendar(year, month)

            # 캘린더 데이터 채우기
            for week_idx, week in enumerate(cal):
                row_idx = week_idx + 2  # 제목과 헤더 다음 행부터 시작

                for day_idx, day in enumerate(week):
                    if day == 0:  # 해당 월에 속하지 않는 날
                        continue

                    date = datetime(year, month, day).date()
                    date_str = date.strftime("%Y-%m-%d")

                    # 셀 형식 결정
                    cell_format = date_format
                    if day_idx == 6:  # 일요일
                        cell_format = weekend_format
                    elif date in kr_holidays:  # 공휴일
                        cell_format = holiday_format
                    elif date_str in vacation_data:  # 휴가가 있는 날
                        cell_format = vacation_format

                    # 날짜 표시
                    cell_content = f"{day}일"
                    if date in kr_holidays:
                        cell_content += f" ({kr_holidays.get(date)})"

                    worksheet.write(row_idx, day_idx, cell_content, cell_format)

                    # 업무 할당 정보 추가
                    if date in schedule and "combined_tasks" in schedule[date]:
                        combined_tasks = schedule[date]["combined_tasks"]
                        task_info = []

                        for task_name, member in sorted(combined_tasks.items()):
                            task_info.append(f"{task_name}: {member}")

                        # 업무 정보를 같은 셀에 추가 (줄바꿈으로 구분)
                        if task_info:
                            task_text = "\n".join(task_info)
                            # 날짜 아래에 업무 정보 추가 (같은 셀에)
                            worksheet.write(row_idx, day_idx, f"{cell_content}\n\n{task_text}", task_format)

                            # 행 높이 조정 (업무 정보가 있는 경우 더 높게)
                            worksheet.set_row(row_idx, 20 * (len(task_info) + 2))  # 기본 높이 + 업무 수에 비례

            # 다음 달로 이동
            if month == 12:
                current_date = current_date.replace(year=year + 1, month=1)
            else:
                current_date = current_date.replace(month=month + 1)

    return output.getvalue()


def calculate_task_type_counts(schedule, team_members):
    # 각 멤버별, 업무 타입별 카운트를 저장할 딕셔너리 초기화
    task_type_counts = {member: {task_type: 0 for task_type in TASK_TYPES.values()} for member in team_members}

    # 스케줄을 순회하며 각 업무 타입별 카운트 계산
    for date, day_schedule in schedule.items():
        if "combined_tasks" in day_schedule:
            combined_tasks = day_schedule["combined_tasks"]

            for combined_task_name, member in combined_tasks.items():
                # 해당 조합 업무에 포함된 개별 업무 타입 찾기
                for rule in ALLOCATION_RULES.values():
                    for task_info in rule["combined_tasks"]:
                        if task_info["name"] == combined_task_name:
                            # 이 조합 업무에 포함된 모든 업무 타입에 대해 카운트 증가
                            for task_type in task_info["tasks"]:
                                task_type_counts[member][task_type] += 1

    return task_type_counts


def create_task_type_counts_table(task_type_counts):
    # 데이터프레임용 데이터 준비
    data = []

    # 업무 타입 한글 이름 매핑 (역매핑)
    task_type_to_korean = {v: k for k, v in TASK_TYPES.items()}

    for member, counts in task_type_counts.items():
        row = {"멤버": member}

        # 각 업무 타입별 카운트 추가
        for task_type, count in counts.items():
            row[task_type_to_korean[task_type]] = count

        # 총 업무 수 계산
        row["총 업무 수"] = sum(counts.values())

        data.append(row)

    # 데이터프레임 생성 및 열 순서 지정
    columns = ["멤버"] + [task_type_to_korean[task_type] for task_type in TASK_TYPES.values()] + ["총 업무 수"]
    df = pd.DataFrame(data)

    # 열 순서 조정
    df = df[columns]

    return df


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

        # 모든 가능한 조합된 업무 목록 생성
        all_combined_tasks = set()
        for rule in ALLOCATION_RULES.values():
            for combined_task in rule["combined_tasks"]:
                all_combined_tasks.add(combined_task["name"])

        for member, stats in work_stats.items():
            row = {
                "멤버": member,
                "총 근무일": stats["total_working_days"],
            }

            # 각 조합된 업무별 목표 추가
            for task_name in sorted(all_combined_tasks):
                row[f"{task_name} 목표"] = stats["target_allocations"].get(task_name, 0)

            stats_table.append(row)

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

        # 각 멤버별 조합된 업무 수행 횟수 계산
        combined_task_counts = {member: {} for member in TEAM_MEMBERS}

        for date, day_schedule in schedule.items():
            if "combined_tasks" in day_schedule:
                for task_name, member in day_schedule["combined_tasks"].items():
                    if task_name not in combined_task_counts[member]:
                        combined_task_counts[member][task_name] = 0
                    combined_task_counts[member][task_name] += 1

        # 목표 대비 실제 할당 비교
        comparison_data = []
        for member in TEAM_MEMBERS:
            row = {
                "멤버": member,
            }

            # 업무 이름의 끝 숫자를 제거하여 통합하기 위한 딕셔너리
            consolidated_tasks = {}
            for task_name, count in combined_task_counts[member].items():
                # 업무 이름 끝의 숫자 제거
                base_name = remove_trailing_numbers(task_name)
                if base_name not in consolidated_tasks:
                    consolidated_tasks[base_name] = 0
                consolidated_tasks[base_name] += count

            # 중복 제거된 기본 업무 이름 목록 생성
            base_task_names = set()
            for task_name in all_combined_tasks:
                base_task_names.add(remove_trailing_numbers(task_name))

            # 각 조합된 업무별 목표/실제 비교
            for base_task_name in base_task_names:
                target = work_stats[member]["target_allocations"].get(base_task_name, 0)
                actual = consolidated_tasks.get(base_task_name, 0)
                row[f"{base_task_name} (목표/실제)"] = f"{target}/{actual}"

            comparison_data.append(row)

        st.table(pd.DataFrame(comparison_data))

        # 날짜별 업무 분배 현황 표시
        st.subheader("날짜별 업무 분배 현황")
        daily_assignment_table = create_daily_assignment_table(schedule, start_date, end_date)

        # 테이블 표시
        st.table(daily_assignment_table)

        # 날짜별 업무 분배 현황 요약 표시 (새로운 형식)
        st.subheader("날짜별 업무 분배 요약")
        daily_summary_table = create_daily_assignment_summary(schedule, start_date, end_date)

        # 테이블 표시
        st.table(daily_summary_table)

        # 업무 타입별 배정 횟수 계산 및 표시
        st.subheader("업무 타입별 배정 횟수")
        task_type_counts = calculate_task_type_counts(schedule, TEAM_MEMBERS)
        task_type_counts_table = create_task_type_counts_table(task_type_counts)

        # 테이블 표시
        st.table(task_type_counts_table)

        # 현재 날짜를 파일명에 포함
        current_date = datetime.now().strftime("%Y%m%d")

        # 업무 타입별 배정 횟수 엑셀 다운로드 버튼
        task_type_excel_data = get_excel_download_data(task_type_counts_table, sheet_name="업무타입별배정횟수")
        task_type_filename = f"업무타입별배정횟수_{current_date}.xlsx"

        st.download_button(
            label="📥 엑셀 파일 다운로드 (업무 타입별 배정 횟수)",
            data=task_type_excel_data,
            file_name=task_type_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 엑셀 다운로드 버튼 (기존 테이블용)
        excel_data = get_excel_download_data(daily_assignment_table, sheet_name="업무분배표")
        filename = f"업무분배표_{current_date}.xlsx"

        st.download_button(
            label="📥 엑셀 파일 다운로드 (업무분배표)",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 엑셀 다운로드 버튼 (요약 테이블용)
        summary_excel_data = get_excel_download_data(daily_summary_table, sheet_name="업무분배요약")
        summary_filename = f"업무분배요약_{current_date}.xlsx"

        st.download_button(
            label="📥 엑셀 파일 다운로드 (업무분배요약)",
            data=summary_excel_data,
            file_name=summary_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 캘린더 엑셀 다운로드
        calendar_excel_data = create_calendar_excel_data(
            schedule, start_date, end_date, vacation_data, selected_holidays
        )
        st.download_button(
            label="📥 엑셀 파일 다운로드 (캘린더 뷰)",
            data=calendar_excel_data,
            file_name=f"캘린더_{current_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 모든 데이터를 하나의 엑셀 파일로 다운로드 (캘린더 뷰 포함)
        combined_output = io.BytesIO()
        with pd.ExcelWriter(combined_output, engine="xlsxwriter") as writer:
            # 기존 테이블 시트 추가
            daily_assignment_table.to_excel(writer, sheet_name="업무분배표", index=False)
            daily_summary_table.to_excel(writer, sheet_name="업무분배요약", index=False)
            task_type_counts_table.to_excel(writer, sheet_name="업무타입별배정횟수", index=False)

            # 워크북 가져오기
            workbook = writer.book

            # 각 워크시트 스타일 적용
            for sheet_name in ["업무분배표", "업무분배요약", "업무타입별배정횟수"]:
                worksheet = writer.sheets[sheet_name]
                if sheet_name == "업무분배표":
                    df = daily_assignment_table
                elif sheet_name == "업무분배요약":
                    df = daily_summary_table
                else:
                    df = task_type_counts_table

                # 열 너비 자동 조정
                for i, col in enumerate(df.columns):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len)

                # 헤더 스타일 설정
                header_format = workbook.add_format(
                    {"bold": True, "text_wrap": True, "valign": "top", "fg_color": "#D7E4BC", "border": 1}
                )

                # 헤더 스타일 적용
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(0, col_num, value, header_format)

            # 캘린더 뷰 시트 추가 (시작 월부터 종료 월까지)
            current_date = start_date.replace(day=1)  # 시작 월의 1일
            end_month_date = end_date.replace(day=1)  # 종료 월의 1일

            while current_date <= end_month_date:
                year = current_date.year
                month = current_date.month

                # 해당 월의 마지막 날짜 계산
                _, last_day = calendar.monthrange(year, month)
                month_end_date = current_date.replace(day=last_day)

                # 워크시트 생성 (월별로 시트 분리)
                worksheet = workbook.add_worksheet(f"캘린더_{year}년{month}월")

                # 스타일 설정
                header_format = workbook.add_format(
                    {
                        "bold": True,
                        "text_wrap": True,
                        "valign": "top",
                        "align": "center",
                        "fg_color": "#D7E4BC",
                        "border": 1,
                    }
                )

                date_format = workbook.add_format({"bold": True, "valign": "top", "align": "left", "border": 1})

                task_format = workbook.add_format({"text_wrap": True, "valign": "top", "align": "left", "border": 1})

                weekend_format = workbook.add_format(
                    {"bold": True, "valign": "top", "align": "left", "fg_color": "#EEEEEE", "border": 1}
                )

                holiday_format = workbook.add_format(
                    {"bold": True, "valign": "top", "align": "left", "fg_color": "#E8F5E9", "border": 1}
                )

                vacation_format = workbook.add_format(
                    {"bold": True, "valign": "top", "align": "left", "fg_color": "#FFEBEE", "border": 1}
                )

                title_format = workbook.add_format(
                    {"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"}
                )

                # 열 너비 설정
                worksheet.set_column(0, 6, 20)  # 모든 요일 열의 너비를 20으로 설정

                # 제목 추가 (병합된 셀)
                worksheet.merge_range("A1:G1", f"{year}년 {month}월 업무 분배 캘린더", title_format)

                # 요일 헤더 추가
                weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
                for i, day in enumerate(weekdays):
                    worksheet.write(1, i, day, header_format)

                # 해당 월의 캘린더 데이터 생성
                cal = calendar.monthcalendar(year, month)

                # 캘린더 데이터 채우기
                for week_idx, week in enumerate(cal):
                    row_idx = week_idx + 2  # 제목과 헤더 다음 행부터 시작

                    for day_idx, day in enumerate(week):
                        if day == 0:  # 해당 월에 속하지 않는 날
                            continue

                        date = datetime(year, month, day).date()
                        date_str = date.strftime("%Y-%m-%d")

                        # 셀 형식 결정
                        cell_format = date_format
                        if day_idx == 6:  # 일요일
                            cell_format = weekend_format
                        elif date in kr_holidays:  # 공휴일
                            cell_format = holiday_format
                        elif date_str in vacation_data:  # 휴가가 있는 날
                            cell_format = vacation_format

                        # 날짜 표시
                        cell_content = f"{day}일"
                        if date in kr_holidays:
                            cell_content += f" ({kr_holidays.get(date)})"

                        worksheet.write(row_idx, day_idx, cell_content, cell_format)

                        # 업무 할당 정보 추가
                        if date in schedule and "combined_tasks" in schedule[date]:
                            combined_tasks = schedule[date]["combined_tasks"]
                            task_info = []

                            for task_name, member in sorted(combined_tasks.items()):
                                task_info.append(f"{task_name}: {member}")

                            # 업무 정보를 같은 셀에 추가 (줄바꿈으로 구분)
                            if task_info:
                                task_text = "\n".join(task_info)
                                # 날짜 아래에 업무 정보 추가 (같은 셀에)
                                worksheet.write(row_idx, day_idx, f"{cell_content}\n\n{task_text}", task_format)

                                # 행 높이 조정 (업무 정보가 있는 경우 더 높게)
                                worksheet.set_row(row_idx, 20 * (len(task_info) + 2))  # 기본 높이 + 업무 수에 비례

                # 다음 달로 이동
                if month == 12:
                    current_date = current_date.replace(year=year + 1, month=1)
                else:
                    current_date = current_date.replace(month=month + 1)

        combined_filename = f"업무분배_전체_{current_date}.xlsx"

        st.download_button(
            label="📥 엑셀 파일 다운로드 (전체 데이터)",
            data=combined_output.getvalue(),
            file_name=combined_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
