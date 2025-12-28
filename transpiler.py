"""
PyHDL Transpiler
================
Core transpilation engine that converts PyHDL (Python) AST to SystemVerilog.

This module implements an AST visitor that traverses Python syntax trees
and generates equivalent SystemVerilog code. It handles:
- Module and port declarations
- Combinational and sequential logic
- Loop unrolling for hardware generation
- Parameterized module instantiation
- Finite state machines with Enum
- Bit slicing and concatenation

Classes:
    ModuleContext: Stores context information for a hardware module
    PyHDLTranspiler: Main AST visitor that performs the transpilation

Author: PyHDL Team
"""

import ast
import math
import operator
from typing import Dict, List, Optional, Any, Tuple


# =============================================================================
# Module Context
# =============================================================================

class ModuleContext:
    """Stores all context information for a hardware module during transpilation.
    
    Attributes:
        name: Module name
        symbol_table: Maps signal names to their dimension info
        constants: Compile-time constant values
        ports: List of port definitions (name, direction, dimensions)
        output_decls: Internal signal declarations
        main_comb_block: Statements for the always_comb block
        output_seq_blocks: Statements for always_ff blocks, keyed by clock spec
        instances: Submodule instantiation info
        enums: Enum definitions for FSM states
    """
    
    def __init__(self, name: str):
        self.name = name
        self.symbol_table: Dict[str, dict] = {}
        self.constants: Dict[str, int] = {}
        self.ports: List[dict] = []
        self.output_decls: List[str] = []
        self.main_comb_block: List[str] = []
        self.output_seq_blocks: Dict[str, List[str]] = {}
        self.instances: Dict[str, dict] = {}
        self.enums: Dict[str, dict] = {}


# =============================================================================
# PyHDL Transpiler
# =============================================================================

class PyHDLTranspiler(ast.NodeVisitor):
    """Transpiles PyHDL Python code to SystemVerilog.
    
    This class extends Python's ast.NodeVisitor to traverse the AST and
    generate equivalent SystemVerilog code. It maintains state about the
    current module being processed and handles various PyHDL constructs.
    
    Attributes:
        modules: Dictionary of generated modules
        templates: Parameterized module templates
        param_stack: Stack of parameter bindings for loop unrolling
        current_mod: Currently processing module context
        current_seq_clk: Current sequential logic clock specification
        warnings: List of warning messages
    """
    
    # =========================================================================
    # Operator Mappings
    # =========================================================================
    
    # Binary operators: Python AST type -> SystemVerilog operator
    BINARY_OPS = {
        ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
        ast.Mod: '%', ast.Pow: '**', ast.BitAnd: '&', ast.BitOr: '|',
        ast.BitXor: '^', ast.LShift: '<<', ast.RShift: '>>'
    }
    
    # Comparison operators
    COMPARE_OPS = {
        ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<',
        ast.LtE: '<=', ast.Gt: '>', ast.GtE: '>='
    }
    
    # Arithmetic operators for constant evaluation
    ARITH_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow
    }
    
    # =========================================================================
    # Initialization
    # =========================================================================
    
    def __init__(self):
        self.modules: Dict[str, ModuleContext] = {}
        self.templates: Dict[str, ast.ClassDef] = {}
        self.param_stack: List[Dict[str, int]] = []
        self.current_mod: Optional[ModuleContext] = None
        self.current_seq_clk: Optional[str] = None
        self.warnings: List[str] = []
    
    # =========================================================================
    # Helper Methods: Dimension and Width Resolution
    # =========================================================================
    
    def _resolve_dims(self, node: ast.AST) -> Tuple[Optional[List], Optional[str]]:
        """Resolve signal dimensions and direction from an AST node.
        
        Args:
            node: AST node representing a type annotation
            
        Returns:
            Tuple of (dimensions list, direction string or None)
        """
        if isinstance(node, ast.Call) and hasattr(node.func, 'id'):
            if node.func.id in ['In', 'Out']:
                direction = "input" if node.func.id == 'In' else "output"
                dims = self._resolve_dims_raw(node.args[0])
                return dims, direction
        
        if isinstance(node, ast.Name):
            if self.current_mod and node.id in self.current_mod.enums:
                return [node.id], None
        
        return self._resolve_dims_raw(node), None
    
    def _resolve_dims_raw(self, node: ast.AST) -> Optional[List[int]]:
        """Extract raw dimensions from nested subscript syntax (e.g., bit[8][16])."""
        dims = []
        curr = node
        
        while isinstance(curr, ast.Subscript):
            val = self._eval_dim_expr(curr.slice)
            if val is not None and isinstance(val, int):
                dims.append(val)
            curr = curr.value
        
        if isinstance(curr, ast.Name) and curr.id == 'bit':
            return dims[::-1]  # Reverse to get [depth, width] order
        return None
    
    def _eval_dim_expr(self, node: ast.AST) -> Optional[int]:
        """Evaluate a dimension expression to a constant integer.
        
        Handles constants, parameter references, and simple arithmetic.
        """
        if isinstance(node, ast.Constant):
            return node.value
        
        if isinstance(node, ast.Name):
            # Check parameter stack first (for loop variables, etc.)
            if self.param_stack and node.id in self.param_stack[-1]:
                return self.param_stack[-1][node.id]
            # Then check module constants
            if self.current_mod and node.id in self.current_mod.constants:
                return self.current_mod.constants[node.id]
            return None
        
        if isinstance(node, ast.BinOp):
            left = self._eval_dim_expr(node.left)
            right = self._eval_dim_expr(node.right)
            if isinstance(left, int) and isinstance(right, int):
                op_type = type(node.op)
                if op_type in self.ARITH_OPS:
                    return self.ARITH_OPS[op_type](left, right)
        
        return None
    
    def _infer_width(self, node: ast.AST) -> int:
        """Infer the bit width of an expression."""
        if isinstance(node, ast.Tuple):
            return sum(self._infer_width(elt) for elt in node.elts)
        
        if isinstance(node, ast.IfExp):
            return max(self._infer_width(node.body), self._infer_width(node.orelse))
        
        if isinstance(node, ast.UnaryOp):
            return self._infer_width(node.operand)
        
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                upper = self._eval_dim_expr(node.slice.lower)
                lower = self._eval_dim_expr(node.slice.upper)
                msb = upper if upper is not None else 0
                lsb = lower if lower is not None else 0
                return abs(msb - lsb) + 1
            
            name = self.visit(node.value)
            if self.current_mod and name in self.current_mod.symbol_table:
                dims = self.current_mod.symbol_table[name]['dims']
                if len(dims) > 1:
                    return dims[1]  # Array element width
                return 1
            return 1
        
        if isinstance(node, ast.BinOp):
            w_l = self._infer_width(node.left)
            w_r = self._infer_width(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                return max(w_l, w_r) + 1
            return max(w_l, w_r)
        
        if isinstance(node, (ast.Compare, ast.BoolOp)):
            return 1
        
        if isinstance(node, ast.Name):
            val = self._eval_dim_expr(node)
            if val is not None:
                return val
            if self.current_mod and node.id in self.current_mod.symbol_table:
                dims = self.current_mod.symbol_table[node.id]['dims']
                if dims and isinstance(dims[0], str):
                    if dims[0] in self.current_mod.enums:
                        return self.current_mod.enums[dims[0]]['width']
                return dims[-1] if dims else 1
        
        if isinstance(node, ast.Attribute):
            name = self.visit(node)
            if self.current_mod and name in self.current_mod.symbol_table:
                dims = self.current_mod.symbol_table[name]['dims']
                return dims[-1] if dims else 1
        
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and node.value != 0:
                return math.floor(math.log2(abs(node.value))) + 1
            return 1
        
        return 1
    
    # =========================================================================
    # Helper Methods: Code Formatting
    # =========================================================================
    
    def _format_sv_type(self, direction: str, name: str, dims: List) -> str:
        """Format a SystemVerilog type declaration."""
        dir_prefix = f"{direction} " if direction else ""
        
        # Enum type
        if dims and isinstance(dims[0], str):
            if self.current_mod and dims[0] in self.current_mod.enums:
                return f"{dir_prefix}{dims[0]}_t {name}"
        
        # Scalar
        if not dims:
            return f"{dir_prefix}logic {name}"
        
        # 1D signal
        if len(dims) == 1:
            return f"{dir_prefix}logic [{dims[0]-1}:0] {name}"
        
        # 2D array (memory)
        return f"{dir_prefix}logic [{dims[1]-1}:0] {name} [0:{dims[0]-1}]"
    
    def _format_const(self, value: int, width: int) -> str:
        """Format a constant with explicit bit width."""
        return f"{width}'d{value}" if width > 0 else str(value)
    
    def _extract_edges(self, node: ast.AST) -> List[Tuple[str, str]]:
        """Extract clock edge specifications from a condition."""
        edges = []
        if isinstance(node, ast.Attribute) and node.attr in ['posedge', 'negedge']:
            edges.append((self.visit(node.value), node.attr))
        elif isinstance(node, ast.BoolOp):
            for val in node.values:
                edges.extend(self._extract_edges(val))
        return edges
    
    # =========================================================================
    # Parameterized Template Detection
    # =========================================================================
    
    def _is_parameterized_template(self, node: ast.ClassDef) -> bool:
        """Check if a class is a parameterized template (uses undefined variables)."""
        
        class UnboundVarChecker(ast.NodeVisitor):
            """Helper visitor to detect unbound variable references."""
            BUILTINS = {
                'bit', 'In', 'Out', 'Module', 'Enum', 'range',
                'True', 'False', 'None', 'not', 'and', 'or'
            }
            
            def __init__(self, defined_names):
                self.defined_names = defined_names
                self.has_unbound = False
            
            def visit_Name(self, n):
                if n.id not in self.defined_names and n.id not in self.BUILTINS:
                    if isinstance(n.ctx, ast.Load):
                        self.has_unbound = True
                self.generic_visit(n)
        
        # Collect defined names within the class
        defined = set()
        
        # Constants (NAME = Constant)
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                if (len(stmt.targets) == 1 and
                    isinstance(stmt.targets[0], ast.Name) and
                    isinstance(stmt.value, ast.Constant)):
                    defined.add(stmt.targets[0].id)
            elif isinstance(stmt, ast.ClassDef):
                defined.add(stmt.name)  # Nested Enum
        
        # Loop variables (including nested)
        for child in ast.walk(node):
            if isinstance(child, ast.For) and isinstance(child.target, ast.Name):
                defined.add(child.target.id)
        
        # All assignment targets
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
        
        # Add known template names
        defined.update(self.templates.keys())
        
        # Check for unbound variables
        checker = UnboundVarChecker(defined)
        for stmt in node.body:
            checker.visit(stmt)
        
        return checker.has_unbound
    
    # =========================================================================
    # AST Visitors: Class and Module Handling
    # =========================================================================
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Process a class definition as a hardware module or Enum."""
        # Handle Enum definitions
        is_enum = any(
            isinstance(base, ast.Name) and base.id == 'Enum'
            for base in node.bases
        )
        if is_enum:
            self._process_enum(node)
            return
        
        # Store as template
        self.templates[node.name] = node
        
        # Skip parameterized templates (will be generated on instantiation)
        if self._is_parameterized_template(node):
            return
        
        # Generate non-parameterized module immediately
        self.current_mod = ModuleContext(node.name)
        self.modules[node.name] = self.current_mod
        for stmt in node.body:
            self.visit(stmt)
        self.current_mod = None
    
    def _process_enum(self, node: ast.ClassDef):
        """Process an Enum class definition for FSM states."""
        enum_name = node.name
        states = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                states[stmt.targets[0].id] = stmt.value.value
        
        width = max(1, math.ceil(math.log2(len(states)))) if states else 1
        self.current_mod.enums[enum_name] = {'states': states, 'width': width}
    
    # =========================================================================
    # AST Visitors: Loop Unrolling
    # =========================================================================
    
    def visit_For(self, node: ast.For):
        """Process for loops by unrolling them at compile time."""
        # Validate loop structure
        if not (isinstance(node.iter, ast.Call) and
                isinstance(node.iter.func, ast.Name) and
                node.iter.func.id == 'range'):
            self.warnings.append(
                f"[{self.current_mod.name}] Only 'range()' loops supported."
            )
            return
        
        # Parse range arguments
        args = node.iter.args
        start, stop, step = 0, 0, 1
        
        try:
            if len(args) == 1:
                stop = self._eval_dim_expr(args[0])
            elif len(args) == 2:
                start = self._eval_dim_expr(args[0])
                stop = self._eval_dim_expr(args[1])
            elif len(args) == 3:
                start = self._eval_dim_expr(args[0])
                stop = self._eval_dim_expr(args[1])
                step = self._eval_dim_expr(args[2])
            else:
                raise ValueError("Invalid range arguments")
            
            if stop is None:
                raise ValueError("Cannot evaluate range stop value")
        except Exception:
            self.warnings.append(
                f"[{self.current_mod.name}] Loop range must be statically evaluable."
            )
            return
        
        # Unroll the loop
        loop_var = node.target.id
        for i in range(start, stop, step):
            self.param_stack.append({loop_var: i})
            for stmt in node.body:
                self.visit(stmt)
            self.param_stack.pop()
    
    # =========================================================================
    # AST Visitors: Assignment Handling
    # =========================================================================
    
    def visit_Assign(self, node: ast.Assign):
        """Process assignment statements."""
        target_node = node.targets[0]
        target = self.visit(target_node)
        
        # Case A: Constant definition (no hardware generated)
        if self._handle_constant_def(node, target_node, target):
            return
        
        # Case B: Submodule port connection
        if self._handle_port_connection(node, target_node, target):
            return
        
        # Case C: Module instantiation
        if self._handle_instantiation(node, target):
            return
        
        # Case D: Signal declaration
        if self._handle_declaration(node, target):
            return
        
        # Case E: Logic assignment
        self._handle_assignment(node, target_node, target)
    
    def _handle_constant_def(self, node, target_node, target) -> bool:
        """Handle constant parameter definitions."""
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
            if isinstance(target_node, ast.Name):
                is_not_in_block = (self.current_seq_clk is None)
                is_not_signal = target not in self.current_mod.symbol_table
                if is_not_in_block and is_not_signal:
                    self.current_mod.constants[target] = node.value.value
                    return True
        return False
    
    def _handle_port_connection(self, node, target_node, target) -> bool:
        """Handle submodule port connections (u1.port = signal)."""
        if isinstance(target_node, ast.Attribute) and not self.current_seq_clk:
            inst_name = self.visit(target_node.value)
            port_name = target_node.attr
            
            if inst_name in self.current_mod.instances:
                mod_type = self.current_mod.instances[inst_name]['mod']
                sub_mod = self.modules[mod_type]
                
                # Find port width
                port_w = 1
                for p in sub_mod.ports:
                    if p['name'] == port_name:
                        port_w = p['dims'][-1] if p['dims'] else 1
                        break
                
                # Format RHS
                if isinstance(node.value, ast.Constant):
                    rhs = self._format_const(node.value.value, port_w)
                else:
                    rhs = self.visit(node.value)
                
                self.current_mod.instances[inst_name]['mapping'][port_name] = rhs
                return True
        return False
    
    def _handle_instantiation(self, node, target) -> bool:
        """Handle parameterized module instantiation."""
        if not isinstance(node.value, ast.Call):
            return False
        if not hasattr(node.value.func, 'id'):
            return False
        if node.value.func.id not in self.templates:
            return False
        
        base_mod_name = node.value.func.id
        
        # Collect parameters
        params = {}
        for keyword in node.value.keywords:
            if isinstance(keyword.value, ast.Constant):
                params[keyword.arg] = keyword.value.value
        
        # Generate unique module name
        if params:
            param_suffix = "_".join([f"{k}{v}" for k, v in params.items()])
            actual_mod_name = f"{base_mod_name}_{param_suffix}"
        else:
            actual_mod_name = base_mod_name
        
        # Generate module if not already exists
        if actual_mod_name not in self.modules:
            prev_mod = self.current_mod
            self.current_mod = ModuleContext(actual_mod_name)
            self.modules[actual_mod_name] = self.current_mod
            self.param_stack.append(params)
            
            template_node = self.templates[base_mod_name]
            for stmt in template_node.body:
                self.visit(stmt)
            
            self.param_stack.pop()
            self.current_mod = prev_mod
        
        # Register instance and create intermediate signals
        mod_ctx = self.modules[actual_mod_name]
        self.current_mod.instances[target] = {'mod': actual_mod_name, 'mapping': {}}
        
        for p in mod_ctx.ports:
            sig = f"{target}_{p['name']}"
            self.current_mod.instances[target]['mapping'][p['name']] = sig
            
            if p['dir'] == 'output':
                self.current_mod.symbol_table[sig] = {'dims': p['dims']}
                self.current_mod.output_decls.append(
                    self._format_sv_type("", sig, p['dims']) + ";"
                )
        
        return True
    
    def _handle_declaration(self, node, target) -> bool:
        """Handle signal/port declarations."""
        dims, direction = self._resolve_dims(node.value)
        
        if dims is not None:
            self.current_mod.symbol_table[target] = {'dims': dims}
            
            if direction:
                self.current_mod.ports.append({
                    'name': target, 'dir': direction, 'dims': dims
                })
            else:
                self.current_mod.output_decls.append(
                    self._format_sv_type("", target, dims) + ";"
                )
            return True
        return False
    
    def _handle_assignment(self, node, target_node, target):
        """Handle logic assignments (combinational or sequential)."""
        # Infer width
        rhs_w = self._infer_width(node.value)
        
        if target in self.current_mod.symbol_table:
            lhs_dims = self.current_mod.symbol_table[target]['dims']
            if lhs_dims and isinstance(lhs_dims[0], str):
                lhs_width = self.current_mod.enums[lhs_dims[0]]['width']
            else:
                lhs_width = lhs_dims[-1] if lhs_dims else 1
        else:
            lhs_width = rhs_w
            lhs_dims = [rhs_w]
            if isinstance(target_node, ast.Name):
                self.current_mod.symbol_table[target] = {'dims': lhs_dims}
                self.current_mod.output_decls.append(
                    self._format_sv_type("", target, lhs_dims) + ";"
                )
        
        # Format RHS
        if isinstance(node.value, ast.Constant):
            rhs_code = self._format_const(node.value.value, lhs_width)
        else:
            rhs_code = self.visit(node.value)
        
        # Add to appropriate block
        if self.current_seq_clk:
            self.current_mod.output_seq_blocks[self.current_seq_clk].append(
                f"{target} <= {rhs_code};"
            )
        else:
            self.current_mod.main_comb_block.append(
                f"{target} = {rhs_code};"
            )
    
    # =========================================================================
    # AST Visitors: Control Flow
    # =========================================================================
    
    def visit_If(self, node: ast.If):
        """Process if statements as combinational or sequential logic."""
        # Already in sequential block
        if self.current_seq_clk:
            self._process_procedural_if(
                node, self.current_mod.output_seq_blocks[self.current_seq_clk]
            )
            return
        
        # Check for clock edge trigger
        edges = self._extract_edges(node.test)
        if edges:
            # Sequential logic
            clk_spec = " or ".join([f"{edge} {name}" for name, edge in edges])
            self.current_seq_clk = clk_spec
            
            if clk_spec not in self.current_mod.output_seq_blocks:
                self.current_mod.output_seq_blocks[clk_spec] = []
            
            for stmt in node.body:
                self.visit(stmt)
            
            self.current_seq_clk = None
        else:
            # Combinational logic
            self._process_procedural_if(node, self.current_mod.main_comb_block)
    
    def _process_procedural_if(self, node: ast.If, target_list: List[str]):
        """Process an if statement into SystemVerilog if-else block."""
        cond = self.visit(node.test)
        original_list = list(target_list)
        target_list.clear()
        
        # Process body
        for stmt in node.body:
            self.visit(stmt)
        body_code = [f"    {line}" for s in target_list for line in s.split('\n')]
        
        # Process else/elif
        else_part = ""
        if node.orelse:
            target_list.clear()
            is_elif = (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If))
            
            if is_elif:
                self.visit(node.orelse[0])
                else_part = f" else {target_list[0]}"
            else:
                for stmt in node.orelse:
                    self.visit(stmt)
                else_code = [f"    {line}" for s in target_list for line in s.split('\n')]
                else_part = " else begin\n" + "\n".join(else_code) + "\nend"
        
        # Reconstruct target list
        target_list.clear()
        target_list.extend(original_list)
        full_block = f"if ({cond}) begin\n" + "\n".join(body_code) + "\nend" + else_part
        target_list.append(full_block)
    
    def visit_Match(self, node: ast.Match):
        """Process match statements as unique case blocks."""
        target_list = (
            self.current_mod.output_seq_blocks[self.current_seq_clk]
            if self.current_seq_clk
            else self.current_mod.main_comb_block
        )
        
        subject = self.visit(node.subject)
        case_lines = [f"unique case ({subject})"]
        original_list = list(target_list)
        has_default = False
        
        for case in node.cases:
            pattern = self.visit(case.pattern)
            target_list.clear()
            
            # Check if this is a wildcard/default pattern
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                has_default = True
                for stmt in case.body:
                    self.visit(stmt)
                branch_stmts = [f"        {line}" for s in target_list for line in s.split('\n')]
                case_lines.append(f"    default: begin\n" + "\n".join(branch_stmts) + "\n    end")
            else:
                for stmt in case.body:
                    self.visit(stmt)
                branch_stmts = [f"        {line}" for s in target_list for line in s.split('\n')]
                case_lines.append(f"    {pattern}: begin\n" + "\n".join(branch_stmts) + "\n    end")
        
        # Add default if not present
        if not has_default:
            case_lines.append("    default: begin\n    end")
        
        case_lines.append("endcase")
        target_list.clear()
        target_list.extend(original_list)
        target_list.append("\n".join(case_lines))
    
    # =========================================================================
    # AST Visitors: Expression Nodes
    # =========================================================================
    
    def visit_IfExp(self, node: ast.IfExp) -> str:
        """Ternary expression: a if cond else b -> (cond ? a : b)"""
        cond = self.visit(node.test)
        true_val = self.visit(node.body)
        false_val = self.visit(node.orelse)
        return f"({cond} ? {true_val} : {false_val})"
    
    def visit_UnaryOp(self, node: ast.UnaryOp) -> str:
        """Unary operators: ~, !, -, +"""
        operand = self.visit(node.operand)
        
        if isinstance(node.op, ast.Invert):
            return f"(~{operand})"
        if isinstance(node.op, ast.Not):
            return f"(!{operand})"
        if isinstance(node.op, ast.USub):
            return f"(-{operand})"
        return f"({operand})"
    
    def visit_BoolOp(self, node: ast.BoolOp) -> str:
        """Boolean operators: and -> &&, or -> ||"""
        op = '&&' if isinstance(node.op, ast.And) else '||'
        values = [self.visit(v) for v in node.values]
        return f"({f' {op} '.join(values)})"
    
    def visit_BinOp(self, node: ast.BinOp) -> str:
        """Binary operators: +, -, *, /, %, &, |, ^, <<, >>"""
        op_type = type(node.op)
        if op_type in self.BINARY_OPS:
            return f"({self.visit(node.left)} {self.BINARY_OPS[op_type]} {self.visit(node.right)})"
        return f"({self.visit(node.left)} ? {self.visit(node.right)})"
    
    def visit_Compare(self, node: ast.Compare) -> str:
        """Comparison operators: ==, !=, <, >, <=, >="""
        op = self.COMPARE_OPS.get(type(node.ops[0]), '==')
        return f"({self.visit(node.left)} {op} {self.visit(node.comparators[0])})"
    
    def visit_Subscript(self, node: ast.Subscript) -> str:
        """Array/bit subscript: a[i], a[7:0]"""
        name = self.visit(node.value)
        declared_msb = None
        
        # Get declared bounds for bounds checking
        if self.current_mod and name in self.current_mod.symbol_table:
            dims = self.current_mod.symbol_table[name]['dims']
            if dims:
                if len(dims) > 1:
                    declared_msb = dims[0] - 1  # Array depth
                else:
                    declared_msb = dims[-1] - 1  # Bit width
        
        # Handle slice: a[7:0]
        if isinstance(node.slice, ast.Slice):
            msb = self._eval_dim_expr(node.slice.lower)
            lsb = self._eval_dim_expr(node.slice.upper)
            
            if msb is None or lsb is None:
                raise ValueError(f"Error: Slice '{name}' must have explicit start/stop.")
            
            if declared_msb is not None and msb > declared_msb:
                self.warnings.append(
                    f"[{self.current_mod.name}] Out of bounds: {name}[{msb}] exceeds [0:{declared_msb}]"
                )
            
            return f"{name}[{msb}:{lsb}]"
        
        # Handle index: a[i]
        if isinstance(node.slice, ast.Constant):
            idx_val = node.slice.value
            idx = str(idx_val)
        else:
            idx_val = self._eval_dim_expr(node.slice)
            idx = str(idx_val) if idx_val is not None else self.visit(node.slice)
        
        # Bounds check
        if declared_msb is not None and idx_val is not None and isinstance(idx_val, int):
            if idx_val > declared_msb:
                self.warnings.append(
                    f"[{self.current_mod.name}] Out of bounds: {name}[{idx_val}] exceeds [0:{declared_msb}]"
                )
        
        return f"{name}[{idx}]"
    
    def visit_Attribute(self, node: ast.Attribute) -> str:
        """Attribute access: State.IDLE, u1.result"""
        v = self.visit(node.value)
        a = node.attr
        
        # Enum member
        if self.current_mod and v in self.current_mod.enums:
            if a in self.current_mod.enums[v]['states']:
                return a
            raise ValueError(f"Error: Enum '{v}' has no member '{a}'")
        
        # Submodule signal
        if self.current_mod and f"{v}_{a}" in self.current_mod.symbol_table:
            return f"{v}_{a}"
        
        return f"{v}.{a}"
    
    def visit_Tuple(self, node: ast.Tuple) -> str:
        """Tuple concatenation: (a, b) -> {a, b}"""
        elements = []
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, int):
                elements.append(f"1'd{e.value}")
            else:
                elements.append(self.visit(e))
        return f"{{{', '.join(elements)}}}"
    
    def visit_Name(self, node: ast.Name) -> str:
        """Variable reference with parameter substitution."""
        # Check parameter stack
        if self.param_stack and node.id in self.param_stack[-1]:
            return str(self.param_stack[-1][node.id])
        
        # Check module constants
        if self.current_mod and node.id in self.current_mod.constants:
            return str(self.current_mod.constants[node.id])
        
        return node.id
    
    def visit_Constant(self, node: ast.Constant) -> str:
        """Constant value."""
        return str(node.value)
    
    def visit_MatchValue(self, node) -> str:
        """Match case pattern value."""
        return self.visit(node.value)
    
    # =========================================================================
    # Code Generation
    # =========================================================================
    
    def get_verilog(self) -> str:
        """Generate the complete SystemVerilog output."""
        all_sv = []
        
        for mod in self.modules.values():
            sv_lines = self._generate_module(mod)
            all_sv.append("\n".join(sv_lines))
        
        return "\n\n".join(all_sv)
    
    def _generate_module(self, mod: ModuleContext) -> List[str]:
        """Generate SystemVerilog for a single module."""
        lines = []
        
        # Module header
        ports = ",\n".join([
            f"    {self._format_sv_type(p['dir'], p['name'], p['dims'])}"
            for p in mod.ports
        ])
        lines.append(f"module {mod.name} (\n{ports}\n);")
        
        # Enum typedefs
        for name, info in mod.enums.items():
            width = info['width']
            states = ", ".join([f"{k}={width}'d{v}" for k, v in info['states'].items()])
            lines.append(
                f"    typedef enum logic [{width-1}:0] {{{states}}} {name}_t;"
            )
        
        # Internal signal declarations
        for decl in mod.output_decls:
            lines.append(f"    {decl}")
        
        # Submodule instances
        for inst_name, inst_info in mod.instances.items():
            mapping = ", ".join([
                f".{port}({sig})"
                for port, sig in inst_info['mapping'].items()
            ])
            lines.append(f"    {inst_info['mod']} {inst_name} ({mapping});")
        
        # Combinational logic block
        if mod.main_comb_block:
            formatted = "\n".join([
                f"        {line}"
                for stmt in mod.main_comb_block
                for line in stmt.split('\n')
            ])
            lines.append(f"    always_comb begin\n{formatted}\n    end")
        
        # Sequential logic blocks
        for clk_spec, stmts in mod.output_seq_blocks.items():
            formatted = "\n".join([
                f"        {line}"
                for stmt in stmts
                for line in stmt.split('\n')
            ])
            lines.append(f"    always_ff @({clk_spec}) begin\n{formatted}\n    end")
        
        lines.append("endmodule")
        return lines
    
    def generate_report(self) -> str:
        """Generate a transpilation summary report."""
        report = [
            "=" * 40,
            "  PyHDL Transpilation Summary",
            "=" * 40
        ]
        
        for mod in self.modules.values():
            report.append(
                f"Module: {mod.name}\n"
                f"  - Ports: {len(mod.ports)}\n"
                f"  - Internal Signals: {len(mod.output_decls)}"
            )
        
        report.append(f"Total Warnings: {len(self.warnings)}")
        for w in self.warnings:
            report.append(f"  [!] {w}")
        
        report.append("=" * 40)
        return "\n".join(report)