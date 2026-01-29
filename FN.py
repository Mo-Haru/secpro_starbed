import multiprocessing
import time
import psutil
import os
import datetime
import ctypes
import sys
import numpy as np  # NumPyを導入

# ==========================================
# 設定
# ==========================================
MEMORY_LIMIT_PERCENT = 95   # 目標メモリ使用率 (%)
CHECK_INTERVAL = 0.5        # 監視更新間隔 (秒)
# NumPy版では、1回のループで確保するメモリ量を直接指定できます
CHUNK_SIZE_MB = 100         # 1回のリズムで確保するメモリ量 (MB)
MATRIX_SIZE = 2000          # CPU負荷用の行列サイズ (大きいほどCPU負荷増)
# ==========================================

def memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record):
    """
    メモリとCPUを監視するプロセス
    """
    print(f"Monitor: 監視開始 (目標: {MEMORY_LIMIT_PERCENT}%)")
    total_mem = psutil.virtual_memory().total
    total_mem_gb = total_mem / (1024**3)
    psutil.cpu_percent(interval=None)
    
    while not stop_event.is_set():
        try:
            cpu_percent = psutil.cpu_percent(interval=CHECK_INTERVAL)
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            used_gb = mem.used / (1024**3)
            
            if mem_percent > max_mem_record.value:
                max_mem_record.value = mem_percent
            if cpu_percent > max_cpu_record.value:
                max_cpu_record.value = cpu_percent

            elapsed = time.time() - start_time
            elapsed_str = str(datetime.timedelta(seconds=int(elapsed)))
            print(f"\r[{elapsed_str}] CPU: {cpu_percent:>5.1f}% | Mem: {mem_percent:>5.1f}% ({used_gb:>6.1f} / {total_mem_gb:.1f} GB)", end="")
            
            if mem_percent >= MEMORY_LIMIT_PERCENT:
                print(f"\nMonitor: 目標メモリ({MEMORY_LIMIT_PERCENT}%)に到達しました。")
                stop_event.set()
                break
        except Exception as e:
            print(f"\nMonitor Error: {e}")
            break

def numpy_stress_worker(stop_event, total_counter):
    """
    NumPyを使用してCPUとメモリに負荷をかけるワーカー
    """
    history = []
    # CPU負荷用の行列を事前作成
    A = np.random.rand(MATRIX_SIZE, MATRIX_SIZE).astype(np.float32)
    B = np.random.rand(MATRIX_SIZE, MATRIX_SIZE).astype(np.float32)
    
    local_count = 0
    try:
        while not stop_event.is_set():
            # --- CPU負荷：行列演算 ---
            # np.dot は非常に重い計算で、全コアを使い切るのに適しています
            _ = np.dot(A, B)
            
            # --- メモリ負荷：巨大配列の確保 ---
            # 指定したMB分の配列（float32）を作成してリストに保持
            # float32は1要素4バイトなので、(1024*1024 / 4) で 1MB
            elements = (CHUNK_SIZE_MB * 1024 * 1024) // 4
            history.append(np.ones(elements, dtype=np.float32))
            
            local_count += 1
            if stop_event.is_set(): break
            
    except MemoryError:
        stop_event.set()
    except Exception:
        pass
    finally:
        with total_counter.get_lock():
            # 確保した合計MBをカウントに記録
            total_counter.value += (local_count * CHUNK_SIZE_MB)

if __name__ == "__main__":
    # Windowsの優先度設定
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)

    cpu_count = os.cpu_count()
    total_allocated_mb = multiprocessing.Value(ctypes.c_ulonglong, 0)
    max_mem_record = multiprocessing.Value('d', 0.0)
    max_cpu_record = multiprocessing.Value('d', 0.0)
    
    print(f"--- StarBED Stress Test (NumPy Enhanced) ---")
    print(f"CPU Cores    : {cpu_count}")
    print(f"Memory Target: {MEMORY_LIMIT_PERCENT}%")
    print(f"Alloc Speed  : {CHUNK_SIZE_MB} MB per loop/core")
    print("---------------------------------------------")

    stop_event = multiprocessing.Event()
    workers = []
    start_time = time.time()
    
    for i in range(cpu_count):
        p = multiprocessing.Process(target=numpy_stress_worker, args=(stop_event, total_allocated_mb))
        p.start()
        workers.append(p)
    
    try:
        memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record)
    except KeyboardInterrupt:
        print("\nInterrupted by User")
        stop_event.set()
    
    for p in workers:
        p.join()
        
    duration = time.time() - start_time
    total_phys_gb = psutil.virtual_memory().total / (1024**3)
    
    print("\n" + "="*45)
    print("                RESULT SUMMARY")
    print("="*45)
    print(f" Peak CPU Usage   : {max_cpu_record.value:.1f} %")
    print(f" Peak Memory Usage: {max_mem_record.value:.1f} %")
    print(f" Total Allocated  : {total_allocated_mb.value / 1024:.2f} GB")
    print(f" Avg Fill Rate    : {total_allocated_mb.value / duration:.1f} MB/sec")
    print("="*45)