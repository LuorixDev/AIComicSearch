import os
from collections import deque
from openai import OpenAI
from dotenv import load_dotenv

from ..utils.logger import logger

# --- 初始化 ---
load_dotenv()

# --- OpenAI 客户端和模型配置 ---
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_API_BASE"),
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "gpt-3.5-turbo")

def get_embedding(text, model=EMBEDDING_MODEL):
    """为文本生成 embedding 向量。"""
    text = text.replace("\n", " ")
    return client.embeddings.create(input=[text], model=model).data[0].embedding

def summarize_text(text, task_id, chapter_name, processing_statuses, model=SUMMARY_MODEL):
    """以流式方式为文本生成摘要，并将日志写入特定的缓冲区。"""
    summary_log_key = f"summary_{chapter_name}"
    try:
        if 'stream_buffers' not in processing_statuses[task_id]:
            processing_statuses[task_id]['stream_buffers'] = {}
        processing_statuses[task_id]['stream_buffers'][summary_log_key] = deque()

        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个善于总结的助手。请根据以下漫画各页描述，生成一个连贯的本章节摘要，用作EMBEDDING关键词搜索。只输出关键词和复杂事件总结关键句（用作事件比对）;格式：\n关键词\n关键词\n关键词。\n\n关键句：\n关键句\n关键句\n关键句。"},
                {"role": "user", "content": text}
            ],
            max_tokens=16384,
            stream=True,
        )
        
        buffer = processing_statuses[task_id]['stream_buffers'][summary_log_key]
        buffer.append("[摘要开始]\n")
        
        summary_content = []
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                buffer.append(content)
                summary_content.append(content)
                yield content
        
        buffer.append("\n[摘要结束]\n")
        
    except Exception as e:
        error_message = f"生成摘要时出错: {e}"
        logger.error(f"[{task_id}] {error_message}")
        if 'stream_buffers' in processing_statuses[task_id] and summary_log_key in processing_statuses[task_id]['stream_buffers']:
            processing_statuses[task_id]['stream_buffers'][summary_log_key].append(error_message)
        yield "摘要生成失败。"
