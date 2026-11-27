# 板厚 `WallThickness`：規格公式 vs 圖紙型號

板厚必須是**實例參數 + 公式**（型別參數的公式不能引用實例參數），所以整份交付只有一條
`WallThickness` 公式，沒有型別目錄、沒有尺寸查表。程式提供兩個變體，預設採用委託訊息中的公式。

## 1. 預設（`spec`，委託指定的公式）

```
WallThickness =
if(and(Width <= 50 mm, Height <= 50 mm), 1 mm,
if(and(Width <= 100 mm, Height <= 75 mm), 1.2 mm,
if(and(Width <= 150 mm, Height <= 100 mm), 1.4 mm, 1.6 mm)))
```

| W×H | 公式 | 圖紙型號 | 相符 |
|---|---|---|---|
| 50×50 | T10 | T10 | ✅ |
| 75×50 | T12 | T12 | ✅ |
| 75×75 | T12 | T12 | ✅ |
| 100×75 | T12 | T12 | ✅ |
| 100×100 | **T14** | **T12** | ⚠️ |
| 150×100 | T14 | T14 | ✅ |
| 150×150 | **T16** | **T14** | ⚠️ |
| 200×150 | T16 | T16 | ✅ |
| 200×200 | T16 | T16 | ✅ |
| 300×100 | T16 | （非標準）| — |
| 50×100 | T14 | （非標準）| — |

兩個分歧點：`and(W<=100, H<=75)` 讓 100×100 落到 1.4（圖紙 T12）；`and(W<=150, H<=100)` 讓
150×150 落到 1.6（圖紙 T14）。其餘 7 個目錄尺寸完全相符。

## 2. 替代（`catalogue`，完全等於圖紙型號）

```
WallThickness =
if(and(Width <= 50 mm, Height <= 50 mm), 1 mm,
if(and(Width <= 100 mm, Height <= 100 mm), 1.2 mm,
if(and(Width <= 150 mm, Height <= 150 mm), 1.4 mm, 1.6 mm)))
```

差別只有兩處界線：`H <= 75` → `H <= 100`（讓 100×100 取 T12）與 `H <= 100` → `H <= 150`（讓 150×150 取 T14）。
`python/trunking/model.py::WALL_THICKNESS_CATALOGUE` 就是這條式子，`tests/test_expr.py`
會驗證它在**全部 9 個目錄尺寸**上都等於圖紙的 T 值。

## 3. 如何切換

```bash
# 預設：委託公式
python3 build_families.py --template ".../Metric Cable Tray Fitting.rft" --out out/families

# 完全符合圖紙型號
python3 build_families.py --wall-variant catalogue --out out/families
```

驗證報告也會註明使用的變體；`docs/04-verification-report.md` 的「板厚公式 vs 圖紙型號」表會列出每一個尺寸。

## 4. 建議

* 若監理/業主要求「型號與報價單一致」，用 `catalogue`；若要求「依委託公式」，用 `spec`（預設）。
* 由於 `WallThickness` 是實例參數，**同一個類型**在同一個專案裡可以同時出現 T12 與 T14 的實例；不需要為板厚另開族類型。
* 彎頭的板厚只影響槽底母體與蓋板厚度（`Cover_Thickness = WallThickness`），不影響接頭尺寸與 `CenterToEnd`，所以切換板厚不會破壞已配對的管網。
