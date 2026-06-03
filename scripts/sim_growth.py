"""S7 - 7스탯 경험치 누적 성장 모델 분포 시뮬레이션.

검증 항목:
1. 시작 스탯 30/50/70/90에서 95 도달까지 평균 실패 trigger 수
2. 95 컷 자연 정체 (94→95 한 번 더 시도해서 95 박힘 후 멈춤)
3. 시간 분포 (1배치당 trigger N회 가정 → 일 단위 환산)
4. 0→1 진입 지략 판정 — 지략 30/50/70 캐릭터별 1회 성공률 + 평균 시도 횟수
5. 누적 분포 (몇 trigger째 +1 성장 패턴)

가정:
- 1배치당 실패 trigger 1회 (단일 스탯·단일 스킬·단일 소재 기준 보수적)
- 모델: required_exp = current // 7 (2026-05-29 c//10→c//7 감속), trigger마다 exp+=1, exp >= required면 다음 trigger 시점에 value+=1·exp=0 리셋
- 공식은 engine.dice.GROWTH_EXP_DENOMINATOR 단일 출처 (본 시뮬은 dice.is_growth_due·required_exp_for 직접 import)
"""

# ruff: noqa: E402
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
import random
import statistics

# scripts/에서 실행 시 firstgame 루트를 import 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.dice import first_learn_check, growth_check, is_growth_due, required_exp_for


def sim_growth_curve(start: int, trigger_count: int, seed: int = 42) -> dict:
    """start 스탯에서 trigger_count번 실패 trigger 발생 시 최종 stat 값·성장 분포."""
    random.seed(seed)
    current = start
    exp = 0
    growths_at = []  # 각 +1이 일어난 trigger 번호 (1-indexed)
    reach_95 = None

    for t in range(1, trigger_count + 1):
        # 다음 trigger 시점 = 배치 시작 hook으로 성장 적용 후 trigger
        if is_growth_due(current, exp):
            current += 1
            exp = 0
            growths_at.append(t)
            if current == 95 and reach_95 is None:
                reach_95 = t
        # trigger: 실패 시 exp +1 (95 컷)
        if current < 95:
            exp += 1
    return {
        "final": current,
        "growths": len(growths_at),
        "growths_at": growths_at,
        "reach_95": reach_95,
    }


def collect(start: int, runs: int, trigger_count: int) -> dict:
    finals = []
    reaches = []
    not_reached = 0
    for s in range(runs):
        r = sim_growth_curve(start=start, trigger_count=trigger_count, seed=s)
        finals.append(r["final"])
        if r["reach_95"] is not None:
            reaches.append(r["reach_95"])
        else:
            not_reached += 1
    return {
        "start": start,
        "runs": runs,
        "final_mean": statistics.mean(finals),
        "final_stdev": statistics.stdev(finals) if len(finals) > 1 else 0,
        "final_min": min(finals),
        "final_max": max(finals),
        "reach_count": len(reaches),
        "not_reached": not_reached,
        "reach_mean": statistics.mean(reaches) if reaches else None,
        "reach_stdev": statistics.stdev(reaches) if len(reaches) > 1 else 0,
        "reach_median": statistics.median(reaches) if reaches else None,
        "reach_p10": sorted(reaches)[len(reaches) // 10] if len(reaches) >= 10 else None,
        "reach_p90": sorted(reaches)[len(reaches) * 9 // 10] if len(reaches) >= 10 else None,
    }


def sim_old_growth_curve(start: int, trigger_count: int, seed: int = 42) -> dict:
    """옛 P5 즉시 +1 모델 (dice.growth_check). 실패 trigger마다 roll_d100() > current면 즉시 +1.
    새 누적 모델과 같은 '실패 trigger마다' 조건에서 속도 비교용. 95 도달 시점까지만 비교.
    """
    random.seed(seed)
    current = start
    reach_95 = None
    for t in range(1, trigger_count + 1):
        if current < 95 and growth_check(current):  # roll_d100() > current
            current += 1
            if current == 95 and reach_95 is None:
                reach_95 = t
    return {"final": current, "reach_95": reach_95}


def first_learn_attempts(intelligence: int, runs: int) -> dict:
    """0→1 진입 1회 시도 성공률 + 성공까지 평균 시도 횟수."""
    successes_first_try = 0
    attempts_to_success = []
    for s in range(runs):
        random.seed(s)
        attempts = 0
        while True:
            attempts += 1
            if first_learn_check(intelligence):
                if attempts == 1:
                    successes_first_try += 1
                attempts_to_success.append(attempts)
                break
            if attempts > 1000:  # 안전 가드
                break
    return {
        "first_try_pct": successes_first_try / runs * 100,
        "attempts_mean": statistics.mean(attempts_to_success),
        "attempts_median": statistics.median(attempts_to_success),
        "attempts_max": max(attempts_to_success),
    }


# ── 본 시뮬 ────────────────────────────────────────────────
RUNS = 1000
TRIGGER_BUDGET = 5000  # 95 컷까지 충분한 trigger 수

print(
    f"# S7 - 7스탯 경험치 누적 성장 모델 분포 시뮬레이션 ({RUNS}회/케이스)\n"
    "가정: 1배치당 실패 trigger 1회 (단일 스탯 단순 모델). required_exp = current // 7 (c//7 감속).\n"
)

# 1. 시작 스탯별 95 도달까지 trigger 수 + 최종 분포
print("## 1. 시작 스탯 → 95 도달까지 trigger 수\n")
print("| 시작 | 95 도달 비율 | 평균 trigger | 표준편차 | 중앙값 | 10%~90% 범위 |")
print("|---|---|---|---|---|---|")
for start in [30, 50, 70, 90]:
    a = collect(start=start, runs=RUNS, trigger_count=TRIGGER_BUDGET)
    print(
        f"| {start} | "
        f"{a['reach_count']}/{a['runs']} ({a['reach_count'] / a['runs'] * 100:.0f}%) | "
        f"{a['reach_mean']:.0f} | ±{a['reach_stdev']:.0f} | "
        f"{a['reach_median']:.0f} | "
        f"{a['reach_p10']} ~ {a['reach_p90']} |"
    )

# 2. 필요 경험치 곡선 (95 도달 후 정체 패턴)
print("\n## 2. required_exp 곡선 (참고용, 단순 모델)\n")
print("| current | required_exp (= current // 7) | 누적 trigger (0부터 누적) |")
print("|---|---|---|")
total = 0
for c in [0, 10, 20, 30, 50, 70, 90, 94, 95]:
    req = required_exp_for(c) if c < 95 else "-1 (성장 봉쇄)"
    if c < 95:
        # 0부터 c까지 누적 trigger 수 (각 단계 required_exp = dice.required_exp_for)
        total = sum(required_exp_for(v) for v in range(c))
        print(f"| {c} | {req} | {total} (누적) |")
    else:
        print(f"| {c} | {req} | (95 컷) |")

# 3. 누적 분포 — 시작 30에서 95까지 각 성장 지점 분포
print("\n## 3. 누적 성장 지점 (시작 30 → 95, 1000회 평균)\n")
all_growths = [[] for _ in range(95 - 30 + 1)]  # idx 0=30→31, idx 64=94→95
for s in range(RUNS):
    r = sim_growth_curve(start=30, trigger_count=TRIGGER_BUDGET, seed=s)
    for i, t in enumerate(r["growths_at"]):
        if i < len(all_growths):
            all_growths[i].append(t)
print("| 성장 단계 | 평균 trigger | 단계 별 누적 trigger 평균 차 (= 이번 +1 소요 trigger) |")
print("|---|---|---|")
sampled_steps = [
    0,
    9,
    19,
    29,
    39,
    49,
    59,
    64,
]  # 30→31, 40→41, 50→51, 60→61, 70→71, 80→81, 90→91, 94→95
prev_mean = 0
for idx in sampled_steps:
    if not all_growths[idx]:
        continue
    m = statistics.mean(all_growths[idx])
    diff = m - prev_mean
    stage = 30 + idx
    print(f"| {stage} → {stage + 1} | {m:.0f} | +{diff:.0f} |")
    prev_mean = m

# 4. 0→1 진입 지략 판정 분포
print("\n## 4. 0→1 진입 지략 판정 (지략별 성공률 + 평균 시도 횟수)\n")
print("| 지략 | 1회 시도 성공률 | 평균 시도 횟수 | 중앙값 | 최대 시도 |")
print("|---|---|---|---|---|")
for intel in [30, 50, 70, 90]:
    r = first_learn_attempts(intelligence=intel, runs=RUNS)
    print(
        f"| {intel} | {r['first_try_pct']:.0f}% | "
        f"{r['attempts_mean']:.2f} | {r['attempts_median']:.0f} | {r['attempts_max']} |"
    )

# 5. 시작별 trigger budget 안에서 최종 평균값 (95 컷 자연 정체 확인)
print("\n## 5. 5000 trigger 후 최종 stat 평균 (95 컷 자연 정체)\n")
print("| 시작 | 최종 평균 | 표준편차 | 최소·최대 |")
print("|---|---|---|---|")
for start in [30, 50, 70, 90]:
    a = collect(start=start, runs=RUNS, trigger_count=TRIGGER_BUDGET)
    print(
        f"| {start} | {a['final_mean']:.2f} | ±{a['final_stdev']:.2f} | "
        f"{a['final_min']} ~ {a['final_max']} |"
    )

# 6. 옛 즉시 모델 vs 새 누적 모델 — 같은 실패 trigger 조건 비교
print("\n## 6. 옛 P5 즉시 모델(growth_check) vs 새 누적 모델 — 95 도달 trigger\n")
print(
    "같은 '실패 trigger마다' 조건. 옛: roll_d100()>current면 즉시 +1 / 새: exp 누적 후 도달 시 +1\n"
)
print("| 시작 | 옛 즉시 모델 평균 | 새 누적 모델 평균 | 새/옛 배수 (느려진 정도) |")
print("|---|---|---|---|")
for start in [30, 50, 70, 90]:
    old_reaches = []
    for s in range(RUNS):
        r = sim_old_growth_curve(start=start, trigger_count=TRIGGER_BUDGET, seed=s)
        if r["reach_95"] is not None:
            old_reaches.append(r["reach_95"])
    old_mean = statistics.mean(old_reaches) if old_reaches else None
    new = collect(start=start, runs=RUNS, trigger_count=TRIGGER_BUDGET)
    new_mean = new["reach_mean"]
    if old_mean and new_mean:
        ratio = new_mean / old_mean
        print(f"| {start} | {old_mean:.0f} trigger | {new_mean:.0f} trigger | {ratio:.2f}배 |")

print("\n# 끝.")
