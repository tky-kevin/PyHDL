class BitMeta(type):
    """支援 bit[8] 或 bit[8][16] 的語法"""
    def __getitem__(cls, params):
        return cls  # 為了讓 AST 能解析，我們只需回傳類別本身

class bit(metaclass=BitMeta):
    """基礎硬體型別"""
    pass

# 用於型別檢查與 IDE 輔助 (Optional)
def Input(t): return t
def Output(t): return t