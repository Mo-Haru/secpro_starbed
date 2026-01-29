import multiprocessing
import os

CHUNK_MB = 64  # 1回で確保するサイズ（32MB）

def burn():
    data = []
    while True:
        buf = bytearray(CHUNK_MB * 1024 * 1024)
        buf[0] = 1          # 実メモリ確保
        data.append(buf)   # 保持して解放させない

if __name__ == "__main__":
    for _ in range(os.cpu_count()*2):
        multiprocessing.Process(target=burn).start()
