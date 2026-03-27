import os
import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool
from dotenv import load_dotenv

load_dotenv()

# 懒加载全局变量，避免在模块导入时就初始化重型对象导致 Vercel 冷启动超时
_llm = None
_agent_executor = None

# ========== 自定义搜索工具（不依赖 ddgs 包） ==========
@tool
def web_search(query: str) -> str:
    """在互联网上搜索最新的信息。当你需要查找新闻、事实或任何最新信息时使用此工具。"""
    try:
        # 使用 DuckDuckGo 的 HTML 接口进行轻量搜索
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        resp = httpx.post(url, data={"q": query, "kl": "cn-zh"}, headers=headers, timeout=15)
        # 从 HTML 中提取前几条搜索结果的标题和摘要
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for i, result in enumerate(soup.select(".result__body")[:5]):
            title_el = result.select_one(".result__title")
            snippet_el = result.select_one(".result__snippet")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title:
                results.append(f"{i+1}. {title}\n   {snippet}")
        if results:
            return "\n\n".join(results)
        return "未找到相关搜索结果，请尝试修改关键词。"
    except Exception as e:
        return f"搜索时出错: {str(e)}"

@tool
def fetch_wechat_article(query: str) -> str:
    """获取指定微信公众号的最新文章。当用户明确要求获取公众号新闻时使用此工具。"""
    # 此处可接入 RSSHub 或其他微信文章 API
    return f"模拟获取到的微信公众号文章列表（根据关键词：{query}）：\n1. 【AI前线】DeepSeek V3 官方发布\n2. 【量子位】全新 Agent 架构解析"

@tool
def list_pm_skills() -> str:
    """列出所有可用的 Product Manager 专项技能（Skills）名称。当用户需要特定场景的指导（如写PRD、竞品分析、需求排期等）时，先调用此工具查找合适的技能名称。"""
    skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pm_skills")
    if not os.path.exists(skills_dir):
        return "本地未安装 pm_skills。"
    skills = [d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))]
    return f"可用的 PM Skills 共 {len(skills)} 个:\n" + ", ".join(skills)

@tool
def read_pm_skill(skill_name: str) -> str:
    """
    读取指定的 Product Manager 技能详情（Markdown 格式的知识框架和工作流指令）。
    调用此工具后，请严格阅读并遵循返回的文件内容来指导你的思考和回复。
    """
    skill_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pm_skills", skill_name, "SKILL.md")
    if os.path.exists(skill_file):
        with open(skill_file, "r", encoding="utf-8") as f:
            return f.read()
    return f"找不到指定的技能: {skill_name}"

@tool
async def create_feishu_doc(title: str, content: str) -> str:
    """
    当你自动分析语义发现用户有【写作需求】或输出内容极长（如 PRD、总结、报告等）时，
    你必须调用此工具，把你的回答和长文本内容直接写成一个单独的飞书文档，
    然后只需要把返回的“飞书文档链接”发给用户即可，切勿在对话框内霸屏长篇大论。
    """
    from core.feishu import create_feishu_doc_from_markdown
    return await create_feishu_doc_from_markdown(title, content)

tools = [web_search, fetch_wechat_article, list_pm_skills, read_pm_skill, create_feishu_doc]

system_prompt = """你是一位专业、高效、务实的互联网产品经理智能助手，服务对象是资深AI产品经理。
你的职责是帮助用户提升产品工作效率，减少重复劳动，强化思考质量。

规则：
1. 回答简洁、结构化、可执行，不空话、不套话。
2. 输出优先使用列表、要点、序号，避免大段文字。
3. 涉及需求、功能、方案时，必须包含：场景、目标、功能、验收、风险。
4. 涉及数据时，给出结论+原因+建议，三步式表达。
5. 涉及沟通时，提供可直接复制发送的话术。
6. 不替用户做最终决策，只提供方案、选项、优先级。
7. 语气专业干练，不情绪化，不冗余。

你具备以下能力：
- 需求梳理与结构化
- PRD/功能逻辑撰写
- 流程与交互梳理
- 数据指标分析与异常解读
- 项目风险识别
- 会议纪要与待办提炼
- 竞品与行业分析
- 汇报/话术/复盘优化
- 日程与待办管理

用户会通过飞书与你对话，你需要随时准备：
- 接收碎片化信息并整理
- 按指令生成结构化文档
- 定时推送简报
- 回答产品相关专业问题

【动态功能指南与强制规范】
你现在已装备了 "Product-Manager-Skills" 技能库，包含多种顶级产品经理业务框架（例如 user-story, prd-development, prioritization-advisor 等）。
当你识别到一项具体的 PM 任务时：
1. 请先调用 `list_pm_skills` 检索相关的专业技能模板。
2. 再调用 `read_pm_skill` 读取所需技能的具体指导和框架。
3. 严格遵循该技能文档中的「理念、框架和步骤」，结合用户的实际上下文思考解决方案。

【写作与输出要求】
当你自动分析语义，发现当前任务是**「写作需求」**（例如写PRD、详细流程梳理、报告总结）时，
你**必须**调用 `create_feishu_doc(title, content)` 工具把最终内容写入一篇新的飞书文档，
生成完毕后，你在这个聊天窗口里只要简短地回复文档的链接即可，不要在对话框直接大段输出文本。"""

# 内存记忆，用于多轮对话
memory = MemorySaver()

def _get_agent():
    """懒加载 Agent：只在第一次真正需要时才初始化 LLM 和 ReAct Agent"""
    global _llm, _agent_executor
    if _agent_executor is None:
        _llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com"
        )
        _agent_executor = create_react_agent(
            _llm,
            tools,
            prompt=system_prompt,
            checkpointer=memory
        )
    return _agent_executor

async def process_user_message(user_id: str, message: str) -> str:
    """
    运行 Agent 处理用户消息
    """
    try:
        inputs = {"messages": [HumanMessage(content=message)]}
        config = {"configurable": {"thread_id": user_id}}

        # 懒加载获取 Agent
        agent = _get_agent()
        response = await agent.ainvoke(inputs, config=config)
        return response["messages"][-1].content
    except Exception as e:
        print(f"Agent Error: {e}")
        return "不好意思，处理您的请求时出错了，请稍后再试。"
