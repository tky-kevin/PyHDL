import ast
import math

class MiniHDLTranspiler(ast.NodeVisitor):
    def __init__(self):
        self.symbol_table = {}  # 儲存變數資訊: {name: {'dims': [8, 16], 'is_mem': True}}
        self.output_decls = []  # 宣告區塊 (logic [15:0] ...)
        self.output_assigns = [] # 邏輯區塊 (assign ...)
        self.declared_vars = set() # 追蹤已生成的 SV 宣告

    def _resolve_dims(self, node):
        """【手動呼叫】解析 bit[8][16] 提取維度，用於判定是否為型別宣告"""
        dims = []
        curr = node
        while isinstance(curr, ast.Subscript):
            if isinstance(curr.slice, ast.Constant):
                dims.append(curr.slice.value)
            curr = curr.value
        if isinstance(curr, ast.Name) and curr.id == 'bit':
            return dims[::-1] # 轉為 [8, 16]
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

    def visit_Assign(self, node):
        target = node.targets[0].id
        
        # 1. 處理顯式型別宣告 (例如 a = bit[16])
        dims = self._resolve_dims(node.value)
        if dims is not None:
            self.symbol_table[target] = {'dims': dims}
            self._generate_logic_decl(target, dims)
            self.declared_vars.add(target)
            return

        # 2. 處理運算賦值 (例如 res = a + b)
        # 執行推斷：如果 target 不在符號表中，則自動推斷寬度
        rhs_width = self._infer_width(node.value)
        
        if target not in self.symbol_table:
            self.symbol_table[target] = {'dims': [rhs_width]}
            self._generate_logic_decl(target, [rhs_width])
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
        """【手動呼叫】轉譯完成後，將所有片段組合成最終的 SystemVerilog 代碼"""
        res = ["module top (", ");"]
        res.extend(self.output_decls)
        res.extend(self.output_assigns)
        res.append("endmodule")
        return "\n".join(res)