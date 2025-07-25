import os
import time
import hashlib
import random
from .tasks import add_task
from .utils.logger import logger
from .core.file_processor import _process_zip_file

def process_comic(filepath, comic_name):
    """将漫画处理任务添加到队列中。"""
    try:
        original_filename = os.path.basename(filepath)
        # 使用纳秒级时间戳、随机数和文件名生成一个唯一的任务ID
        task_id = f"{time.time_ns()}-{random.randint(1000, 9999)}-{original_filename}"

        # 计算文件内容的哈希值，用于未来的存储标识
        with open(filepath, 'rb') as f:
            file_content_hash = hashlib.sha256(f.read()).hexdigest()

        task_data = {
            'task_id': task_id,
            'filepath': filepath,
            'original_filename': original_filename,
            'comic_name': comic_name,
            'file_content_hash': file_content_hash
        }
        # 将任务数据和处理函数一起添加到队列
        add_task(task_data, _process_zip_file)

    except Exception as e:
        logger.error(f"将任务添加到队列时出错: {e}")
