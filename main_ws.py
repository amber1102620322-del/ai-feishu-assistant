"""
飞书 AI Agent - 长连接模式入口
使用飞书官方 SDK (lark-oapi) 建立 WebSocket 长连接，无需公网域名或 ngrok。
运行命令：uv run python main_ws.py
"""
import asyncio
import json
import os
from dotenv import load_dotenv

import lark_oapi as lark
from lark_oapi.api.im.v1 import *

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 用于消息去重
processed_message_ids: set = set()


async def _handle_message(message_info: P2ImMessageReceiveV1Data) -> None:
    """
    收到飞书消息后的异步处理函数：
    1. 调用 Agent 进行回复
    2. 通过飞书接口发送回复消息
    """
    from core.agent import process_user_message
    from core.feishu import send_feishu_message, add_message_reaction

    msg = message_info.message
    sender = message_info.sender

    message_id = msg.message_id
    chat_id = msg.chat_id
    open_id = sender.sender_id.open_id if sender and sender.sender_id else ""

    # 消息去重
    if message_id in processed_message_ids:
        print(f"[长连接] 重复消息，跳过: {message_id}")
        return
    processed_message_ids.add(message_id)
    if len(processed_message_ids) > 100:
        processed_message_ids.clear()

    if msg.message_type != "text":
        return

    # 解析消息内容
    try:
        content = json.loads(msg.content)
        text = content.get("text", "")
    except Exception:
        text = msg.content or ""

    if not text:
        return

    reply_id = chat_id if chat_id else open_id
    reply_type = "chat_id" if chat_id else "open_id"

    print(f"[长连接] 收到消息: '{text}', chat_id={chat_id}, open_id={open_id}")

    # 先给消息点一个 OK 表情表示已接收
    await add_message_reaction(message_id, "OK")

    # 调用 Agent 处理并回复
    reply = await process_user_message(reply_id, text)
    if reply:
        result = await send_feishu_message(
            receive_id=reply_id,
            receive_id_type=reply_type,
            msg_type="text",
            content=reply
        )
        print(f"[长连接] 发送结果: {result}")


def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    """飞书 SDK 的事件回调（同步包装器）"""
    print(f"[长连接] 收到事件: {data.header.event_type}")
    # 🚨 修正：SDK 已在运行循环中，不能再调用 asyncio.run()。
    # 我们使用当前线程的事件循环来调度异步处理任务。
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(_handle_message(data.event))
    else:
        loop.run_until_complete(_handle_message(data.event))


def main():
    if not APP_ID or not APP_SECRET:
        print("错误：请在 .env 文件中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        return

    print(f"[长连接] 启动飞书 AI Agent，App ID: {APP_ID}")
    print("[长连接] 正在与飞书服务器建立 WebSocket 长连接，请稍候...")

    # 使用官方 SDK 创建带长连接的客户端
    cli = lark.Client.builder() \
        .app_id(APP_ID) \
        .app_secret(APP_SECRET) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()

    # 注册消息事件回调
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .build()

    # 启动 WebSocket 长连接（阻塞运行）
    wsClient = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.DEBUG
    )
    wsClient.start()


if __name__ == "__main__":
    main()
