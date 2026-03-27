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
    创建一个新的飞书 Docx 文档并写入内容，返回文档的 URL。
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
        resp = await client.post(create_url, headers=headers, json=create_payload)
        res_data = resp.json()
        if res_data.get("code") != 0:
            print("创建文档失败:", res_data)
            return f"创建飞书文档失败（可能需开通 docx:document:create 权限）。错误信息: {res_data.get('msg')}"
            
        doc_data = res_data.get("data", {}).get("document", {})
        document_id = doc_data.get("document_id")
        
        # 2. 写入内容（添加到根 block，即 document_id 作为 parent block）
        add_blocks_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
        
        block_payload = {
            "children": [
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": content
                                }
                            }
                        ]
                    }
                }
            ]
        }
        
        block_resp = await client.post(add_blocks_url, headers=headers, json=block_payload)
        block_res_data = block_resp.json()
        if block_res_data.get("code") != 0:
            print("写入文档内容失败:", block_res_data)
            return f"文档已创建但内容写入失败：{block_res_data.get('msg')}。链接: https://feishu.cn/docx/{document_id}"
            
        return f"已自动为您生成飞书文档：https://feishu.cn/docx/{document_id}"

