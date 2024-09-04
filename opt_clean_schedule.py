from ortools.sat.python import cp_model
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
    # 휴가를 고려하여 스케줄 필터링
    filtered_schedule = {}
    print(schedule)
    print(vacation_days)

    def change_date_format(date):
        if isinstance(date, str):
            return datetime.strptime(date, "%Y-%m-%d")
        return date

    vacation_days = {change_date_format(day): workers for day, workers in vacation_days.items()}
    for day, day_workers in schedule.items():
        if isinstance(day, str):
            day = datetime.strptime(day, "%Y-%m-%d")

        available_workers = [w for w in day_workers if w not in vacation_days.get(day, [])]
        if available_workers:  # 근무 가능한 직원이 있는 경우에만 스케줄에 포함
            filtered_schedule[day] = available_workers

    print("Filtered schedule:", filtered_schedule)
    model = cp_model.CpModel()
    days = sorted(filtered_schedule.keys())
    num_workers = len(workers)

    expected_b_count_min, expected_b_count_max = get_b_zone_min_max(filtered_schedule)
    print(expected_b_count_min, expected_b_count_max)
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
        model.Add(
            solo_zone2_cleanings[worker]
            == sum(cleaning_assignments.get((day, worker, 2), 0) for day in days if len(filtered_schedule[day]) == 3)
        )
        model.Add(total_zone2_cleanings[worker] == sum(cleaning_assignments.get((day, worker, 2), 0) for day in days))

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

    model.Minimize(sum(deviations) + sum(deviations_2) + sum(solo_cleaning_penalties))
    print("start")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60  # 최대 10초 동안만 실행되도록 설정

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
