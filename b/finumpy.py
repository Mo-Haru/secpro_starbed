import os
import sys

# ==========================================
# 重要: NumPy読み込み前の環境変数設定
# ==========================================
# これにより、NumPyが勝手にマルチスレッド化してCPUを奪い合うのを防ぎ、
# Pythonのマルチプロセス機能で綺麗に全コアを埋められるようにします。
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import multiprocessing
import time
import psutil
import datetime
import ctypes
import numpy as np

# ==========================================
# 設定パラメータ
# ==========================================
MEMORY_LIMIT_PERCENT = 95   # 目標メモリ使用率 (%)
CHECK_INTERVAL = 0.5        # 監視更新間隔 (秒)

# 1つの行列のサイズ (2500x2500 float64 = 約50MB)
# StarBEDのような大規模環境では、これくらい大きい方が効率が良いです
MATRIX_SIZE = 2500          

def memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record):
    """
    リソース監視プロセス
    """
    print(f"Monitor: 監視開始 (目標: {MEMORY_LIMIT_PERCENT}%)")
    
    # マシンの全メモリ容量(GB)
    total_mem_gb = psutil.virtual_memory().total / (1024**3)
    
    # 初回の不安定な値を捨てる
    psutil.cpu_percent(interval=None)
    
    while not stop_event.is_set():
        try:
            # intervalを指定して正確な平均CPU負荷を取得
            cpu = psutil.cpu_percent(interval=CHECK_INTERVAL)
            mem = psutil.virtual_memory()
            
            # 最大値の更新
            if mem.percent > max_mem_record.value:
                max_mem_record.value = mem.percent
            if cpu > max_cpu_record.value:
                max_cpu_record.value = cpu
            
            elapsed = str(datetime.timedelta(seconds=int(time.time() - start_time)))
            
            # 状況表示
            # CPUが100%近く、メモリが徐々に増えていけば成功です
            print(f"\r[{elapsed}] CPU: {cpu:>5.1f}% | Mem: {mem.percent:>5.1f}% ({mem.used/(1024**3):>6.1f}/{total_mem_gb:.1f} GB)", end="")
            
            # 目標到達チェック
            if mem.percent >= MEMORY_LIMIT_PERCENT:
                print(f"\nMonitor: 目標({MEMORY_LIMIT_PERCENT}%)に到達しました。全ワーカーを停止します。")
                stop_event.set()
                break
                
        except Exception as e:
            print(f"\nMonitor Error: {e}")
            break

def matrix_worker(stop_event, total_counter, total_bytes):
    """
    行列演算でCPUを焼きつつ、結果を溜め込んでメモリを埋めるワーカー
    """
    data_store = []
    
    # 初期行列生成 (乱数)
    A = np.random.rand(MATRIX_SIZE, MATRIX_SIZE)
    B = np.random.rand(MATRIX_SIZE, MATRIX_SIZE)
    
    # 1ステップで増えるメモリ量（概算）
    size_per_step = A.nbytes # 約50MB
    
    local_count = 0
    local_bytes = 0
    
    try:
        while not stop_event.is_set():
            # 【CPU負荷】 行列積 (Dot Product)
            # 浮動小数点演算ユニット(FPU)をフル活用します
            C = np.dot(A, B)
            
            # 【メモリ負荷】 結果をリストに保持
            data_store.append(C)
            
            # 次の計算へ（入力を更新して計算を止めない）
            A = C 
            
            local_count += 1
            local_bytes += size_per_step
            
            # プロセス間通信の頻度を抑えるための簡易チェック
            if local_count % 10 == 0:
                if stop_event.is_set():
                    break

    except MemoryError:
        # 自分の担当分のメモリがいっぱいになったら停止待機
        stop_event.set()
    except Exception:
        pass
    finally:
        # 終了時に成果を共有カウンタへ報告
        with total_counter.get_lock():
            total_counter.value += local_count
        with total_bytes.get_lock():
            total_bytes.value += local_bytes

if __name__ == "__main__":
    # OSが認識しているCPUコア数（論理コア数）を取得
    cpu_count = os.cpu_count()
    
    # 共有変数（結果集計用）
    total_matrices = multiprocessing.Value(ctypes.c_ulonglong, 0)
    total_bytes = multiprocessing.Value(ctypes.c_ulonglong, 0)
    max_mem_record = multiprocessing.Value('d', 0.0)
    max_cpu_record = multiprocessing.Value('d', 0.0)

    print(f"--- StarBED HPC Stress Test (NumPy Edition) ---")
    print(f"CPU Cores    : {cpu_count}")
    print(f"Matrix Size  : {MATRIX_SIZE}x{MATRIX_SIZE} (approx {MATRIX_SIZE**2 * 8 / (1024**2):.1f} MB each)")
    print("---------------------------------------------")

    stop_event = multiprocessing.Event()
    workers = []
    start_time = time.time()
    
    # ワーカープロセスをコア数分だけ起動
    # これにより全コア使用率100%を目指します
    for i in range(cpu_count):
        p = multiprocessing.Process(target=matrix_worker, args=(stop_event, total_matrices, total_bytes))
        p.start()
        workers.append(p)
    
    try:
        # 監視開始（メインプロセスで実行）
        memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record)
    except KeyboardInterrupt:
        print("\nユーザーによる中断")
        stop_event.set()
    
    print("\nStopping workers... (Join process)")
    for p in workers:
        p.join()
    
    # 結果計算
    duration = time.time() - start_time
    total_mem_obj = psutil.virtual_memory()
    total_mem_gb = total_mem_obj.total / (1024**3)
    
    # ピーク時の使用率からGBを逆算（プロセス終了後はメモリが解放されるため）
    peak_gb = total_mem_gb * (max_mem_record.value / 100.0)
    
    print("\n" + "="*45)
    print("              RESULT SUMMARY")
    print("="*45)
    print(f" Execution Time    : {str(datetime.timedelta(seconds=int(duration)))}")
    print(f" Peak CPU Usage    : {max_cpu_record.value:.1f} %")
    print(f" Peak Memory Usage : {max_mem_record.value:.1f} %")
    print(f" Peak Memory (est) : {peak_gb:.1f} / {total_mem_gb:.1f} GB")
    print("-" * 45)
    print(f" Matrices Gen      : {total_matrices.value:,}")
    print(f" Data Generated    : {total_bytes.value / (1024**3):.2f} GB")
    if duration > 0:
        throughput = total_bytes.value / (1024**3) / duration
        print(f" Memory Throughput : {throughput:.2f} GB/sec")
    print("="*45)
    print("Done.")