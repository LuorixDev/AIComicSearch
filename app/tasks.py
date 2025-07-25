import threading
import time
from collections import deque

from .utils.logger import logger

# --- 任务队列和状态管理 ---
processing_queue = deque()
processing_statuses = {}
queue_lock = threading.Lock()
status_lock = threading.Lock() # 为状态更新添加专用的锁
MAX_WORKERS = 4 # 定义最大并发任务数

def add_task(task_data, process_func):
    """将任务添加到队列中，并初始化其状态。"""
    task_id = task_data['task_id']
    comic_name = task_data['comic_name']
    
    with queue_lock:
        if task_id in processing_statuses:
            logger.warning(f"任务 {task_id} ({comic_name}) 已存在，跳过。")
            return

        # 将要执行的函数和其参数一起存储
        task = {'data': task_data, 'func': process_func}
        processing_queue.append(task)
        
        processing_statuses[task_id] = {
            'task_id': task_id,
            'filename': comic_name,
            'status': '排队中',
            'progress': 0,
            'details': '',
            'start_time': time.time(),
            'end_time': None,
            'stream_buffers': {}
        }
        logger.info(f"任务 {task_id} ({comic_name}) 已加入队列。")

def get_all_statuses():
    """返回所有任务的状态。"""
    with status_lock:
        return sorted(list(processing_statuses.values()), key=lambda x: x['start_time'], reverse=True)

def update_task_status(task_id, updates):
    """安全地更新任务状态。"""
    with status_lock:
        if task_id in processing_statuses:
            processing_statuses[task_id].update(updates)
            # 如果需要，可以记录状态更新
            # logger.debug(f"状态更新 for {task_id}: {updates}")
        else:
            logger.warning(f"尝试更新一个不存在的任务状态: {task_id}")

def get_or_create_stream_buffer(task_id, log_key):
    """安全地获取或创建流缓冲区。"""
    with status_lock:
        if task_id in processing_statuses:
            if 'stream_buffers' not in processing_statuses[task_id]:
                processing_statuses[task_id]['stream_buffers'] = {}
            
            if log_key not in processing_statuses[task_id]['stream_buffers']:
                processing_statuses[task_id]['stream_buffers'][log_key] = deque()
            
            return processing_statuses[task_id]['stream_buffers'][log_key]
        else:
            logger.warning(f"尝试为不存在的任务 {task_id} 获取流缓冲区。")
            return None

def worker():
    """后台工作线程"""
    while True:
        task_to_run = None
        with queue_lock:
            if processing_queue:
                task_to_run = processing_queue.popleft()
        
        if task_to_run:
            task_data = task_to_run['data']
            process_func = task_to_run['func']
            task_id = task_data['task_id']
            
            logger.info(f"工作线程获取到新任务: {task_id}")
            try:
                process_func(task_data)
            except Exception as e:
                logger.error(f"执行任务 {task_id} 时发生未捕获的异常: {e}", exc_info=True)
                update_task_status(task_id, {'status': '失败', 'details': f'工作线程错误: {e}'})
        else:
            time.sleep(1)

def start_worker_threads():
    """启动后台工作线程池。"""
    # 计算已在运行的工作线程数量
    running_workers = [t for t in threading.enumerate() if t.name.startswith('comic-worker-')]
    
    if len(running_workers) >= MAX_WORKERS:
        logger.info(f"工作线程池已满 ({len(running_workers)}/{MAX_WORKERS})，无需启动新线程。")
        return

    # 启动所需数量的新线程
    for i in range(MAX_WORKERS - len(running_workers)):
        thread_name = f'comic-worker-{len(running_workers) + i}'
        worker_thread = threading.Thread(target=worker, daemon=True, name=thread_name)
        worker_thread.start()
    
    logger.info(f"后台处理工作线程已启动。当前工作线程数: {sum(1 for t in threading.enumerate() if t.name.startswith('comic-worker-'))}")
