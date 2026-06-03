"""S7 후속 - 경험치 누적 모델 계수 조정 후보 비교.

목표: 현행 floor(current/10) 대비 "전체적으로 ~1.5배 느리게" 만드는 공식 탐색.
곡선 모양(완만·95 도달 보장)은 유지하고 필요 경험치 공식만 조정.

두 방식 비교:
- 나눗셈 분모 조정: floor(current/D) — D를 줄이면 전 구간 비례적으로 느려짐 (기울기만 가팔라짐)
- 상수 추가: floor(current/10) + K — 저스탯을 상대적으로 더 무겁게 (저레벨 가속 억제)

로직은 sim_growth.py sim_growth_curve와 동일 (매 trigger 시작에 성장 체크 후 exp+1).
"""

# ruff: noqa: E402
import sys

sys.stdout.reconfigure(encoding="utf-8")
import statistics

RUNS = 1000  # 결정론적 모델이라 사실 1회면 충분하나 일관성 위해 유지
TRIGGER_BUDGET = 12000  # 가장 느린 공식도 95 도달하도록 넉넉히
STARTS = [30, 50, 70, 90]

# 후보 공식 (current → 필요 경험치)
CANDIDATES = {
    "현행 c//10": lambda c: c // 10,
    "c//8": lambda c: c // 8,
    "c//7": lambda c: c // 7,
    "c//6": lambda c: c // 6,
    "c//10 +2": lambda c: c // 10 + 2,
    "c//10 +3": lambda c: c // 10 + 3,
    "c//10 +5": lambda c: c // 10 + 5,
    "c//7 +1": lambda c: c // 7 + 1,
}


def reach_95(required_fn, start: int, trigger_count: int) -> int | None:
    """start에서 95 도달까지 trigger 수. 결정론적 (난수 없음 — 누적 모델)."""
    current = start
    exp = 0
    for t in range(1, trigger_count + 1):
        if current < 95 and exp >= required_fn(current):
            current += 1
            exp = 0
            if current == 95:
                return t
        if current < 95:
            exp += 1
    return None


print("# S7 후속 - 경험치 누적 모델 계수 조정 후보 비교\n")
print("현행 floor(current/10) 대비 95 도달 trigger 수 + 배수. 곡선 모양 유지, 공식만 조정.\n")

# 1. 각 후보별 시작값별 95 도달 trigger
print("## 1. 후보 공식별 95 도달 trigger (시작값별)\n")
print("| 공식 | 30→95 | 50→95 | 70→95 | 90→95 |")
print("|---|---|---|---|---|")
base = {}  # 현행 기준값 저장 (배수 계산용)
results = {}
for label, fn in CANDIDATES.items():
    row = {}
    for start in STARTS:
        row[start] = reach_95(fn, start, TRIGGER_BUDGET)
    results[label] = row
    if label == "현행 c//10":
        base = row
    print(f"| {label} | {row[30]} | {row[50]} | {row[70]} | {row[90]} |")

# 2. 현행 대비 배수 (각 시작값별)
print("\n## 2. 현행 c//10 대비 배수 (1.5배 목표 대조)\n")
print("| 공식 | 30 배수 | 50 배수 | 70 배수 | 90 배수 | 평균 배수 |")
print("|---|---|---|---|---|---|")
for label, row in results.items():
    ratios = [row[s] / base[s] for s in STARTS]
    avg = statistics.mean(ratios)
    print(
        f"| {label} | "
        f"{ratios[0]:.2f} | {ratios[1]:.2f} | {ratios[2]:.2f} | {ratios[3]:.2f} | "
        f"**{avg:.2f}** |"
    )

# 3. 단계별 비용 곡선 (선형 vs 상수추가 모양 차이 시각화)
print("\n## 3. 단계별 필요 경험치 (곡선 모양 비교)\n")
print("| current | 현행 c//10 | c//7 | c//6 | c//10+3 | c//10+5 |")
print("|---|---|---|---|---|---|")
for c in [10, 30, 50, 70, 90, 94]:
    print(f"| {c} | {c // 10} | {c // 7} | {c // 6} | {c // 10 + 3} | {c // 10 + 5} |")

# 4. 일 단위 환산 (시작 30, 단일 trigger 보수 가정: 1배치 1 trigger, 1일 2배치)
print("\n## 4. 시작 30 기준 일 단위 환산 (단일 trigger 보수 가정, 1일 2배치)\n")
print("| 공식 | 30→95 trigger | 배치 환산 | 일 환산 | 현행 대비 |")
print("|---|---|---|---|---|")
base30 = base[30]
for label, row in results.items():
    t = row[30]
    days = t / 2  # 1일 2배치
    ratio = t / base30
    print(f"| {label} | {t} | {t} 배치 | {days:.0f}일 | {ratio:.2f}배 |")

print("\n# 끝.")
