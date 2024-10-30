# from ortools.sat.python import cp_model
import math


def get_b_zone_min_max(schedule):
    three_days = 0
    four_days = 0
    five_days = 0
    for day, members in schedule.items():
        if len(members) == 3:
            three_days += 1
        elif len(members) == 4:
            four_days += 1
        elif len(members) == 5:
            five_days += 1

    total_b_count = three_days + 2 * (four_days + five_days)
    expected_b_cout = total_b_count / len(members)
    expected_b_cout_max = math.ceil(expected_b_cout)
    expected_b_cout_min = math.floor(expected_b_cout)
    return expected_b_cout_min, expected_b_cout_max


from datetime import datetime


def solve_cleaning_schedule(schedule, workers, vacation_days):
    from ortools.sat.python import cp_model

    # 휴가를 고려하여 스케줄 필터링
    filtered_schedule = {}

    def change_date_format(date):
        if isinstance(date, str):
            return datetime.strptime(date, "%Y-%m-%d").date()
        return date

    vacation_days = {change_date_format(day): workers for day, workers in vacation_days.items()}
    for day, day_workers in schedule.items():
        if isinstance(day, str):
            day = datetime.strptime(day, "%Y-%m-%d").date()

        available_workers = [w for w in day_workers if w not in vacation_days.get(day, [])]
        if available_workers:  # 근무 가능한 직원이 있는 경우에만 스케줄에 포함
            filtered_schedule[day] = available_workers

    print("Filtered schedule:", filtered_schedule)
    model = cp_model.CpModel()
    days = sorted(filtered_schedule.keys())
    expected_b_count_min, expected_b_count_max = get_b_zone_min_max(filtered_schedule)
    print("B Range", expected_b_count_min, " ~ ", expected_b_count_max)
    cleaning_assignments = {}
    for day in days:
        for worker in filtered_schedule[day]:
            cleaning_assignments[(day, worker, 1)] = model.NewBoolVar(f"clean_{worker}_day{day}_zone1")
            cleaning_assignments[(day, worker, 2)] = model.NewBoolVar(f"clean_{worker}_day{day}_zone2")

    zone2_cleaners_count = {}
    for day in days:
        zone2_cleaners_count[day] = model.NewIntVar(1, 2, f"zone2_cleaners_day{day}")
        model.Add(
            zone2_cleaners_count[day]
            == sum(cleaning_assignments.get((day, worker, 2), 0) for worker in filtered_schedule[day])
        )

    for day in days:
        workers_on_duty = filtered_schedule[day]
        model.Add(
            sum(cleaning_assignments[(day, worker, 1)] for worker in workers_on_duty)
            + sum(cleaning_assignments[(day, worker, 2)] for worker in workers_on_duty)
            == len(workers_on_duty)
        )

        for worker in workers_on_duty:
            model.Add(cleaning_assignments[(day, worker, 1)] + cleaning_assignments[(day, worker, 2)] == 1)

        if len(workers_on_duty) == 3:
            model.Add(zone2_cleaners_count[day] == 1)
        elif len(workers_on_duty) >= 4:
            model.Add(zone2_cleaners_count[day] == 2)

    total_zone2_cleanings = {}
    solo_zone2_cleanings = {}

    for worker in workers:
        solo_zone_max_cleanings = int(expected_b_count_max / 2) + 1
        total_zone2_cleanings[worker] = model.NewIntVar(0, expected_b_count_max, f"total_zone2_{worker}")
        solo_zone2_cleanings[worker] = model.NewIntVar(0, solo_zone_max_cleanings, f"solo_zone2_{worker}")
        # model.Add(
        #     solo_zone2_cleanings[worker]
        #     == sum(cleaning_assignments.get((day, worker, 2), 0) for day in days if len(filtered_schedule[day]) == 3)
        # )
        # model.Add(total_zone2_cleanings[worker] == sum(cleaning_assignments.get((day, worker, 2), 0) for day in days))

    for worker in workers:
        model.Add(total_zone2_cleanings[worker] >= expected_b_count_min)
        model.Add(total_zone2_cleanings[worker] <= expected_b_count_max)

    deviations = []
    for worker in workers:
        deviation = model.NewIntVar(0, len(days), f"deviation_{worker}")
        avg_cleanings = (expected_b_count_min + expected_b_count_max) // 2
        model.AddAbsEquality(deviation, total_zone2_cleanings[worker] - avg_cleanings)
        deviations.append(deviation)

    deviations_2 = []
    for worker in workers:
        deviation2 = model.NewIntVar(0, len(days), f"deviation_{worker}_2")
        model.AddAbsEquality(deviation2, solo_zone2_cleanings[worker] - 3)
        deviations_2.append(deviation2)

    solo_cleaning_penalties = []
    for worker in workers:
        penalty = model.NewIntVar(0, len(days), f"penalty_{worker}")
        model.AddMaxEquality(penalty, [0, 2 - solo_zone2_cleanings[worker]])
        solo_cleaning_penalties.append(penalty)

    model.Minimize(sum(deviations) + sum(solo_cleaning_penalties) + sum(deviations_2))
    print("start")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120  # 최대 10초 동안만 실행되도록 설정

    best_solution = None
    best_cost = float("inf")
    iteration = 1
    solver.parameters.random_seed = iteration
    status = solver.Solve(model)
    print(status)
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        current_cost = solver.ObjectiveValue()

        if current_cost < best_cost:
            best_cost = current_cost
            best_solution = [
                (
                    day,
                    [
                        worker
                        for worker in filtered_schedule[day]
                        if solver.Value(cleaning_assignments[(day, worker, 1)])
                    ],
                    [
                        worker
                        for worker in filtered_schedule[day]
                        if solver.Value(cleaning_assignments[(day, worker, 2)])
                    ],
                )
                for day in days
            ]

    if best_solution:
        output_schedule = {}
        for day, a_zone_workers, b_zone_workers in best_solution:
            output_schedule[day] = {
                "workers": ", ".join(filtered_schedule[day]),
                "zone_A": ", ".join(a_zone_workers),
                "zone_B": ", ".join(b_zone_workers),
            }
        return output_schedule
    else:
        return None


from datetime import datetime


def solve_cleaning_schedule_logic(schedule, workers, vacation_days):
    # 휴가를 고려하여 스케줄 필터링
    filtered_schedule = {}

    def change_date_format(date):
        if isinstance(date, str):
            return datetime.strptime(date, "%Y-%m-%d").date()
        return date

    vacation_days = {change_date_format(day): workers for day, workers in vacation_days.items()}
    for day, day_workers in schedule.items():
        if isinstance(day, str):
            day = datetime.strptime(day, "%Y-%m-%d").date()

        available_workers = [w for w in day_workers if w not in vacation_days.get(day, [])]
        if available_workers:  # 근무 가능한 직원이 있는 경우에만 스케줄에 포함
            filtered_schedule[day] = available_workers

    # 청소 횟수 및 혼자 청소한 횟수 추적
    b_cleaning_count = {worker: 0 for worker in workers}  # B 구역에서 청소한 횟수
    solo_b_cleaning_count = {worker: 0 for worker in workers}  # 혼자 B 구역에서 청소한 횟수
    a_cleaning_count = {worker: 0 for worker in workers}  # A 구역에서 청소한 횟수
    previous_day_b_allocations = []  # 이전 날 B 구역에 배정된 사람들

    # B 구역 할당 결과
    b_allocations = {}
    b_weight = {}

    # 최종 출력 결과를 저장할 딕셔너리
    output_schedule = {}

    # 날짜별로 루프 실행
    for work_date, people in filtered_schedule.items():
        # A 구역에 배치할 사람 수 결정
        if len(people) <= 3:
            b_workers = 1  # A 구역에 1명 배정
            weight = 1  # 혼자서 B 구역을 맡으면 가중치 1
        else:
            b_workers = 2  # A 구역에 2명 배정
            weight = 1  # 둘 이상이 맡으면 가중치 0.5

        b_weight[work_date] = weight  # 가중치를 저장

        # B 구역에 배치할 사람 결정 (이전 날 B 구역에 배정되지 않은 사람을 우선 배정)
        available_people = set(people)  # 현재 날짜의 근무 가능한 인원들

        # 이전 날 B 구역에 있던 사람을 배제한 사람들 중 최소 청소 횟수인 사람 선택
        eligible_people = available_people - set(previous_day_b_allocations)

        # 체크를 해서 이전 날 배정된 사람을 피하고, 안되면 기존 로직대로 최소 청소 횟수인 사람 배정
        if len(eligible_people) >= b_workers:
            # 충분한 인원이 있을 경우
            b_allocations[work_date] = []
            if b_workers == 1:
                # 혼자 B 구역에서 일할 경우, eligible_people에서 선택
                least_cleaned = min((solo_b_cleaning_count[p], b_cleaning_count[p], p) for p in eligible_people)[2]
                solo_b_cleaning_count[least_cleaned] += weight  # 혼자 일한 횟수에 가중치 적용
                b_cleaning_count[least_cleaned] += weight  # 전체 청소 횟수에 가중치 적용
                b_allocations[work_date].append(least_cleaned)
            else:
                # 둘 이상일 경우, eligible_people에서 선택
                for _ in range(b_workers):
                    least_cleaned = min((b_cleaning_count[p], p) for p in eligible_people)[1]
                    b_cleaning_count[least_cleaned] += weight  # 전체 청소 횟수에 가중치 적용
                    b_allocations[work_date].append(least_cleaned)
                    eligible_people.remove(least_cleaned)
        else:
            # 충분한 인원이 없으면 기존 로직으로 돌아가기
            b_allocations[work_date] = []
            if b_workers == 1:
                # 혼자 B 구역에서 일할 경우
                least_cleaned = min((solo_b_cleaning_count[p], b_cleaning_count[p], p) for p in available_people)[2]
                solo_b_cleaning_count[least_cleaned] += weight  # 혼자 일한 횟수에 가중치 적용
                b_cleaning_count[least_cleaned] += weight  # 전체 청소 횟수에 가중치 적용
                b_allocations[work_date].append(least_cleaned)
            else:
                # 둘 이상일 경우
                for _ in range(b_workers):
                    least_cleaned = min((b_cleaning_count[p], p) for p in available_people)[1]
                    b_cleaning_count[least_cleaned] += weight  # 전체 청소 횟수에 가중치 적용
                    b_allocations[work_date].append(least_cleaned)
                    available_people.remove(least_cleaned)

        # 이전 날 B 구역에 배정된 사람 업데이트
        previous_day_b_allocations = b_allocations[work_date]

        # A 구역에 배치할 사람 결정 (B 구역에 배정되지 않은 인원들)
        available_for_a_zone = set(people) - set(b_allocations[work_date])

        # 남은 인원 모두 A 구역에 배정
        a_zone_workers = list(available_for_a_zone)

        # A 구역 배정 횟수 업데이트
        for worker in a_zone_workers:
            a_cleaning_count[worker] += 1

        # 결과를 딕셔너리로 저장
        output_schedule[work_date] = {
            "workers": ", ".join(people),
            "zone_A": ", ".join(a_zone_workers),
            "zone_B": ", ".join(b_allocations[work_date]),
            "weight_B": b_weight[work_date],
        }

    # 최종 스케줄 결과 반환
    return output_schedule
