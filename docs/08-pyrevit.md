# 在 pyRevit 裡使用

本 repo 附帶一個 pyRevit 擴充套件 `Trunking.extension`，在 Revit 功能區加一個 **Trunking** 頁籤、
兩個按鈕：**Build Families**（產生六個 `.rfa`）與 **Verify Families**（在 Revit 內逐一伸縮量測）。

## 0. 先確認引擎（最重要）

| pyRevit 引擎 | 能不能跑 | 說明 |
|---|---|---|
| **CPython 3.6+** | ✅ 可以 | 本工具需要的引擎。按鈕檔頭已寫 `#! python3` |
| IronPython 2.7（pyRevit 預設） | ❌ 不行 | `trunking` 套件用到 dataclasses / 型別註解 / f-string，IronPython 2.7 無法解析 |

按鈕在 IronPython 下**不會噴 SyntaxError**，而是跳出說明視窗告訴你要切換引擎——這是刻意設計的
（按鈕本身用 Python 2/3 共同語法寫）。

取得 CPython 引擎的辦法：

1. **pyRevit 5.x**（2023 之後）：已內建 CPython，直接可用，建議升級。
2. **pyRevit 4.8.14+**：`pyRevit ▸ Settings ▸ Engines`，指定 CPython 3 執行檔（或讓它自動偵測），
   並保持按鈕的 `#! python3` 檔頭。
3. 如果只能用 IronPython：改在 Revit 外用 CPython 執行 `python/build_families.py`（同一個流程、
   同樣的產出），或改用 C# Add-in（見第 6 節）。

在 Revit 的 **pyRevit ▸ Settings ▸ About** 可看到版本；`pyRevit ▸ Settings ▸ Engines` 可看到目前引擎。

## 1. 安裝擴充套件

1. `pyRevit ▸ Settings ▸ Custom Extension Directories` → **Add Folder** → 選這個 repo 的根目錄
   （也就是**包含** `Trunking.extension` 的那一層，例如 `C:\GIT\revit`）。
2. `pyRevit ▸ Reload`。
3. 功能區出現 **Trunking** 頁籤 → **Trunking** 面板 → `Build Families` / `Verify Families`。

> 也可以把 `Trunking.extension` 複製到 `%APPDATA%\pyRevit\Extensions\`。此時按鈕找不到 `python/trunking`，
> 第一次執行會請你選資料夾；或建立一個 `trunking_home.txt`（放在按鈕的 `script.py` 旁邊），
> 內容一行：`C:\GIT\revit`。

## 2. 環境變數（可選）

| 變數 | 用途 | 預設 |
|---|---|---|
| `TRUNKING_HOME` | 含 `python/trunking` 的資料夾 | 自動往上找、再問你 |
| `TRUNKING_OUT` | `.rfa` 輸出資料夾 | `%USERPROFILE%\Documents\Trunking\families` |
| `TRUNKING_TEMPLATE` | `Metric Cable Tray Fitting.rft` 完整路徑 | 自動搜尋 `RVT 2026…2020` |

## 3. Build Families

按下去之後會：

1. 找樣板（`TRUNKING_TEMPLATE` → 自動搜尋 → 跳出檔案選擇）。
2. 逐一開啟樣板、建立參數／實體／草圖尺寸／兩個接頭、設 `PartType.Elbow`、存檔，**存完就關閉文件**
   （不想關可用 CLI 的 `--keep-open`）。
3. 印出每一步，並在結束時跳出摘要（每族的類型數、參數數、降級數）。

產出：

```
Documents\Trunking\families\
├── Trunking_90_MitreBend_FrontOpening.rfa
├── Trunking_90_MitreBend_InternalOpening.rfa
├── Trunking_90_MitreBend_ExternalOpening.rfa
├── Trunking_90_SharpBend_FrontOpening.rfa
├── Trunking_90_SharpBend_InternalOpening.rfa
├── Trunking_90_SharpBend_ExternalOpening.rfa
├── build-summary.json
└── docs\05-build-report.md
```

建置報告會列出每一步的 `OK / FALLBACK / SKIPPED / FAILED`；只要出現 `FALLBACK`，就照
`docs/03-manual-labelling.md` 在族編輯器補做（通常是草圖尺寸的標籤）。

## 4. Verify Families

選 `.rfa` 資料夾 → 腳本會**不新增任何類型**，只以 `FamilyManager.Set` 改 `Width` / `Height`，
跑完 9 個目錄尺寸 + `300×100` + `50×100`，把每個實體的邊界框與體積和模型預測比對，
輸出 `docs\06-revit-verification.md`。全部通過時跳出「All families flex correctly」。

若某族在某尺寸失敗，報告會指出是「哪個實體、哪個軸、實測 vs 預測」的差異，例如：

```
Tray_Base.x [0.0,275.0] != [0.0,225.0]
```

常見原因與對策：

| 症狀 | 原因 | 對策 |
|---|---|---|
| 某實體整個缺失 | 拉伸沒建立成功（看建置報告）| 重跑 Build，或貼上建置報告的錯誤 |
| 尺寸沒跟著參數變 | 草圖尺寸沒有標籤到參數（`FALLBACK`）| 照 `03-manual-labelling.md` 補標 |
| 邊界框差一個固定值 | 拉伸偏移沒關聯到 `EXTRUSION_*` 參數 | 檢查建置報告 `extrusion_offsets:*` |

## 5. 直接從 pyRevit 的輸出視窗跑 CLI

想加參數（例如 `--wall-variant catalogue`）時，用 pyRevit 的 **Settings ▸ …** 或直接在
RevitPythonShell／CPython 環境執行：

```python
import sys
sys.path.insert(0, r"C:\GIT\revit\python")
import build_families
build_families.main(["--out", r"D:\BIM\Trunking", "--wall-variant", "catalogue"])
```

## 6. 如果專案規定只能用 IronPython

那就走 C# Add-in 路線（本 repo 的 API 層 `python/trunking/revit_api.py` 有意寫成「每個方法對應一個
Revit 呼叫」，可以直接照抄成 C#；幾何與尺寸計畫則由 `python/` 產出的 JSON／Markdown 規格書當依據）。
告訴我一聲，我可以把 `adapter.py` 的介面逐一翻成 C# 專案（`IExternalCommand` + `.addin` manifest）。

## 7. 疑難排解

| 症狀 | 對策 |
|---|---|
| 按鈕灰色／不存在 | `pyRevit ▸ Reload`；確認「Custom Extension Directories」指向 repo 根目錄 |
| 跳出「needs CPython engine」 | 見第 0 節，切換引擎或升級 pyRevit |
| 跳出「Could not find the 'trunking' python package」 | 設 `TRUNKING_HOME`，或建立 `trunking_home.txt` |
| 跳出「Metric Cable Tray Fitting.rft was not found」 | 設 `TRUNKING_TEMPLATE`；樣板在 `C:\ProgramData\Autodesk\RVT 20xx\Family Templates\<語言>\` |
| 執行到一半 Revit 卡住 | 族檔較大時逐族建置較穩；先只建一個（CLI `--only mitre_front`）確認流程 |
| 中文路徑出錯 | pyRevit CPython 對非 ASCII 路徑一般沒問題，但輸出資料夾建議用純英文路徑 |
