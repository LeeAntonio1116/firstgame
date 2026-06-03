// 대장간 작업실 — 명령서 제출 폼 (소재 드롭다운·예측·검증)
// 데이터는 window.__DASH__ 부트스트랩 객체에서 받는다.
const charactersData = window.__DASH__.characters_data;
const matLabels = window.__DASH__.material_labels;
const materialGroups = window.__DASH__.material_groups;
const weaponCodes = window.__DASH__.weapon_codes;
const weaponLabels = window.__DASH__.weapon_labels;
const weaponRecipes = window.__DASH__.weapon_recipes;
const weaponStaminaBonus = window.__DASH__.weapon_stamina_bonus;
const oreCodes = window.__DASH__.ore_codes;
const alloyCodesSet = new Set(window.__DASH__.alloy_codes);
const matInfoCmd = window.__DASH__.material_info;
const skillLabels = {
  smelting: "제련",
  forging: "단조",
  heat_treat: "열처리",
  finishing: "마감",
  appraisal: "감정",
};
const stepsByInput = {
  ore: ["smelting", "forging", "heat_treat", "finishing"],
  ingot: ["forging", "heat_treat", "finishing"],
  alloy_ingot: ["forging", "heat_treat", "finishing"],
  alloy: ["smelting", "forging", "heat_treat", "finishing"], // 광석 4공정
};
const staminaCostByInput = { ore: 4, ingot: 3, alloy_ingot: 3, alloy: 4 };
const inputTypeLabels = { ore: "광석", ingot: "주괴", alloy_ingot: "합금주괴", alloy: "합금 제작" };

function getCurrentChar() {
  return charactersData[document.getElementById("cmd-character").value];
}

function ownedQty(char, inputType, material) {
  if (inputType === "ore") return (char.ore_inventory || {})[material] || 0;
  if (inputType === "ingot") return (char.ingot_inventory || {})[material] || 0;
  if (inputType === "alloy_ingot") return (char.alloy_ingot_inventory || {})[material] || 0;
  return 0;
}

function statusSuffix(matCode, char) {
  const st = (char.mat_status || {})[matCode];
  const prof = (char.mat_proficiency || {})[matCode] || 0;
  const bonus = (char.prereq_bonus || {})[matCode] || 0;
  if (st === "unlocked") return "숙련 " + prof;
  if (st === "temp") return "임시 해금 +" + bonus;
  return "지식 없음";
}

function makeOption(value, label, locked) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = label;
  if (locked) opt.disabled = true;
  return opt;
}

function rebuildMaterialDropdown() {
  const matSel = document.getElementById("cmd-material");
  const char = getCurrentChar();
  const workType = document.querySelector('input[name="work_type"]:checked').value;
  const prevValue = matSel.value;
  matSel.innerHTML = "";

  if (!char) return;

  // 표시 조건: 보유 ≥ 1 AND status !== 'locked'
  // (사용자 요청 — 재고 0 / 선행보너스조차 없는 잠금 소재는 아예 숨김)
  function visible(matCode, inputType) {
    const st = (char.mat_status || {})[matCode];
    if (st === "locked") return false;
    return ownedQty(char, inputType, matCode) > 0;
  }

  if (workType === "ingot") {
    // 주괴 제작 — 광석만 (input_type='ore')
    materialGroups.ores.forEach((m) => {
      if (!visible(m.code, "ore")) return;
      const owned = ownedQty(char, "ore", m.code);
      const stars = "★".repeat(m.rarity);
      const label =
        stars +
        " " +
        m.name +
        " 광석 (4공정, " +
        statusSuffix(m.code, char) +
        ", 보유 " +
        owned +
        ")";
      matSel.appendChild(makeOption(m.code + "|ore", label, false));
    });
  } else if (workType === "weapon") {
    // 무기 제작 — WEAPON_RECIPES[weapon]에 따라 ore/ingot/alloy_ingot 분기
    const wc = document.getElementById("cmd-weapon").value;
    const recipe = weaponRecipes[wc] || [];
    recipe.forEach((matCode) => {
      const info = matInfoCmd[matCode] || {};
      const matName = info.name || matCode;
      const stars = "★".repeat(info.rarity || 0);
      if (alloyCodesSet.has(matCode)) {
        if (!visible(matCode, "alloy_ingot")) return;
        const owned = ownedQty(char, "alloy_ingot", matCode);
        const label =
          stars +
          " " +
          matName +
          " 합금주괴 (3공정, " +
          statusSuffix(matCode, char) +
          ", 보유 " +
          owned +
          ")";
        matSel.appendChild(makeOption(matCode + "|alloy_ingot", label, false));
      } else {
        if (visible(matCode, "ore")) {
          const oreOwned = ownedQty(char, "ore", matCode);
          matSel.appendChild(
            makeOption(
              matCode + "|ore",
              stars +
                " " +
                matName +
                " 광석 (4공정, " +
                statusSuffix(matCode, char) +
                ", 보유 " +
                oreOwned +
                ")",
              false
            )
          );
        }
        if (info.ingot && visible(matCode, "ingot")) {
          const ingOwned = ownedQty(char, "ingot", matCode);
          matSel.appendChild(
            makeOption(
              matCode + "|ingot",
              stars +
                " " +
                matName +
                " 주괴 (3공정, " +
                statusSuffix(matCode, char) +
                ", 보유 " +
                ingOwned +
                ")",
              false
            )
          );
        }
      }
    });
  } else if (workType === "alloy") {
    // 합금주괴 제작 — ALLOY_RECIPES 광석 2종 모두 보유 + 합금 자체 잠금 해제
    Object.entries(window.__DASH__.alloy_recipes).forEach(([alloyCode, ores]) => {
      const st = (char.mat_status || {})[alloyCode];
      if (st === "locked") return;
      // 광석 2종 모두 보유 ≥ 1
      const oreOwned = ores.map((o) => ownedQty(char, "ore", o));
      if (oreOwned.some((q) => q < 1)) return;
      const info = matInfoCmd[alloyCode] || {};
      const stars = "★".repeat(info.rarity || 0);
      const name = info.name || alloyCode;
      const oreNames = ores.map((o, i) => (matInfoCmd[o] || {}).name + " " + oreOwned[i]);
      const label =
        stars +
        " " +
        name +
        " 합금주괴 (4공정, " +
        statusSuffix(alloyCode, char) +
        ", 재료 " +
        oreNames.join(" + ") +
        ")";
      matSel.appendChild(makeOption(alloyCode + "|alloy", label, false));
    });
  }

  // 모든 옵션이 숨겨졌으면 placeholder
  if (matSel.options.length === 0) {
    const empty = makeOption("", "사용 가능한 소재가 없습니다 (보유·해금 확인)", true);
    empty.selected = true;
    matSel.appendChild(empty);
  } else if (Array.from(matSel.options).some((o) => o.value === prevValue)) {
    matSel.value = prevValue;
  }

  // 소재 목록이 재생성되면 선택 소재가 바뀔 수 있으므로 품질 옵션도 함께 갱신.
  rebuildQualityDropdown();
}

// 현재 입력 종류별 등급별 재고 dict 반환 (재료 품질 보너스, 2026-06-01)
function qualityInventoryFor(char, inputType) {
  if (inputType === "ingot") return char.ingot_inventory_by_quality || {};
  if (inputType === "alloy_ingot") return char.alloy_ingot_inventory_by_quality || {};
  if (inputType === "ore") return char.ore_inventory_by_quality || {};
  return {};
}

// 선택 소재의 품질 등급 드롭다운 재생성. ingot/alloy_ingot만 등급별, ore/alloy는 "—"(0).
function rebuildQualityDropdown() {
  const qSel = document.getElementById("cmd-quality-grade");
  if (!qSel) return;
  const matSel = document.getElementById("cmd-material");
  const char = getCurrentChar();
  qSel.innerHTML = "";
  const parts = (matSel.value || "|ore").split("|");
  const material = parts[0] || "";
  const inputType = parts[1] || "ore";

  if (!char || !material || inputType === "ore" || inputType === "alloy") {
    qSel.appendChild(makeOption("0", "—", false));
    return;
  }
  const byQuality = qualityInventoryFor(char, inputType)[material] || {};
  const grades = Object.keys(byQuality)
    .map(Number)
    .filter((g) => g >= 1 && byQuality[g] > 0)
    .sort((a, b) => a - b);
  if (grades.length === 0) {
    const empty = makeOption("0", "보유 등급 없음", true);
    empty.selected = true;
    qSel.appendChild(empty);
    return;
  }
  grades.forEach((g) => {
    qSel.appendChild(makeOption(String(g), g + "등급 ×" + byQuality[g], false));
  });
}

// 소재 변경 시 품질 옵션 리셋 후 예측 갱신
function onMaterialChange() {
  rebuildQualityDropdown();
  updateCommandInfo();
}

function onWorkTypeChange() {
  const wt = document.querySelector('input[name="work_type"]:checked').value;
  document.getElementById("cmd-weapon-row").style.display = wt === "weapon" ? "" : "none";
  rebuildMaterialDropdown();
  updateCommandInfo();
}

// P5: 담당 actor 변경 시 소재 드롭다운도 재빌드 (NPC면 NPC 창고 보유 기준)
// 담당(actor) 선택 유지 — dashboard.js와 sessionStorage 키 "fg_actor"만 공유(함수 공유 X).
function writeActor(id) {
  try {
    if (id) sessionStorage.setItem("fg_actor", id);
  } catch (e) {
    /* private mode 등 — 무시 */
  }
}
function applyStoredActor(sel) {
  let id = null;
  try {
    id = sessionStorage.getItem("fg_actor");
  } catch (e) {
    return;
  }
  if (!id || !sel) return;
  if (Array.from(sel.options).some((o) => o.value === id && !o.disabled)) sel.value = id;
}

function onCommandActorChange() {
  writeActor(document.getElementById("cmd-character").value);
  rebuildMaterialDropdown();
  updateCommandInfo();
}

// 합금주괴 제작 시 소모 소재 (광석 2종) 텍스트 생성
const alloyRecipesCmd = window.__DASH__.alloy_recipes;
function alloyConsumeText(alloyCode, quantity) {
  const ores = alloyRecipesCmd[alloyCode] || [];
  return ores
    .map((o) => {
      const name = (matInfoCmd[o] || {}).name || o;
      return name + " 광석 " + quantity + "개";
    })
    .join(" + ");
}

function onWeaponChange() {
  rebuildMaterialDropdown();
  updateCommandInfo();
}

function onQuantityInput() {
  const q = document.getElementById("cmd-quantity");
  const n = parseInt(q.value);
  if (isNaN(n) || n < 0) q.value = 0;
  updateCommandInfo();
}

function updateCommandInfo() {
  const charSel = document.getElementById("cmd-character");
  const matSel = document.getElementById("cmd-material");
  const qInput = document.getElementById("cmd-quantity");
  if (!charSel || !matSel || !qInput) return;
  const char = charactersData[charSel.value];
  if (!char) return;

  const workType = document.querySelector('input[name="work_type"]:checked').value;
  const weaponCat = document.getElementById("cmd-weapon").value;
  const parts = (matSel.value || "|ore").split("|");
  const material = parts[0] || "";
  const inputType = parts[1] || "ore";
  const quantity = Math.max(0, parseInt(qInput.value) || 0);

  const matLabel = matLabels[material] || material || "—";
  const baseStamina = staminaCostByInput[inputType] || 0;
  const bonus = workType === "weapon" ? weaponStaminaBonus[weaponCat] || 0 : 0;
  const needStamina = (baseStamina + bonus) * quantity;

  document.getElementById("info-name").textContent = char.name;

  // 결과물
  let resultText;
  if (workType === "weapon") {
    resultText = matLabel + " " + (weaponLabels[weaponCat] || weaponCat) + " × " + quantity;
  } else if (workType === "alloy") {
    resultText = matLabel + " 합금주괴 × " + quantity;
  } else {
    resultText = matLabel + " 주괴 × " + quantity;
  }
  document.getElementById("info-result").textContent = resultText;

  // 스태미너 (가산 표시)
  const bonusText =
    bonus > 0
      ? " (" + baseStamina + "+" + bonus + " × " + quantity + ")"
      : " (필요 " + needStamina + ")";
  document.getElementById("info-stamina").textContent =
    char.stamina_current + " / " + char.stamina_max + bonusText;

  // 공정 스킬
  const steps = stepsByInput[inputType] || [];
  document.getElementById("info-craft-skills").textContent =
    steps.map((s) => skillLabels[s] + " " + (char.skills[s] || 0)).join(" / ") || "—";

  // 소재 스킬
  const direct = char.mat_proficiency[material] || 0;
  const matBonus = char.prereq_bonus[material] || 0;
  document.getElementById("info-mat-skill").textContent =
    matLabel + " " + direct + (matBonus > 0 ? " (+" + matBonus + ")" : "");

  // 소모 소재 — 합금 모드는 광석 2종 표시, 그 외는 단일 입력 소재
  const matTypeLabel = inputTypeLabels[inputType] || inputType;
  let costText,
    ownedOK = true;
  if (workType === "alloy") {
    costText = alloyConsumeText(material, quantity);
    const ores = alloyRecipesCmd[material] || [];
    ownedOK = ores.every((o) => ownedQty(char, "ore", o) >= quantity);
  } else {
    const owned = ownedQty(char, inputType, material);
    costText = matLabel + " " + matTypeLabel + " " + quantity + "개 (보유 " + owned + "개)";
    ownedOK = owned >= quantity;
  }
  document.getElementById("info-mat-cost").textContent = costText;

  // 재료 품질 보너스 (선택 등급 기준) — bonus = max(0, 등급-1). 광석/1등급 = +0.
  const gradeEl = document.getElementById("cmd-quality-grade");
  const grade = gradeEl ? parseInt(gradeEl.value) || 0 : 0;
  const qbEl = document.getElementById("info-quality-bonus");
  if (qbEl) qbEl.textContent = "+" + Math.max(0, grade - 1);

  // P5: NPC 수수료 표시 (대장간 명령도 1배치 = 수수료 1회)
  // F-5: fee_held > 0 이면 이번 배치 창에 이미 선불됨 → 이 명령은 추가 차감 없음(선불 홀드 0)
  const actorNpcCmd =
    typeof hiredNpcsData !== "undefined" ? hiredNpcsData.find((n) => n.id === charSel.value) : null;
  const cmdBaseFee = actorNpcCmd ? actorNpcCmd.fee_per_batch || 0 : 0;
  const cmdAlreadyHeld = actorNpcCmd && (actorNpcCmd.fee_held || 0) > 0;
  const feeEl = document.getElementById("info-fee");
  if (feeEl) {
    if (!actorNpcCmd) {
      feeEl.textContent = "0량 (본인 작업, 수수료 없음)";
    } else if (cmdAlreadyHeld) {
      feeEl.textContent =
        "0량 (이미 선불됨 — " +
        actorNpcCmd.name +
        ", 선불 " +
        cmdBaseFee.toLocaleString() +
        "량 / 이번 배치 추가 없음)";
    } else {
      feeEl.textContent =
        cmdBaseFee.toLocaleString() + "량 (NPC 수수료 선불 홀드, " + actorNpcCmd.name + " 1배치)";
    }
  }

  // 부족 경고
  const submitBtn = document.getElementById("cmd-submit");
  const warning = document.getElementById("cmd-warning");
  let warnMsg = "";
  if (quantity > 0) {
    if (needStamina > char.stamina_current) warnMsg = "스태미나 부족";
    else if (!ownedOK)
      warnMsg = workType === "alloy" ? "재료 광석 부족" : matLabel + " " + matTypeLabel + " 부족";
  }
  submitBtn.disabled = !!warnMsg;
  warning.textContent = warnMsg;
  warning.style.display = warnMsg ? "inline" : "none";
}

document.addEventListener("DOMContentLoaded", () => {
  applyStoredActor(document.getElementById("cmd-character")); // 마지막 선택 담당 복원
  rebuildMaterialDropdown();
  updateCommandInfo();
});
