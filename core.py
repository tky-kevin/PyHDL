# core.py
class Module:
    """所有硬體模組的基類"""
    pass

class BitMeta(type):
    def __getitem__(cls, params): return cls
    @property
    def posedge(cls): return cls

class bit(metaclass=BitMeta): pass

def In(t): return t
def Out(t): return t