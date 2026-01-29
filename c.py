import multiprocessing
import time
import psutil
import os
import datetime
import ctypes
import sys

# ==========================================
# 設定
# ==========================================
MEMORY_LIMIT_PERCENT = 95   # 目標メモリ使用率 (%)
CHECK_INTERVAL = 0.5        # 監視更新間隔 (秒)
BATCH_SIZE = 50000          # まとめて処理する回数
THRESHOLD = 1e300           # inf回避の閾値
SCALE_FACTOR = 1e-150       # 桁落とし倍率
# ==========================================

def memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record):
    """
    メモリとCPUを監視するプロセス
    """
    print(f"Monitor: 監視開始 (目標: {MEMORY_LIMIT_PERCENT}%)")
    
    total_mem = psutil.virtual_memory().total
    total_mem_gb = total_mem / (1024**3)
    
    # CPU測定の初期化（最初の呼び出しは0や不正確な値を返すため捨てます）
    psutil.cpu_percent(interval=None)
    
    while not stop_event.is_set():
        try:
            # intervalを指定することで、その間の平均CPU使用率を取得しつつsleep代わりになる
            # これにより正確なCPU負荷が測定できます
            cpu_percent = psutil.cpu_percent(interval=CHECK_INTERVAL)
            
            # メモリ情報の取得
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            used_gb = mem.used / (1024**3)
            
            # 最大値の更新（共有メモリへの書き込み）
            if mem_percent > max_mem_record.value:
                max_mem_record.value = mem_percent
            
            if cpu_percent > max_cpu_record.value:
                max_cpu_record.value = cpu_percent

            # 経過時間
            elapsed = time.time() - start_time
            elapsed_str = str(datetime.timedelta(seconds=int(elapsed)))
            
            # リアルタイム表示
            # [時間] CPU: 100.0% | Mem: 45.0% (14.2 / 31.5 GB)
            print(f"\r[{elapsed_str}] CPU: {cpu_percent:>5.1f}% | Mem: {mem_percent:>5.1f}% ({used_gb:>6.1f} / {total_mem_gb:.1f} GB)", end="")
            
            # 目標到達チェック
            if mem_percent >= MEMORY_LIMIT_PERCENT:
                print(f"\nMonitor: 目標メモリ({MEMORY_LIMIT_PERCENT}%)に到達しました。停止します。")
                stop_event.set()
                break
            
        except Exception as e:
            print(f"\nMonitor Error: {e}")
            break

def fibonacci_worker_safe(stop_event, total_counter, scale_counter):
    """
    負荷をかけるワーカープロセス
    """
    # ... (変更なし) ...
    a, b = 1.0, 1.0
    local_added_count = 0
    local_scale_count = 0
    
    try:
        while not stop_event.is_set():
            for _ in range(BATCH_SIZE):
                a, b = b, a + b
                if b > THRESHOLD:
                    a *= SCALE_FACTOR
                    b *= SCALE_FACTOR
                    local_scale_count += 1
                # 計算結果を保持してメモリ消費
                # (appendは計算より遅いが、メモリを確実に食うために必要)
                # 高速化のため、変数をリストに入れるだけに簡略化しても良いが
                # 今回は確実に増やすためこのまま
                
                # リストへの追加自体を少しサボる（計算負荷重視）なら
                # ここでリストに入れない手もあるが、メモリ目的主眼なので入れる
            
            # メモリ消費用リスト（ローカル変数として保持し続ける）
            # ここでappendしないとPythonのGCで消える可能性があるため
            # 実際にはここに global_list.extend([b]*BATCH_SIZE) 的なことをしたいが
            # メモリ消費効率のため、この関数内で巨大リストを持つ構造にする
            
            # ※ 前回のコードでは history.append(b) をループ内に入れていました。
            # ここでは再掲します。
            pass 

    except:
        pass

# ワーカー関数の再定義（前回のロジックをそのまま使用）
def fibonacci_worker_real(stop_event, total_counter, scale_counter):
    history = []
    a, b = 1.0, 1.0
    local_added = 0
    local_scale = 0

    try:
        while not stop_event.is_set():
            for _ in range(BATCH_SIZE):
                a, b = b, a + b
                if b > THRESHOLD:
                    a *= SCALE_FACTOR
                    b *= SCALE_FACTOR
                    local_scale += 1

                buf = bytearray(1024 * 1024)  # 1MB
                buf[0] = 1                    # 実メモリ確保
                history.append(buf)

            local_added += BATCH_SIZE
    except MemoryError:
        stop_event.set()
    finally:
        with total_counter.get_lock():
            total_counter.value += local_added
        with scale_counter.get_lock():
            scale_counter.value += local_scale

if __name__ == "__main__":
    cpu_count = os.cpu_count()
    
    # 共有変数
    total_items = multiprocessing.Value(ctypes.c_ulonglong, 0)
    scale_counts = multiprocessing.Value(ctypes.c_ulonglong, 0)
    max_mem_record = multiprocessing.Value('d', 0.0)
    max_cpu_record = multiprocessing.Value('d', 0.0)  # CPU最大値用を追加
    
    print(f"--- StarBED Stress Test (CPU & Memory) ---")
    print(f"CPU Cores: {cpu_count}")
    print(f"Target   : {MEMORY_LIMIT_PERCENT}% Memory Usage")
    print("---------------------------------------------")

    stop_event = multiprocessing.Event()
    workers = []
    start_time = time.time()
    
    # ワーカー起動
    for i in range(cpu_count):
        p = multiprocessing.Process(target=fibonacci_worker_real, args=(stop_event, total_items, scale_counts))
        p.start()
        workers.append(p)
    
    try:
        memory_monitor(stop_event, start_time, max_mem_record, max_cpu_record)
    except KeyboardInterrupt:
        print("\nInterrupted by User")
        stop_event.set()
    
    print("\nStopping workers... (Calculating results)")
    for p in workers:
        p.join()
        
    end_time = time.time()
    duration = end_time - start_time
    duration_str = str(datetime.timedelta(seconds=int(duration)))
    
    # 最終的なマシンスペック情報
    total_phys_mem_gb = psutil.virtual_memory().total / (1024**3)
    
    # ピーク時のメモリGB換算 (記録された最大% × 合計容量)
    peak_mem_gb = total_phys_mem_gb * (max_mem_record.value / 100.0)
    
    print("\n" + "="*45)
    print("              RESULT SUMMARY")
    print("="*45)
    print(f" Execution Time    : {duration_str}")
    print(f" Peak CPU Usage    : {max_cpu_record.value:.1f} %")  # CPU結果
    print(f" Peak Memory Usage : {max_mem_record.value:.1f} %")
    print(f" Peak Memory (est) : {peak_mem_gb:.1f} / {total_phys_mem_gb:.1f} GB") # わかりやすいGB表示
    print("-" * 45)
    print(f" Total Items Gen   : {total_items.value:,}")
    print(f" Scaling Resets    : {scale_counts.value:,}")
    if duration > 0:
        print(f" Throughput        : {total_items.value / duration:,.0f} items/sec")
    print("="*45)
    print("Done.")