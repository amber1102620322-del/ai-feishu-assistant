# 飞书 AI Agent (小晨助手)

基于 LangGraph + DeepSeek 构建的飞书智能对话机器人。

## 项目结构

```
feishu-agent/
├── api/
│   └── index.py          # FastAPI 主入口 (Webhook + Cron 端点)
├── core/
│   ├── agent.py           # Agent 大脑 (LangGraph ReAct + 自定义 Tools)
│   └── feishu.py          # 飞书 SDK (消息解密、Token获取、消息发送)
├── .env                   # 环境变量 (不提交到 Git)
├── .env.example           # 环境变量模板
├── pyproject.toml         # 项目依赖配置
└── README.md
```

## 快速启动

```bash
# 1. 安装依赖
uv sync

# 2. 复制并编辑环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 3. 启动服务
uv run uvicorn api.index:app --host 0.0.0.0 --port 8001

# 4. 内网穿透 (另一个终端)
ngrok http 8001
```

## 环境变量说明

| 变量名 | 说明 |
|---|---|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `FEISHU_ENCRYPT_KEY` | 飞书事件加密密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `CRON_SECRET_KEY` | 定时任务鉴权密钥 |
| `TARGET_FEISHU_CHAT_ID` | 定时推送的目标群聊/用户 ID |
