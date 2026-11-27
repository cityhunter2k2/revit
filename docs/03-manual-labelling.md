# 手動標註清單（僅在 `sketch_dimensions` 降級時需要）

若建置報告出現 `sketch_dimensions: FALLBACK`，代表該 Revit 版本不允許透過 API 建立草圖尺寸。此時依下表在**族編輯器**中補標：每個實體的草圖 → 註解 → 對齊尺寸，把尺寸的「標籤」設為指定參數即可。表格由程式自動推導，數值為 100×50 的預設尺寸。

## Trunking_90_MitreBend_FrontOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Tray_Base` | 0 | u | `Mitre_Leg` | 75.00 |
| `Tray_Base` | 0 | u | `Width` | 100.00 |
| `Tray_Base` | 0 | u | `Arm_Half` | 50.00 |
| `Tray_Base` | 0 | v | `Width` | 100.00 |
| `Tray_Base` | 0 | v | `Mitre_Leg` | 75.00 |
| `Tray_Base` | 0 | v | `Arm_Half` | 50.00 |
| `Tray_Wall_Outer` | 0 | u | `Span_Outer_Minus_Wall` | 173.80 |
| `Tray_Wall_Outer` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Wall_Outer` | 0 | u | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Outer` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Wall_Outer` | 0 | v | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Outer` | 0 | diag | `WallThickness` | 1.20 |
| `Tray_Wall_Inner` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Wall_Inner` | 0 | u | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Inner` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Wall_Inner` | 0 | v | `Mitre_Leg` | 75.00 |
| `Tray_Wall_Inner` | 0 | v | `Span_Half_Minus_Wall` | 48.80 |
| `Cover` | 0 | u | `Span_Inner_Minus_Overhang` | 72.60 |
| `Cover` | 0 | u | `Span_Full_Plus_Overhang` | 104.80 |
| `Cover` | 0 | u | `Span_Half_Plus_Overhang` | 52.40 |
| `Cover` | 0 | v | `Span_Full_Plus_Overhang` | 104.80 |
| `Cover` | 0 | v | `Span_Inner_Minus_Overhang` | 72.60 |
| `Cover` | 0 | v | `Span_Half_Plus_Overhang` | 52.40 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |

## Trunking_90_MitreBend_InternalOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Wall_Near` | 0 | u | `Mitre_Leg` | 75.00 |
| `Wall_Near` | 0 | u | `Height` | 50.00 |
| `Wall_Near` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Near` | 0 | v | `Height` | 50.00 |
| `Wall_Near` | 0 | v | `Mitre_Leg` | 75.00 |
| `Wall_Near` | 0 | v | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | u | `Mitre_Leg` | 75.00 |
| `Wall_Far` | 0 | u | `Height` | 50.00 |
| `Wall_Far` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | v | `Height` | 50.00 |
| `Wall_Far` | 0 | v | `Mitre_Leg` | 75.00 |
| `Wall_Far` | 0 | v | `Arm_Half` | 25.00 |
| `Tray_Base` | 0 | u | `Span_Outer_Minus_Wall` | 123.80 |
| `Tray_Base` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | u | `Span_Half_Minus_Wall` | 23.80 |
| `Tray_Base` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | v | `Span_Half_Minus_Wall` | 23.80 |
| `Tray_Base` | 0 | diag | `WallThickness` | 1.20 |
| `Cover` | 0 | u | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | u | `Arm_Half` | 25.00 |
| `Cover` | 0 | v | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | v | `Span_Inner_Minus_CoverThk` | 73.80 |
| `Cover` | 0 | v | `Arm_Half` | 25.00 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |

## Trunking_90_MitreBend_ExternalOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Wall_Near` | 0 | u | `Mitre_Leg` | 75.00 |
| `Wall_Near` | 0 | u | `Height` | 50.00 |
| `Wall_Near` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Near` | 0 | v | `Height` | 50.00 |
| `Wall_Near` | 0 | v | `Mitre_Leg` | 75.00 |
| `Wall_Near` | 0 | v | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | u | `Mitre_Leg` | 75.00 |
| `Wall_Far` | 0 | u | `Height` | 50.00 |
| `Wall_Far` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | v | `Height` | 50.00 |
| `Wall_Far` | 0 | v | `Mitre_Leg` | 75.00 |
| `Wall_Far` | 0 | v | `Arm_Half` | 25.00 |
| `Tray_Base` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | u | `Span_Half_Minus_Wall` | 23.80 |
| `Tray_Base` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | v | `Mitre_Leg` | 75.00 |
| `Tray_Base` | 0 | v | `Span_Half_Minus_Wall` | 23.80 |
| `Cover` | 0 | u | `Outer_Edge_DE` | 125.00 |
| `Cover` | 0 | u | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | u | `Arm_Half` | 25.00 |
| `Cover` | 0 | v | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | v | `Arm_Half` | 25.00 |
| `Cover` | 0 | diag | `Cover_Thickness` | 1.20 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |

## Trunking_90_SharpBend_FrontOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Tray_Base` | 0 | u | `Stub` | 75.00 |
| `Tray_Base` | 0 | u | `Width` | 100.00 |
| `Tray_Base` | 0 | u | `Arm_Half` | 50.00 |
| `Tray_Base` | 0 | v | `Width` | 100.00 |
| `Tray_Base` | 0 | v | `Stub` | 75.00 |
| `Tray_Base` | 0 | v | `Arm_Half` | 50.00 |
| `Tray_Wall_Outer` | 0 | u | `Span_Outer_Minus_Wall` | 173.80 |
| `Tray_Wall_Outer` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Wall_Outer` | 0 | u | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Outer` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Wall_Outer` | 0 | v | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Inner` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Wall_Inner` | 0 | u | `Span_Half_Minus_Wall` | 48.80 |
| `Tray_Wall_Inner` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Wall_Inner` | 0 | v | `Stub` | 75.00 |
| `Tray_Wall_Inner` | 0 | v | `Span_Half_Minus_Wall` | 48.80 |
| `Cover` | 0 | u | `Span_Inner_Minus_Overhang` | 72.60 |
| `Cover` | 0 | u | `Span_Full_Plus_Overhang` | 104.80 |
| `Cover` | 0 | u | `Span_Half_Plus_Overhang` | 52.40 |
| `Cover` | 0 | v | `Span_Full_Plus_Overhang` | 104.80 |
| `Cover` | 0 | v | `Span_Inner_Minus_Overhang` | 72.60 |
| `Cover` | 0 | v | `Span_Half_Plus_Overhang` | 52.40 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |

## Trunking_90_SharpBend_InternalOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Wall_Near` | 0 | u | `Stub` | 75.00 |
| `Wall_Near` | 0 | u | `Height` | 50.00 |
| `Wall_Near` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Near` | 0 | v | `Height` | 50.00 |
| `Wall_Near` | 0 | v | `Stub` | 75.00 |
| `Wall_Near` | 0 | v | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | u | `Stub` | 75.00 |
| `Wall_Far` | 0 | u | `Height` | 50.00 |
| `Wall_Far` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | v | `Height` | 50.00 |
| `Wall_Far` | 0 | v | `Stub` | 75.00 |
| `Wall_Far` | 0 | v | `Arm_Half` | 25.00 |
| `Tray_Base` | 0 | u | `Span_Outer_Minus_Wall` | 123.80 |
| `Tray_Base` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | u | `Span_Half_Minus_Wall` | 23.80 |
| `Tray_Base` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | v | `Span_Half_Minus_Wall` | 23.80 |
| `Cover` | 0 | u | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | u | `Arm_Half` | 25.00 |
| `Cover` | 0 | v | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | v | `Span_Inner_Minus_CoverThk` | 73.80 |
| `Cover` | 0 | v | `Arm_Half` | 25.00 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |

## Trunking_90_SharpBend_ExternalOpening.rfa

| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |
|---|---|---|---|---|
| `Wall_Near` | 0 | u | `Stub` | 75.00 |
| `Wall_Near` | 0 | u | `Height` | 50.00 |
| `Wall_Near` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Near` | 0 | v | `Height` | 50.00 |
| `Wall_Near` | 0 | v | `Stub` | 75.00 |
| `Wall_Near` | 0 | v | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | u | `Stub` | 75.00 |
| `Wall_Far` | 0 | u | `Height` | 50.00 |
| `Wall_Far` | 0 | u | `Arm_Half` | 25.00 |
| `Wall_Far` | 0 | v | `Height` | 50.00 |
| `Wall_Far` | 0 | v | `Stub` | 75.00 |
| `Wall_Far` | 0 | v | `Arm_Half` | 25.00 |
| `Tray_Base` | 0 | u | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | u | `Span_Half_Minus_Wall` | 23.80 |
| `Tray_Base` | 0 | v | `WallThickness` | 1.20 |
| `Tray_Base` | 0 | v | `Stub` | 75.00 |
| `Tray_Base` | 0 | v | `Span_Half_Minus_Wall` | 23.80 |
| `Cover` | 0 | u | `Outer_Edge_DE` | 125.00 |
| `Cover` | 0 | u | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | u | `Arm_Half` | 25.00 |
| `Cover` | 0 | v | `Cover_Thickness` | 1.20 |
| `Cover` | 0 | v | `Arm_Half` | 25.00 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_A` | 0 | u | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_A` | 0 | v | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_A` | 1 | u | `Width` | 100.00 |
| `Flange_Port_A` | 1 | u | `Half_Width` | 50.00 |
| `Flange_Port_A` | 1 | v | `Height` | 50.00 |
| `Flange_Port_A` | 1 | v | `Half_Height` | 25.00 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Height_Z` | 53.60 |
| `Flange_Port_B` | 0 | u | `Flange_Outer_Half_Height_Z` | 26.80 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Width_Y` | 103.60 |
| `Flange_Port_B` | 0 | v | `Flange_Outer_Half_Width_Y` | 51.80 |
| `Flange_Port_B` | 1 | u | `Height` | 50.00 |
| `Flange_Port_B` | 1 | u | `Half_Height` | 25.00 |
| `Flange_Port_B` | 1 | v | `Width` | 100.00 |
| `Flange_Port_B` | 1 | v | `Half_Width` | 50.00 |
