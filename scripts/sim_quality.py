"""품질 등급 임계값 시뮬레이션.

광석 4공정 / 주괴 3공정 × 2회 판정(공정+소재)을 평균 숙련도 시나리오별로
10,000회 몬테카를로 → total_points 분포·분위수 + 현재 임계값에서의 등급 분포.

실행: firstgame/ 폴더에서
  .venv\\Scripts\\python.exe scripts/sim_quality.py
"""

import os
import statistics
import sys
from collections import Counter

# firstgame/ 루트를 import 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import blacksmith
from engine.materials import STEPS_INGOT, STEPS_ORE

RUNS = 10000


def simulate(steps: list, skill_value: int, mat_value: int, is_injured: bool = False) -> dict:
    skills = {step["skill_name"]: skill_value for step in steps}
    character = {"luck": 50, "health": 50}

    points_list = []
    quality_counter: Counter = Counter()
    injury_count = 0

    for _ in range(RUNS):
        body = blacksmith.process_blacksmith_command(
            character=character,
            steps=steps,
            skills=skills,
            mat_proficiency=mat_value,
            prereq_bonus=0,
            is_injured=is_injured,
        )
        points_list.append(body["total_points"])
        quality_counter[body["quality"]] += 1
        if body["is_injured"]:
            injury_count += 1

    points_list.sort()
    n = len(points_list)

    def pct(p: int) -> int:
        idx = min(n - 1, max(0, int(n * p / 100)))
        return points_list[idx]

    return {
        "min": points_list[0],
        "max": points_list[-1],
        "p5": pct(5),
        "p25": pct(25),
        "p50": pct(50),
        "p75": pct(75),
        "p95": pct(95),
        "mean": statistics.mean(points_list),
        "quality_dist": dict(sorted(quality_counter.items())),
        "injury_rate": injury_count / RUNS,
    }


def print_result(label: str, r: dict) -> None:
    print(f"\n--- {label} ---")
    print(f"  Range: {r['min']:+d} ~ {r['max']:+d}, Mean: {r['mean']:+.2f}")
    print(
        f"  Percentile: p5={r['p5']:+d}, p25={r['p25']:+d}, p50={r['p50']:+d}, p75={r['p75']:+d}, p95={r['p95']:+d}"
    )
    print("  Quality dist (1~5등급, 현재 임계값 ≥8/5/2/-1):")
    total = sum(r["quality_dist"].values())
    for q in range(1, 6):
        cnt = r["quality_dist"].get(q, 0)
        pct = cnt / total * 100
        bar = "#" * int(pct / 2)
        print(f"    {q}등급: {cnt:5d} ({pct:5.2f}%) {bar}")
    print(f"  부상 발생률: {r['injury_rate'] * 100:.2f}%")


def main() -> None:
    print(f"=== 품질 임계값 시뮬레이션 (각 {RUNS:,}회) ===")
    print("현재 _quality_grade 임계값: total>=8→5등급, >=5→4, >=2→3, >=-1→2, 그 외→1\n")

    scenarios = [(20, 20), (50, 50), (70, 70)]

    print("### 광석 4공정 (제련→단조→열처리→마감) ###")
    for skill, mat in scenarios:
        r = simulate(STEPS_ORE, skill, mat, is_injured=False)
        print_result(f"광석, skill={skill}, mat={mat}, 정상", r)
        r = simulate(STEPS_ORE, skill, mat, is_injured=True)
        print_result(f"광석, skill={skill}, mat={mat}, 부상(-20)", r)

    print("\n### 주괴 3공정 (단조→열처리→마감) ###")
    for skill, mat in scenarios:
        r = simulate(STEPS_INGOT, skill, mat, is_injured=False)
        print_result(f"주괴, skill={skill}, mat={mat}, 정상", r)


if __name__ == "__main__":
    main()
