import asyncio
import httpx
from core.feishu import get_tenant_access_token

async def test_create_doc():
    token = await get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/docx/v1/documents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"title": "测试文档"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
        print("Create Doc Response:", resp.json())

if __name__ == "__main__":
    asyncio.run(test_create_doc())
