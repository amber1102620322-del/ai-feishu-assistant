from fastapi import FastAPI, BackgroundTasks, Request
import os
import json
import traceback
from dotenv import load_dotenv

# 注意：不在模块顶部 import 重型库，避免 Vercel 冷启动超时
# 这些 import 全部延迟到具体函数内部进行

load_dotenv()

app = FastAPI(title="Feishu AI Agent", description="基于 LangGraph 构建的飞书智能体")

# 用于消息去重，避免飞书重试导致重复处理
processed_message_ids = set()

async def handle_agent_background(chat_id: str, receive_id_type: str, message: str):
    """
    后台任务：调用 Agent 并发送结果给用户或群组
    """
    # 延迟 import 重型库，避免影响冷启动速度
    from core.feishu import send_feishu_message
    from core.agent import process_user_message
    try:
        print(f"[Agent] 开始处理消息: {message}")
        reply = await process_user_message(chat_id, message)
        print(f"[Agent] 回复内容: {reply[:100] if reply else 'None'}...")
        if reply:
            result = await send_feishu_message(
                receive_id=chat_id,
                receive_id_type=receive_id_type,
                msg_type="text",
                content=reply
            )
            print(f"[飞书] 发送结果: {result}")
    except Exception as e:
        print(f"[Agent] 后台任务出错: {e}")
        traceback.print_exc()

@app.post("/api/feishu/webhook")
async def feishu_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()

    # ⚡ 第一优先级：飞书 Challenge 验证，不依赖任何第三方库，必须在 3 秒内极速返回
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Challenge 通过后，再延迟加载重型依赖库
    from core.feishu import decrypt_msg, add_message_reaction
    print(f"\n{'='*50}")
    print(f"[Webhook] 收到请求: {json.dumps(body, ensure_ascii=False)[:500]}")
        
    # 处理加密情况
    if "encrypt" in body:
        try:
            decrypted_body = decrypt_msg(body["encrypt"])
            print(f"[Webhook] 解密成功: {json.dumps(decrypted_body, ensure_ascii=False)[:500]}")
        except Exception as e:
            print(f"[Webhook] 解密失败: {e}")
            traceback.print_exc()
            return {"msg": "decrypt error"}
    else:
        decrypted_body = body
        print("[Webhook] 无需解密，使用原始数据")

    # 加密模式下的首次 challenge
    if decrypted_body.get("type") == "url_verification":
        print("[Webhook] Challenge 验证（加密模式）")
        return {"challenge": decrypted_body.get("challenge")}

    # 处理消息事件
    header = decrypted_body.get("header", {})
    event = decrypted_body.get("event", {})
    event_type = header.get("event_type")
    print(f"[Webhook] 事件类型: {event_type}")
    
    if event_type == "im.message.receive_v1":
        message_info = event.get("message", {})
        message_id = message_info.get("message_id", "")
        
        # 消息去重
        if message_id in processed_message_ids:
            print(f"[Webhook] 重复消息，跳过: {message_id}")
            return {"msg": "duplicate"}
        processed_message_ids.add(message_id)
        # 只保留最近 100 条消息 ID
        if len(processed_message_ids) > 100:
            processed_message_ids.clear()
        
        msg_type = message_info.get("message_type")
        print(f"[Webhook] 消息类型: {msg_type}, 消息ID: {message_id}")
        
        if msg_type == "text":
            try:
                content_dict = json.loads(message_info.get("content", "{}"))
                text = content_dict.get("text", "")
            except:
                text = message_info.get("content", "")
            
            # 获取发送者信息，优先使用 open_id 进行回复
            sender = event.get("sender", {}).get("sender_id", {})
            open_id = sender.get("open_id", "")
            chat_id = message_info.get("chat_id", "")
            
            print(f"[Webhook] 收到用户消息: '{text}', open_id={open_id}, chat_id={chat_id}")
            
            # 优先使用 chat_id 回复（群聊与单聊都支持）
            reply_id = chat_id if chat_id else open_id
            reply_type = "chat_id" if chat_id else "open_id"
            
            if reply_id and text:
                # 收到请求后立刻回复一个 get 表情
                background_tasks.add_task(add_message_reaction, message_id, "OK")
                background_tasks.add_task(handle_agent_background, reply_id, reply_type, text)
                print(f"[Webhook] 已调度后台任务: reply_id={reply_id}, type={reply_type}")
            else:
                print(f"[Webhook] 跳过: reply_id={reply_id}, text={text}")
    else:
        print(f"[Webhook] 非消息事件，忽略: {event_type}")

    return {"msg": "success"}

@app.get("/api/cron/daily_news")
async def daily_news_cron(key: str, background_tasks: BackgroundTasks):
    """
    Cron Job 触发端点
    """
    cron_key = os.getenv("CRON_SECRET_KEY", "default-secret-key")
    if key != cron_key:
        return {"error": "Unauthorized"}
        
    target_chat_id = os.getenv("TARGET_FEISHU_CHAT_ID", "")
    
    if target_chat_id:
        instruction = "现在是早上9点，请帮我自动获取最新的 AI 新闻和指定的微信公众号文章，排版总结后输出。这是定时推送任务。"
        background_tasks.add_task(handle_agent_background, target_chat_id, "chat_id", instruction)
        return {"status": "Scheduled daily news task"}
    return {"error": "TARGET_FEISHU_CHAT_ID not set"}
