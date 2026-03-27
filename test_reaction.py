import asyncio
from core.feishu import add_message_reaction

async def test():
    res = await add_message_reaction("om_x100b53613436b4a0c36ce424121bf55", "GOT_IT")
    print("GOT_IT:", res)
    res2 = await add_message_reaction("om_x100b53613436b4a0c36ce424121bf55", "OK")
    print("OK:", res2)
    res3 = await add_message_reaction("om_x100b53613436b4a0c36ce424121bf55", "DONE")
    print("DONE:", res3)

if __name__ == "__main__":
    asyncio.run(test())
