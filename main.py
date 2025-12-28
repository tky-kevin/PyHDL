import ast
from transpiler import PyHDLTranspiler

def run_transpiler(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    
    tree = ast.parse(code)
    
    transpiler = PyHDLTranspiler()
    transpiler.visit(tree)
    
    print("// Generated SystemVerilog")
    print(transpiler.get_verilog())

if __name__ == "__main__":
    run_transpiler("test_code/example_code.phd")