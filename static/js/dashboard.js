// 대시보드 전역 — 탭 전환, 카운트다운, NPC, 통제실, 창고, 중앙광장
// 데이터는 window.__DASH__ 부트스트랩 객체에서 받는다.
const STAT_DESCS = {
  무력: "전투 능력을 나타냅니다. 전투 판정, 제압, 물리적 위협 등에 사용됩니다.",
  지략: "전략과 계획 능력을 나타냅니다. 작전 수립, 함정 탐지, 정보 분석에 사용됩니다.",
  매력: "설득과 외교 능력을 나타냅니다. 협상, 포섭, NPC 관계 형성에 영향을 줍니다.",
  건강: "체력과 생존력을 나타냅니다. 스태미너 최대치 및 회복력에 영향을 줍니다.",
  운: "행운을 나타냅니다. 판정 성공률 보정 및 돌발 이벤트에 영향을 줍니다.",
  민첩: "재빠름을 나타냅니다. 시장 거래 경쟁 체결 우선권 판정에 사용됩니다.",
  // 통솔은 2026-05-31 '인재관리' 스킬로 이관 (대장간 기술 옆 공용 기술). 스탯 설명에서 제외.
};

let currentSection = "blacksmith";
let currentTab = "character";

function switchSection(section) {
  // 상단 탭 활성화
  document.querySelectorAll(".top-tab").forEach((btn) => btn.classList.remove("active"));
  event.currentTarget.classList.add("active");

  // 사이드바 섹션 전환
  document.querySelectorAll(".sidebar-section").forEach((s) => s.classList.remove("active"));
  document.getElementById("sidebar-" + section).classList.add("active");

  // 해당 섹션의 첫 번째 사이드 아이템 클릭
  const firstItem = document.querySelector("#sidebar-" + section + " .sidebar-item");
  if (firstItem) firstItem.click();

  currentSection = section;
}

function switchTab(tab) {
  // 좌측 탭 활성화 (현재 섹션 안에서만)
  const sidebarSection = document.getElementById("sidebar-" + currentSection);
  sidebarSection.querySelectorAll(".sidebar-item").forEach((btn) => btn.classList.remove("active"));
  event.currentTarget.classList.add("active");

  // 중앙 패널 전환
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("content-" + tab).classList.add("active");

  // 우측 패널 초기화
  showRightDefault();

  currentTab = tab;
}

function showStatDesc(name, val) {
  document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("right-stat").classList.add("active");
  document.getElementById("right-stat-name").textContent = name;
  document.getElementById("right-stat-val").textContent = val + " / 95";
  document.getElementById("right-stat-desc").textContent = STAT_DESCS[name] || "";
}

function showRightDefault() {
  document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("right-default").classList.add("active");
}

// 카운트다운 — BATCH_HOURS_KST 환경변수 기반
const BATCH_HOURS_KST = window.__DASH__.batch_hours_kst;
const CANCEL_CUTOFF_SECONDS = 600;

function getNextBatchSeconds() {
  const now = new Date();
  const kst = new Date(now.getTime() + 9 * 3600 * 1000);
  const h = kst.getUTCHours(),
    m = kst.getUTCMinutes(),
    s = kst.getUTCSeconds();
  const nowSec = h * 3600 + m * 60 + s;
  for (const bh of BATCH_HOURS_KST) {
    const target = bh * 3600;
    if (target > nowSec) return target - nowSec;
  }
  // 오늘 시각 모두 지남 → 내일 첫 시각
  return (BATCH_HOURS_KST[0] + 24) * 3600 - nowSec;
}

function formatHMS(diff) {
  const hh = Math.floor(diff / 3600)
    .toString()
    .padStart(2, "0");
  const mm = Math.floor((diff % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const ss = (diff % 60).toString().padStart(2, "0");
  return hh + ":" + mm + ":" + ss;
}

function updateCountdown() {
  const diff = getNextBatchSeconds();
  const text = formatHMS(diff);
  const head = document.getElementById("countdown");
  if (head) head.textContent = text;
  const ctrl = document.getElementById("control-countdown");
  if (ctrl) ctrl.textContent = text;
  // 통제실 § 우측 패널 취소 버튼 비활성 (10분 컷)
  const btn = document.getElementById("right-command-cancel-btn");
  if (btn) {
    const cutoff = diff < CANCEL_CUTOFF_SECONDS;
    btn.disabled = cutoff;
    const hint = document.getElementById("right-command-cancel-hint");
    if (hint) hint.style.color = cutoff ? "#e74c3c" : "";
  }
}

updateCountdown();
setInterval(updateCountdown, 1000);

// ── P5 NPC 고용인 탭 ────────────────────────────────────
const hiredNpcsData = window.__DASH__.hired_npcs;
const npcCandidatesData = window.__DASH__.npc_candidates;
const skillLabelKr = {
  smelting: "제련",
  forging: "단조",
  heat_treat: "열처리",
  finishing: "마감",
  appraisal: "감정",
  talent_management: "인재관리",
};
const matLabelsP5 = window.__DASH__.material_labels;

function _fmtStats(s) {
  return (
    "무 " +
    (s.strength || 0) +
    " 지 " +
    (s.intelligence || 0) +
    " 매 " +
    (s.charisma || 0) +
    " 건 " +
    (s.health || 0) +
    " 운 " +
    (s.luck || 0) +
    " 민 " +
    (s.dexterity || 0)
  );
}
function _fmtSkills(sk) {
  return Object.entries(sk || {})
    .filter(([k, _]) => k !== "appraisal")
    .map(([k, v]) => skillLabelKr[k] + " " + v)
    .join(" / ");
}
function _fmtProf(p) {
  const nz = Object.entries(p || {}).filter(([_, v]) => v > 0);
  if (nz.length === 0) return "없음";
  return nz.map(([k, v]) => (matLabelsP5[k] || k) + " " + v).join(" / ");
}
function _fmtGold(n) {
  return (n || 0).toLocaleString() + "량";
}

function showHiredNpcDetail(npcId) {
  const n = hiredNpcsData.find((x) => x.id === npcId);
  if (!n) return;
  document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("right-npc-hired").classList.add("active");
  document
    .querySelectorAll(".npc-card")
    .forEach((el) => el.classList.toggle("selected", el.dataset.npcId === npcId));
  document.getElementById("right-npc-hired-name").textContent = n.name;
  document.getElementById("right-npc-hired-stats").textContent = _fmtStats(n.stats || {});
  document.getElementById("right-npc-hired-skills").textContent = _fmtSkills(n.skills);
  document.getElementById("right-npc-hired-prof").textContent = _fmtProf(n.proficiency);
  document.getElementById("right-npc-hired-stamina").textContent =
    (n.stamina_current || 0) + "/" + (n.stamina_max || 0);
  document.getElementById("right-npc-hired-fee").textContent =
    _fmtGold(n.fee_per_batch) + " / 배치";
  document.getElementById("right-npc-hired-hire").textContent = _fmtGold(n.hire_cost);
  let status = "정상";
  if (n.is_serious_injured) status = "🩹 중상 (" + (n.serious_injury_remaining || 0) + "배치 남음)";
  else if (n.is_injured) status = "⚠ 부상";
  document.getElementById("right-npc-hired-status").textContent = status;
  document.getElementById("right-npc-hired-id").value = npcId;
}

function showCandidateDetail(candId) {
  const c = npcCandidatesData.find((x) => x.id === candId);
  if (!c) return;
  document.querySelectorAll(".right-content").forEach((el) => el.classList.remove("active"));
  document.getElementById("right-npc-candidate").classList.add("active");
  document
    .querySelectorAll(".npc-card")
    .forEach((el) => el.classList.toggle("selected", el.dataset.candId === candId));
  document.getElementById("right-npc-cand-name").textContent = c.name;
  document.getElementById("right-npc-cand-stats").textContent = _fmtStats(c.stats || {});
  document.getElementById("right-npc-cand-total").textContent = c.stat_total;
  document.getElementById("right-npc-cand-skills").textContent = _fmtSkills(c.skills);
  document.getElementById("right-npc-cand-prof").textContent = _fmtProf(c.proficiency);
  document.getElementById("right-npc-cand-hire").textContent = _fmtGold(c.hire_cost);
  document.getElementById("right-npc-cand-fee").textContent = _fmtGold(c.fee) + " / 배치";
  document.getElementById("right-npc-cand-id").value = candId;
  // 자금 부족 시 버튼 비활성
  const btn = document.getElementById("right-npc-cand-hire-btn");
  btn.disabled = userGold < c.hire_cost;
  btn.textContent =
    userGold < c.hire_cost
      ? "자금 부족 (필요 " + _fmtGold(c.hire_cost) + ")"
      : "매력 판정으로 고용 시도";
}

// ── 통제실 § 명령 상세 (A-1) ────────────────────────────
const pendingCommandsData = window.__DASH__.pending_commands;
function showCommandDetail(cmdId) {
  const cmd = pendingCommandsData.find((c) => c.id === cmdId);
  if (!cmd) return;
  document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("right-command").classList.add("active");
  document
    .querySelectorAll(".control-command-item")
    .forEach((el) => el.classList.toggle("selected", el.dataset.cmdId === cmdId));
  document.getElementById("right-command-owner").textContent = cmd.character_name || "—";
  document.getElementById("right-command-result").textContent = cmd.result_label || "—";
  document.getElementById("right-command-stamina").textContent = cmd.reserved_stamina + " 점";
  document.getElementById("right-command-gold").textContent = cmd.reserved_gold
    ? cmd.reserved_gold.toLocaleString() + " 량"
    : "없음";
  document.getElementById("right-command-time").textContent = cmd.created_at
    ? cmd.created_at.replace("T", " ").slice(0, 16)
    : "—";
  document.getElementById("right-command-id").value = cmdId;
  updateCountdown();
}

function toggleMailDetail(id) {
  const el = document.getElementById(id);
  el.style.display = el.style.display === "none" ? "block" : "none";
}

// ── P3-4 창고 UI ──────────────────────────────────────────
const itemsData = window.__DASH__.items;
const categoryByType = window.__DASH__.category_by_type;
const categoryOrder = window.__DASH__.category_order;
const categoryLabels = window.__DASH__.category_labels;
const matLabelsAll = window.__DASH__.material_labels;
const itemTypeLabels = window.__DASH__.item_type_labels;
const alloyRecipes = window.__DASH__.alloy_recipes;
const materialInfo = window.__DASH__.material_info;

// 아이템 한 줄 설명 — P4-3. 키 = 'item_type|material' (무기는 'dagger|' 처럼 material 빈 값).
const ITEM_DESCRIPTIONS = window.__DASH__.item_descriptions;

// ── P4-1 중앙광장 데이터 ──────────────────────────────────
const merchants = window.__DASH__.merchants;
const merchantInventory = window.__DASH__.merchant_inventory;
const marketPrices = window.__DASH__.market_prices;
const inventoryItems = window.__DASH__.inventory_items;
const qualityMultipliers = window.__DASH__.quality_multipliers;
const userGold = window.__DASH__.user_gold;
const plazaCharsData = window.__DASH__.characters_data;

function buildItemUsage(item) {
  const usages = [];
  if (item.item_type === "ore") {
    // 광석 → 주괴 제련
    const info = materialInfo[item.material];
    if (info) {
      const matName = info.name || item.material;
      usages.push("제련 → " + matName + " 주괴 (4공정)");
    }
    // 합금 재료로 쓰이는지
    const alloyUses = Object.entries(alloyRecipes)
      .filter(([_, mats]) => mats.includes(item.material))
      .map(([alloyCode]) => (materialInfo[alloyCode] || {}).name || alloyCode);
    if (alloyUses.length > 0) {
      usages.push("합금 재료: " + alloyUses.join(", "));
    }
  } else if (item.item_type === "ingot") {
    usages.push("무기 제작 재료 (3공정)");
    usages.push("※ 무기 제작은 P3-2 도입 예정");
  } else if (item.item_type === "alloy_ingot") {
    usages.push("합금 무기 제작 재료 (3공정)");
    usages.push("※ 무기 제작은 P3-2 도입 예정");
  } else if (item.item_type === "weapon") {
    usages.push("전투·장비용");
  }
  return usages;
}

const warehouseState = { cat: "all", sort: "created_desc", q: "", selectedId: null };

function itemDisplayName(item) {
  const matName = matLabelsAll[item.material] || item.material || "";
  const typeName = itemTypeLabels[item.item_type] || item.item_type || "";
  const qualityText = item.item_type === "ore" ? "" : " (품질 " + (item.quality || 0) + "등급)";
  return (matName + " " + typeName).trim() + qualityText;
}

function renderWarehouse() {
  // 카테고리별 카운트
  const counts = { all: itemsData.length };
  categoryOrder.forEach((c) => (counts[c] = 0));
  itemsData.forEach((it) => {
    const cat = categoryByType[it.item_type];
    if (cat && cat in counts) counts[cat] += 1;
  });
  document.querySelectorAll("[data-cat-count]").forEach((el) => {
    el.textContent = counts[el.dataset.catCount] || 0;
  });
  document.querySelectorAll(".cat-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.cat === warehouseState.cat);
  });

  // 필터링
  const q = (warehouseState.q || "").trim().toLowerCase();
  let filtered = itemsData.filter((it) => {
    if (warehouseState.cat !== "all" && categoryByType[it.item_type] !== warehouseState.cat)
      return false;
    if (!q) return true;
    const name = itemDisplayName(it).toLowerCase();
    const matCode = (it.material || "").toLowerCase();
    const qualityText = (it.quality || 0) + "등급";
    return name.includes(q) || matCode.includes(q) || qualityText.includes(q);
  });

  // 정렬
  const [field, dir] = warehouseState.sort.split("_");
  const sign = dir === "asc" ? 1 : -1;
  filtered.sort((a, b) => {
    let va, vb;
    if (field === "created") {
      va = a.created_at || "";
      vb = b.created_at || "";
    } else if (field === "quality") {
      va = a.quality || 0;
      vb = b.quality || 0;
    } else {
      va = a.quantity || 0;
      vb = b.quantity || 0;
    }
    if (va < vb) return -sign;
    if (va > vb) return sign;
    return 0;
  });

  // 렌더 — 이름·품질·수량·제작일 4컬럼 표
  const table = document.getElementById("warehouse-items");
  const tbody = document.getElementById("warehouse-tbody");
  const empty = document.getElementById("warehouse-empty");
  if (filtered.length === 0) {
    tbody.innerHTML = "";
    table.style.display = "none";
    empty.style.display = "block";
  } else {
    table.style.display = "";
    empty.style.display = "none";
    tbody.innerHTML = filtered
      .map((it) => {
        // 등급 색 매핑 통일: quality 1~5면 quality, 아니면(광석·quality 0 옛 데이터) 소재 rarity로 fallback
        const r =
          it.quality >= 1 && it.quality <= 5
            ? it.quality
            : (materialInfo[it.material] || {}).rarity || 0;
        const classes = [];
        if (it.id === warehouseState.selectedId) classes.push("selected");
        if (r >= 1 && r <= 5) classes.push("rarity-" + r);
        const clsAttr = classes.length ? ' class="' + classes.join(" ") + '"' : "";
        const matName = matLabelsAll[it.material] || it.material || "";
        const typeName = itemTypeLabels[it.item_type] || it.item_type || "";
        const name = (matName + " " + typeName).trim();
        // 등급 표시 통일: quality 1~5만 'N등급', 그 외(광석·미정·옛 데이터)는 모두 '—'
        const qualityCell = it.quality >= 1 && it.quality <= 5 ? it.quality + "등급" : "—";
        return (
          "<tr" +
          clsAttr +
          " onclick=\"showWarehouseItem('" +
          it.id +
          "')\">" +
          '<td class="col-name">' +
          escapeHtml(name) +
          "</td>" +
          '<td class="col-quality">' +
          escapeHtml(qualityCell) +
          "</td>" +
          '<td class="col-quantity">' +
          (it.quantity || 0) +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  syncWarehouseUrl();
}

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

function setWarehouseCat(cat) {
  warehouseState.cat = cat;
  warehouseState.selectedId = null;
  renderWarehouse();
  showRightDefault();
}

function onWarehouseSearch() {
  warehouseState.q = document.getElementById("warehouse-search").value;
  renderWarehouse();
}

function onWarehouseSort() {
  warehouseState.sort = document.getElementById("warehouse-sort").value;
  renderWarehouse();
}

function showWarehouseItem(itemId) {
  const item = itemsData.find((it) => it.id === itemId);
  if (!item) return;
  warehouseState.selectedId = itemId;
  document.querySelectorAll("#warehouse-tbody tr").forEach((el) => el.classList.remove("selected"));
  const clicked = document.querySelector('#warehouse-tbody tr[onclick*="' + itemId + '"]');
  if (clicked) clicked.classList.add("selected");

  document.querySelectorAll(".right-content").forEach((c) => c.classList.remove("active"));
  document.getElementById("right-item").classList.add("active");
  document.getElementById("right-item-name").textContent = itemDisplayName(item);
  document.getElementById("right-item-move-id").value = item.id;
  // A-3: quantity max·기본값 = row 전체. 대상은 첫 옵션(본인)으로 초기화.
  const moveQty = document.getElementById("right-item-move-qty");
  const moveMax = document.getElementById("right-item-move-max");
  if (moveQty) {
    moveQty.max = item.quantity || 1;
    moveQty.value = item.quantity || 1;
  }
  if (moveMax) moveMax.textContent = "/ " + (item.quantity || 0);

  // 품질·수량 한 줄
  const statsEl = document.getElementById("right-item-stats");
  const qualityPill =
    item.item_type === "ore"
      ? ""
      : '<span class="item-stat-pill"><strong>품질</strong> ' + (item.quality || 0) + "등급</span>";
  statsEl.innerHTML =
    qualityPill +
    '<span class="item-stat-pill"><strong>수량</strong> ' +
    (item.quantity || 0) +
    "개</span>";

  // 설명 — P4-3 ITEM_DESCRIPTIONS. 무기는 카테고리 단위(material 무시).
  const descEl = document.getElementById("right-item-desc");
  const isWeapon = categoryByType[item.item_type] === "weapon";
  const descKey = item.item_type + "|" + (isWeapon ? "" : item.material);
  const desc = ITEM_DESCRIPTIONS[descKey];
  if (desc) {
    descEl.textContent = desc;
    descEl.classList.remove("item-section-placeholder");
  } else {
    descEl.textContent = "아직 등록된 설명이 없습니다.";
    descEl.classList.add("item-section-placeholder");
  }

  // 사용처 — 동적 생성
  const usageEl = document.getElementById("right-item-usage");
  const usages = buildItemUsage(item);
  if (usages.length === 0) {
    usageEl.innerHTML = '<span class="item-section-placeholder">—</span>';
  } else {
    usageEl.innerHTML =
      "<ul>" + usages.map((u) => "<li>" + escapeHtml(u) + "</li>").join("") + "</ul>";
  }
}

function syncWarehouseUrl() {
  // 창고 필터(카테고리·검색·정렬)를 sessionStorage에 백킹 — 이동 후 #storage 리다이렉트(파라미터 없음)에도 유지.
  try {
    sessionStorage.setItem(
      "fg_wh",
      JSON.stringify({ cat: warehouseState.cat, sort: warehouseState.sort, q: warehouseState.q })
    );
  } catch (e) {
    /* private mode 등 — 무시 */
  }
  if (currentTab !== "storage") return;
  const params = new URLSearchParams();
  if (warehouseState.cat !== "all") params.set("cat", warehouseState.cat);
  if (warehouseState.sort !== "created_desc") params.set("sort", warehouseState.sort);
  if (warehouseState.q) params.set("q", warehouseState.q);
  const qs = params.toString();
  history.replaceState(null, "", "#storage" + (qs ? "?" + qs : ""));
}

function parseWarehouseFromHash() {
  const hash = location.hash.substring(1);
  const idx = hash.indexOf("?");
  if (idx >= 0) {
    const params = new URLSearchParams(hash.substring(idx + 1));
    if (params.has("cat")) warehouseState.cat = params.get("cat");
    if (params.has("sort")) warehouseState.sort = params.get("sort");
    if (params.has("q")) warehouseState.q = params.get("q");
  } else {
    // URL 해시에 필터 없음(이동 후 #storage 리다이렉트 등) → sessionStorage 복원
    try {
      const saved = JSON.parse(sessionStorage.getItem("fg_wh") || "null");
      if (saved) {
        if (saved.cat) warehouseState.cat = saved.cat;
        if (saved.sort) warehouseState.sort = saved.sort;
        if (saved.q) warehouseState.q = saved.q;
      }
    } catch (e) {
      /* 무시 */
    }
  }
  const searchEl = document.getElementById("warehouse-search");
  const sortEl = document.getElementById("warehouse-sort");
  if (searchEl) searchEl.value = warehouseState.q;
  if (sortEl) sortEl.value = warehouseState.sort;
}

// ── P4-1 중앙광장 ──────────────────────────────────────────
function plazaIsWeapon(t) {
  return categoryByType[t] === "weapon";
}

function plazaStackLimit(itemType, material) {
  if (itemType === "ore") {
    const r = (materialInfo[material] || {}).rarity || 3;
    return { 1: 999, 2: 500, 3: 100, 4: 50, 5: 20 }[r] || 99;
  }
  if (itemType === "ingot") return 100;
  if (itemType === "alloy_ingot") return 50;
  return 99;
}

function plazaItemName(itemType, material, quality) {
  const mat = matLabelsAll[material] || material || "";
  const tn = itemTypeLabels[itemType] || itemType || "";
  let s = (mat + " " + tn).trim();
  if (plazaIsWeapon(itemType) && quality) s += " (품질 " + quality + "등급)";
  return s;
}

function plazaCharId() {
  const sel = document.getElementById("plaza-character");
  return sel ? sel.value : "";
}

function plazaChar() {
  return plazaCharsData[plazaCharId()] || {};
}

// ── 담당(actor) 선택 유지 — sessionStorage 공유 키 "fg_actor" (2026-06-01) ──
// 작업 후 전체 새로고침 시 select가 첫 옵션으로 리셋되는 문제 → 마지막 선택 actor 복원.
// workshop_form.js와 키만 공유(함수 공유 X) → 두 파일 로드 순서 무관.
function writeActor(id) {
  try {
    if (id) sessionStorage.setItem("fg_actor", id);
  } catch (e) {
    /* private mode 등 — 무시 */
  }
}
function readActor() {
  try {
    return sessionStorage.getItem("fg_actor");
  } catch (e) {
    return null;
  }
}
// 저장 id가 그 select의 非disabled 옵션이면 value 설정(없으면 첫 옵션 폴백). change dispatch 안 함.
function applyStoredActor(sel) {
  const id = readActor();
  if (!id || !sel) return;
  if (Array.from(sel.options).some((o) => o.value === id && !o.disabled)) sel.value = id;
}

function onPlazaCharChange() {
  writeActor(plazaCharId());
  const buyChar = document.getElementById("buy-char-id");
  if (buyChar) buyChar.value = plazaCharId();
  renderInventorySlots();
  rebuildSellItems();
  updateBuyPrediction();
  updateSellPrediction();
}

// P5: 현재 선택된 actor(본인 캐릭터 or NPC)의 인벤만 필터링
function inventoryItemsForPlazaActor() {
  const aid = plazaCharId();
  if (!aid) return inventoryItems.slice();
  return inventoryItems.filter((it) => it.owner_id === aid);
}

function renderInventorySlots() {
  const wrap = document.getElementById("plaza-inv-slots");
  if (!wrap) return;
  // CSRF: 서버 렌더된 폼의 토큰을 재사용 (쿠키는 httponly라 JS가 못 읽음).
  const csrf = (document.querySelector('input[name="csrf_token"]') || {}).value || "";
  const own = inventoryItemsForPlazaActor();
  let html = "";
  for (let i = 0; i < 5; i++) {
    const it = own[i];
    if (it) {
      html +=
        '<div class="inv-slot">' +
        '<div class="inv-slot-name">' +
        escapeHtml(plazaItemName(it.item_type, it.material, it.quality)) +
        "</div>" +
        '<div class="inv-slot-qty">×' +
        (it.quantity || 0) +
        "</div>" +
        '<form method="post" action="/commands/move-item">' +
        '<input type="hidden" name="item_id" value="' +
        it.id +
        '">' +
        '<input type="hidden" name="direction" value="to_warehouse">' +
        '<input type="hidden" name="csrf_token" value="' +
        csrf +
        '">' +
        '<button type="submit">창고로</button></form>' +
        "</div>";
    } else {
      html += '<div class="inv-slot empty">빈 칸</div>';
    }
  }
  wrap.innerHTML = html;
}

function buyMerchantOptions() {
  const sel = document.getElementById("buy-merchant");
  if (!sel) return;
  sel.innerHTML = "";
  merchants
    .filter((m) => m.merchant_type === "fixed" || m.merchant_type === "random")
    .forEach((m) => {
      const o = document.createElement("option");
      o.value = m.id;
      o.textContent = m.name;
      sel.appendChild(o);
    });
}

function onBuyMerchantChange() {
  const mSel = document.getElementById("buy-merchant");
  const iSel = document.getElementById("buy-item");
  if (!mSel || !iSel) return;
  iSel.innerHTML = "";
  const rows = merchantInventory.filter((r) => r.merchant_id === mSel.value);
  rows.sort(
    (a, b) =>
      ((materialInfo[a.material] || {}).rarity || 0) -
      ((materialInfo[b.material] || {}).rarity || 0)
  );
  rows.forEach((r) => {
    const o = document.createElement("option");
    o.value = r.item_type + "|" + r.material;
    const price = marketPrices[r.merchant_id + "|" + r.item_type + "|" + r.material];
    const priceText = price != null ? price.toLocaleString() + "량" : "시세 미정";
    o.textContent =
      plazaItemName(r.item_type, r.material, 0) +
      " · " +
      priceText +
      " · 재고 " +
      (r.stock_current || 0);
    iSel.appendChild(o);
  });
  if (iSel.options.length === 0) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "취급 품목이 없습니다";
    o.disabled = true;
    iSel.appendChild(o);
  }
  updateBuyPrediction();
}

function updateBuyPrediction() {
  const iSel = document.getElementById("buy-item");
  const predEl = document.getElementById("buy-predict");
  const submit = document.getElementById("buy-submit");
  if (!iSel || !predEl || !submit) return;
  const parts = (iSel.value || "").split("|");
  const itemType = parts[0] || "";
  const material = parts[1] || "";
  document.getElementById("buy-item-type").value = itemType;
  document.getElementById("buy-item-material").value = material;

  const char = plazaChar();
  if (char.is_serious_injured) {
    predEl.textContent = "중상 중 — 거래할 수 없습니다.";
    predEl.classList.add("warn");
    submit.disabled = true;
    return;
  }
  if (!itemType || !material) {
    predEl.textContent = "취급 품목이 없습니다.";
    predEl.classList.add("warn");
    submit.disabled = true;
    return;
  }
  const qty = Math.max(0, parseInt(document.getElementById("buy-qty").value) || 0);
  const mid = document.getElementById("buy-merchant").value;
  const unit = marketPrices[mid + "|" + itemType + "|" + material] || 0;
  const invRow = merchantInventory.find(
    (r) => r.merchant_id === mid && r.item_type === itemType && r.material === material
  );
  const stock = invRow ? invRow.stock_current || 0 : 0;
  const stamina = char.stamina_current || 0;

  const maxGold = unit > 0 ? Math.floor(userGold / unit) : 0;
  // P5: buy 도착 actor(plazaCharId)의 인벤만 카운트
  const ownInv = inventoryItemsForPlazaActor();
  const slot = ownInv.find(
    (it) => it.item_type === itemType && it.material === material && (it.quality || 0) === 0
  );
  const maxSlot = slot
    ? Math.max(0, plazaStackLimit(itemType, material) - (slot.quantity || 0))
    : ownInv.length < 5
      ? plazaStackLimit(itemType, material)
      : 0;
  // 거래는 명령당 고정 1 스태미너 — 수량을 스태미너로 캡하지 않음(스태미너 ≥ 1만 요구)
  const maxOrder = Math.min(maxGold, maxSlot);

  let msg =
    "단가 <strong>" +
    unit.toLocaleString() +
    "량</strong>" +
    " · 최대 <strong>" +
    maxOrder +
    "개</strong> 주문 가능" +
    '<br><span style="color:#a0a0b0;">자금 ' +
    maxGold +
    " / 인벤 " +
    maxSlot +
    " / 스태미너 " +
    stamina +
    " · 상인 재고 " +
    stock +
    "</span>";
  let warn = "";
  if (qty > 0) {
    if (stamina < 1) warn = "스태미너가 부족합니다 (거래 1건당 1 소모).";
    else if (maxSlot <= 0) warn = "인벤토리 5칸이 가득 찼습니다. 창고로 옮기세요.";
    else if (qty > maxGold) warn = "자금이 부족합니다.";
    else if (qty > maxSlot) warn = "인벤 슬롯 적재 한도를 초과합니다.";
  }
  if (warn) {
    msg += '<br><span style="color:#ff6b8a;">⚠ ' + warn + "</span>";
  } else if (qty > 0) {
    const goods = qty * unit;
    // P5: 도착 actor가 NPC면 그 NPC의 배치당 수수료 1회 추가 (한 명령 = 1배치 수행)
    // F-5: fee_held > 0 이면 이번 배치에 이미 선불됨 → 이 명령의 한계 수수료 0
    const actorNpc = hiredNpcsData.find((n) => n.id === plazaCharId());
    const baseFee = actorNpc ? actorNpc.fee_per_batch || 0 : 0;
    const alreadyHeld = actorNpc && (actorNpc.fee_held || 0) > 0;
    const fee = alreadyHeld ? 0 : baseFee;
    msg += "<br>예상 지불 <strong>" + goods.toLocaleString() + "량</strong>";
    if (qty > stock)
      msg += ' <span style="color:#a0a0b0;">(재고 ' + stock + "개 초과분은 부분 도착·환불)</span>";
    if (actorNpc && alreadyHeld) {
      msg +=
        "<br>NPC 수수료 <strong>0량</strong>" +
        ' <span style="color:#a0a0b0;">(' +
        escapeHtml(actorNpc.name) +
        " — 이미 선불 " +
        baseFee.toLocaleString() +
        "량, 이번 배치 추가 없음)</span>";
    } else if (actorNpc) {
      msg +=
        "<br>NPC 수수료 <strong>" +
        baseFee.toLocaleString() +
        "량</strong>" +
        ' <span style="color:#a0a0b0;">(' +
        escapeHtml(actorNpc.name) +
        " 1배치 선불 홀드)</span>";
    }
    msg += "<br>총 예상 지출 <strong>" + (goods + fee).toLocaleString() + "량</strong>";
  }
  predEl.innerHTML = msg;
  predEl.classList.toggle("warn", !!warn);
  submit.disabled = qty < 1 || !!warn;
}

function rebuildSellItems() {
  const sel = document.getElementById("sell-item");
  if (!sel) return;
  sel.innerHTML = "";
  // P5: 현재 선택된 actor의 인벤만 표시
  const own = inventoryItemsForPlazaActor();
  if (own.length === 0) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "판매할 인벤 아이템이 없습니다";
    o.disabled = true;
    sel.appendChild(o);
    return;
  }
  own.forEach((it) => {
    const o = document.createElement("option");
    o.value = it.id;
    o.textContent =
      plazaItemName(it.item_type, it.material, it.quality) + " ×" + (it.quantity || 0);
    sel.appendChild(o);
  });
}

function updateSellPrediction() {
  const sel = document.getElementById("sell-item");
  const predEl = document.getElementById("sell-predict");
  const submit = document.getElementById("sell-submit");
  const merchEl = document.getElementById("sell-merchant");
  if (!sel || !predEl || !submit) return;
  const it = inventoryItems.find((x) => x.id === sel.value);
  if (!it) {
    predEl.textContent = "판매할 인벤 아이템이 없습니다.";
    predEl.classList.add("warn");
    merchEl.textContent = "—";
    submit.disabled = true;
    return;
  }
  merchEl.textContent = plazaIsWeapon(it.item_type) ? "성주 직속 군수관" : "관시 행상";

  const char = plazaChar();
  if (char.is_serious_injured) {
    predEl.textContent = "중상 중 — 거래할 수 없습니다.";
    predEl.classList.add("warn");
    submit.disabled = true;
    return;
  }
  const qty = Math.max(0, parseInt(document.getElementById("sell-qty").value) || 0);
  const held = it.quantity || 0;
  let unit;
  if (plazaIsWeapon(it.item_type)) {
    // 무기는 태수가 매입 — 태수 시세 × 품질 배율
    const officerId = (merchants.find((x) => x.code === "officer_buyer") || {}).id;
    const base = marketPrices[officerId + "|" + it.item_type + "|" + it.material] || 0;
    unit = Math.floor(base * (qualityMultipliers[it.quality] || 0));
  } else {
    // 광물·주괴·합금주괴는 관시 행상이 매입 — 관시 시세 × 90%
    const fixedId = (merchants.find((x) => x.code === "fixed_official") || {}).id;
    unit = Math.floor((marketPrices[fixedId + "|" + it.item_type + "|" + it.material] || 0) * 0.9);
  }
  const stamina = char.stamina_current || 0;
  // 거래는 명령당 고정 1 스태미너 — 보유 수량 전체를 한 명령으로 판매 가능(스태미너 ≥ 1만 요구)
  const maxSell = held;

  let msg =
    "보유 <strong>" +
    held +
    "개</strong> · 단가 <strong>" +
    unit.toLocaleString() +
    "량</strong>" +
    '<br><span style="color:#a0a0b0;">스태미너 ' +
    stamina +
    " · 최대 " +
    maxSell +
    "개 판매 가능</span>";
  let warn = "";
  if (qty > 0) {
    if (stamina < 1) warn = "스태미너가 부족합니다 (거래 1건당 1 소모).";
    else if (unit <= 0)
      warn = "이 매입처가 사주지 않는 자원입니다 (시세 없음). 관시 행상은 ★1 자원만 취급.";
    else if (qty > held) warn = "보유 수량을 초과합니다.";
  }
  if (warn) {
    msg += '<br><span style="color:#ff6b8a;">⚠ ' + warn + "</span>";
  } else if (qty > 0) {
    const income = qty * unit;
    // P5: 판매 actor가 NPC면 그 NPC의 배치당 수수료 1회 차감 (한 명령 = 1배치 수행)
    // F-5: fee_held > 0 이면 이번 배치에 이미 선불됨 → 이 명령의 한계 수수료 0
    const actorNpc = hiredNpcsData.find((n) => n.id === plazaCharId());
    const baseFee = actorNpc ? actorNpc.fee_per_batch || 0 : 0;
    const alreadyHeld = actorNpc && (actorNpc.fee_held || 0) > 0;
    const fee = alreadyHeld ? 0 : baseFee;
    msg += "<br>예상 수입 <strong>" + income.toLocaleString() + "량</strong>";
    if (actorNpc && alreadyHeld) {
      msg +=
        "<br>NPC 수수료 <strong>-0량</strong>" +
        ' <span style="color:#a0a0b0;">(' +
        escapeHtml(actorNpc.name) +
        " — 이미 선불 " +
        baseFee.toLocaleString() +
        "량, 이번 배치 추가 없음)</span>";
    } else if (actorNpc) {
      msg +=
        "<br>NPC 수수료 <strong>-" +
        baseFee.toLocaleString() +
        "량</strong>" +
        ' <span style="color:#a0a0b0;">(' +
        escapeHtml(actorNpc.name) +
        " 1배치 선불 홀드)</span>";
    }
    msg += "<br>총 실 수령 <strong>" + (income - fee).toLocaleString() + "량</strong>";
  }
  predEl.innerHTML = msg;
  predEl.classList.toggle("warn", !!warn);
  submit.disabled = qty < 1 || !!warn || maxSell < 1;
}

function initPlaza() {
  const plazaSel = document.getElementById("plaza-character");
  if (!plazaSel) return;
  applyStoredActor(plazaSel); // 마지막 선택 actor 복원 → 이후 본문이 그 기준으로 재계산
  const buyChar = document.getElementById("buy-char-id");
  if (buyChar) buyChar.value = plazaCharId();
  renderInventorySlots();
  buyMerchantOptions();
  onBuyMerchantChange();
  rebuildSellItems();
  updateSellPrediction();
}

// ── fragment 자동 탭 + 창고 상태 복원 ──────────────────────
window.addEventListener("DOMContentLoaded", () => {
  parseWarehouseFromHash();
  renderWarehouse();
  initPlaza();
  applyStoredActor(document.getElementById("right-item-move-target")); // 우측패널 이동 대상 복원
  if (!location.hash) return;
  const target = location.hash.substring(1).split("?")[0];
  const btn = document.querySelector(".sidebar-item[onclick*=\"'" + target + "'\"]");
  if (!btn) return;
  // 대상 사이드 아이템이 속한 섹션의 상단 탭 먼저 활성화
  const section = btn.closest(".sidebar-section");
  if (section) {
    const sectionName = section.id.replace("sidebar-", "");
    const topTab = document.querySelector(".top-tab[onclick*=\"'" + sectionName + "'\"]");
    if (topTab && !topTab.classList.contains("active")) topTab.click();
  }
  btn.click();
});

// ── <select> 마우스 휠 스크롤로 옵션 변경 (편의성) ─────────
// 닫힌 select 위에서 휠 회전 → 다음/이전 옵션 (disabled 건너뜀) + change 이벤트 dispatch
document.addEventListener(
  "wheel",
  (e) => {
    const sel = e.target;
    if (!sel || sel.tagName !== "SELECT" || sel.disabled) return;
    const options = sel.options;
    if (!options.length) return;
    e.preventDefault();
    const dir = e.deltaY > 0 ? 1 : -1;
    let idx = sel.selectedIndex;
    for (let i = idx + dir; i >= 0 && i < options.length; i += dir) {
      if (!options[i].disabled) {
        idx = i;
        break;
      }
    }
    if (idx !== sel.selectedIndex) {
      sel.selectedIndex = idx;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  },
  { passive: false }
);
