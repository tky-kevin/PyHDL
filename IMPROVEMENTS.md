# PyHDL 轉譯器改進建議清單

## 📊 總覽

本文件整理 PyHDL 轉譯器可改進的功能與已知限制。

---

## 🔴 高優先級（功能缺失）

### 1. 有號數類型支援
**現狀：** 所有訊號預設為無號數（`logic`）
**問題：** 無法生成 `$signed()` 進行有號數比較/運算
**影響：** SLT（Set Less Than）等運算只能用無號比較

**建議語法：**
```python
# 方案 A：新增 signed_bit 類型
a = In(signed_bit[8])

# 方案 B：裝飾器標記
a = In(bit[8], signed=True)
```

**預期輸出：**
```verilog
input logic signed [7:0] a
// 或
if ($signed(a) < $signed(b)) ...
```

---

### 2. Match-Case 自動 Default 分支
**現狀：** unique case 不含 default，op 超出範圍時模擬會警告
**問題：** 雖然預設值防止 Latch，但 unique case 語意要求完整覆蓋

**建議：**
- 自動在 `unique case` 結尾加入 `default: ;`
- 或提供語法讓使用者指定 default 行為

**預期輸出：**
```verilog
unique case (op)
    0: ...
    1: ...
    default: ; // 自動加入
endcase
```

---

### 3. 參數化切片表達式
**現狀：** `data[width-1:0]` 在模板階段無法解析
**問題：** 切片邊界必須是靜態可計算的值

**建議：** 增強 `_eval_dim_expr` 支援更複雜的表達式

**預期語法：**
```python
class ParamModule(Module):
    sum = full_sum[width-1:0]  # 應在實例化時解析
```

---

## 🟡 中優先級（功能增強）

### 4. 右移類型選擇（邏輯移位 vs 算術移位）
**現狀：** `>>` 只生成邏輯右移
**問題：** 無法區分 `>>>`（算術右移，保留符號位）

**建議語法：**
```python
result = a >> b        # 邏輯右移 (SRL)
result = a.sra(b)      # 算術右移 (SRA)
# 或
result = signed_shr(a, b)
```

---

### 5. 明確位元寬度格式化
**現狀：** 賦值 `0` 轉為 `1'd0`，可能不符預期寬度
**問題：** `mem[i] <= 1'd0` 對 8-bit 記憶體可能需要 `8'd0`

**建議：** 根據左側目標寬度自動調整常數格式

---

### 6. 直接埠連接語法
**現狀：** 子模組輸出必須透過中間訊號
**問題：** 生成較冗長的代碼

**當前生成：**
```verilog
logic [7:0] u_alu_result;
SimpleALU u_alu (..., .result(u_alu_result));
always_comb begin
    sys_result = u_alu_result;
end
```

**建議選項：** 可選擇直接埠映射模式
```verilog
SimpleALU u_alu (..., .result(sys_result));
```

---

### 7. 陣列初始化常數寬度
**現狀：** `mem[i] = 0` 轉為 `mem[i] <= 1'd0`
**問題：** 應該是 `mem[i] <= 8'd0`（根據記憶體寬度）

**建議：** 在 symbol_table 追蹤陣列元素寬度

---

## 🟢 低優先級（錦上添花）

### 8. 支援 SRL/SRA 右移運算符
**建議語法：** `>>>` for arithmetic shift right

---

### 9. 支援 Reduction 運算符
**現狀：** 需手動迴圈展開 XOR 所有位元
**建議語法：**
```python
parity = reduce_xor(data)  # 生成 ^data
any_bit = reduce_or(data)  # 生成 |data
```

---

### 10. 支援 Repeat 重複運算
**建議語法：**
```python
extended = repeat(sign_bit, 8)  # 生成 {8{sign_bit}}
```

---

### 11. 輸出格式美化
**現狀：** `(10 - 1)` 可簡化為 `9`
**建議：** 編譯時期常數折疊 (Constant Folding)

---

### 12. 原始碼位置追蹤
**建議：** 錯誤訊息顯示 .phd 檔案的行號

---

## 🛠️ 已修復的問題（本次會話）

| 問題 | 狀態 |
|------|------|
| 二維陣列越界檢查錯誤 | ✅ 已修復 |
| 常數未替換（如 DEPTH） | ✅ 已修復 |
| 參數化模板立即生成 | ✅ 已修復 |
| 巢狀 for 迴圈變數檢測 | ✅ 已修復 |

---

## 📈 功能完整度評估

| 功能類別 | 完成度 | 備註 |
|---------|--------|------|
| 基本埠宣告 | 95% | 缺 signed 類型 |
| 組合邏輯 | 90% | 缺 reduction ops |
| 時序邏輯 | 95% | 完善 |
| FSM / Enum | 100% | 完善 |
| 迴圈展開 | 100% | 完善 |
| 參數化 | 85% | 缺參數化切片 |
| 子模組實例化 | 90% | 缺直接埠連接 |
| 運算符 | 85% | 缺 signed ops, reduction |

---

## 🎯 建議實作順序

1. **有號數類型** - 影響面最廣
2. **Match-Case Default** - 簡單改動，提升品質
3. **常數寬度推斷** - 改善輸出正確性
4. **參數化切片** - 解除語法限制
5. **Reduction 運算符** - 實用功能
