class BitMeta(type):
    def __getitem__(cls, params):
        return cls

class bit(metaclass=BitMeta):
    pass

def In(t): return t
def Out(t): return t