import multiprocessing
import time
import psutil
import os
import datetime
import ctypes

# ==========================================
# 設定
# ==========================================
MEMORY_LIMIT_PERCENT = 95   # 目標メモリ使用率 (%)
CHECK_INTERVAL = 0.5        # 監視更新間隔 (秒)
BATCH_SIZE = 50000          # まとめて処理する回数
THRESHOLD = 1e300           # これを超えたら桁落としする（inf回避）
SCALE_FACTOR = 1e-150       # 桁落とし倍率（10の150乗分の1にする）
# ==========================================

def memory_monitor(stop_event, start_time, max_mem_record):
    """
    メモリ監視プロセス
    """
    print(f"Monitor: 監視開始 (目標: {MEMORY_LIMIT_PERCENT}%)")
    total_mem_gb = psutil.virtual_memory().total / (1024**3)
    
    while not stop_event.is_set():
        try:
            mem = psutil.virtual_memory()
            usage_percent = mem.percent
            used_gb = mem.used / (1024**3)
            
            if usage_percent > max_mem_record.value:
                max_mem_record.value = usage_percent

            elapsed = time.time() - start_time
            elapsed_str = str(datetime.timedelta(seconds=int(elapsed)))
            
            print(f"\r[{elapsed_str}] Memory: {usage_percent:>5.1f}% ({used_gb:>6.1f} / {total_mem_gb:.1f} GB)", end="")
            
            if usage_percent >= MEMORY_LIMIT_PERCENT:
                print(f"\nMonitor: 目標({MEMORY_LIMIT_PERCENT}%)に到達しました。停止信号送信。")
                stop_event.set()
                break
            
            time.sleep(CHECK_INTERVAL)
        except Exception:
            break

def fibonacci_worker_safe(stop_event, total_counter, scale_counter):
    """
    inf(無限大)を回避しながら実数で計算するプロセス
    """
    history = []
    a, b = 1.0, 1.0
    
    local_added_count = 0
    local_scale_count = 0
    
    try:
        while not stop_event.is_set():
            for _ in range(BATCH_SIZE):
                a, b = b, a + b
                
                # === 無限大回避ロジック ===
                if b > THRESHOLD:
                    # 両方の値を小さくして、比率を維持したままリセット
                    a *= SCALE_FACTOR
                    b *= SCALE_FACTOR
                    local_scale_count += 1
                
                history.append(b)
            
            local_added_count += BATCH_SIZE
            
            if stop_event.is_set():
                break
                
    except MemoryError:
        stop_event.set()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # カウンタの反映
        with total_counter.get_lock():
            total_counter.value += local_added_count
        with scale_counter.get_lock():
            scale_counter.value += local_scale_count

if __name__ == "__main__":
    cpu_count = os.cpu_count()
    num_workers = cpu_count 
    
    # 共有変数
    total_items = multiprocessing.Value(ctypes.c_ulonglong, 0) # 生成要素数
    scale_counts = multiprocessing.Value(ctypes.c_ulonglong, 0) # 無限大回避回数
    max_mem_record = multiprocessing.Value('d', 0.0)           # 最大メモリ記録
    
    print(f"--- Memory Eater (Float / Infinite Avoidance Mode) ---")
    print(f"CPU Cores: {cpu_count}")
    print(f"Workers  : {num_workers}")
    print("---------------------------------------------")

    stop_event = multiprocessing.Event()
    workers = []
    start_time = time.time()
    
    for i in range(num_workers):
        p = multiprocessing.Process(target=fibonacci_worker_safe, args=(stop_event, total_items, scale_counts))
        p.start()
        workers.append(p)
    
    try:
        memory_monitor(stop_event, start_time, max_mem_record)
    except KeyboardInterrupt:
        print("\nユーザーによる中断")
        stop_event.set()
    
    print("\nStopping workers... (集計中)")
    for p in workers:
        p.join()
        
    end_time = time.time()
    duration = end_time - start_time
    duration_str = str(datetime.timedelta(seconds=int(duration)))
    final_mem = psutil.virtual_memory()
    
    print("\n" + "="*40)
    print("           RESULT SUMMARY")
    print("="*40)
    print(f" Execution Time   : {duration_str}")
    print(f" Peak Memory Usage: {max_mem_record.value:.1f} %")
# ピーク時の使用率から、GB換算値を逆算して表示（あくまで目安ですが、見た目は整合します）
    peak_gb = (final_mem.total * (max_mem_record.value / 100)) / (1024**3)
    print(f" Peak Memory GB   : {peak_gb:.1f} / {final_mem.total / (1024**3):.1f} GB")
    print(f" Total Items Saved: {total_items.value:,} items")
    print(f" Resets (Avoided inf): {scale_counts.value:,} times") # 回避回数を表示
    if duration > 0:
        print(f" Speed (approx)   : {total_items.value / duration:,.0f} items/sec")
    print("="*40)
    print("Done.")