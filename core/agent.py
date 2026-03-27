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
    print(f"[Agent Tool] 触发创建文档工具: title='{title}'")
    from core.feishu import create_feishu_doc_from_markdown
    return await create_feishu_doc_from_markdown(title, content)

@tool
async def create_feishu_ppt(title: str, slides_json: str) -> str:
    """
    当用户显式要求“做 PPT”、“生成幻灯片”、“制作汇报演示”时调用此工具。
    slides_json: 必须是一个 JSON 格式的数组字符串，每个对象包含 title 和 content。
    请直接输出纯 JSON 字符串，不要带 ```json 标记。
    """
    import json
    import re
    print(f"[Agent Tool] 触发 PPT 制作工具: title='{title}'")
    
    data = None
    try:
        # 1. 尝试直接解析
        data = json.loads(slides_json)
    except:
        try:
            # 2. 尝试剥离 Markdown 代码块
            cleaned = re.sub(r'```json\s*|\s*```', '', slides_json).strip()
            data = json.loads(cleaned)
        except Exception as e:
            print(f"[Agent Tool] 解析失败: {e}")

    if not data:
        return "PPT 内容解析失败，请检查工具调用参数是否为标准的 JSON 列表。"
    
    from core.ppt_generator import create_structured_pptx
    from core.feishu import upload_file_to_drive
    
    # 清理文件名非法字符
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
    file_name = f"{safe_title}.pptx"
    file_path = f"/tmp/{file_name}"
    
    try:
        create_structured_pptx(title, data, file_path)
        link = await upload_file_to_drive(file_path, file_name)
        return f"PPT 已为您精心制作完成！飞书云文档链接如下：{link}"
    except Exception as e:
        print(f"[Agent Tool] PPT 生成或上传失败: {e}")
        return f"PPT 制作过程中出现错误: {str(e)}"

tools = [web_search, fetch_wechat_article, list_pm_skills, read_pm_skill, create_feishu_doc, create_feishu_ppt]

# 核心系统提示词
# 获取 skills 目录中的 PM 技能列表（作为背景知识）
skills_context = ""
pm_skills_dir = "/Users/amber/Amber 助手/feishu-agent/pm_skills"
if os.path.exists(pm_skills_dir):
    skill_files = os.listdir(pm_skills_dir)
    skills_context = "\n".join([f"- {f.replace('.md', '')}" for f in skill_files if f.endswith(".md")])

system_prompt = f"""你是一个顶级的、极具效率的产品经理/业务架构师 (PM/Architect)。
你现在的宿主平台是飞书。你可以通过各种工具来为用户提供专业服务。

【核心人设】
1. 你的回答必须专业、严谨且富有逻辑。
2. 你熟练掌握以下专业产品经理技能：
{skills_context}
3. 严格遵循以上框架和步骤进行思考。

【写作与输出要求】
1. **去除冗余符号**：在对话框回复和文档内容中，**禁用**使用 `*` 符号作为列表标记（使用 1. 2. 3. 代替）。
2. **文档与格式**：
   - 发现写作需求或长文本时，调用 `create_feishu_doc`。
   - 必须使用有序列表 (1. 2. 3. 2) 进行自动排序。
   - 允许且建议使用 Markdown 加粗 (`**内容**`) 来增强重点，但内容本身不要带有多余的 `*`。
3. **PPT 制作**：
   - 当用户要求做 PPT 时，你必须调用 `create_feishu_ppt` 工具。
   - 你需要先构建一个专业的幻灯片结构（数组），包含各页标题和精炼的内容，然后作为 JSON 传给工具。

对话窗口内请保持回复简洁，文档/PPT 内容请保持内容详细专业。"""

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
        reply = response["messages"][-1].content
        
        # 根据用户要求，彻底去掉回复中所有的 * 符号
        if reply:
            reply = reply.replace("*", "")
            
        return reply
    except Exception as e:
        print(f"Agent Error: {e}")
        return "不好意思，处理您的请求时出错了，请稍后再试。"
