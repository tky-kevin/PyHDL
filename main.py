import ast
from transpiler import MiniHDLTranspiler

def run_transpiler(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    
    # 1. 解析為抽象語法樹 (AST)
    tree = ast.parse(code)
    
    # 2. 執行轉譯器
    transpiler = MiniHDLTranspiler()
    transpiler.visit(tree)
    
    # 3. 輸出結果
    print("// Generated SystemVerilog")
    print(transpiler.get_verilog())

if __name__ == "__main__":
    run_transpiler("example_input.py")