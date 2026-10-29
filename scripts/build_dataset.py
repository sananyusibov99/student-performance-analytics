"""Build the relational Student Performance dataset (star schema) from a flat seed CSV.

Version 2. The flat file holds one row per student; this script keeps every original attribute,
moves it to the table where it belongs and synthesises the operational tables of a school system.
Compared with version 1 (kept in StudentExamPBI_backup/generator-v1):

- schools have realistic sizes and teachers a per-term load, so ratios are plausible at any scale;
- skewed source distributions (attendance, stress, assignment completion, anxiety) are calibrated
  to benchmark levels by rank mapping: every student keeps their position, only the scale changes;
- exam scores = student ability + school effect + teacher effect + programme effect + noise,
  so value added and programme effects are real and can be recovered;
- attendance has month and weekday seasonality and is stored as exceptions (late/absent days only);
- LMS activity rises in exam weeks;
- ground-truth effects and a validation report go to data/truth/.

All parameters live in generator_config.json.

Usage:
    py -3.13 -I build_dataset.py <source csv> <model dir> <truth dir> [--config generator_config.json]
"""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TERMS = [
    # term_key, academic_year, term_name, start, end, breaks (inclusive ranges)
    (1, "2024/25", "Spring 2025", date(2025, 1, 13), date(2025, 5, 30), [(date(2025, 3, 17), date(2025, 3, 21))]),
    (2, "2025/26", "Fall 2025", date(2025, 9, 1), date(2025, 12, 19), [(date(2025, 11, 27), date(2025, 11, 28))]),
    (3, "2025/26", "Spring 2026", date(2026, 1, 12), date(2026, 5, 29), [(date(2026, 3, 23), date(2026, 3, 27))]),
]
CURRENT_TERMS = [2, 3]          # terms with full operational data; term 1 holds prior-year finals only
PRIOR_TERM = 1
GRADE_BANDS = [(85, "A", 4.0), (75, "B", 3.0), (65, "C", 2.0), (50, "D", 1.0), (0, "F", 0.0)]
PLACES = ["Riverside", "Oakridge", "Hillcrest", "Lakeview", "Maplewood", "Northgate", "Westbrook",
          "Eastwood", "Cedar Park", "Silver Creek", "Brookfield", "Pinecrest", "Fairview", "Stonebridge",
          "Willow Glen", "Highland", "Clearwater", "Ashford", "Kingsley", "Meadowvale", "Summit",
          "Harborview", "Elmhurst", "Greenfield", "Bayside", "Foxborough", "Redwood", "Sunnyvale"]
DISTRICTS = ["North", "South", "East", "West", "Central"]
FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Jamie", "Robin", "Avery", "Riley",
         "Elena", "Omar", "Lina", "David", "Sara", "Ivan", "Maria", "Ali", "Nina", "Leo",
         "Hana", "Marco", "Aisha", "Tom", "Yuki", "Pavel", "Zara", "Noah", "Ines", "Kemal"]
LAST = ["Smith", "Novak", "Garcia", "Kim", "Ivanova", "Hassan", "Muller", "Rossi", "Silva", "Brown",
        "Petrov", "Aliyev", "Khan", "Nowak", "Lopez", "Weber", "Costa", "Moreau", "Sato", "Clark",
        "Fischer", "Haddad", "Larsen", "Okafor", "Romano", "Tanaka", "Yilmaz", "Dubois", "Kowalski", "Reyes"]
KINDS = ["Homework", "Quiz", "Homework", "Lab", "Homework", "Project"]
KIND_WEIGHT = {"Homework": 0.05, "Quiz": 0.10, "Lab": 0.15, "Project": 0.25}


def date_key(d):
    return d.year * 10000 + d.month * 100 + d.day


def grade_of(score):
    for low, letter, points in GRADE_BANDS:
        if score >= low:
            return letter, points
    return "F", 0.0


def term(term_key):
    return next(t for t in TERMS if t[0] == term_key)


def school_days(t):
    _, _, _, start, end, breaks = t
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and not any(a <= d <= b for a, b in breaks):
            days.append(d)
        d += timedelta(days=1)
    return days


def rank_map(x, target_sample, rng):
    """Replace the values of x by a sorted target sample, keeping each element's rank (ties broken randomly)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    idx = np.flatnonzero(~np.isnan(x))
    order = idx[np.lexsort((rng.random(len(idx)), x[idx]))]
    out[order] = np.sort(target_sample(len(idx)))
    return out


def beta_sampler(rng, mean, sd):
    k = mean * (1 - mean) / sd ** 2 - 1
    return lambda size: rng.beta(mean * k, (1 - mean) * k, size)


def build_dim_date():
    school = {d for t in TERMS for d in school_days(t)}
    rows, d = [], date(2025, 1, 1)
    while d <= date(2026, 6, 30):
        rows.append({
            "date_key": date_key(d), "date": d.isoformat(), "year": d.year,
            "quarter": (d.month - 1) // 3 + 1, "month": d.month, "month_name": d.strftime("%B"),
            "week_of_year": d.isocalendar()[1], "day_of_week": d.isoweekday(), "day_name": d.strftime("%A"),
            "is_weekend": d.weekday() >= 5, "is_school_day": d in school,
            "term_key": next((t[0] for t in TERMS if t[3] <= d <= t[4]), None),
            "academic_year": "2024/25" if d < date(2025, 7, 1) else "2025/26",
        })
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def build(src, cfg):
    rng = np.random.default_rng(cfg["seed"])
    raw = pd.read_csv(src).sample(n=min(cfg["students"], 100000), random_state=cfg["seed"]).reset_index(drop=True)
    n = len(raw)
    num = lambda c: pd.to_numeric(raw[c], errors="coerce").to_numpy(dtype=float)
    eff = cfg["effects"]
    cal = cfg["calibration"]
    truth = {}

    # ---------------- calibrated student traits ----------------
    att_src = num("attendance_percentage")
    att_src = np.where(np.isnan(att_src), rng.choice(att_src[~np.isnan(att_src)], n), att_src)
    attendance = rank_map(att_src, beta_sampler(rng, cal["attendance"]["mean"], cal["attendance"]["sd"]), rng)
    completion = rank_map(num("assignment_completion_rate"), beta_sampler(rng, cal["completion"]["mean"], cal["completion"]["sd"]), rng)
    stress = rank_map(num("stress_level"), lambda k: np.clip(np.round(rng.normal(cal["stress"]["mean"], cal["stress"]["sd"], k)), 1, 10), rng).astype(int)
    anxiety = rank_map(num("exam_anxiety_level"), lambda k: np.clip(rng.normal(cal["anxiety"]["mean"], cal["anxiety"]["sd"], k), 1, 10), rng)
    now, prev = num("exam_score"), num("previous_exam_score")
    tm = np.nan_to_num(num("time_management_score"), nan=np.nanmean(num("time_management_score")))

    # ---------------- calendar ----------------
    dim_date = build_dim_date()
    dim_term = pd.DataFrame([{
        "term_key": t[0], "academic_year": t[1], "term_name": t[2], "start_date": t[3].isoformat(),
        "end_date": t[4].isoformat(), "instructional_days": len(school_days(t)), "is_current_year": t[1] == "2025/26",
    } for t in TERMS])

    # ---------------- schools: realistic size first, then location ----------------
    schools, school_of = [], np.zeros(n, dtype=int)
    for (level, stype), grp in raw.groupby(["education_level", "school_type"]):
        k = max(1, round(len(grp) / cfg["school_size"][level]))
        share = grp["urban_rural"].value_counts(normalize=True)
        seats = np.floor(share * k).astype(int)
        for a in (share * k - seats).sort_values(ascending=False).index[: k - seats.sum()]:
            seats[a] += 1
        keys = []
        for area, cnt in seats.items():
            for _ in range(cnt):
                i = len(schools)
                noun = "High School" if level == "High School" else "College"
                budget = int({"Public": 7000, "Charter": 8500, "Private": 15000}[stype] * rng.uniform(0.8, 1.25))
                schools.append({
                    "school_key": i + 1, "school_code": f"SCH{i + 1:03d}",
                    "school_name": f"{PLACES[i % len(PLACES)]} {stype} {noun}",
                    "institution_level": level, "school_type": stype, "urban_rural": area,
                    "district": DISTRICTS[i % len(DISTRICTS)], "founded_year": int(rng.integers(1955, 2018)),
                    "capacity": 0, "budget_per_student_usd": budget,
                    "has_library": bool(rng.random() < (0.95 if stype != "Charter" else 0.75)),
                    "has_stem_lab": bool(rng.random() < (0.9 if stype == "Private" else 0.6)),
                })
                keys.append((i + 1, area))
        for s, area in zip(grp.index, grp["urban_rural"]):
            same = [k_ for k_, a in keys if a == area] or [k_ for k_, _ in keys]
            school_of[s] = rng.choice(same)
    dim_school = pd.DataFrame(schools)
    sizes = np.bincount(school_of, minlength=len(schools) + 1)[1:]
    dim_school["capacity"] = (np.ceil(sizes * rng.uniform(1.05, 1.3, len(sizes)) / 50) * 50).astype(int)
    budget = dim_school["budget_per_student_usd"].to_numpy()
    school_eff = rng.normal(0, eff["school_sd"], len(schools)) + eff["school_per_1000_budget"] * (budget - budget.mean()) / 1000
    school_eff -= school_eff.mean()
    truth["school_effects"] = pd.DataFrame({"school_key": dim_school["school_key"], "true_effect": school_eff.round(3)})
    s_eff = school_eff[school_of - 1]

    # ---------------- students ----------------
    age = num("age")
    birth = [date(2025, 9, 1) - timedelta(days=int(a * 365.25 + rng.integers(0, 365))) for a in age]
    hs = (raw["education_level"] == "High School").to_numpy()
    grade_level = np.where(hs, np.clip(age - 6, 9, 12), np.clip(age - 17, 1, 4)).astype(int)
    cohort = np.where(hs, 2025 - (grade_level - 9), 2025 - (grade_level - 1))
    area_of = dim_school.set_index("school_key")["urban_rural"]
    dim_student = pd.DataFrame({
        "student_key": np.arange(1, n + 1), "student_id": raw["student_id"], "school_key": school_of,
        "gender": raw["gender"], "birth_date": [b.isoformat() for b in birth], "education_level": raw["education_level"],
        "grade_level": [f"Grade {g}" if h else f"Year {g}" for g, h in zip(grade_level, hs)],
        "cohort_year": cohort, "enrollment_date": [date(int(c), 9, 1).isoformat() for c in cohort],
        "family_income": raw["family_income"], "parent_education": raw["parent_education"].fillna("Not specified"),
        "internet_access": num("internet_access").astype(int),
        "device_availability": raw["device_availability"].fillna("Not specified"),
        "scholarship_flag": (rng.random(n) < np.where(raw["family_income"].isin(["Low", "Lower-Middle"]), 0.25, 0.05)).astype(int),
        "special_needs_flag": (rng.random(n) < 0.08).astype(int),
        "commute_km": np.round(np.where(area_of[school_of].to_numpy() == "Rural", rng.gamma(3, 4, n), rng.gamma(2, 2.5, n)), 1),
        "entry_gpa": num("previous_gpa"),
    })

    # ---------------- subjects and course choice ----------------
    subj = cfg["subjects"]
    dim_subject = pd.DataFrame([{"subject_key": i + 1, "subject_name": s["name"], "department": s["department"],
                                 "credits": s["credits"], "is_core": s["core"]} for i, s in enumerate(subj)])
    core = [i for i, s in enumerate(subj) if s["core"]]
    elect = [i for i, s in enumerate(subj) if not s["core"]]
    takes = np.zeros((n, len(subj)), dtype=bool)
    takes[:, core] = True
    k_el = cfg["subjects_per_student"] - len(core)
    for s in range(n):
        takes[s, rng.choice(elect, k_el, replace=False)] = True

    # ---------------- classes and teachers (load per term) ----------------
    teachers, classes = [], []
    cls = {t: np.zeros((n, len(subj)), dtype=int) for t in CURRENT_TERMS}
    load = cfg["sections_per_teacher_per_term"]
    for sk in dim_school["school_key"]:
        members = np.flatnonzero(school_of == sk)
        for j in range(len(subj)):
            roster = members[takes[members, j]]
            if len(roster) == 0:
                continue
            n_sec = max(1, int(np.ceil(len(roster) / cfg["section_size"])))
            t_keys = []
            for _ in range(int(np.ceil(n_sec / load))):
                exp = int(rng.integers(0, 31))
                teachers.append({
                    "teacher_key": len(teachers) + 1, "teacher_code": f"T{len(teachers) + 1:05d}",
                    "teacher_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "school_key": sk, "subject_key": j + 1,
                    "gender": rng.choice(["Female", "Male"]), "years_experience": exp,
                    "qualification": rng.choice(["Bachelor", "Master", "PhD"], p=[0.45, 0.45, 0.10]),
                    "employment_type": rng.choice(["Full-time", "Part-time"], p=[0.85, 0.15]),
                    "hire_date": date(2025 - min(exp, 20), 8, 15).isoformat(),
                })
                t_keys.append(len(teachers))
            for t in CURRENT_TERMS:
                order = rng.permutation(roster)
                for sec in range(n_sec):
                    ck = len(classes) + 1
                    classes.append({
                        "class_key": ck, "class_code": f"{sk:03d}-{subj[j]['name'][:4].upper()}-{t}{sec + 1:02d}",
                        "school_key": sk, "subject_key": j + 1, "term_key": t, "teacher_key": t_keys[sec % len(t_keys)],
                        "section": sec + 1, "room": f"R{int(rng.integers(100, 400))}", "capacity": cfg["section_size"] + 4,
                        "schedule_slot": rng.choice(["Mon/Wed 09:00", "Tue/Thu 10:30", "Mon/Wed 13:00", "Tue/Thu 14:30", "Fri 09:00"]),
                    })
                    cls[t][order[sec::n_sec], j] = ck
    dim_teacher = pd.DataFrame(teachers)
    dim_class = pd.DataFrame(classes)
    exp_years = dim_teacher["years_experience"].to_numpy()
    teacher_eff = rng.normal(0, eff["teacher_sd"], len(teachers)) + eff["teacher_per_experience_year"] * (
        np.minimum(exp_years, eff["teacher_experience_cap"]) - eff["teacher_experience_cap"] / 2)
    teacher_eff -= teacher_eff.mean()
    truth["teacher_effects"] = pd.DataFrame({"teacher_key": dim_teacher["teacher_key"], "true_effect": teacher_eff.round(3)})
    class_teacher_eff = np.concatenate([[0.0], teacher_eff[dim_class["teacher_key"].to_numpy() - 1]])

    # ---------------- programmes decided before the year ----------------
    tuition = num("private_tuition") == 1
    mentoring = rng.random(n) < eff["mentoring_rate"]
    counseling = (stress >= 9) & (rng.random(n) < eff["counseling_rate"])
    prog = eff["programs"]

    # ---------------- exams, generated in date order ----------------
    diff_p = raw["exam_difficulty"].value_counts(normalize=True)
    plan = []
    for j in range(len(subj)):
        plan.append((j, PRIOR_TERM, "Final", date(2025, 5, 26)))
        for t in CURRENT_TERMS:
            tt = term(t)
            mid = tt[3] + (tt[4] - tt[3]) / 2
            while mid.weekday() >= 5:
                mid += timedelta(days=1)
            plan.append((j, t, "Midterm", mid))
            plan.append((j, t, "Final", tt[4] - timedelta(days=4)))
    plan.sort(key=lambda p: (p[3], p[0]))
    dim_exam = pd.DataFrame([{
        "exam_key": i + 1, "subject_key": j + 1, "term_key": t, "exam_type": typ, "exam_date_key": date_key(d),
        "difficulty": rng.choice(diff_p.index, p=diff_p.values), "max_score": 100, "pass_mark": 50,
        "question_count": 100, "duration_min": 90 if typ == "Midterm" else 120,
        "weight_in_term": 0.4 if typ == "Midterm" else 0.6,
    } for i, (j, t, typ, d) in enumerate(plan)])
    progress = {(PRIOR_TERM, "Final"): 0.0, (2, "Midterm"): 0.25, (2, "Final"): 0.5, (3, "Midterm"): 0.75, (3, "Final"): 1.0}
    diff_shift = {"Easy": 3.0, "Medium": 0.0, "Hard": -4.0}
    withdraw_p = 0.008 + 0.05 * (now < 45) + 0.03 * (attendance < 0.88)
    withdrawn = {t: (rng.random((n, len(subj))) < withdraw_p[:, None]) & (cls[t] > 0) for t in CURRENT_TERMS}
    remedial = np.zeros(n, dtype=bool)
    parts, fall = [], []
    for e in dim_exam.itertuples():
        j, t, typ = e.subject_key - 1, e.term_key, e.exam_type
        if t == 3 and not remedial.any() and fall:
            fall_avg = pd.concat(fall).groupby("s")["score"].mean()
            remedial[fall_avg.index[fall_avg < eff["remedial_threshold"]]] = True
        w = progress[(t, typ)]
        idx = np.flatnonzero(takes[:, j])
        if t != PRIOR_TERM:
            idx = idx[~(withdrawn[t][idx, j] & (typ == "Final"))]
        ck = cls[t][idx, j] if t != PRIOR_TERM else np.zeros(len(idx), dtype=int)
        stage = 0.0 if t == PRIOR_TERM else (0.6 if typ == "Midterm" else 1.0)
        spring = 1.0 if t == 3 else 0.0
        score = ((1 - w) * prev[idx] + w * now[idx] + subj[j]["offset"] + diff_shift[e.difficulty] + eff["score_shift"]
                 + w * s_eff[idx] + stage * class_teacher_eff[ck]
                 + prog["Private tuition"] * tuition[idx] * w
                 + prog["Remedial class"] * remedial[idx] * spring * stage
                 + prog["Peer mentoring"] * mentoring[idx] * spring * stage
                 + prog["Counseling"] * counseling[idx] * (t != PRIOR_TERM) * (1.0 if (t == 3 or typ == "Final") else 0.5)
                 + rng.normal(0, eff["noise_sd"], len(idx)))
        score = np.clip(score, 0, 100)
        no_show = rng.random(len(idx)) < 0.012 + 0.02 * (anxiety[idx] > 8.5)
        part = pd.DataFrame({"s": idx, "exam_key": e.exam_key, "class_key": ck, "date_key": e.exam_date_key,
                             "score": score, "no_show": no_show, "term_key": t, "exam_type": typ, "subject": j})
        parts.append(part)
        if t == 2:
            fall.append(part[~part["no_show"]])
    res = pd.concat(parts, ignore_index=True)
    sc, s_idx, ns = res["score"].to_numpy(), res["s"].to_numpy(), res["no_show"].to_numpy()
    attempted0 = num("questions_attempted")
    correct = np.where(ns, np.nan, np.round(sc))
    attempted = np.where(ns, np.nan, np.maximum(correct, np.clip(attempted0[s_idx] + rng.integers(-3, 4, len(res)), 0, 100)))
    prep = num("exam_preparation_days")
    fact_exam_result = pd.DataFrame({
        "exam_result_key": np.arange(1, len(res) + 1), "student_key": s_idx + 1, "exam_key": res["exam_key"],
        "class_key": res["class_key"].replace(0, np.nan).astype("Int64"), "date_key": res["date_key"],
        "attendance_status": np.where(ns, "No-show", "Sat"), "score": np.where(ns, np.nan, np.round(sc, 2)),
        "questions_attempted": attempted, "questions_correct": correct,
        "time_spent_min": np.where(ns, np.nan, np.round(rng.normal(75, 15, len(res)).clip(25, 120))),
        "preparation_days": np.clip(prep[s_idx] + rng.integers(-5, 6, len(res)), 1, 30),
        "exam_anxiety_level": np.round(np.clip(anxiety[s_idx] + rng.normal(0, 0.6, len(res)), 1, 10), 2),
        "time_management_score": np.round(tm[s_idx], 2),
        "grade_letter": np.where(ns, None, [grade_of(x)[0] for x in sc]),
        "is_pass": np.where(ns, 0, (sc >= 50).astype(int)),
    })

    # ---------------- enrolments ----------------
    sat = res[~res["no_show"] & (res["term_key"] != PRIOR_TERM)].copy()
    sat["wt"] = np.where(sat["exam_type"] == "Midterm", 0.4, 0.6)
    sat["ws"] = sat["score"] * sat["wt"]
    g = sat.groupby(["class_key", "s"])[["ws", "wt"]].sum()
    course_score = (g["ws"] / g["wt"]).to_dict()
    enrol = []
    for t in CURRENT_TERMS:
        tt = term(t)
        ss, jj = np.nonzero(cls[t])
        for s, j in zip(ss, jj):
            ck = cls[t][s, j]
            wd = withdrawn[t][s, j]
            avg = course_score.get((ck, s), np.nan)
            letter, points = grade_of(avg) if not (wd or np.isnan(avg)) else (None, np.nan)
            credits = subj[j]["credits"]
            enrol.append((s + 1, ck, t, date_key(tt[3] - timedelta(days=int(rng.integers(3, 20)))),
                          "Withdrawn" if wd else "Completed",
                          date_key(tt[3] + timedelta(days=int(rng.integers(30, 80)))) if wd else None,
                          None if wd or np.isnan(avg) else round(avg, 2), letter, points, credits,
                          0 if wd or points == 0 or np.isnan(points) else credits))
    fact_enrollment = pd.DataFrame(enrol, columns=["student_key", "class_key", "term_key", "enroll_date_key", "status",
                                                   "withdraw_date_key", "final_score", "final_grade", "grade_points",
                                                   "credits_attempted", "credits_earned"])
    fact_enrollment.insert(0, "enrollment_key", np.arange(1, len(fact_enrollment) + 1))
    fact_enrollment["withdraw_date_key"] = fact_enrollment["withdraw_date_key"].astype("Int64")

    # ---------------- attendance: seasonal, stored as exceptions ----------------
    seas = cfg["seasonality"]
    days = [d for t in CURRENT_TERMS for d in school_days(term(t))]
    f = np.array([seas["month_attendance"][str(d.month)] * seas["weekday_attendance"][str(d.isoweekday())] for d in days])
    f /= f.mean()
    p_present = np.clip(attendance[:, None] * f[None, :], 0, 1)
    present = rng.random((n, len(days))) < p_present
    late = present & (rng.random((n, len(days))) < ((0.02 + 0.06 * (tm < 60))[:, None] * np.where([d.isoweekday() == 1 for d in days], 1.4, 1.0)))
    excused = rng.random((n, len(days))) < 0.45
    status = np.where(present, np.where(late, "Late", ""), np.where(excused, "Excused", "Absent"))
    s_i, d_i = np.nonzero(status != "")
    day_keys = np.array([date_key(d) for d in days])
    fact_attendance = pd.DataFrame({"student_key": s_i + 1, "date_key": day_keys[d_i], "school_key": school_of[s_i],
                                    "status": status[s_i, d_i]})
    fact_attendance["minutes_late"] = np.where(fact_attendance["status"] == "Late", rng.integers(5, 40, len(fact_attendance)), 0)

    # ---------------- assignments and submissions ----------------
    a_rows = []
    sd_cache = {t: school_days(term(t)) for t in CURRENT_TERMS}
    for c in dim_class.itertuples():
        sd = sd_cache[c.term_key]
        for i, kind in enumerate(KINDS):
            pos = int(len(sd) * i / len(KINDS))
            a_rows.append((len(a_rows) + 1, c.class_key, kind, f"{kind} {i + 1}", date_key(sd[pos]),
                           date_key(sd[min(len(sd) - 1, pos + (10 if kind == "Project" else 4))]),
                           100 if kind in ("Project", "Lab") else 20, KIND_WEIGHT[kind]))
    dim_assignment = pd.DataFrame(a_rows, columns=["assignment_key", "class_key", "assignment_type", "title",
                                                   "assigned_date_key", "due_date_key", "max_points", "weight"])
    roster = pd.DataFrame([(cls[t][s, j], s) for t in CURRENT_TERMS for s, j in zip(*np.nonzero(cls[t]))], columns=["class_key", "s"])
    sub = dim_assignment.merge(roster, on="class_key")
    si = sub["s"].to_numpy()
    submitted = rng.random(len(sub)) < completion[si]
    late_sub = submitted & (rng.random(len(sub)) < 0.07 + 0.12 * (tm[si] < 60))
    days_late = np.where(late_sub, rng.integers(1, 6, len(sub)), 0)
    due = pd.to_datetime(sub["due_date_key"].astype(str), format="%Y%m%d")
    sub_date = due + pd.to_timedelta(np.where(late_sub, days_late, -rng.integers(0, 3, len(sub))), unit="D")
    pct = np.clip(now[si] + 10 + 0.5 * class_teacher_eff[sub["class_key"].to_numpy()] + rng.normal(0, 10, len(sub)) - 5 * late_sub, 0, 100) / 100
    fact_submission = pd.DataFrame({
        "submission_key": np.arange(1, len(sub) + 1), "assignment_key": sub["assignment_key"], "student_key": si + 1,
        "submitted_date_key": pd.array(np.where(submitted, sub_date.dt.strftime("%Y%m%d").astype(int), 0), dtype="Int64"),
        "status": np.where(~submitted, "Missing", np.where(late_sub, "Late", "On time")),
        "days_late": pd.array(np.where(submitted, days_late, -1), dtype="Int64"),
        "points_earned": np.where(submitted, np.round(pct * sub["max_points"], 1), np.nan),
        "max_points": sub["max_points"],
    })
    fact_submission.loc[~submitted, ["submitted_date_key", "days_late"]] = pd.NA

    # ---------------- weekly LMS activity, busier in exam weeks ----------------
    weeks = sorted({d - timedelta(days=d.weekday()) for d in days})
    exam_days = {date(int(k) // 10000, int(k) // 100 % 100, int(k) % 100) for k in dim_exam.loc[dim_exam["term_key"] != PRIOR_TERM, "exam_date_key"]}
    exam_weeks = {d - timedelta(days=d.weekday()) for d in exam_days} | {d - timedelta(days=d.weekday() + 7) for d in exam_days}
    wf = np.array([seas["lms_exam_week_factor"] if w_ in exam_weeks else 1.0 for w_ in weeks])
    online, course = num("online_learning_hours"), num("online_course_hours")
    app_level = raw["educational_app_usage"].map({"Low": 20, "Moderate": 60, "High": 140}).to_numpy(dtype=float)
    net = np.where(num("internet_access") == 1, 1.0, 0.35)
    noise = rng.gamma(4, 0.25, (n, len(weeks))) * wf[None, :]
    fact_lms = pd.DataFrame({
        "student_key": np.repeat(np.arange(1, n + 1), len(weeks)),
        "week_start_date_key": np.tile([date_key(x) for x in weeks], n),
        "logins": rng.poisson((4 + online)[:, None] * net[:, None] * noise).ravel(),
        "online_learning_min": np.round((online * 60 * 5)[:, None] * net[:, None] * noise).ravel(),
        "online_course_min": np.round((course * 60)[:, None] * net[:, None] * noise).ravel(),
        "edu_app_min": np.round(app_level[:, None] * net[:, None] * noise).ravel(),
        "videos_watched": rng.poisson(np.maximum(online, 0.2)[:, None] * 2 * net[:, None] * noise).ravel(),
        "forum_posts": rng.poisson(0.6 * noise).ravel(),
    })

    # ---------------- wellbeing survey ----------------
    habits = ["study_hours_per_day", "self_study_hours", "sleep_hours", "daily_screen_time", "physical_activity_hours"]
    cats = ["sleep_quality", "class_participation", "study_consistency", "study_environment", "study_method",
            "revision_frequency", "notes_quality", "break_frequency", "motivation_level", "educational_app_usage"]
    surveys = []
    for t, drift in ((2, -1), (3, 0)):
        d = pd.DataFrame({"student_key": np.arange(1, n + 1), "term_key": t, "survey_date_key": date_key(term(t)[3] + timedelta(days=45))})
        for h in habits:
            d[h] = np.round(np.clip(num(h) + (drift * rng.normal(0, 0.3, n) if drift else 0), 0, 24), 2)
        spring_stress = stress - counseling.astype(int)
        d["stress_level"] = np.clip(stress if t == 2 else spring_stress, 1, 10).astype(int)
        d["practice_tests_completed"] = np.clip(num("practice_tests_completed") + drift * rng.integers(0, 3, n), 0, None).astype(int)
        for c in cats:
            d[c] = raw[c].fillna("Not specified").to_numpy()
        surveys.append(d)
    fact_survey = pd.concat(surveys, ignore_index=True)
    fact_survey.insert(0, "survey_key", np.arange(1, len(fact_survey) + 1))

    # ---------------- behaviour incidents ----------------
    lam = 0.15 + 0.45 * (attendance < 0.88) + 0.2 * (stress >= 8) + 0.3 * (raw["motivation_level"] == "Low").to_numpy()
    counts = rng.poisson(lam)
    types = ["Late arrival", "Classroom disruption", "Phone misuse", "Academic dishonesty", "Bullying", "Truancy"]
    inc = []
    for s in np.flatnonzero(counts):
        for _ in range(counts[s]):
            typ = rng.choice(types, p=[0.32, 0.25, 0.2, 0.08, 0.05, 0.10])
            sev = "Major" if typ in ("Bullying", "Academic dishonesty") and rng.random() < 0.5 else rng.choice(["Minor", "Moderate"], p=[0.7, 0.3])
            action = {"Minor": "Warning", "Moderate": "Detention", "Major": "Suspension"}[sev]
            inc.append((s + 1, school_of[s], day_keys[int(rng.integers(0, len(days)))], typ, sev, action,
                        int(rng.integers(1, 4)) if action == "Suspension" else 0))
    fact_incident = pd.DataFrame(inc, columns=["student_key", "school_key", "date_key", "incident_type", "severity",
                                               "action_taken", "suspension_days"]).sort_values("date_key")
    fact_incident.insert(0, "incident_key", np.arange(1, len(fact_incident) + 1))

    # ---------------- support interventions ----------------
    iv = []

    def add(s, typ, provider, start, end, planned, cost):
        attended = int(rng.binomial(planned, np.clip(attendance[s] - 0.05, 0.3, 1)))
        iv.append((s + 1, typ, provider, date_key(start), date_key(end), planned, attended, round(attended * cost, 2)))
    for s in range(n):
        if tuition[s]:
            add(s, "Private tuition", "External", date(2025, 9, 15), date(2026, 5, 22), 60, float(rng.uniform(20, 40)))
        if remedial[s]:
            add(s, "Remedial class", "School", date(2026, 1, 19), date(2026, 5, 15), 24, 0.0)
        if counseling[s]:
            add(s, "Counseling", "School", date(2025, 10, 6), date(2025, 12, 12), 8, 0.0)
        if mentoring[s]:
            add(s, "Peer mentoring", "School", date(2026, 1, 19), date(2026, 4, 30), 12, 0.0)
    fact_intervention = pd.DataFrame(iv, columns=["student_key", "intervention_type", "provider", "start_date_key",
                                                  "end_date_key", "sessions_planned", "sessions_attended", "cost_usd"])
    fact_intervention.insert(0, "intervention_key", np.arange(1, len(fact_intervention) + 1))
    truth["programs"] = prog
    truth["n_school_days"] = len(days)

    tables = {
        "dim_date": dim_date, "dim_term": dim_term, "dim_school": dim_school, "dim_student": dim_student,
        "dim_subject": dim_subject, "dim_teacher": dim_teacher, "dim_class": dim_class, "dim_exam": dim_exam,
        "dim_assignment": dim_assignment,
        "fact_enrollment": fact_enrollment, "fact_exam_result": fact_exam_result, "fact_attendance": fact_attendance,
        "fact_assignment_submission": fact_submission, "fact_lms_activity": fact_lms,
        "fact_wellbeing_survey": fact_survey, "fact_behavior_incident": fact_incident,
        "fact_intervention": fact_intervention,
    }
    return tables, truth


# primary keys and foreign keys, used for the integrity check and documented in DATA_MODEL.md
PK = {"dim_date": ["date_key"], "dim_term": ["term_key"], "dim_school": ["school_key"], "dim_student": ["student_key"],
      "dim_subject": ["subject_key"], "dim_teacher": ["teacher_key"], "dim_class": ["class_key"], "dim_exam": ["exam_key"],
      "dim_assignment": ["assignment_key"], "fact_enrollment": ["enrollment_key"], "fact_exam_result": ["exam_result_key"],
      "fact_attendance": ["student_key", "date_key"], "fact_assignment_submission": ["submission_key"],
      "fact_lms_activity": ["student_key", "week_start_date_key"], "fact_wellbeing_survey": ["survey_key"],
      "fact_behavior_incident": ["incident_key"], "fact_intervention": ["intervention_key"]}
FK = [
    ("dim_date", "term_key", "dim_term", "term_key"),
    ("dim_student", "school_key", "dim_school", "school_key"),
    ("dim_teacher", "school_key", "dim_school", "school_key"),
    ("dim_teacher", "subject_key", "dim_subject", "subject_key"),
    ("dim_class", "school_key", "dim_school", "school_key"),
    ("dim_class", "subject_key", "dim_subject", "subject_key"),
    ("dim_class", "term_key", "dim_term", "term_key"),
    ("dim_class", "teacher_key", "dim_teacher", "teacher_key"),
    ("dim_exam", "subject_key", "dim_subject", "subject_key"),
    ("dim_exam", "term_key", "dim_term", "term_key"),
    ("dim_exam", "exam_date_key", "dim_date", "date_key"),
    ("dim_assignment", "class_key", "dim_class", "class_key"),
    ("dim_assignment", "due_date_key", "dim_date", "date_key"),
    ("fact_enrollment", "student_key", "dim_student", "student_key"),
    ("fact_enrollment", "class_key", "dim_class", "class_key"),
    ("fact_enrollment", "term_key", "dim_term", "term_key"),
    ("fact_enrollment", "enroll_date_key", "dim_date", "date_key"),
    ("fact_exam_result", "student_key", "dim_student", "student_key"),
    ("fact_exam_result", "exam_key", "dim_exam", "exam_key"),
    ("fact_exam_result", "class_key", "dim_class", "class_key"),
    ("fact_exam_result", "date_key", "dim_date", "date_key"),
    ("fact_attendance", "student_key", "dim_student", "student_key"),
    ("fact_attendance", "date_key", "dim_date", "date_key"),
    ("fact_attendance", "school_key", "dim_school", "school_key"),
    ("fact_assignment_submission", "assignment_key", "dim_assignment", "assignment_key"),
    ("fact_assignment_submission", "student_key", "dim_student", "student_key"),
    ("fact_lms_activity", "student_key", "dim_student", "student_key"),
    ("fact_lms_activity", "week_start_date_key", "dim_date", "date_key"),
    ("fact_wellbeing_survey", "student_key", "dim_student", "student_key"),
    ("fact_wellbeing_survey", "term_key", "dim_term", "term_key"),
    ("fact_behavior_incident", "student_key", "dim_student", "student_key"),
    ("fact_behavior_incident", "date_key", "dim_date", "date_key"),
    ("fact_intervention", "student_key", "dim_student", "student_key"),
    ("fact_intervention", "start_date_key", "dim_date", "date_key"),
]


def check(tables):
    ok = True
    for name, cols in PK.items():
        dup = tables[name].duplicated(subset=cols).sum()
        nulls = tables[name][cols].isna().any(axis=1).sum()
        if dup or nulls:
            ok = False
            print(f"PK FAIL {name}{cols}: {dup} duplicates, {nulls} nulls")
    for child, col, parent, pcol in FK:
        vals = pd.to_numeric(tables[child][col], errors="coerce").dropna()
        orphans = (~vals.isin(tables[parent][pcol])).sum()
        if orphans:
            ok = False
            print(f"FK FAIL {child}.{col} -> {parent}.{pcol}: {orphans} orphans")
    print("integrity:", "OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    from validate_dataset import validate  # noqa: E402  (sibling module)

    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("truth")
    ap.add_argument("--config", default=str(Path(__file__).with_name("generator_config.json")))
    a = ap.parse_args()
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    tbls, tru = build(Path(a.source), config)
    out, tdir = Path(a.out), Path(a.truth)
    out.mkdir(parents=True, exist_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    for name, df in tbls.items():
        df.to_csv(out / f"{name}.csv", index=False)
    tru["teacher_effects"].to_csv(tdir / "teacher_effects.csv", index=False)
    tru["school_effects"].to_csv(tdir / "school_effects.csv", index=False)
    (tdir / "program_effects.json").write_text(json.dumps(tru["programs"], indent=1), encoding="utf-8")
    good = check(tbls)
    report = validate(tbls, tru, config)
    (tdir / "validation_report.md").write_text(report, encoding="utf-8")
    tru["evaluation"].to_csv(tdir / "program_evaluation.csv", index=False)
    print(report)
    raise SystemExit(0 if good else 1)
