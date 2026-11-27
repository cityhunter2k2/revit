# 電纜線槽 90° 彎頭族 — 規格、公式與尺寸計畫

本文件記錄六個族的**規格來源**與**參數化推導**，是所有程式碼的唯一尺寸依據。

資料來源：廠商規格表 `Trunking21 - 25v2_09.jpg`（第 8 頁 "Cable trunking - Fittings and accessories 電線槽曲及配件"）。

## 1. 規格表（逐字抄錄）

| W×H | 型號 | A | B | C 斜角 (mitre) | C 直段 (sharp) | D | E | 板厚 |
|---|---|---|---|---|---|---|---|---|
| 50×50 | 2X2 | 125 | 125 | 106 | 75 | 125 | 125 | T10 |
| 75×50 | 3X2 | 150 | 150 | 106 | 75 | 125 | 125 | T12 |
| 75×75 | 3X3 | 150 | 150 | 106 | 75 | 150 | 150 | T12 |
| 100×75 | 4X3 | 175 | 175 | 106 | 75 | 150 | 150 | T12 |
| 100×100 | 4X4 | 175 | 175 | 106 | 75 | 175 | 175 | T12 |
| 150×100 | 6X4 | 225 | 225 | 106 | 75 | 175 | 175 | T14 |
| 150×150 | 6X6 | 225 | 225 | 106 | 75 | 225 | 225 | T14 |
| 200×150 | 8X6 | 275 | 275 | 106 | 75 | 225 | 225 | T16 |
| 200×200 | 8X8 | 275 | 275 | 106 | 75 | 275 | 275 | T16 |

推導出的閉合公式（與上表 9 列完全吻合）：

```
A = B = W + 75            →  CenterToEnd = W/2 + 75   （正面 / 水平彎）
D = E = H + 75            →  CenterToEnd = H/2 + 75   （內開 / 外開，垂直彎）
C_mitre = 75 · √2 = 106.07（圖紙四捨五入為 106）
C_sharp = 75
```

`python/trunking/spec.py::DRAWING_TABLE` 是這張表的程式版本，`tests/test_model.py` 會驗證每一列都符合上述公式——若日後拿到完整規格表（原始訊息在第五節被截斷），只要改動這一個 tuple 即可。

## 2. 為什麼 A/B 對「垂直彎」要換軸

Revit 的電纜線槽彎頭由兩個矩形接頭定義，接頭的法線必須與線槽走向一致：

| 族 | 2D 平面 | 平面內的「寬」| 平面內的「高」| 蓋板位置 |
|---|---|---|---|---|
| 正面 / 水平彎 `Front` | XY | `Width` (W) | `Height` (H) | +Z（頂面）|
| 內開 / 垂直內彎 `Internal` | XZ | `Height` (H) | `Width` (W) | 凹側（concave）|
| 外開 / 垂直外彎 `External` | YZ / XZ 組合 | `Height` (H) | `Width` (W) | 凸側（convex）|

所以垂直彎的 `CenterToEnd = H/2 + 75`，而 `Width` 變成**管身深度**（不參與 2D 外形）。
**沒有任何 W/H 交換**：`Width` 永遠是「線槽標稱寬度」，接頭寬度永遠綁 `Width`、高度綁 `Height`。
這正是 Routing Preferences 所需要的行為——線槽尺寸變更時，彎頭必須跟著 W/H 走，而不是自行改軸。

## 3. 外形建構（2D）

以「中心線 → 兩條平行鏈」的方式建構，而不是硬畫頂點，這樣才能保證 `A`、`B`、`C` 三者同時正確：

```
        凸側鏈（convex）── 外邊 A
        ┌──────────────┐
        │              │  ← arm B
   ─────┘  凹側鏈（concave）── 內邊
```

* 中心線交點 = 原點 `(0,0,0)`；`Port_A` 在 `(-CenterToEnd, 0)`（法線 −X），`Port_B` 在 `(0, CenterToEnd)`（法線 +Y 或 +Z）。
* **Sharp**：凸側鏈 = 兩條全長外邊（A、B）在角點相接 → 外角 90°；凹側鏈在中段留一個 75 的直段（C）。
* **Mitre**：凸側鏈在外角切掉 45° 斜角，兩邊各退 75（`Mitre_Leg = 75`），斜邊長 `C = 75√2`。
* 兩條鏈都會在**端口處被裁掉**（`split_chains`），因此槽體不會突出接頭面；接頭面永遠是乾淨的矩形。
* 斜角可行性由 `geometry.elbow_outline` 檢查：`Mitre_Leg < Arm_Half + CenterToEnd` 且 `Mitre_Leg < 4·Arm_Half`，否則直接 `ValueError`（例：50 寬配 200 斜角會切掉端口）。

## 4. 3D 實體

| 實體 | 平面 | 拉伸方向 | 說明 |
|---|---|---|---|
| `Tray_Base` | 外形輪廓 | 板厚 `WallThickness` | U 形槽底／槽壁的母體 |
| `Tray_Wall_Outer` / `Tray_Wall_Inner`（正面） | 外邊／內邊鏈的條帶 | 高 `Height` | 兩側槽壁 |
| `Wall_Near` / `Wall_Far`（垂直彎） | 同上 | 寬 `Width` | 兩側槽壁 |
| `Cover` | 蓋板鏈的條帶 | `Cover_Thickness` | 蓋板，`Show_Cover` 控制顯示 |
| `Flange_Port_A` / `Flange_Port_B` | 端口矩形 | `Flange_Length` | 連接耳／接頭套，**Fine 才顯示**，`Show_Flanges` 控制 |

延伸量（`Tray_Base`、`Cover` 等）一律以 `Solid.start` / `Solid.end` 表示，兩者都是**實例參數**，
建置時以 `AssociateElementParameterToFamilyParameter` 綁定到 Family 參數的 `EXTRUSION_START_PARAM` /
`EXTRUSION_END_PARAM`，所以拉伸厚度也隨尺寸自動變化。

蓋板與端耳的實體都**不落在接頭面上**（端耳厚度方向貼齊端口面），因此不會干擾接頭配對與 Routing Preferences 的連接。

## 5. 尺寸計畫（為什麼一個類型就能涵蓋所有尺寸）

Revit 的尺寸標註可以「標籤」(FamilyLabel) 到實例參數，被標註的草圖線因此由參數驅動。
`trunking/dimplan.py` 會**自動推導**每個實體、每一條迴圈、每一個方向要標哪一個參數：

* 每條直線與參考平面的距離以精確仿射式（`Lin`）表示，因此 41 條尺寸在 11 種尺寸下**完全精確**（誤差 1e-6 mm，測試 `test_plan_is_exact_for_every_size`）。
* 每個方向都必須有一個「原點參考平面」錨點（`RP_X0` / `RP_Y0` / `RP_Z0`），否則該方向會浮動 → `test_every_axis_is_anchored_to_an_origin_plane`。
* 推導出的新參數（例如 `Mitre_Face_C`、`Mitre_Leg`、`Half_Width`）全部以公式定義、**全部是實例參數**。
* 沒有任何 `if(Width = 100 mm, …)` 形式的尺寸查表；唯一的 `if()` 是規格要求的板厚公式（見 `02-walls.md`）。

完整清單（每個族約 37–43 條）由 `python/verify_families.py --model-only` 產生到
`docs/03-manual-labelling.md`，也就是「若某版 Revit 不允許 API 標註草圖尺寸」時要人工補標的表。

## 6. 蓋板方位規則（垂直彎）

* **內開 (Internal)**：線槽開口面向凹側 → 蓋板在**凹側**，槽底在凸側。
* **外開 (External)**：開口面向凸側 → 蓋板在**凸側**，槽底在凹側。
* 這兩條規則由 `trunking/verify.py::check_cover_side` 以「投影到 band 座標後與凸/凹鏈的平均最短距離」判定（不是用質心左右，因為質心在斜角族會誤判）。
