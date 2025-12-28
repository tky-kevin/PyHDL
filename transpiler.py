import ast
import math

class MiniHDLTranspiler(ast.NodeVisitor):
    def __init__(self):
        self.symbol_table = {}  # 儲存變數資訊: {name: {'dims': [8, 16], 'is_mem': True}}
        self.ports = []        # 儲存 In/Out 埠號
        self.output_decls = []  # 儲存內部 logic 宣告
        self.output_assigns = [] # 儲存 assign 語句
        self.declared_vars = set()

    def _resolve_dims(self, node):
        """遞迴解析 bit[8][16] 或 In(bit[8])"""
        # 處理 In(...) 或 Out(...) 呼叫
        if isinstance(node, ast.Call) and node.func.id in ['In', 'Out']:
            direction = "input" if node.func.id == 'In' else "output"
            inner_node = node.args[0]
            dims = self._resolve_dims_raw(inner_node)
            return dims, direction
        
        # 處理一般內部宣告 bit[8]
        dims = self._resolve_dims_raw(node)
        return dims, None

    def _resolve_dims_raw(self, node):
        """解析 bit[8][16] 的維度"""
        dims = []
        curr = node
        while isinstance(curr, ast.Subscript):
            if isinstance(curr.slice, ast.Constant):
                dims.append(curr.slice.value)
            curr = curr.value
        if isinstance(curr, ast.Name) and curr.id == 'bit':
            return dims[::-1] # 回傳如 [8, 16] (Depth, Width)
        return None

    def _infer_width(self, node):
        """遞迴推斷運算式的位元寬度"""
        if isinstance(node, ast.BinOp):
            w_l = self._infer_width(node.left)
            w_r = self._infer_width(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return max(w_l, w_r) + 1
            elif isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                return max(w_l, w_r)
            return max(w_l, w_r) # 預設

        elif isinstance(node, ast.Name):
            # 從符號表查找已定義變數的寬度
            if node.id in self.symbol_table:
                dims = self.symbol_table[node.id]['dims']
                return dims[-1] if dims else 1
            return 1 # 找不到則預設 1-bit

        elif isinstance(node, ast.Constant):
            # 自動計算整數常數需要的位元數
            if node.value == 0: return 1
            return math.floor(math.log2(node.value)) + 1
        
        elif isinstance(node, ast.Subscript):
            # 如果是 mem[i]，寬度就是該記憶體的 Width (第二維度)
            name = node.value.id
            dims = self.symbol_table[name]['dims']
            return dims[1] if len(dims) > 1 else 1

        return 1

    def _generate_logic_decl(self, name, dims):
        """輔助生成 SV 宣告語法"""
        if not dims:
            self.output_decls.append(f"logic {name};")
        elif len(dims) == 1:
            self.output_decls.append(f"logic [{dims[0]-1}:0] {name};")
        elif len(dims) == 2:
            # 第一維為列 (Row/Depth)，第二維為行 (Column/Width)
            self.output_decls.append(f"logic [{dims[1]-1}:0] {name} [0:{dims[0]-1}];")

    def _format_sv_type(self, direction, name, dims):
        """格式化為 SystemVerilog 語法"""
        dir_prefix = f"{direction} " if direction else ""
        if not dims:
            return f"{dir_prefix}logic {name}"
        elif len(dims) == 1:
            # logic [7:0] name
            return f"{dir_prefix}logic [{dims[0]-1}:0] {name}"
        elif len(dims) == 2:
            # logic [width-1:0] name [0:depth-1]
            return f"{dir_prefix}logic [{dims[1]-1}:0] {name} [0:{dims[0]-1}]"
        return f"{dir_prefix}logic {name}"

    def visit_Assign(self, node):
        target = node.targets[0].id
        
        # 1. 處理顯式宣告 (In, Out, 或內部 bit)
        dims, direction = self._resolve_dims(node.value)
        
        if dims is not None:
            self.symbol_table[target] = {'dims': dims}
            if direction:
                # 記錄為 Module 的 Input/Output 埠號
                self.ports.append({'name': target, 'dir': direction, 'dims': dims})
            else:
                # 記錄為內部線路 Signal
                self.output_decls.append(self._format_sv_type("", target, dims) + ";")
            self.declared_vars.add(target)
            return

        # 2. 處理邏輯賦值 (自動推斷寬度)
        rhs_width = self._infer_width(node.value)
        
        # 若左側變數從未宣告，自動生成 logic 宣告
        if target not in self.symbol_table:
            self.symbol_table[target] = {'dims': [rhs_width]}
            self.output_decls.append(self._format_sv_type("", target, [rhs_width]) + ";")
            self.declared_vars.add(target)

        rhs_code = self.visit(node.value)
        self.output_assigns.append(f"assign {target} = {rhs_code};")

    def visit_BinOp(self, node):
        """【自動觸發】當遇到算術或位元運算（+ - & |）時"""
        """處理加減法與位元運算"""
        left = self.visit(node.left)
        right = self.visit(node.right)
        ops = {ast.Add: '+', ast.Sub: '-', ast.BitAnd: '&', ast.BitOr: '|'}
        return f"({left} {ops[type(node.op)]} {right})"

    def visit_Name(self, node):
        """【自動觸發】當遇到變數名稱時直接回傳其 ID 字符串"""
        return node.id

    def visit_Constant(self, node):
        """【自動觸發】當遇到數值（如 255）時轉換為字串"""
        return str(node.value)

    def visit_Subscript(self, node):
        """【自動觸發】當遇到索引存取（如 mem[i]）時"""
        name = self.visit(node.value)
        index = self.visit(node.slice)
        return f"{name}[{index}]"

    def get_verilog(self):
        """生成最終的 SystemVerilog 代碼結構"""
        # 格式化埠號列表 (Ports)
        port_lines = [f"    {self._format_sv_type(p['dir'], p['name'], p['dims'])}" for p in self.ports]
        port_block = ",\n".join(port_lines)
        
        # 組合 Module
        res = [f"module top (\n{port_block}\n);"]
        
        # 內部宣告 (Internal Declarations)
        if self.output_decls:
            res.append("\n    // Internal Signals")
            res.extend([f"    {d}" for d in self.output_decls])
        
        # 邏輯電路 (Logic)
        if self.output_assigns:
            res.append("\n    // Combinational Logic")
            res.extend([f"    {a}" for a in self.output_assigns])
            
        res.append("\nendmodule")
        return "\n".join(res)