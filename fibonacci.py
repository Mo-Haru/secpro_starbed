from functools import lru_cache

@lru_cache(maxsize=None)  # 計算結果をすべてメモリにキャッシュ
def fibonacci(n):
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# 実行
print([fibonacci(i) for i in range(1000)])
