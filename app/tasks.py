import threading
import time
from collections import deque

from .utils.logger import logger
from .core.file_processor import _process_zip_file

# --- 任务队列和状态管理 ---
processing_queue = deque()
processing_statuses = {}
queue_lock = threading.Lock()

def add_task(task):
    """将任务添加到队列中，并初始化其状态。"""
    task_id = task['task_id']
    comic_name = task['comic_name']
    
    with queue_lock:
        if task_id in processing_statuses:
            logger.warning(f"任务 {task_id} ({comic_name}) 已存在，跳过。")
            return

        processing_queue.append(task)
        
        processing_statuses[task_id] = {
            'task_id': task_id,
            'filename': comic_name, # 使用提取的漫画名称
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
    with queue_lock:
        return sorted(processing_statuses.values(), key=lambda x: x['start_time'], reverse=True)

def worker():
    """后台工作线程"""
    while True:
        task = None
        with queue_lock:
            if processing_queue:
                task = processing_queue.popleft()
        
        if task:
            from app.core.file_processor import _process_zip_file
            logger.info(f"工作线程获取到新任务: {task['task_id']}")
            # 注意：这里我们直接调用了 _process_zip_file，它需要被正确导入
            _process_zip_file(task, processing_statuses)
        else:
            time.sleep(1)

def start_worker_thread():
    """启动后台工作线程。"""
    if any(t.name == 'comic-worker' for t in threading.enumerate()):
        return
    worker_thread = threading.Thread(target=worker, daemon=True, name='comic-worker')
    worker_thread.start()
    logger.info("后台处理工作线程已启动。")
