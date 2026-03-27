import hashlib
import base64
import json
import httpx
from Crypto.Cipher import AES
import os
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")

class AESCipher(object):
    def __init__(self, key):
        self.bs = AES.block_size
        self.key = hashlib.sha256(key.encode()).digest()

    def decrypt(self, enc):
        iv = enc[:AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return self._unpad(cipher.decrypt(enc[AES.block_size:]))

    def decrypt_string(self, enc_str):
        enc = base64.b64decode(enc_str)
        dec = self.decrypt(enc)
        return dec.decode("utf-8")

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s) - 1:])]

def decrypt_msg(encrypt_str: str) -> dict:
    if not ENCRYPT_KEY:
        return {}
    cipher = AESCipher(ENCRYPT_KEY)
    decrypted = cipher.decrypt_string(encrypt_str)
    return json.loads(decrypted)

async def get_tenant_access_token() -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        resp_data = resp.json()
        if resp_data.get("code") == 0:
            return resp_data.get("tenant_access_token")
        else:
            print("Failed to get token:", resp_data)
            return ""

async def send_feishu_message(receive_id: str, receive_id_type: str, msg_type: str, content: str):
    """
    发送普通文本消息给飞书用户或群组
    receive_id_type: open_id, user_id, union_id, email, chat_id
    content: 若为 text 类型，直接传字符串，会自动封装为 json string
    """
    token = await get_tenant_access_token()
    if not token:
        return None
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": json.dumps({"text": content}) if msg_type == "text" else content
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        return resp.json()

async def add_message_reaction(message_id: str, emoji_type: str = "GOT_IT"):
    """
    给指定的消息添加表情回复（点赞、Get等）
    """
    token = await get_tenant_access_token()
    if not token:
        return None
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "reaction_type": {
            "emoji_type": emoji_type
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        result = resp.json()
        print(f"[Feishu] 添加表情回复结果: {result}")
        return result

async def create_feishu_doc_from_markdown(title: str, content: str) -> str:
    """
    创建一个新的飞书 Docx 文档并根据 Markdown 语法优化格式写入。
    """
    token = await get_tenant_access_token()
    if not token:
        return "获取 Token 失败，无法创建文档"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 1. 创建文档
    create_url = "https://open.feishu.cn/open-apis/docx/v1/documents"
    create_payload = {"title": title}
    
    async with httpx.AsyncClient() as client:
        print(f"[Feishu API] 正在创建文档, title='{title}'")
        resp = await client.post(create_url, headers=headers, json=create_payload)
        res_data = resp.json()
        if res_data.get("code") != 0:
            print(f"[Feishu API] 创建文档失败: {res_data}")
            return f"创建飞书文档失败（可能需开通 docx:document:create 权限）。错误信息: {res_data.get('msg')}"
            
        doc_data = res_data.get("data", {}).get("document", {})
        document_id = doc_data.get("document_id")
        print(f"[Feishu API] 文档创建成功, document_id='{document_id}'")
        
        # 解析 Markdown 行
        import re
        lines = content.split('\n')
        children = []
        
        def _parse_text_to_elements(text: str):
            """将一行文本中的 **bold** 标记解析为多个 text_run"""
            # 兼容：用户想去掉 *，我们这里解析 ** 为加粗，并过滤掉单独的 *
            parts = re.split(r'(\*\*.*?\*\*)', text)
            elements = []
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    bold_text = part[2:-2]
                    if bold_text:
                        elements.append({"text_run": {"content": bold_text, "text_element_style": {"bold": True}}})
                else:
                    # 去掉单独的 * 符号（通常是模型误生成的）
                    cleaned_part = part.replace("*", "")
                    if cleaned_part:
                        elements.append({"text_run": {"content": cleaned_part}})
            return elements

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            #识别 H1
            if line.startswith("# "):
                block = {"block_type": 3, "heading1": {"elements": _parse_text_to_elements(line[2:])}}
            #识别 H2
            elif line.startswith("## "):
                block = {"block_type": 4, "heading2": {"elements": _parse_text_to_elements(line[3:])}}
            #识别 H3
            elif line.startswith("### "):
                block = {"block_type": 5, "heading3": {"elements": _parse_text_to_elements(line[4:])}}
            #识别 有序列表
            elif re.match(r'^\d+\.\s', line):
                content_part = re.sub(r'^\d+\.\s', '', line)
                block = {"block_type": 13, "ordered": {"elements": _parse_text_to_elements(content_part)}}
            #识别 无序列表 (尽管提示词要求不用，但代码保持兼容)
            elif line.startswith("- ") or line.startswith("* "):
                content_part = line[2:]
                block = {"block_type": 12, "bullet": {"elements": _parse_text_to_elements(content_part)}}
            #识别 分割线
            elif line == "---":
                block = {"block_type": 22, "divider": {}}
            #普通文本
            else:
                block = {
                    "block_type": 2, 
                    "text": {"elements": _parse_text_to_elements(line)}
                }
            children.append(block)

        # 2. 写入内容（添加到根 block）
        add_blocks_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
        
        # 飞书 API 限制一次性写入数量，这里分批写入或限制总量
        # 简单处理：只取前 50 个 block 避免超时
        block_payload = {"children": children[:50]}
        
        print(f"[Feishu API] 正在写入内容, blocks={len(children)}")
        block_resp = await client.post(add_blocks_url, headers=headers, json=block_payload)
        block_res_data = block_resp.json()
        if block_res_data.get("code") != 0:
            print(f"[Feishu API] 写入文档内容失败: {block_res_data}")
            return f"文档已创建但内容写入失败：{block_res_data.get('msg')}。链接: https://feishu.cn/docx/{document_id}"
            
        print(f"[Feishu API] 文档内容写入成功")
        return f"已自动为您生成飞书文档：https://feishu.cn/docx/{document_id}"


async def upload_file_to_drive(file_path: str, file_name: str) -> str:
    """
    将本地文件上传到飞书云文档 (Drive)，返回文件下载/预览链接。
    """
    token = await get_tenant_access_token()
    if not token:
        return "获取 Token 失败，无法上传文件"
        
    file_size = os.path.getsize(file_path)
    url = "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    # 飞书 upload_all 接口需要 multipart/form-data
    files = {
        "file": (file_name, open(file_path, "rb"), "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    }
    data = {
        "file_name": file_name,
        "parent_type": "explorer",
        "parent_node": "", # 留空代表根目录
        "size": str(file_size)
    }
    
    async with httpx.AsyncClient() as client:
        print(f"[Feishu API] 正在上传文件: {file_name}, size={file_size}")
        # 注意：httpx 处理 files 时会自动设置 boundary
        resp = await client.post(url, headers=headers, data=data, files=files)
        res_data = resp.json()
        
        if res_data.get("code") != 0:
            print(f"[Feishu API] 文件上传失败: {res_data}")
            return f"上传失败：{res_data.get('msg')}"
            
        file_token = res_data.get("data", {}).get("file_token")
        print(f"[Feishu API] 文件上传成功, token='{file_token}'")
        # 飞书云文档链接格式
        return f"https://feishu.cn/file/{file_token}"

