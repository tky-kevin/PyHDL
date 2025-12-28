"""
PyHDL Core Module
=================
Defines the base classes and types for PyHDL hardware description.

These classes serve as markers for the transpiler and enable Python's
type hints to work during development, while having no runtime behavior.

Classes:
    Module: Base class for all hardware modules
    bit: Represents a hardware signal type with optional width
    BitMeta: Metaclass enabling bit[N] syntax and .posedge/.negedge attributes

Functions:
    In(t): Marks a port as input
    Out(t): Marks a port as output
"""


class Module:
    """Base class for all hardware modules.
    
    Hardware modules are defined by inheriting from this class.
    The transpiler converts class definitions to SystemVerilog modules.
    
    Example:
        class MyALU(Module):
            a = In(bit[8])
            b = In(bit[8])
            result = Out(bit[8])
            
            result = a + b
    """
    pass


class BitMeta(type):
    """Metaclass for the bit type.
    
    Enables the following syntax:
        - bit[8]  : 8-bit signal
        - bit[16] : 16-bit signal
        - clk.posedge : Positive edge trigger
        - rst.negedge : Negative edge trigger
    """
    
    def __getitem__(cls, params):
        """Enable subscript syntax: bit[N] for N-bit signals."""
        return cls
    
    @property
    def posedge(cls):
        """Marker for positive edge sensitivity."""
        return cls
    
    @property
    def negedge(cls):
        """Marker for negative edge sensitivity."""
        return cls


class bit(metaclass=BitMeta):
    """Represents a hardware signal type.
    
    Usage:
        signal = bit       # 1-bit signal
        signal = bit[8]    # 8-bit signal
        signal = bit[N][M] # N-element array of M-bit signals
    """
    pass


class Enum:
    """Base class for state enumeration in FSMs.
    
    Example:
        class State(Enum):
            IDLE = 0
            RUN = 1
            DONE = 2
    """
    pass


def In(t):
    """Marks a port as input direction.
    
    Args:
        t: The signal type (e.g., bit, bit[8])
    
    Returns:
        The type unchanged (marker for transpiler)
    
    Example:
        clk = In(bit)
        data = In(bit[8])
    """
    return t


def Out(t):
    """Marks a port as output direction.
    
    Args:
        t: The signal type (e.g., bit, bit[8])
    
    Returns:
        The type unchanged (marker for transpiler)
    
    Example:
        result = Out(bit[8])
        valid = Out(bit)
    """
    return t