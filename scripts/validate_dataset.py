"""Validation report for build_dataset.py: KPI levels against config targets and recovery of the
ground-truth teacher and programme effects. Returns Markdown."""
import numpy as np
import pandas as pd


def _per_student(res, exams, term_key, exam_type=None):
    r = res.merge(exams[["exam_key", "term_key", "exam_type"]], on="exam_key")
    r = r[(r["term_key"] == term_key) & (r["attendance_status"] == "Sat")]
    if exam_type:
        r = r[r["exam_type"] == exam_type]
    return r.groupby("student_key")["score"].mean()


def validate(t, truth, cfg):
    n = len(t["dim_student"])
    days = truth["n_school_days"]
    res, exams = t["fact_exam_result"], t["dim_exam"]
    att, sub, enr = t["fact_attendance"], t["fact_assignment_submission"], t["fact_enrollment"]
    survey = t["fact_wellbeing_survey"]

    absent = att[att["status"].isin(["Excused", "Absent"])].groupby("student_key").size().reindex(t["dim_student"]["student_key"], fill_value=0)
    current = res.merge(exams[["exam_key", "term_key"]], on="exam_key")
    current = current[(current["term_key"] != 1) & (current["attendance_status"] == "Sat")]
    kpi = {
        "Students per Teacher": n / len(t["dim_teacher"]),
        "Avg Class Size": len(enr) / len(t["dim_class"]),
        "Attendance Rate": 1 - absent.sum() / (n * days),
        "Chronic Absentee Rate": (absent / days > 0.10).mean(),
        "Completion Rate": (sub["status"] != "Missing").mean(),
        "On-time Rate": (sub["status"] == "On time").sum() / (sub["status"] != "Missing").sum(),
        "Exam Pass Rate": current["is_pass"].mean(),
        "Course Withdrawal Rate": (enr["status"] == "Withdrawn").mean(),
        "Incidents per 100": len(t["fact_behavior_incident"]) / n * 100,
        "Program Reach": t["fact_intervention"]["student_key"].nunique() / n,
        "High Stress Share": (survey["stress_level"] >= 8).mean(),
    }

    # ---- teacher value added: growth over the prior-year final in the same subject, vs subject-term mean ----
    prior = res.merge(exams[["exam_key", "term_key", "exam_type", "subject_key"]], on="exam_key")
    prior = prior[(prior["term_key"] == 1) & (prior["attendance_status"] == "Sat")].groupby(["student_key", "subject_key"])["score"].mean()
    e = enr[enr["status"] == "Completed"].merge(t["dim_class"][["class_key", "subject_key", "teacher_key"]], on="class_key")
    e["prior"] = [prior.get((s, j), np.nan) for s, j in zip(e["student_key"], e["subject_key"])]
    e["growth"] = e["final_score"] - e["prior"]
    e = e.dropna(subset=["growth"])
    e["resid"] = e["growth"] - e.groupby(["subject_key", "term_key"])["growth"].transform("mean")
    va = e.groupby("teacher_key")["resid"].agg(["mean", "size"])
    va = va[va["size"] >= 30].join(truth["teacher_effects"].set_index("teacher_key"))
    kpi["Teacher VA recovery r"] = va["mean"].corr(va["true_effect"])

    # ---- programmes: naive dashboard comparison vs a design-appropriate estimate ----
    iv = t["fact_intervention"]
    member = {p: set(iv.loc[iv["intervention_type"] == p, "student_key"]) for p in truth["programs"]}
    st = pd.DataFrame({"student_key": t["dim_student"]["student_key"]}).set_index("student_key")
    st["prior"] = _per_student(res, exams, 1)
    st["fall_avg"] = _per_student(res, exams, 2)
    st["fall_final"] = _per_student(res, exams, 2, "Final")
    st["spring_final"] = _per_student(res, exams, 3, "Final")
    st["yoy"] = st["spring_final"] - st["prior"]
    st["g"] = st["spring_final"] - st["fall_final"]
    for p in member:
        st[p] = st.index.isin(member[p])
    stress = survey[survey["term_key"] == 2].set_index("student_key")["stress_level"].reindex(st.index)
    rem, men, tut, cou = st["Remedial class"], st["Peer mentoring"], st["Private tuition"], st["Counseling"]

    def ols(rows, y, treat, controls):
        """Coefficient and standard error of `treat` in y ~ 1 + treat + controls."""
        d = st.loc[rows, [y, treat] + controls].dropna().astype(float)
        X = np.column_stack([np.ones(len(d)), d[[treat] + controls].to_numpy()])
        beta, *_ = np.linalg.lstsq(X, d[y].to_numpy(), rcond=None)
        resid = d[y].to_numpy() - X @ beta
        cov = resid.var(ddof=X.shape[1]) * np.linalg.inv(X.T @ X)
        return beta[1], np.sqrt(cov[1, 1])

    cut = cfg["effects"]["remedial_threshold"]
    st["below"] = (st["fall_avg"] < cut).astype(float)
    st["dist"] = st["fall_avg"] - cut
    st["dist_below"] = st["dist"] * st["below"]
    est = {
        # all-year tuition, assignment unrelated to ability: ANCOVA on the spring final with the prior final as control
        "Private tuition": ols(~rem & ~men, "spring_final", "Private tuition", ["prior"]),
        # spring programme assigned at random: spring final controlling for the fall final
        "Peer mentoring": ols(~rem, "spring_final", "Peer mentoring", ["fall_final", "prior"]),
        # threshold assignment: local linear regression discontinuity at the fall-average cut-off (bandwidth 10)
        "Remedial class": ols(st["dist"].abs() <= 10, "g", "below", ["dist", "dist_below"]),
        # random among high-stress students: ANCOVA within that group
        "Counseling": ols(~rem & (stress >= 9), "spring_final", "Counseling", ["prior"]),
    }
    naive = {p: st.loc[st[p], "yoy"].mean() - st.loc[~st[p], "yoy"].mean() for p in member}
    kpi["Program effects recovered"] = sum(abs(est[p][0] - truth["programs"][p]) <= 2 * est[p][1] for p in member)
    method = {
        "Private tuition": "ANCOVA: spring final adjusted for prior-year score",
        "Peer mentoring": "ANCOVA: spring final adjusted for fall final and prior score",
        "Remedial class": f"Regression discontinuity at the fall average cut-off ({cut})",
        "Counseling": "ANCOVA within the high-stress group (stress 9-10)",
    }
    # written to data/truth/program_evaluation.csv next to the report
    truth["evaluation"] = pd.DataFrame([{
        "program": p, "participants": len(member[p]), "naive_gap": round(naive[p], 2),
        "design_estimate": round(est[p][0], 2), "ci_low": round(est[p][0] - 2 * est[p][1], 2),
        "ci_high": round(est[p][0] + 2 * est[p][1], 2), "true_effect": truth["programs"][p], "method": method[p],
    } for p in member])

    # ---- source relationships kept after the split ----
    sv = survey[survey["term_key"] == 3].set_index("student_key")
    drivers = {
        "corr(final, study hours)": st["spring_final"].corr(sv["study_hours_per_day"]),
        "corr(final, sleep hours)": st["spring_final"].corr(sv["sleep_hours"]),
        "corr(final, stress)": st["spring_final"].corr(sv["stress_level"]),
        "income gap High - Low": st.join(t["dim_student"].set_index("student_key")["family_income"]).groupby("family_income")["spring_final"].mean().pipe(lambda x: x["High"] - x["Low"]),
    }

    lines = ["# Validation report", "", f"Students: {n:,} · schools: {len(t['dim_school'])} · teachers: {len(t['dim_teacher']):,} · classes: {len(t['dim_class']):,}", "",
             "## KPI levels vs targets", "", "| KPI | Value | Target | |", "|---|---:|---|---|"]
    for k, v in kpi.items():
        lo, hi = cfg["targets"][k]
        fmt = (lambda x: f"{x:.1%}") if hi <= 1 and k != "Teacher VA recovery r" else (lambda x: f"{x:.2f}".rstrip("0").rstrip("."))
        lines.append(f"| {k} | {fmt(v)} | {fmt(lo)} – {fmt(hi)} | {'OK' if lo <= v <= hi else 'OFF'} |")
    lines += ["", "## Programme effects", "",
              "Naive = year-over-year growth of participants minus everyone else (what the dashboard measure shows). "
              "Design estimate uses the comparison that fits how each programme assigns students; ± is two standard errors.", "",
              "| Programme | Participants | True | Naive (dashboard) | Design estimate |", "|---|---:|---:|---:|---:|"]
    for p in member:
        lines.append(f"| {p} | {len(member[p]):,} | {truth['programs'][p]:+.1f} | {naive[p]:+.1f} | {est[p][0]:+.1f} ± {2 * est[p][1]:.1f} |")
    lines += ["", "## Source relationships", "", "| Check | Value |", "|---|---:|"]
    lines += [f"| {k} | {v:+.3f} |" for k, v in drivers.items()]
    lines += ["", "## Table sizes", "", "| Table | Rows |", "|---|---:|"]
    lines += [f"| {k} | {len(v):,} |" for k, v in t.items()]
    return "\n".join(lines) + "\n"
