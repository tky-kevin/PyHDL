# PyHDL 轉譯器改進建議清單

## 總覽

本文件整理 PyHDL 轉譯器的已知限制、待改進功能與開發路線圖。

---

## 已完成功能

### 核心功能

| 功能 | 說明 |
|------|------|
| 模組定義 | Python class 繼承 `Module` 生成 SystemVerilog module |
| 埠宣告 | `In(bit[N])`, `Out(bit[N])` 生成 input/output logic |
| 組合邏輯 | 自動生成 `always_comb` 區塊 |
| 時序邏輯 | `clk.posedge`, `rst.negedge` 生成 `always_ff` |
| 非同步重置 | 支援高電平 (`posedge rst`) 與低電平 (`negedge rst_n`) |
| 有限狀態機 | `Enum` + `match/case` 生成 `typedef enum` + `unique case` |
| 迴圈展開 | `for i in range(N)` 自動展開為個別語句 |
| 參數化模組 | `MyModule(width=8)` 自動生成對應寬度的模組 |
| 子模組實例化 | 自動建立中間訊號並生成埠映射 |
| 記憶體陣列 | `bit[DEPTH][WIDTH]` 生成二維陣列 |
| 位元切片 | `data[15:8]`, `data[0]` 正確轉譯 |
| 串接運算 | `(a, b, c)` 轉為 `{a, b, c}` |

### 本次開發完成項目

| 項目 | 狀態 |
|------|------|
| Enum 值位寬格式化（Quartus 相容） | 已完成 |
| match/case 自動加入 default 分支 | 已完成 |
| 重命名 core.py 為 pyhdl.py | 已完成 |
| 統一 import 語法為 `from pyhdl import *` | 已完成 |
| 新增 `python pyhdl.py` CLI 入口 | 已完成 |
| 預設路徑調整為 `../src` 與 `../hdl` | 已完成 |
| VS Code 設定支援 .phd 檔案 | 已完成 |
| README 更新（Quartus 整合、Git Submodule） | 已完成 |

---

## 高優先級（功能缺失）

### 1. 有號數類型支援

**現狀：** 所有訊號預設為無號數（`logic`）

**問題：** 無法生成 `$signed()` 進行有號數比較/運算，SLT 等運算只能用無號比較

**建議語法：**
```python
# 方案 A：新增 signed_bit 類型
a = In(signed_bit[8])

# 方案 B：裝飾器標記
a = In(bit[8], signed=True)
```

**預期輸出：**
```systemverilog
input logic signed [7:0] a
// 或
if ($signed(a) < $signed(b)) ...
```

---

### 2. 參數化切片表達式

**現狀：** `data[width-1:0]` 在模板階段無法解析

**問題：** 切片邊界必須是靜態可計算的常數值

**建議：** 增強 `_eval_dim_expr` 支援更複雜的參數運算

**預期語法：**
```python
class ParamModule(Module):
    sum = full_sum[width-1:0]  # 應在實例化時正確解析
```

---

## 中優先級（功能增強）

### 3. 右移類型選擇

**現狀：** `>>` 只生成邏輯右移

**問題：** 無法區分算術右移（保留符號位）

**建議語法：**
```python
result = a >> b        # 邏輯右移 (SRL)
result = a.sra(b)      # 算術右移 (SRA)
```

---

### 4. 常數位寬自動推斷

**現狀：** 賦值 `0` 轉為 `1'd0`，可能不符預期寬度

**問題：** `mem[i] = 0` 對 8-bit 記憶體應生成 `8'd0` 而非 `1'd0`

**建議：** 根據左側目標寬度自動調整常數格式

---

### 5. 直接埠連接語法

**現狀：** 子模組輸出必須透過中間訊號

**當前生成：**
```systemverilog
logic [7:0] u_alu_result;
SimpleALU u_alu (..., .result(u_alu_result));
always_comb begin
    sys_result = u_alu_result;
end
```

**建議選項：** 可選擇直接埠映射模式
```systemverilog
SimpleALU u_alu (..., .result(sys_result));
```

---

## 低優先級（未來功能）

### 6. Reduction 運算符

**現狀：** 需手動迴圈展開 XOR 所有位元

**建議語法：**
```python
parity = reduce_xor(data)  # 生成 ^data
any_bit = reduce_or(data)  # 生成 |data
```

---

### 7. Repeat 重複運算

**建議語法：**
```python
extended = repeat(sign_bit, 8)  # 生成 {8{sign_bit}}
```

---

### 8. 輸出格式美化

**現狀：** `(10 - 1)` 可簡化為 `9`

**建議：** 編譯時期常數折疊 (Constant Folding)

---

### 9. 原始碼位置追蹤

**建議：** 錯誤訊息顯示 .phd 檔案的行號

---

## 功能完整度評估

| 功能類別 | 完成度 | 備註 |
|---------|--------|------|
| 基本埠宣告 | 95% | 缺 signed 類型 |
| 組合邏輯 | 95% | 缺 reduction ops |
| 時序邏輯 | 100% | 完善 |
| FSM / Enum | 100% | 含 default 分支 |
| 迴圈展開 | 100% | 完善 |
| 參數化 | 85% | 缺參數化切片 |
| 子模組實例化 | 90% | 缺直接埠連接 |
| 運算符 | 85% | 缺 signed ops, reduction |
| Quartus 相容性 | 100% | enum 位寬、default 已修復 |
| 開發者體驗 | 90% | VS Code 設定已加入 |

---

## 建議實作順序

1. **有號數類型** - 影響面最廣
2. **常數寬度推斷** - 改善輸出正確性
3. **參數化切片** - 解除語法限制
4. **Reduction 運算符** - 實用功能
5. **直接埠連接** - 優化輸出程式碼

---

## 版本歷史

| 版本 | 日期 | 主要變更 |
|------|------|----------|
| v0.2 | 2025-12-30 | Quartus 相容性修復、CLI 改進、VS Code 支援 |
| v0.1 | 2025-12-28 | 初始版本，基本轉譯功能 |
