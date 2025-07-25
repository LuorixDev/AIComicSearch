import os
import time
import hashlib
from .tasks import add_task
from .utils.logger import logger

def process_comic(filepath, comic_name):
    """将漫画处理任务添加到队列中。"""
    try:
        original_filename = os.path.basename(filepath)
        # 使用时间戳和文件名生成一个唯一的任务ID
        task_id = f"{int(time.time())}-{original_filename}"

        # 计算文件内容的哈希值，用于未来的存储标识
        with open(filepath, 'rb') as f:
            file_content_hash = hashlib.sha256(f.read()).hexdigest()

        task = {
            'task_id': task_id,
            'filepath': filepath,
            'original_filename': original_filename,
            'comic_name': comic_name,
            'file_content_hash': file_content_hash
        }
        add_task(task)

    except Exception as e:
        logger.error(f"将任务添加到队列时出错: {e}")
