# 导入必要的库
import os
import time
import base64  # 用于将图片编码为 Base64 字符串
from openai import OpenAI  # OpenAI 官方库
from dotenv import load_dotenv  # 用于从 .env 文件加载环境变量
from app.utils.logger import logger

# 加载 .env 文件中的环境变量
load_dotenv()

# --- API 客户端初始化 ---
# 从环境变量中获取 API 密钥和基础 URL
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE")

# 确保关键的环境变量已设置
if not api_key:
    raise ValueError("未在 .env 文件中找到 OPENAI_API_KEY")
if not api_base:
    raise ValueError("未在 .env 文件中找到 OPENAI_API_BASE")

# 创建 OpenAI 客户端实例
client = OpenAI(
    api_key=api_key,
    base_url=api_base,
)

def encode_image(image_data):
    """将图片数据（路径或字节）编码为 Base64 字符串。"""
    if isinstance(image_data, str):
        # 如果是文件路径，则读取文件
        with open(image_data, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    elif isinstance(image_data, bytes):
        # 如果已经是字节，则直接编码
        return base64.b64encode(image_data).decode('utf-8')
    else:
        raise TypeError("输入必须是文件路径（str）或图片字节（bytes）")

def analyze_image(image_data, retry_delay=5):
    """
    使用视觉模型以流式方式分析单个漫画图片，并返回其内容的文字描述。
    增加了无限重试逻辑以提高健壮性。
    
    Args:
        image_data (str or bytes): 本地图片文件的路径或图片的二进制数据。
        retry_delay (int): 重试前的延迟秒数。
        
    Yields:
        str: AI 模型生成的图片描述的文本块。
    """
    # 将图片编码为 Base64
    base64_image = encode_image(image_data)
    # 从环境变量获取视觉模型名称，如果未设置则使用默认值
    vision_model = os.getenv("VISION_MODEL", "gpt-4-vision-preview")
    image_identifier = image_data if isinstance(image_data, str) else "提供的图片字节"
    attempt = 0

    while True:
        try:
            # 调用 OpenAI 的 chat completions API，并启用流式响应
            stream = client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # 提示词，指导模型生成详细的描述
                            {"type": "text", "text": "请详细描述这幅漫画图片的关键的内容、风格、人物、动作和对话。（精炼，但是内容全面）"},
                            # 图片数据
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            },
                        ],
                    }
                ],
                max_tokens=2048,  # 限制生成描述的最大长度
                stream=True,      # 启用流式响应
            )
            # 遍历流式响应的每个块
            for chunk in stream:
                # 提取并返回内容部分
                content = chunk.choices[0].delta.content
                if content:
                    yield content
            # 如果成功处理完流，则跳出重试循环
            return
        except Exception as e:
            # 如果 API 调用失败，记录错误并无限重试
            attempt += 1
            error_message = f"分析 {image_identifier} 时出错 (尝试 #{attempt}): {e}"
            logger.warning(error_message)
            logger.info(f"{retry_delay}秒后重试...")
            time.sleep(retry_delay)
