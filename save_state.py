# save_state.py
import asyncio
from playwright.async_api import async_playwright

async def save_state():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://market-qtx.trade/en/demo-trade")

        print("➡️ Silakan login secara manual di jendela browser...")
        input("Tekan Enter setelah selesai login...")

        await context.storage_state(path="state.json")
        print("✅ Session disimpan ke state.json")

        await browser.close()

asyncio.run(save_state())
