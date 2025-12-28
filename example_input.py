from core import bit

# 宣告：8列、每列16位元
mem = bit[8][16]
a = bit[16]
b = bit[16]

# 組合邏輯
val = mem[2]    # 取出第 2 列 (Row)
res = a + b     # 無號數加法 (加法器)