import json
import time
from flask import Blueprint, jsonify, Response, stream_with_context, render_template
from ..tasks import get_all_statuses, processing_statuses
from app.utils.logger import logger

api_bp = Blueprint('api', __name__)

@api_bp.route('/processing')
def processing_status():
    """显示文件处理状态的页面。"""
    statuses = get_all_statuses()
    return render_template('processing.html', statuses=statuses)

@api_bp.route('/api/processing-status')
def api_processing_status():
    """以 JSON 格式返回所有任务的状态，移除不可序列化的部分。"""
    statuses = get_all_statuses()
    serializable_statuses = []
    for task in statuses:
        serializable_task = {k: v for k, v in task.items() if k != 'stream_buffers'}
        serializable_statuses.append(serializable_task)
    return jsonify(serializable_statuses)

@api_bp.route('/stream-ai/<task_id>')
def stream_ai(task_id):
    def generate():
        if task_id not in processing_statuses:
            error_data = json.dumps({"stream_id": "error", "content": f"错误：未找到任务ID {task_id}"})
            yield f"data: {error_data}\n\n"
            return

        task_status = processing_statuses.get(task_id)
        if not task_status:
            return

        finished_stream_ids = set()
        if 'stream_buffers' in task_status:
            for stream_id, buffer in task_status['stream_buffers'].items():
                if any(isinstance(item, dict) and item.get('type') == 'stream_end' for item in buffer):
                    finished_stream_ids.add(stream_id)

        if 'stream_buffers' in task_status:
            for stream_id, buffer in task_status['stream_buffers'].items():
                if stream_id in finished_stream_ids:
                    continue
                
                if buffer:
                    history_content = "".join([item for item in buffer if isinstance(item, str)])
                    if history_content:
                        data = json.dumps({"stream_id": stream_id, "content": history_content, "is_history": True})
                        yield f"data: {data}\n\n"
        
        known_stream_ids = set(task_status.get('stream_buffers', {}).keys())
        sent_positions = {stream_id: len(buffer) for stream_id, buffer in task_status.get('stream_buffers', {}).items()}

        try:
            while True:
                task_status = processing_statuses.get(task_id)
                if not task_status:
                    break

                current_stream_ids = set(task_status.get('stream_buffers', {}).keys())
                new_streams = current_stream_ids - known_stream_ids
                if new_streams:
                    for stream_id in new_streams:
                        known_stream_ids.add(stream_id)
                        sent_positions[stream_id] = 0

                has_data = False
                for stream_id in list(known_stream_ids):
                    buffer = task_status.get('stream_buffers', {}).get(stream_id)
                    if buffer:
                        current_pos = sent_positions.get(stream_id, 0)
                        if len(buffer) > current_pos:
                            new_chunks = list(buffer)[current_pos:]
                            for chunk in new_chunks:
                                if isinstance(chunk, dict):
                                    data = json.dumps(chunk)
                                else:
                                    data = json.dumps({"stream_id": stream_id, "content": chunk})
                                yield f"data: {data}\n\n"
                                has_data = True
                            sent_positions[stream_id] = len(buffer)
                
                if task_status['status'] in ['完成', '失败']:
                    break
                
                if not has_data:
                    time.sleep(0.1)

            yield "event: close\ndata: Task finished\n\n"

        except Exception as e:
            logger.error(f"流式传输 AI 输出时出错: {e}", exc_info=True)
            error_data = json.dumps({"stream_id": "error", "content": f"发生内部错误: {e}"})
            yield f"data: {error_data}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
