# Validation report

Students: 20,000 · schools: 18 · teachers: 1,145 · classes: 10,936

## KPI levels vs targets

| KPI | Value | Target | |
|---|---:|---|---|
| Students per Teacher | 17.47 | 14 – 20 | OK |
| Avg Class Size | 25.6 | 20 – 30 | OK |
| Attendance Rate | 93.4% | 91.0% – 95.0% | OK |
| Chronic Absentee Rate | 21.5% | 18.0% – 32.0% | OK |
| Completion Rate | 86.1% | 80.0% – 90.0% | OK |
| On-time Rate | 91.8% | 80.0% – 92.0% | OK |
| Exam Pass Rate | 83.5% | 72.0% – 86.0% | OK |
| Course Withdrawal Rate | 1.9% | 1.5% – 5.0% | OK |
| Incidents per 100 | 32.02 | 30 – 80 | OK |
| Program Reach | 42.7% | 25.0% – 50.0% | OK |
| High Stress Share | 23.8% | 20.0% – 40.0% | OK |
| Teacher VA recovery r | 0.82 | 0.5 – 1 | OK |
| Program effects recovered | 4 | 4 – 4 | OK |

## Programme effects

Naive = year-over-year growth of participants minus everyone else (what the dashboard measure shows). Design estimate uses the comparison that fits how each programme assigns students; ± is two standard errors.

| Programme | Participants | True | Naive (dashboard) | Design estimate |
|---|---:|---:|---:|---:|
| Private tuition | 6,019 | +3.0 | +3.2 | +3.3 ± 0.4 |
| Remedial class | 1,678 | +4.0 | -2.9 | +3.6 ± 0.9 |
| Peer mentoring | 1,205 | +1.5 | +1.2 | +1.5 ± 0.3 |
| Counseling | 913 | +1.0 | +0.0 | +2.1 ± 1.2 |

## Source relationships

| Check | Value |
|---|---:|
| corr(final, study hours) | +0.357 |
| corr(final, sleep hours) | +0.162 |
| corr(final, stress) | -0.122 |
| income gap High - Low | +5.695 |

## Table sizes

| Table | Rows |
|---|---:|
| dim_date | 546 |
| dim_term | 3 |
| dim_school | 18 |
| dim_student | 20,000 |
| dim_subject | 9 |
| dim_teacher | 1,145 |
| dim_class | 10,936 |
| dim_exam | 45 |
| dim_assignment | 65,616 |
| fact_enrollment | 280,000 |
| fact_exam_result | 694,605 |
| fact_attendance | 316,805 |
| fact_assignment_submission | 1,680,000 |
| fact_lms_activity | 700,000 |
| fact_wellbeing_survey | 40,000 |
| fact_behavior_incident | 6,404 |
| fact_intervention | 9,815 |
