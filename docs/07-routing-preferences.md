# 部署與 Routing Preferences 設定

## 1. 檔案

| 族檔 | Routing Preferences 槽位 | 說明 |
|---|---|---|
| `Trunking_90_MitreBend_FrontOpening.rfa` | **Horizontal Bend** | 水平轉彎，蓋板朝上（+Z）|
| `Trunking_90_MitreBend_InternalOpening.rfa` | **Vertical Inside Bend** | 垂直內彎，蓋板在凹側 |
| `Trunking_90_MitreBend_ExternalOpening.rfa` | **Vertical Outside Bend** | 垂直外彎，蓋板在凸側 |
| `Trunking_90_SharpBend_FrontOpening.rfa` | Horizontal Bend | 同上，外角 90°、內側 75 直段 |
| `Trunking_90_SharpBend_InternalOpening.rfa` | Vertical Inside Bend | |
| `Trunking_90_SharpBend_ExternalOpening.rfa` | Vertical Outside Bend | |

每個 `.rfa` 只有一個類型 `Standard`；不需要（也不應該）為每個尺寸建類型。

## 2. 建置

**A. 在 Revit 內建置（正式）**

1. 確認 `Metric Cable Tray Fitting.rft` 存在（預設會搜尋
   `C:\ProgramData\Autodesk\RVT 2024\Family Templates\...`，可用 `--template` 或環境變數 `TRUNKING_TEMPLATE` 指定）。
2. 以 pyRevit / RevitPythonShell 執行：

   ```
   python\build_families.py --out C:\BIM\Trunking --template "<path>\Metric Cable Tray Fitting.rft"
   ```

3. 終端機會列出每一步；任何 `FALLBACK` 都會指出要人工補做什麼（見第 5 節）。
   建置完成會寫出 `docs/05-build-report.md`（每族的能力矩陣）與 `docs/03-manual-labelling.md`。
4. 在 Revit 內驗證：

   ```
   python\verify_families.py --families C:\BIM\Trunking
   ```

   這支腳本**不新增任何類型**，只用 `FamilyManager.Set` 改 `Width` / `Height`，量測實體邊界框與體積，
   和程式模型比對（容差 0.5 mm / 2%），並輸出 `docs/06-revit-verification.md`。

**B. 無 Revit 的預演（CI / 沙盒）**

```
python3 python/build_families.py --dry-run --out build/dryrun
python3 python/verify_families.py --model-only
```

`--dry-run` 用的是記憶體中的假 Revit 文件（`trunking/fake_revit.py`），
走完與正式建置完全相同的 8 個步驟，並把「虛擬族檔」寫成 JSON 以便比對契約。

## 3. 載入與設定 Routing Preferences

1. 開啟專案 → `Manage ▸ MEP Settings ▸ Cable Tray Settings`（或編輯 Cable Tray 的 **Routing Preferences**）。
2. 在 **Bend** 列（Horizontal / Vertical Inside / Vertical Outside）依序 `Load Family…` 選入上表對應的 `.rfa`。
3. 選取載入的族後按 **Preferences**，把 `Width` / `Height` / `Angle` 對應到線槽參數
   （族內這三個參數已建立為實例參數並綁定接頭尺寸，通常無需再改）。
4. 完成後以「線槽」工具繪製，切換尺寸（例如 100×100 → 300×100）時彎頭會自動伸縮，**不會**要求另選型。

## 4. 族參數使用

| 參數 | 類型 | 作用 |
|---|---|---|
| `Width` / `Height` / `Angle` | 長度 / 角度（實例）| 由 Routing Preferences 驅動，接頭尺寸綁定於此 |
| `Stub` | 長度（實例）| 直段 75 mm（圖紙 C/sharp 基準），可微調 |
| `WallThickness` | 長度（實例，公式）| 板厚，見 `02-walls.md` |
| `Cover_Type` | 文字（實例）| `QT` 中心肚臍 / `ST` 螺絲 / `CT` 夾片，用於明細表與標籤，不新增類型 |
| `Show_Cover` | 是/否（實例）| 隱藏蓋板（例如繪製內部電纜時）|
| `Show_Flanges` | 是/否（實例）| 連接耳，僅 **Fine** 顯示 |
| `Tray_Material` / `Cover_Material` | 材質（實例）| 預設 `Galvanised Steel`，可切換 |

**LOD 行為**

* **Coarse**：只有一條符號線（中心線），供平面/系統圖使用，檔案輕量。
* **Medium**：槽體實體（不含連接耳）。
* **Fine**：槽體 + 連接耳（`Flange_Port_A/B`）。

連接耳與蓋板都不會突出接頭面，所以任何 LOD 下接頭都能正常配對與連接。

## 5. `FALLBACK` 與人工補做

Revit API 對「在草圖中建立並標註尺寸」的支援依版本而異（`SketchEditScope` + `Dimension.FamilyLabel`）。
程式對每一步都以 `_probe` 嘗試多種 API 形狀，失敗時**不會**硬失敗，而是標記 `FALLBACK` 並印出
「哪個實體、哪一條迴圈、哪個方向、要標哪個參數」。此時：

1. 打開該族 → 編輯對應實體的拉伸草圖。
2. 依 `docs/03-manual-labelling.md` 標上對齊尺寸。
3. 選取尺寸 → 選項列/性質面板把「標籤」設為表上指定的參數。
4. 存檔後重跑 `verify_families.py --families …` 確認。

其他步驟的降級（`part_type`、可見性綁定、`Show_Cover` 綁定）同樣會出現在建置報告裡，處理方式在報告的「降級提示」段落。

## 6. 發佈前檢查清單

- [ ] `FamilyManager.Types.Size == 1`（類型名稱 `Standard`）
- [ ] 品類為 **Cable Tray Fitting**、零件類型為 **Elbow**
- [ ] 兩個矩形接頭已互相連結（`SetLinkedConnectorElement`），尺寸綁 `Width`/`Height`/`Angle`
- [ ] 原點在中心線交點，接頭法線朝外
- [ ] 9 個目錄尺寸 + `300×100` + `50×100` 皆可正常伸縮（`verify_families.py` 全綠）
- [ ] Coarse/Medium/Fine 顯示正確
- [ ] `Show_Cover` / `Show_Flanges` / `Cover_Type` 可用
