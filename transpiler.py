import ast
import math

class ModuleContext:
    """儲存單個硬體模組 (Module) 的獨立上下文資訊"""
    def __init__(self, name):
        self.name = name
        self.symbol_table = {}      # 變數符號表: {name: {'dims': [depth, width]}}
        self.ports = []             # 模組埠號 (Ports): In/Out
        self.output_decls = []      # 內部信號 (Internal Signals) 宣告
        self.output_assigns = []    # 組合邏輯 (Combinational Logic)
        self.output_seq_blocks = {} # 同步邏輯 (Sequential Logic): {trigger: [statements]}
        self.instances = {}         # 子模組實例化: {inst_name: {'mod': str, 'mapping': dict}}
        self.enums = {}

class PyHDLTranspiler(ast.NodeVisitor):
    def __init__(self):
        self.modules = {}           # 儲存所有模組上下文: {name: ModuleContext}
        self.current_mod = None     # 目前處理中的模組
        self.current_seq_clk = None # 目前處理中的時脈域觸發條件

    def _resolve_dims(self, node):
        """解析 In/Out 或 Enum 類型宣告"""
        # A. 處理 In(bit[8]) 或 Out(...)
        if isinstance(node, ast.Call) and node.func.id in ['In', 'Out']:
            direction = "input" if node.func.id == 'In' else "output"
            dims = self._resolve_dims_raw(node.args[0])
            return dims, direction
        
        # B. 處理 Enum 類型宣告: curr_state = State
        if isinstance(node, ast.Name) and self.current_mod and node.id in self.current_mod.enums:
            # 傳回 Enum 名稱字串，作為特殊的標記
            return [node.id], None
            
        return self._resolve_dims_raw(node), None

    def _resolve_dims_raw(self, node):
        """解析 bit[8][16] 的純維度列表"""
        dims = []
        curr = node
        while isinstance(curr, ast.Subscript):
            if isinstance(curr.slice, ast.Constant):
                dims.append(curr.slice.value)
            curr = curr.value
        if isinstance(curr, ast.Name) and curr.id == 'bit':
            return dims[::-1] # 回傳 [Depth, Width]
        return None

    def _infer_width(self, node):
        """遞迴推斷運算式的位元寬度 (新增 Tuple 支援)"""
        # --- 新增: 處理位元串接 (Tuple) ---
        if isinstance(node, ast.Tuple):
            total_width = 0
            for elt in node.elts:
                total_width += self._infer_width(elt)
            return total_width

        # --- 以下為原本的邏輯 ---
        if isinstance(node, ast.BinOp):
            w_l = self._infer_width(node.left)
            w_r = self._infer_width(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return max(w_l, w_r) + 1
            return max(w_l, w_r)
        
        elif isinstance(node, (ast.Compare, ast.BoolOp)):
            return 1
            
        elif isinstance(node, ast.UnaryOp):
            return self._infer_width(node.operand)
            
        elif isinstance(node, ast.Name):
            if self.current_mod and node.id in self.current_mod.symbol_table:
                dims = self.current_mod.symbol_table[node.id]['dims']
                return dims[-1] if dims else 1
                
        elif isinstance(node, ast.Constant):
            if node.value == 0: return 1
            return math.floor(math.log2(abs(node.value))) + 1
            
        elif isinstance(node, ast.Subscript):
            name = self.visit(node.value)
            if self.current_mod and name in self.current_mod.symbol_table:
                dims = self.current_mod.symbol_table[name]['dims']
                return dims[1] if len(dims) > 1 else 1
        return 1

    def _format_sv_type(self, direction, name, dims):
        """產出 SystemVerilog 的宣告字串 (支援 Enum 類型)"""
        dir_prefix = f"{direction} " if direction else ""
        
        # 檢查 dims[0] 是否為已定義的 Enum 名稱
        if dims and isinstance(dims[0], str) and self.current_mod and dims[0] in self.current_mod.enums:
            # 返回如 "State_t curr_state"
            return f"{dir_prefix}{dims[0]}_t {name}"
            
        # 一般 bit 寬度格式化邏輯
        if not dims:
            return f"{dir_prefix}logic {name}"
        elif len(dims) == 1:
            return f"{dir_prefix}logic [{dims[0]-1}:0] {name}"
        elif len(dims) == 2:
            return f"{dir_prefix}logic [{dims[1]-1}:0] {name} [0:{dims[0]-1}]"
        return f"{dir_prefix}logic {name}"

    def _format_const(self, value, width):
        """將常數格式化為 SV 標準: [width]'d[value]"""
        # 如果寬度資訊大於 0，則加上位元數與十進位標記 'd
        if width > 0:
            return f"{width}'d{value}"
        return str(value)

    def _extract_edges(self, node):
        """從條件式中提取 posedge/negedge 訊號用於敏感列表"""
        edges = []
        if isinstance(node, ast.Attribute) and node.attr in ['posedge', 'negedge']:
            edges.append((self.visit(node.value), node.attr))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for val in node.values:
                edges.extend(self._extract_edges(val))
        return edges

    def visit_ClassDef(self, node):
        """定義模組或狀態機列舉"""
        # 檢查是否為 Enum 定義 (假設使用者繼承了 Enum 或類別名包含 State)
        is_enum = any(isinstance(base, ast.Name) and base.id == 'Enum' for base in node.bases)
        
        if is_enum:
            enum_name = node.name
            states = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                    states[stmt.targets[0].id] = stmt.value.value
            
            # 計算需要的位元寬度
            width = math.ceil(math.log2(len(states))) if len(states) > 1 else 1
            self.current_mod.enums[enum_name] = {'states': states, 'width': width}
            return

        # 原本的 Module 定義邏輯
        mod_name = node.name
        self.current_mod = ModuleContext(mod_name)
        self.modules[mod_name] = self.current_mod
        for stmt in node.body:
            self.visit(stmt)
        self.current_mod = None

    def visit_Match(self, node):
        """處理 FSM 狀態跳轉 (優化縮排版面)"""
        subject = self.visit(node.subject)
        case_lines = [f"unique case ({subject})"]
        
        for case in node.cases:
            pattern = self.visit(case.pattern)
            
            # 暫存當前序列塊，收集該分支下的語句
            saved_clk = self.current_seq_clk
            temp_list = self.current_mod.output_seq_blocks[saved_clk]
            self.current_mod.output_seq_blocks[saved_clk] = []
            
            for stmt in case.body:
                self.visit(stmt)
            
            # 【關鍵修正】將分支內部的每一行往右縮排 8 個空白
            branch_stmts = []
            for s in self.current_mod.output_seq_blocks[saved_clk]:
                for line in s.split('\n'):
                    branch_stmts.append(f"            {line}") # 加強縮排
            
            self.current_mod.output_seq_blocks[saved_clk] = temp_list
            
            # 將 case 標籤也加上 4 個空白的縮排
            case_lines.append(f"    {pattern}: begin")
            case_lines.extend(branch_stmts)
            case_lines.append("    end")
            
        case_lines.append("endcase")
        
        if self.current_seq_clk:
            self.current_mod.output_seq_blocks[self.current_seq_clk].append("\n".join(case_lines))

    def visit_MatchValue(self, node):
        """處理 case 裡面的數值，如 State.IDLE"""
        return self.visit(node.value)

    def visit_If(self, node):
        """處理同步邊緣觸發 (Top-level) 或內部的條件分支 (Internal)"""
        
        # --- 場景 1: 同步塊內部的條件邏輯 (如 if rst: 或 if start:) ---
        if self.current_seq_clk:
            cond = self.visit(node.test)
            saved_clk = self.current_seq_clk
            
            # 1. 捕捉 Body (If 成立的分支)
            temp_list = self.current_mod.output_seq_blocks[saved_clk]
            self.current_mod.output_seq_blocks[saved_clk] = [] # 開啟乾淨的 buffer
            
            for stmt in node.body:
                self.visit(stmt)
            
            # 對 body 內部的每一行進行縮排處理
            body_code = []
            for s in self.current_mod.output_seq_blocks[saved_clk]:
                for line in s.split('\n'):
                    body_code.append(f"    {line}") # 向右推 4格
            
            # 2. 捕捉 Orelse (Else 或 Elif 分支)
            else_code = []
            if node.orelse:
                self.current_mod.output_seq_blocks[saved_clk] = [] # 清空以收集 else 內容
                for stmt in node.orelse:
                    self.visit(stmt)
                
                for s in self.current_mod.output_seq_blocks[saved_clk]:
                    for line in s.split('\n'):
                        else_code.append(f"    {line}") # 向右推 4格
            
            # 3. 恢復原始 Block 並組裝代碼
            self.current_mod.output_seq_blocks[saved_clk] = temp_list
            
            if_str = f"if ({cond}) begin\n" + "\n".join(body_code) + "\nend"
            if else_code:
                if_str += " else begin\n" + "\n".join(else_code) + "\nend"
            
            self.current_mod.output_seq_blocks[saved_clk].append(if_str)
            return

        # --- 場景 2: 頂層 If (偵測時脈或重置邊緣: clk.posedge) ---
        edges = self._extract_edges(node.test)
        if edges:
            # 產生敏感列表 (Sensitivity List): posedge clk or posedge rst
            clk_spec = " or ".join([f"{edge} {name}" for name, edge in edges])
            self.current_seq_clk = clk_spec
            
            if clk_spec not in self.current_mod.output_seq_blocks:
                self.current_mod.output_seq_blocks[clk_spec] = []
            
            # 進入 Body 處理 (此時 current_seq_clk 已設定，內部的 Assign 會變為 <=)
            for stmt in node.body:
                self.visit(stmt)
            
            # 離開同步塊，重置標記
            self.current_seq_clk = None
        else:
            # 場景 3: 頂層組合邏輯 If (可用於轉譯成三元運算子或警告)
            # 在目前的 MVP 架構中，通常建議使用 assign out = cond ? a : b
            print(f"Warning: 偵測到不含邊緣觸發的頂層 If，此功能尚未完整支援組合邏輯轉譯。")

    def visit_Assign(self, node):
        """處理宣告、實例化、埠號連線與邏輯賦值"""
        
        # 1. 處理左側為屬性的情況 (例如子模組埠號連線: u1.a = sw_a)
        if isinstance(node.targets[0], ast.Attribute):
            if not self.current_seq_clk: # 僅在組合邏輯層級處理連線
                inst_name = self.visit(node.targets[0].value)
                port_name = node.targets[0].attr
                
                if inst_name in self.current_mod.instances:
                    mod_type = self.current_mod.instances[inst_name]['mod']
                    sub_mod_context = self.modules[mod_type]
                    
                    # 尋找子模組該埠號的定義寬度
                    port_width = 1
                    for p in sub_mod_context.ports:
                        if p['name'] == port_name:
                            port_width = p['dims'][-1] if p['dims'] else 1
                            break

                    # 如果連線的是常數，格式化為 [width]'d[val]
                    if isinstance(node.value, ast.Constant):
                        rhs_code = self._format_const(node.value.value, port_width)
                    else:
                        rhs_code = self.visit(node.value)
                        
                    self.current_mod.instances[inst_name]['mapping'][port_name] = rhs_code
            return

        # 取得左側目標變數名稱
        target = node.targets[0].id

        # 2. 處理實例化語法: u1 = Adder()
        if isinstance(node.value, ast.Call) and node.value.func.id in self.modules:
            module_type = node.value.func.id
            sub_mod_context = self.modules[module_type]
            self.current_mod.instances[target] = {'mod': module_type, 'mapping': {}}
            for port in sub_mod_context.ports:
                if port['dir'] == 'output':
                    internal_sig = f"{target}_{port['name']}"
                    self.current_mod.instances[target]['mapping'][port['name']] = internal_sig
                    self.current_mod.symbol_table[internal_sig] = {'dims': port['dims']}
                    self.current_mod.output_decls.append(self._format_sv_type("", internal_sig, port['dims']) + ";")
            return

        # 3. 處理變數宣告 (In/Out/bit/Enum)
        dims, direction = self._resolve_dims(node.value)
        if dims is not None:
            self.current_mod.symbol_table[target] = {'dims': dims}
            if direction:
                self.current_mod.ports.append({'name': target, 'dir': direction, 'dims': dims})
            else:
                decl_str = self._format_sv_type("", target, dims) + ";"
                self.current_mod.output_decls.append(decl_str)
            return

        # 4. 處理邏輯賦值 (Combinational 或 Sequential)
        rhs_w = self._infer_width(node.value)
        
        # --- 變數定義區域：確保 lhs_dims 在所有分支都被初始化 ---
        if target in self.current_mod.symbol_table:
            lhs_dims = self.current_mod.symbol_table[target]['dims']
            # 處理 Enum 或一般位元寬度
            if lhs_dims and isinstance(lhs_dims[0], str) and lhs_dims[0] in self.current_mod.enums:
                lhs_width = self.current_mod.enums[lhs_dims[0]]['width']
            else:
                lhs_width = lhs_dims[-1] if lhs_dims else 1
        else:
            # 隱式宣告：變數第一次出現
            lhs_width = rhs_w
            lhs_dims = [rhs_w]
            self.current_mod.symbol_table[target] = {'dims': lhs_dims}
            self.current_mod.output_decls.append(self._format_sv_type("", target, lhs_dims) + ";")

        # 5. 生成賦值內容與寬度檢查
        if isinstance(node.value, ast.Constant):
            rhs_code = self._format_const(node.value.value, lhs_width)
        else:
            rhs_code = self.visit(node.value)
            # 寬度警告檢查 (僅針對非 Enum 型別且非空 dims)
            is_enum_var = lhs_dims and isinstance(lhs_dims[0], str) and lhs_dims[0] in self.current_mod.enums
            if not is_enum_var:
                if lhs_width != rhs_w:
                    print(f"Warning: '{target}' ({lhs_width}-bit) 與運算結果 ({rhs_w}-bit) 寬度不符。")

        # 6. 生成賦值語句
        if self.current_seq_clk:
            self.current_mod.output_seq_blocks[self.current_seq_clk].append(f"{target} <= {rhs_code};")
        else:
            self.current_mod.output_assigns.append(f"assign {target} = {rhs_code};")
            
    # --- 運算子與基本節點 ---
    def visit_BinOp(self, node):
        ops = {ast.Add:'+', ast.Sub:'-', ast.BitAnd:'&', ast.BitOr:'|', ast.BitXor:'^', ast.LShift:'<<', ast.RShift:'>>'}
        return f"({self.visit(node.left)} {ops.get(type(node.op), '+')} {self.visit(node.right)})"

    def visit_Compare(self, node):
        ops = {ast.Eq:'==', ast.NotEq:'!=', ast.Lt:'<', ast.LtE:'<=', ast.Gt:'>', ast.GtE:'>='}
        return f"({self.visit(node.left)} {ops.get(type(node.ops[0]), '==')} {self.visit(node.comparators[0])})"

    def visit_BoolOp(self, node):
        op = "&&" if isinstance(node.op, ast.And) else "||"
        return f"({f' {op} '.join([self.visit(v) for v in node.values])})"

    def visit_UnaryOp(self, node):
        ops = {ast.Not:'!', ast.Invert:'~', ast.USub:'-'}
        return f"{ops.get(type(node.op), '')}{self.visit(node.operand)}"

    def visit_Subscript(self, node):
        name = self.visit(node.value)
        idx = self.visit(node.slice)
        if name in self.current_mod.symbol_table:
            dims = self.current_mod.symbol_table[name]['dims']
            if len(dims) >= 2 and isinstance(node.slice, ast.Constant):
                if node.slice.value >= dims[0]:
                    raise IndexError(f"Error: 陣閱 '{name}' 超界。深度 {dims[0]}, 存取 {node.slice.value}")
        return f"{name}[{idx}]"

    def visit_Name(self, node): return node.id
    def visit_Constant(self, node): return str(node.value)

    def visit_Tuple(self, node):
        """處理位元串接，例如 (a, b) 轉為 {a, b}"""
        # 拜訪元組中的每一個元素並轉換為字串
        elements = [self.visit(elt) for elt in node.elts]
        # 使用花括號組合
        return f"{{{', '.join(elements)}}}"

    def visit_Attribute(self, node):
        """處理屬性存取，修正 Enum 前綴與子模組存取"""
        value = self.visit(node.value) # 取得物件名稱，如 "State"
        attr = node.attr               # 取得屬性名稱，如 "IDLE"
        
        # 1. 檢查是否為 Enum 成員存取 (如 State.IDLE)
        if self.current_mod and value in self.current_mod.enums:
            if attr in self.current_mod.enums[value]['states']:
                return attr # 直接返回 "IDLE"，去除 "State."
        
        # 2. 檢查是否為子模組輸出存取 (如 u1.s)
        internal_sig_name = f"{value}_{attr}"
        if self.current_mod and internal_sig_name in self.current_mod.symbol_table:
            return internal_sig_name
        
        # 3. 預設返回原樣 (例如 clk.posedge)
        return f"{value}.{attr}"

    # --- 程式碼生成 ---
    def get_verilog(self):
        all_sv = []
        for mod in self.modules.values():
            port_s = ",\n".join([f"    {self._format_sv_type(p['dir'], p['name'], p['dims'])}" for p in mod.ports])
            res = [f"module {mod.name} (\n{port_s}\n);"]
            
            if mod.enums:
                res.append("\n    // FSM State Definitions")
                for e_name, info in mod.enums.items():
                    states_str = ", ".join([f"{k}={v}" for k, v in info['states'].items()])
                    res.append(f"    typedef enum logic [{info['width']-1}:0] {{{states_str}}} {e_name}_t;")

            if mod.output_decls:
                res.append("\n    // Internal Signals")
                res.extend([f"    {d}" for d in mod.output_decls])
                
            if mod.instances:
                res.append("\n    // Submodule Instantiations")
                for n, info in mod.instances.items():
                    # 生成如 .a(sw_a), .b(100), .s(u1_s)
                    m_map = ", ".join([f".{p}({s})" for p, s in info['mapping'].items()])
                    res.append(f"    {info['mod']} {n} ({m_map});")
                    
            if mod.output_assigns:
                res.append("\n    // Combinational Logic")
                res.extend([f"    {a}" for a in mod.output_assigns])
                
            for clk, stmts in mod.output_seq_blocks.items():
                res.append(f"\n    always_ff @({clk}) begin")
                for s in stmts:
                    for line in s.split('\n'): 
                        res.append(f"        {line}")
                res.append("    end")
                
            res.append("\nendmodule")
            all_sv.append("\n".join(res))
        return "\n\n".join(all_sv)