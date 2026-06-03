"""S7 - S2-B v2 재굴림 효과 시뮬레이션.

토큰 0/1/2/3 × craft·material 시작값 50/70/90 × 부상 X/O × 4공정·3공정 평균 × 1000회.
process_blacksmith_command 직접 호출.

측정:
- 평균 quality (1~5등급)
- quality 분포 (1~5등급 비율)
- 즉시 재굴림 vs 후처리 재굴림 발동 횟수
- craft vs material 후처리 비율 (max skill 룰 균형 검증)
- 부상 발생율
- penalty_modifier=-3 케이스 quality 저하 폭 (별도 비교)

가정:
- 4공정 = 광석 시작(제련→단조→열처리→마감), 3공정 = 주괴 시작(단조→열처리→마감)
- prereq_bonus = 5 (소재 숙련도 50 가정 → +5 보너스)
- mat_bonus_dice=0 / mat_fumble_safe=False (베이스 케이스)
- luck=50, health=50 (안전망 통과율 기준)
- 무력·지략 stat_trigger는 결과에 영향 없음 (exp 누적만, quality 무관)
"""

# ruff: noqa: E402
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
import random
import statistics
from collections import Counter

# scripts/에서 실행 시 firstgame 루트를 import 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.blacksmith import process_blacksmith_command
from engine.materials import STEPS_INGOT, STEPS_ORE

RUNS = 1000
SKILL_PAIRS = [(50, 50), (70, 70), (90, 90)]  # (craft, material)
TOKEN_OPTIONS = [0, 1, 2, 3]
PENALTY_OPTIONS = [0, -3]  # 0 = 페널티 없음, -3 = 대실패로 박힌 페널티
INJURY_OPTIONS = [False, True]
STEP_SETS = [("4공정", STEPS_ORE), ("3공정", STEPS_INGOT)]


def build_character(craft: int, injured: bool) -> dict:
    return {
        "strength": craft,
        "intelligence": craft,
        "charisma": 50,
        "leadership": 50,
        "health": 50,
        "luck": 50,
        "dexterity": 50,
        "is_injured": injured,
    }


def build_skills(craft: int) -> dict:
    return {
        "smelting": craft,
        "forging": craft,
        "heat_treat": craft,
        "finishing": craft,
    }


def run_one(
    steps: list, craft: int, mat: int, tokens: int, penalty: int, injured: bool, seed: int
) -> dict:
    random.seed(seed)
    char = build_character(craft, injured)
    skills = build_skills(craft)
    result = process_blacksmith_command(
        character=char,
        steps=steps,
        skills=skills,
        mat_proficiency=mat,
        prereq_bonus=5,
        is_injured=injured,
        mat_bonus_dice=0,
        mat_fumble_safe=False,
        rerolls_remaining=tokens,
        penalty_modifier=penalty,
    )
    rerolls_used = result["rerolls_used"]
    # 즉시(craft.reroll·material.reroll에 postprocessed 없음) vs 후처리 분리
    immediate = 0
    postproc = 0
    craft_post = 0
    mat_post = 0
    for step_r in result["process_results"]:
        for layer in ("craft", "material"):
            ld = step_r.get(layer)
            if not ld:
                continue
            rr = ld.get("reroll")
            if rr:
                if rr.get("postprocessed"):
                    postproc += 1
                    if layer == "craft":
                        craft_post += 1
                    else:
                        mat_post += 1
                else:
                    immediate += 1
    return {
        "quality": result["quality"],
        "total_points": result["total_points"],
        "is_injured_new": result["is_injured"],
        "rerolls_used": rerolls_used,
        "immediate_rerolls": immediate,
        "postproc_rerolls": postproc,
        "craft_post": craft_post,
        "mat_post": mat_post,
    }


def aggregate(label: str, runs_data: list) -> dict:
    qualities = [r["quality"] for r in runs_data]
    q_dist = Counter(qualities)
    injuries = sum(1 for r in runs_data if r["is_injured_new"])
    return {
        "label": label,
        "runs": len(runs_data),
        "q_mean": statistics.mean(qualities),
        "q_stdev": statistics.stdev(qualities) if len(qualities) > 1 else 0,
        "q_dist": {q: q_dist.get(q, 0) for q in range(1, 6)},
        "q1_pct": q_dist.get(1, 0) / len(runs_data) * 100,
        "q5_pct": q_dist.get(5, 0) / len(runs_data) * 100,
        "injury_pct": injuries / len(runs_data) * 100,
        "rerolls_used_mean": statistics.mean(r["rerolls_used"] for r in runs_data),
        "immediate_mean": statistics.mean(r["immediate_rerolls"] for r in runs_data),
        "postproc_mean": statistics.mean(r["postproc_rerolls"] for r in runs_data),
        "craft_post_total": sum(r["craft_post"] for r in runs_data),
        "mat_post_total": sum(r["mat_post"] for r in runs_data),
    }


def fmt_dist(dist: dict, total: int) -> str:
    return " | ".join(f"{q}등급 {dist[q]}({dist[q] / total * 100:.0f}%)" for q in range(1, 6))


# ── 본 시뮬 ──────────────────────────────────────────────────
print(
    f"# S7 - S2-B v2 재굴림 효과 시뮬레이션 ({RUNS}회/케이스)\n"
    "가정: 4공정·3공정 각각, craft=material skill, prereq_bonus=5, luck/health=50, "
    "stat_trigger는 quality 무관(exp만)\n"
)

# 1. 토큰별 효과 (페널티 0, 부상 X, skill 70/70 기준 — 가장 흔한 NPC 시나리오)
print("## 1. 재굴림 토큰별 효과 (skill 70/70, 페널티 0, 부상 X)\n")
print("| 공정 | 토큰 | 평균 quality | quality 분포 | 부상율 | 사용 토큰 | 즉시 | 후처리 |")
print("|---|---|---|---|---|---|---|---|")
for step_label, steps in STEP_SETS:
    for tokens in TOKEN_OPTIONS:
        runs_data = [run_one(steps, 70, 70, tokens, 0, False, seed=s) for s in range(RUNS)]
        agg = aggregate(f"{step_label}_t{tokens}", runs_data)
        print(
            f"| {step_label} | {tokens} | "
            f"{agg['q_mean']:.2f} ±{agg['q_stdev']:.2f} | "
            f"{fmt_dist(agg['q_dist'], agg['runs'])} | "
            f"{agg['injury_pct']:.1f}% | "
            f"{agg['rerolls_used_mean']:.2f} | "
            f"{agg['immediate_mean']:.2f} | "
            f"{agg['postproc_mean']:.2f} |"
        )

# 2. 시작 skill별 효과 (토큰 2, 페널티 0, 부상 X)
print("\n## 2. 시작 skill별 효과 (토큰 2, 페널티 0, 부상 X)\n")
print("| 공정 | skill | 평균 quality | quality 분포 | 부상율 | 즉시 | 후처리 |")
print("|---|---|---|---|---|---|---|")
for step_label, steps in STEP_SETS:
    for craft, mat in SKILL_PAIRS:
        runs_data = [run_one(steps, craft, mat, 2, 0, False, seed=s) for s in range(RUNS)]
        agg = aggregate(f"{step_label}_s{craft}", runs_data)
        print(
            f"| {step_label} | {craft}/{mat} | "
            f"{agg['q_mean']:.2f} ±{agg['q_stdev']:.2f} | "
            f"{fmt_dist(agg['q_dist'], agg['runs'])} | "
            f"{agg['injury_pct']:.1f}% | "
            f"{agg['immediate_mean']:.2f} | "
            f"{agg['postproc_mean']:.2f} |"
        )

# 3. 부상 케이스 비교 (skill 70/70, 토큰 0/2)
print("\n## 3. 부상 X vs O (skill 70/70, 페널티 0)\n")
print("| 공정 | 토큰 | 부상 | 평균 quality | 부상 발생율 | 사용 토큰 | 후처리 |")
print("|---|---|---|---|---|---|---|")
for step_label, steps in STEP_SETS:
    for tokens in [0, 2]:
        for injured in INJURY_OPTIONS:
            runs_data = [run_one(steps, 70, 70, tokens, 0, injured, seed=s) for s in range(RUNS)]
            agg = aggregate(f"{step_label}_t{tokens}_inj{injured}", runs_data)
            print(
                f"| {step_label} | {tokens} | {'O' if injured else 'X'} | "
                f"{agg['q_mean']:.2f} | "
                f"{agg['injury_pct']:.1f}% | "
                f"{agg['rerolls_used_mean']:.2f} | "
                f"{agg['postproc_mean']:.2f} |"
            )

# 4. 페널티 비교 (skill 70/70, 부상 X)
print("\n## 4. 페널티 0 vs -3 (skill 70/70, 부상 X)\n")
print("| 공정 | 토큰 | 페널티 | 평균 quality | quality 분포 | 후처리 |")
print("|---|---|---|---|---|---|")
for step_label, steps in STEP_SETS:
    for tokens in [0, 2]:
        for penalty in PENALTY_OPTIONS:
            runs_data = [
                run_one(steps, 70, 70, tokens, penalty, False, seed=s) for s in range(RUNS)
            ]
            agg = aggregate(f"{step_label}_t{tokens}_p{penalty}", runs_data)
            print(
                f"| {step_label} | {tokens} | {penalty} | "
                f"{agg['q_mean']:.2f} | "
                f"{fmt_dist(agg['q_dist'], agg['runs'])} | "
                f"{agg['postproc_mean']:.2f} |"
            )

# 5. 후처리 layer 균형 (craft vs material 어느 쪽이 더 자주 후처리 받나)
print("\n## 5. 후처리 layer 균형 (skill 70/70, 토큰 3, 페널티 0, 부상 X)\n")
print("같은 skill인데 craft·material 어느 쪽이 더 자주 후처리 받는지 (max skill 룰 균형)\n")
print("| 공정 | craft 후처리 합 | material 후처리 합 | 비율 |")
print("|---|---|---|---|")
for step_label, steps in STEP_SETS:
    runs_data = [run_one(steps, 70, 70, 3, 0, False, seed=s) for s in range(RUNS)]
    agg = aggregate(f"{step_label}_layer", runs_data)
    total = agg["craft_post_total"] + agg["mat_post_total"]
    if total > 0:
        c_pct = agg["craft_post_total"] / total * 100
        m_pct = agg["mat_post_total"] / total * 100
        print(
            f"| {step_label} | {agg['craft_post_total']} | {agg['mat_post_total']} | "
            f"craft {c_pct:.0f}% / mat {m_pct:.0f}% |"
        )
    else:
        print(f"| {step_label} | 0 | 0 | 후처리 없음 |")

print("\n# 끝.")
