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

# 환경팀 멤버
TEAM_MEMBERS = ["다혜실", "희진", "예지", "수현", "예진", "현옥", "다해"]

# Database 설정
DB_FILE = "environment_team_schedule.db"
TABLE_NAME = "vacation_days"


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
    return date.weekday() < 6 and date not in selected_holidays and date not in kr_holidays


def solve_environment_team_schedule(start_date, end_date, team_members, vacation_data, selected_holidays):
    num_days = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(num_days)]
    workdays = [date for date in dates if is_workday(date, selected_holidays)]

    schedule = {date: {"morning": "", "afternoon": ""} for date in workdays}
    member_shifts = {member: {"morning": 0, "afternoon": 0} for member in team_members}

    for date in workdays:
        date_str = date.strftime("%Y-%m-%d")
        available_members = [m for m in team_members if m not in vacation_data.get(date_str, [])]

        for shift in ["morning", "afternoon"]:
            if not available_members:
                continue

            # 할당이 덜 된 순서대로 정렬
            sorted_members = sorted(
                available_members,
                key=lambda m: (member_shifts[m][shift], member_shifts[m]["morning"] + member_shifts[m]["afternoon"]),
            )

            # 가장 적게 할당된 멤버 선택
            selected_member = sorted_members[0]
            schedule[date][shift] = selected_member
            member_shifts[selected_member][shift] += 1

    total_shifts = sum(sum(shifts.values()) for shifts in member_shifts.values())
    target_shifts = total_shifts // len(team_members)

    return schedule, member_shifts, {member: target_shifts for member in team_members}


def create_calendar_html(year, month, schedule, vacation_data, selected_holidays):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    html = f"""
    <style>
        .calendar {{
            font-family: Arial, sans-serif;
            border-collapse: collapse;
            width: 100%;
        }}
        .calendar th, .calendar td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: center;
        }}
        .calendar th {{
            background-color: #f2f2f2;
        }}
        .calendar .date {{
            font-weight: bold;
        }}
        .calendar .morning {{
            color: #4CAF50;
        }}
        .calendar .afternoon {{
            color: #2196F3;
        }}
        .calendar .vacation {{
            background-color: #FFCCCB;
        }}
        .calendar .holiday {{
            background-color: #FFD700;
        }}
        .calendar .saturday {{
            background-color: #E6E6FA;
        }}
    </style>
    <table class="calendar">
        <caption>{month_name} {year}</caption>
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
                class_name = "vacation" if date_str in vacation_data else ""
                class_name += " holiday" if date in selected_holidays else ""
                class_name += " saturday" if day_index == 5 else ""  # 토요일 스타일 추가
                html += f'<td class="{class_name}">'
                html += f'<div class="date">{day}</div>'
                if date in schedule:
                    morning = schedule[date]["morning"]
                    afternoon = schedule[date]["afternoon"]
                    html += f'<div class="morning">아침: {morning}</div>'
                    html += f'<div class="afternoon">오후: {afternoon}</div>'
                if date_str in vacation_data:
                    html += f'<div class="vacation">휴가: {", ".join(vacation_data[date_str])}</div>'
                if date in selected_holidays:
                    html += f'<div class="holiday">공휴일</div>'
                html += "</td>"
        html += "</tr>"

    html += "</table>"
    return html


def parse_csv_vacations(csv_contents):
    vacations = {}
    df = pd.read_csv(io.StringIO(csv_contents.decode("utf-8")))
    for _, row in df.iterrows():
        date = datetime.strptime(str(row["Date"]), "%Y%m%d").date()
        worker = row["Worker"]
        if date not in vacations:
            vacations[date] = []
        vacations[date].append(worker)
    return vacations


def save_vacation_data_from_csv(vacations):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for date, workers in vacations.items():
        for worker in workers:
            date_str = date.strftime("%Y-%m-%d")
            # 먼저 해당 날짜와 작업자의 조합이 이미 존재하는지 확인
            c.execute(f"SELECT * FROM {TABLE_NAME} WHERE date = ? AND worker = ?", (date_str, worker))
            if c.fetchone() is None:
                # 존재하지 않는 경우에만 새로운 데이터 삽입
                c.execute(f"INSERT INTO {TABLE_NAME} (date, worker) VALUES (?, ?)", (date_str, worker))
    conn.commit()
    conn.close()


def create_vacation_table(year, month, vacation_data):
    _, last_day = calendar.monthrange(year, month)
    # dates = [f"{year}-{month:02d}-{day:02d}" for day in range(1, last_day + 1)]
    dates = [f"{year}-{month:02d}-{day:02d}" for day in range(1, last_day + 1)]

    df = pd.DataFrame(index=TEAM_MEMBERS, columns=dates)
    df = df.fillna("")

    for date, members in vacation_data.items():
        if date in df.columns:
            for member in members:
                if member in df.index:
                    df.at[member, date] = "●"

    return df


def delete_vacation_data_by_month(year, month):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-31"  # 31일로 설정해도 괜찮습니다. SQLite는 자동으로 처리합니다.
    c.execute(f"DELETE FROM {TABLE_NAME} WHERE date BETWEEN ? AND ?", (start_date, end_date))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()
    return deleted_count


def main():
    st.title("환경팀 스케줄 최적화")

    init_db()

    # 현재 날짜 계산
    today = datetime.now().date()
    current_year = today.year
    current_month = today.month
    last_day_of_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    # 휴가 데이터를 세션 상태로 관리
    if "vacation_data" not in st.session_state:
        st.session_state.vacation_data = load_vacation_data()

    st.header("휴가 관리")
    with st.expander("관리"):

        # CSV 파일 업로드와 개별 휴가 입력을 나란히 배치
        col1, col2, col3 = st.columns(3)

        with col1:
            st.subheader("휴가 데이터 업로드 (CSV)")
            uploaded_file = st.file_uploader("휴가 데이터 CSV 파일 선택", type="csv")
            if uploaded_file is not None:
                csv_contents = uploaded_file.read()
                vacations = parse_csv_vacations(csv_contents)
                save_vacation_data_from_csv(vacations)
                st.session_state.vacation_data.update(vacations)
                st.success("휴가 데이터가 성공적으로 업로드되었습니다.")

        with col2:
            st.subheader("개별 휴가 데이터 입력")
            vacation_date = st.date_input("휴가 날짜", key="individual_vacation_date")
            vacation_member = st.selectbox("휴가자", TEAM_MEMBERS, key="individual_vacation_member")
            if st.button("휴가 추가"):
                date_str = vacation_date.strftime("%Y-%m-%d")
                save_vacation_data(date_str, vacation_member)
                if date_str not in st.session_state.vacation_data:
                    st.session_state.vacation_data[date_str] = []
                if vacation_member not in st.session_state.vacation_data[date_str]:
                    st.session_state.vacation_data[date_str].append(vacation_member)
                    st.success("휴가가 추가되었습니다.")
                else:
                    st.warning("이미 해당 날짜에 같은 사람의 휴가가 등록되어 있습니다.")

        with col3:
            st.subheader("월별 휴가 데이터 삭제")
            delete_year = st.selectbox("삭제할 연도", range(current_year, current_year + 5), key="delete_year")
            delete_month = st.selectbox("삭제할 월", range(1, 13), key="delete_month")
            if st.button("선택한 월의 휴가 데이터 삭제"):
                deleted_count = delete_vacation_data_by_month(delete_year, delete_month)
                if deleted_count > 0:
                    st.success(f"{delete_year}년 {delete_month}월의 휴가 데이터 {deleted_count}개가 삭제되었습니다.")
                    # 세션 상태의 휴가 데이터도 업데이트
                    st.session_state.vacation_data = load_vacation_data()
                else:
                    st.info(f"{delete_year}년 {delete_month}월에 삭제할 휴가 데이터가 없습니다.")

            # Start Generation Here
        st.markdown("---")
    # 휴가 일정 시각화
    st.subheader("휴가 일정")
    _, _, _, _, col1, col2 = st.columns(6)
    # 현재 월 선택
    with col1:
        selected_year = st.selectbox("년도 선택", range(current_year, current_year + 5), index=0)
    with col2:
        selected_month = st.selectbox("월 선택", range(1, 13), index=current_month - 1)

    # 선택된 월의 시작일과 마지막 날 계산
    vis_start_date = datetime(selected_year, selected_month, 1).date()
    vis_end_date = (vis_start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    # 선택된 월의 휴가 데이터 조회
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        f"SELECT date, worker FROM {TABLE_NAME} WHERE date BETWEEN ? AND ?",
        (vis_start_date.strftime("%Y-%m-%d"), vis_end_date.strftime("%Y-%m-%d")),
    )
    result = c.fetchall()
    conn.close()

    filtered_vacation_data = {}
    for date, worker in result:
        if date not in filtered_vacation_data:
            filtered_vacation_data[date] = []
        filtered_vacation_data[date].append(worker)

    # 휴가 일정 테이블 생성
    vacation_table = create_vacation_table(selected_year, selected_month, filtered_vacation_data)

    # 스타일링을 위한 CSS
    st.markdown(
        """
    <style>
    .vacation-table td {
        text-align: center;
    }
    .vacation-table .vacation {
        color: red;
        font-weight: bold;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # 테이블 표시
    st.markdown(
        f"<h2 style='text-align: center;'>{selected_year}년 {selected_month}월 휴가 일정</h2>", unsafe_allow_html=True
    )
    vacation_table.columns = [
        f"{datetime.strptime(date, '%Y-%m-%d').strftime('%d')}({['월','화','수','목','금','토','일'][datetime.strptime(date, '%Y-%m-%d').weekday()]})"
        for date in vacation_table.columns
    ]
    # CSS 스타일 정의
    table_style = """
    <style>
        .small-table {
            font-size: 11px;  /* 글자 크기 줄이기 */
            transform: scale(1.0);  /* 전체 테이블 크기 80%로 축소 */
            transform-origin: top left;  /* 축소 시 왼쪽 상단 기준 */
        }
        .small-table th, .small-table td {
            padding: 2px 4px;  /* 셀 내부 여백 줄이기 */
        }
    </style>
    """

    # HTML로 테이블 생성
    html_table = vacation_table.style.applymap(lambda x: "color: red" if x == "●" else "").to_html()

    # CSS 클래스 추가 및 Streamlit에 표시
    st.markdown(table_style, unsafe_allow_html=True)
    st.markdown(f'<div class="small-table">{html_table}</div>', unsafe_allow_html=True)
    # 시작 날짜와 종료 날짜 선택 (이번 달의 현재 날짜부터 마지막 날짜까지)
    _, _, _, _, col1, col2 = st.columns(6)

    with col1:
        start_date = st.date_input(
            "시작 날짜", value=today, min_value=today.replace(day=1), max_value=last_day_of_month
        )
    with col2:
        end_date = st.date_input(
            "종료 날짜", value=last_day_of_month, min_value=start_date, max_value=last_day_of_month
        )

    # 공휴일 선택
    holiday_list = get_kr_holidays(start_date, end_date)
    holiday_options = [f"{date.strftime('%Y-%m-%d')} ({name})" for date, name in holiday_list]
    selected_holiday_options = st.multiselect("공휴일 선택", options=holiday_options)
    selected_holidays = [
        datetime.strptime(option.split()[0], "%Y-%m-%d").date() for option in selected_holiday_options
    ]

    # 스케줄 최적화
    if st.button("스케줄 최적화", key="optimize_schedule"):
        schedule, member_shifts, target_shifts = solve_environment_team_schedule(
            start_date, end_date, TEAM_MEMBERS, st.session_state.vacation_data, selected_holidays
        )
        if schedule:
            st.success("스케줄이 생성되었습니다!")

            # 결과를 DataFrame으로 변환
            results = []
            for day, shifts in schedule.items():
                results.append({"날짜": day, "아침": shifts["morning"], "오후": shifts["afternoon"]})
            df = pd.DataFrame(results)

            # 결과 표시
            col1, col2 = st.columns([7, 3])
            with col2:
                st.subheader("생성된 스케줄")
                st.dataframe(df, height=500)
            with col1:
                # 달력 형식으로 표시
                st.subheader("달력 형식의 스케줄")
                current_month = start_date.replace(day=1)
                end_month = end_date.replace(day=1)
                while current_month <= end_month:
                    calendar_html = create_calendar_html(
                        current_month.year,
                        current_month.month,
                        schedule,
                        st.session_state.vacation_data,
                        selected_holidays,
                    )
                    st.markdown(calendar_html, unsafe_allow_html=True)
                    current_month += timedelta(days=32)
                    current_month = current_month.replace(day=1)

            # 각 멤버별 근무 횟수 및 목표 대비 실제 근무 비율 표시
            member_counts = defaultdict(lambda: {"morning": 0, "afternoon": 0, "total": 0})
            # "target": 0, "achievement_rate": 0
            for member in TEAM_MEMBERS:
                member_counts[member]["morning"] = member_shifts[member]["morning"]
                member_counts[member]["afternoon"] = member_shifts[member]["afternoon"]
                member_counts[member]["total"] = member_shifts[member]["morning"] + member_shifts[member]["afternoon"]
                # member_counts[member]["target"] = target_shifts[member]
                # member_counts[member]["achievement_rate"] = (
                #     member_counts[member]["total"] / target_shifts[member] if target_shifts[member] > 0 else 0
                # )
            count_col, count_day = st.columns([3, 7])
            with count_col:
                st.subheader("멤버별 근무 횟수")

                count_df = pd.DataFrame.from_dict(member_counts, orient="index")
                # count_df = count_df.sort_values("achievement_rate", ascending=False)
                st.dataframe(
                    count_df.style.format(
                        {
                            "morning": "{:.0f}",
                            "afternoon": "{:.0f}",
                            "total": "{:.0f}",
                            # "target": "{:.0f}",
                            # "achievement_rate": "{:.2%}",
                        }
                    )
                )
            with count_day:
                # 근무 횟수별 환경팀 청소 일정 표시
                st.subheader("근무 횟수별 환경팀 청소 일정")
                shift_counts = defaultdict(lambda: {"morning": [], "afternoon": []})
                for date, shifts in schedule.items():
                    shift_counts[shifts["morning"]]["morning"].append(date)
                    shift_counts[shifts["afternoon"]]["afternoon"].append(date)

                cols = st.columns(len(TEAM_MEMBERS))
                for i, member in enumerate(TEAM_MEMBERS):
                    with cols[i]:
                        st.write(f"**{member}**")
                        st.write(f"아침 근무 ({len(shift_counts[member]['morning'])}회):")
                        for date in shift_counts[member]["morning"]:
                            st.write(date.strftime("%Y-%m-%d"))
                        st.write(f"오후 근무 ({len(shift_counts[member]['afternoon'])}회):")
                        for date in shift_counts[member]["afternoon"]:
                            st.write(date.strftime("%Y-%m-%d"))

        else:
            st.error("스케줄을 생성할 수 없습니다. 휴가 일정을 확인해주세요.")


if __name__ == "__main__":
    main()
