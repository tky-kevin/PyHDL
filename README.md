# PyHDL：Python 至 SystemVerilog 轉譯器

**PyHDL** 是一個輕量級、現代化的硬體描述語言轉譯器，讓開發者使用優雅的 Python 語法描述數位電路，並編譯為可合成的 **SystemVerilog** 程式碼。

透過 Python 的動態特性（如靜態迴圈展開與參數化生成），PyHDL 大幅加速硬體設計流程，同時保持與業界標準 EDA 工具的完整相容性。

---

## 目錄

- [功能特色](#功能特色)
- [安裝方式](#安裝方式)
- [快速開始](#快速開始)
- [語法參考](#語法參考)
  - [模組定義](#模組定義)
  - [埠宣告](#埠宣告)
  - [時序邏輯與組合邏輯](#時序邏輯與組合邏輯)
  - [運算符](#運算符)
  - [位元切片與串接](#位元切片與串接)
  - [迴圈展開](#迴圈展開)
  - [有限狀態機](#有限狀態機)
  - [參數化模組](#參數化模組)
- [專案結構](#專案結構)
- [範例程式](#範例程式)
- [已知限制](#已知限制)
- [貢獻指南](#貢獻指南)

---

## 功能特色

### 核心能力

| 功能 | 說明 |
|------|------|
| **Pythonic 語法** | 使用 Python `class` 定義硬體模組，使用 `if/else` 和 `match/case` 描述邏輯 |
| **靜態迴圈展開** | `for i in range(N)` 自動展開，生成重複的硬體結構 |
| **參數化設計** | 如同呼叫函數般傳入參數（如 `width=16`），自動生成對應寬度的模組 |
| **自動連線** | 實例化子模組時，自動推斷並宣告中間訊號 |
| **靜態分析** | 內建位元寬度推斷與陣列越界檢查，在轉譯階段發現錯誤 |
| **邏輯優化** | 巢狀 `if-elif-else` 自動扁平化為清晰的 SystemVerilog 結構 |

### 支援的語法結構

- **組合邏輯**：生成 `always_comb` 區塊
- **時序邏輯**：生成具有邊緣敏感的 `always_ff` 區塊
- **非同步重置**：支援高電平有效（`posedge rst`）與低電平有效（`negedge rst_n`）
- **有限狀態機**：`Enum` 類別搭配 `match/case` 生成 `typedef enum` 與 `unique case`
- **記憶體陣列**：二維陣列宣告（`bit[DEPTH][WIDTH]`）
- **模組實例化**：支援階層式設計與自動埠映射

---

## 安裝方式

### 環境需求

- Python 3.8 或更高版本
- `colorama` 套件（用於彩色終端輸出）

### 安裝步驟

```bash
# 複製專案
git clone https://github.com/yourusername/pyhdl.git
cd pyhdl

# 安裝相依套件
pip install colorama
```

---

## 快速開始

### 步驟一：撰寫 PyHDL 模組

建立檔案 `example.phd`：

```python
from core import bit, In, Out, Module

class PriorityEncoder(Module):
    # 參數定義
    WIDTH = 8
    CODE_W = 3
    
    # 埠宣告
    req = In(bit[WIDTH])
    code = Out(bit[CODE_W])
    valid = Out(bit)

    # 預設值（防止產生 Latch）
    code = 0
    valid = 0

    # 使用迴圈展開生成優先權邏輯
    for i in range(WIDTH):
        if req[i]:
            code = i
            valid = 1
```

### 步驟二：執行轉譯器

```bash
python compiler.py example.phd -o output/
```

### 步驟三：查看生成的 SystemVerilog

轉譯器產生 `output/example.sv`：

```systemverilog
module PriorityEncoder (
    input logic [7:0] req,
    output logic [2:0] code,
    output logic valid
);
    always_comb begin
        code = 3'd0;
        valid = 1'd0;
        if (req[0]) begin
            code = 3'd0;
            valid = 1'd1;
        end
        if (req[1]) begin
            code = 3'd1;
            valid = 1'd1;
        end
        // ... 迴圈展開至全部 8 位元
        if (req[7]) begin
            code = 3'd7;
            valid = 1'd1;
        end
    end
endmodule
```

---

## 語法參考

### 模組定義

硬體模組以繼承 `Module` 的 Python 類別定義：

```python
from core import bit, In, Out, Module

class MyModule(Module):
    # 埠宣告
    clk = In(bit)
    data = In(bit[8])
    result = Out(bit[16])
    
    # 邏輯描述
    result = data * data
```

### 埠宣告

| 語法 | 說明 | 生成的 SystemVerilog |
|------|------|---------------------|
| `In(bit)` | 1 位元輸入 | `input logic` |
| `In(bit[8])` | 8 位元輸入 | `input logic [7:0]` |
| `Out(bit[16])` | 16 位元輸出 | `output logic [15:0]` |

### 內部訊號

```python
# 1 位元內部訊號
temp = bit

# 多位元內部訊號
counter = bit[8]

# 二維陣列（記憶體）
mem = bit[16][8]  # 16 個項目，每個 8 位元 → logic [7:0] mem [0:15]
```

### 時序邏輯與組合邏輯

PyHDL 根據語境自動判斷生成 `always_ff` 或 `always_comb`。

#### 時序邏輯（暫存器）

```python
# 同步邏輯（正緣觸發時脈）
if clk.posedge:
    count = count + 1

# 非同步高電平重置
if clk.posedge or rst.posedge:
    if rst:
        count = 0
    else:
        count = count + 1

# 非同步低電平重置（工業標準）
if clk.posedge or rst_n.negedge:
    if not rst_n:
        count = 0
    else:
        count = count + 1
```

**生成的 SystemVerilog：**

```systemverilog
always_ff @(posedge clk or negedge rst_n) begin
    if ((!rst_n)) begin
        count <= 8'd0;
    end else begin
        count <= (count + 1);
    end
end
```

#### 組合邏輯

```python
# 直接賦值（不在時脈邊緣內）
result = a + b

# 條件式組合邏輯
if sel:
    out = in_a
else:
    out = in_b
```

**生成的 SystemVerilog：**

```systemverilog
always_comb begin
    if (sel) begin
        out = in_a;
    end else begin
        out = in_b;
    end
end
```

### 運算符

#### 算術運算符

| PyHDL | SystemVerilog | 說明 |
|-------|---------------|------|
| `a + b` | `(a + b)` | 加法 |
| `a - b` | `(a - b)` | 減法 |
| `a * b` | `(a * b)` | 乘法 |
| `a / b` | `(a / b)` | 除法 |
| `a % b` | `(a % b)` | 取餘數 |

#### 位元運算符

| PyHDL | SystemVerilog | 說明 |
|-------|---------------|------|
| `a & b` | `(a & b)` | 位元 AND |
| `a \| b` | `(a \| b)` | 位元 OR |
| `a ^ b` | `(a ^ b)` | 位元 XOR |
| `~a` | `(~a)` | 位元 NOT |

#### 邏輯運算符

| PyHDL | SystemVerilog | 說明 |
|-------|---------------|------|
| `a and b` | `(a && b)` | 邏輯 AND |
| `a or b` | `(a \|\| b)` | 邏輯 OR |
| `not a` | `(!a)` | 邏輯 NOT |

#### 比較運算符

| PyHDL | SystemVerilog | 說明 |
|-------|---------------|------|
| `a == b` | `(a == b)` | 等於 |
| `a != b` | `(a != b)` | 不等於 |
| `a < b` | `(a < b)` | 小於（無號數） |
| `a <= b` | `(a <= b)` | 小於等於 |
| `a > b` | `(a > b)` | 大於 |
| `a >= b` | `(a >= b)` | 大於等於 |

#### 位移運算符

| PyHDL | SystemVerilog | 說明 |
|-------|---------------|------|
| `a << n` | `(a << n)` | 左移 |
| `a >> n` | `(a >> n)` | 右移（邏輯） |

### 位元切片與串接

#### 位元切片

```python
high_byte = data[15:8]   # → data[15:8]
low_nibble = data[3:0]   # → data[3:0]
msb = data[7]            # → data[7]
```

#### 串接

使用 Python 元組進行訊號串接：

```python
result = (a, b)           # → {a, b}
extended = (sign, data)   # → {sign, data}
with_const = (sel, 0, a)  # → {sel, 1'd0, a}
```

### 迴圈展開

靜態 `for` 迴圈在轉譯時自動展開：

```python
WIDTH = 8

for i in range(WIDTH):
    data_out[i] = data_in[WIDTH - 1 - i]
```

**生成的 SystemVerilog：**

```systemverilog
always_comb begin
    data_out[0] = data_in[7];
    data_out[1] = data_in[6];
    data_out[2] = data_in[5];
    // ... 繼續展開所有索引
    data_out[7] = data_in[0];
end
```

支援的 `range()` 變體：
- `range(N)` — 0 到 N-1
- `range(start, stop)` — start 到 stop-1
- `range(start, stop, step)` — 自訂步進值

### 有限狀態機

使用 `Enum` 定義狀態，使用 `match/case` 描述轉移：

```python
from core import bit, In, Out, Module, Enum

class TrafficLight(Module):
    clk = In(bit)
    rst_n = In(bit)
    
    red = Out(bit)
    yellow = Out(bit)
    green = Out(bit)
    
    class State(Enum):
        RED = 0
        GREEN = 1
        YELLOW = 2
    
    state = State
    
    # 狀態轉移（時序邏輯）
    if clk.posedge or rst_n.negedge:
        if not rst_n:
            state = State.RED
        else:
            match state:
                case State.RED:
                    state = State.GREEN
                case State.GREEN:
                    state = State.YELLOW
                case State.YELLOW:
                    state = State.RED
    
    # 輸出邏輯（組合邏輯）
    red = 0
    yellow = 0
    green = 0
    
    match state:
        case State.RED:
            red = 1
        case State.GREEN:
            green = 1
        case State.YELLOW:
            yellow = 1
```

**生成的 SystemVerilog：**

```systemverilog
typedef enum logic [1:0] {RED=0, GREEN=1, YELLOW=2} State_t;
State_t state;

always_ff @(posedge clk or negedge rst_n) begin
    if ((!rst_n)) begin
        state <= RED;
    end else begin
        unique case (state)
            RED: state <= GREEN;
            GREEN: state <= YELLOW;
            YELLOW: state <= RED;
        endcase
    end
end

always_comb begin
    red = 1'd0;
    yellow = 1'd0;
    green = 1'd0;
    unique case (state)
        RED: red = 1'd1;
        GREEN: green = 1'd1;
        YELLOW: yellow = 1'd1;
    endcase
end
```

### 參數化模組

定義參數化模板並以特定數值實例化：

```python
# 參數化加法器模板
class ParamAdder(Module):
    a = In(bit[width])
    b = In(bit[width])
    sum = Out(bit[width + 1])
    
    sum = a + b

# 頂層模組實例化
class Top(Module):
    in_a = In(bit[8])
    in_b = In(bit[8])
    out_sum = Out(bit[9])
    
    # 實例化 8 位元版本
    u_add = ParamAdder(width=8)
    u_add.a = in_a
    u_add.b = in_b
    out_sum = u_add.sum
```

**生成的 SystemVerilog：**

```systemverilog
module ParamAdder_width8 (
    input logic [7:0] a,
    input logic [7:0] b,
    output logic [8:0] sum
);
    always_comb begin
        sum = (a + b);
    end
endmodule

module Top (...);
    logic [8:0] u_add_sum;
    ParamAdder_width8 u_add (.a(in_a), .b(in_b), .sum(u_add_sum));
    always_comb begin
        out_sum = u_add_sum;
    end
endmodule
```

---

## 專案結構

```
pyhdl/
├── compiler.py        # 命令列介面入口
├── transpiler.py      # 核心轉譯器（AST 訪問器與程式碼生成器）
├── core.py            # PyHDL 基礎類別（Module, In, Out, bit, Enum）
├── test_code/         # 範例 .phd 原始碼
│   ├── demo_alu.phd
│   ├── demo_traffic_light.phd
│   └── ...
├── test_output/       # 生成的 .sv 檔案
├── README.md          # 本文件
└── IMPROVEMENTS.md    # 已知限制與未來改進項目
```

---

## 範例程式

`test_code/` 目錄包含完整的範例：

| 檔案 | 說明 |
|------|------|
| `demo_alu.phd` | 8 位元 ALU，支援 8 種運算（ADD, SUB, AND, OR, XOR, NOR, SLTU, SLL） |
| `demo_traffic_light.phd` | 交通燈 FSM 控制器 |
| `01_basic_ports.phd` | 埠宣告與寬度計算 |
| `02_operators.phd` | 所有支援的運算符 |
| `03_slice_concat.phd` | 位元切片與串接 |
| `04_comb_logic.phd` | 組合邏輯模式 |
| `05_seq_logic.phd` | 各種重置方式的時序邏輯 |
| `06_loop_unroll.phd` | 迴圈展開示範 |
| `07_memory.phd` | RAM 與暫存器檔實作 |
| `08_fsm.phd` | 有限狀態機範例 |
| `09_param_inst.phd` | 參數化模組實例化 |
| `10_fifo.phd` | 完整同步 FIFO 實作 |

---

## 已知限制

詳細清單請參閱 [IMPROVEMENTS.md](IMPROVEMENTS.md)。主要限制包括：

1. **有號數類型**：不支援 `$signed()` 運算，所有比較皆為無號數
2. **參數化切片**：如 `data[width-1:0]` 的表達式需要靜態求值
3. **算術右移**：僅支援邏輯右移（`>>`）
4. **直接埠連接**：子模組輸出需透過中間訊號

---

## 命令列用法

```bash
# 轉譯單一檔案
python compiler.py input.phd -o output_dir/

# 轉譯目錄內所有 .phd 檔案
python compiler.py src/ -o hdl/

# 啟用詳細輸出
python compiler.py src/ -o hdl/ -v
```

---

## 貢獻指南

歡迎貢獻！請參閱 [IMPROVEMENTS.md](IMPROVEMENTS.md) 了解需要協助的項目。

---

## 授權

本專案供教育用途使用。

---

## 致謝

PyHDL 的設計靈感來自 Chisel、SpinalHDL 和 Amaranth 等現代硬體描述框架，將 Python 的表達力帶入硬體設計領域。
