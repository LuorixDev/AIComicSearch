import logging
import os

def setup_logger():
    """配置全局日志记录器"""
    # 创建 logs 目录（如果不存在）
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'processing.log')

    # 获取根日志记录器
    logger = logging.getLogger()
    if logger.hasHandlers():
        # 如果已经配置过，则不再重复配置
        return logger

    logger.setLevel(logging.INFO)

    # 创建一个文件处理器，将日志写入文件
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    # 创建一个流处理器，将日志输出到控制台
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)

    # 创建日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    # 将处理器添加到日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger

# 在模块加载时立即设置日志记录器
logger = setup_logger()
