import re
import os
import asyncio
import random
from dataclasses import dataclass
from telethon import TelegramClient, events
from datetime import datetime, timedelta


# Playwright 
from playwright.async_api import async_playwright, Browser, Page

playwright_browser: Browser = None
playwright_page: Page = None


# === Konfigurasi Telethon ===
from dotenv import load_dotenv
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
SESSION_NAME = os.getenv("SESSION_NAME", "anon")
SITE = os.getenv("SITE")
CHANNEL = os.getenv("CHANNEL")

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# === Struktur Data TradeSignal ===
@dataclass
class TradeSignal:
    pair: str
    direction: str
    time: str  # Waktu dalam GMT+7
    index: int  # 0 = utama, 1 = kompensasi 1, 2 = kompensasi 2

signal_queue = []
current_trade = None
is_trading = False
base_investment = 14000

# === Konversi zona waktu GMT-3 → GMT+7 ===
def convert_to_gmt7(timestr):
    dt = datetime.strptime(timestr, "%H:%M")
    dt += timedelta(hours=10)  # GMT+7 - GMT-3 = +10 jam
    return dt.strftime("%H:%M")

# === Parsing sinyal dari pesan ===
def parse_trade_signal(text: str):
    signals = []

    main_match = re.search(r"([A-Z]{3}/[A-Z]{3});(\d{2}:\d{2});(NAIK|TURUN)", text)
    if not main_match:
        print("❌ Format sinyal utama tidak dikenali.")
        return []

    pair = main_match.group(1)
    base_time = convert_to_gmt7(main_match.group(2))
    direction = main_match.group(3).upper()
    signals.append(TradeSignal(pair, direction, base_time, 0))

    komp1_match = re.search(r"KOMPENSASI PERTAMA.*?(\d{2}:\d{2})", text)
    if komp1_match:
        komp1_time = convert_to_gmt7(komp1_match.group(1))
        signals.append(TradeSignal(pair, direction, komp1_time, 1))

    komp2_match = re.search(r"KOMPENSASI KEDUA.*?(\d{2}:\d{2})", text)
    if komp2_match:
        komp2_time = convert_to_gmt7(komp2_match.group(1))
        signals.append(TradeSignal(pair, direction, komp2_time, 2))

    return signals

async def detect_toast():
    global playwright_page
    try:
        while True:
            toasts = await playwright_page.query_selector_all(".trades-notifications-item")

            for toast in toasts:
                name_el = await toast.query_selector(".trades-notifications-item__name")
                result_el = await toast.query_selector(".trades-notifications-item__total")

                if not name_el or not result_el:
                    continue

                result = (await result_el.text_content() or "").strip()

                if "+" in result:
                    return "MENANG"
                elif "0" in result:
                    return "KALAH"

            await asyncio.sleep(1)

    except Exception as e:
        print(f"[TOAST] Error saat memantau notifikasi: {e}")
        return "ERROR"

async def execute_trade(signal: TradeSignal):
    global is_trading, signal_queue, playwright_page, base_investment
    is_trading = True
    print(f"\n🚀 EKSEKUSI: {signal.pair} arah {signal.direction} [index={signal.index}] pada {signal.time}")
    print("⏳ Menunggu hasil trade...")

    # Simulasi atau eksekusi tombol
    try:
        if signal.direction == "NAIK":
            await playwright_page.click("button.call-btn")
        else:
            await playwright_page.click("button.put-btn")
        print(f"🖱️ Tombol {signal.direction} diklik di halaman broker.")
    except Exception as e:
        print(f"❌ Gagal klik tombol: {e}")


    result = await detect_toast()
    print(f"🎯 HASIL: {result}")

    if result == "MENANG":
        print("✅ Menghapus semua kompensasi untuk sinyal ini...")
        signal_queue = [s for s in signal_queue if not (s.pair == signal.pair and s.index in [1, 2])]
        base_investment = 14000
    elif result == "KALAH":
        print("⚠️ Lanjut ke kompensasi berikutnya jika ada...")
        base_investment *= 2
        await set_investment(str(base_investment))

    is_trading = False


# === Scheduler utama ===
# async def scheduler_loop():
#     while True:
#         await asyncio.sleep(1)
#         now = datetime.now().strftime("%H:%M")

#         if not is_trading and signal_queue:
#             next_signal = signal_queue[0]
#             if next_signal.time == now:
#                 signal_queue.pop(0)
#                 await execute_trade(next_signal)


async def scheduler_loop():
    while True:
        await asyncio.sleep(1)
        now = datetime.now().replace(microsecond=0)

        if not is_trading and signal_queue:
            next_signal = signal_queue[0]

            # Parse waktu sinyal, misal "19:05" jadi datetime hari ini jam 19:05:00
            target_time = datetime.strptime(next_signal.time, "%H:%M").time()
            target_datetime = now.replace(hour=target_time.hour, minute=target_time.minute, second=0)

            # Kurangi 1 detik dari waktu target
            execute_at = target_datetime - timedelta(seconds=1)

            if now == execute_at:
                signal_queue.pop(0)
                await execute_trade(next_signal)

async def set_investment(investment):
    input_elem = await playwright_page.query_selector(
    '.section-deal__investment.section-deal__input-black .input-control-wrapper.section-deal--black input.input-control__input[type="text"]'
)
    await input_elem.fill(investment)

async def klik_pair(first_signal: TradeSignal):
    global playwright_page
    pair = first_signal.pair

    try:
        await playwright_page.click(".asset-select__button")
        await asyncio.sleep(1)

        items = await playwright_page.query_selector_all(".assets-table__item")
        for item in items:
            span = await item.query_selector("span")
            if span:
                text = (await span.inner_text()).strip()
                if pair in text:
                    await item.click()
                    print(f"🎯 Pair {pair} dipilih.")
                    break
        await set_investment(str(base_investment))
    except Exception as e:
        print(f"⛔ Gagal memilih pair {pair}: {e}")

# === Handler pesan masuk ===
@client.on(events.NewMessage)
async def handler(event):
    chat = await event.get_chat()
    if hasattr(chat, 'title') and chat.title == CHANNEL:
        message = event.message.message
        print(f"\n📩 Pesan baru diterima:\n{message}\n")

        signals = parse_trade_signal(message)
        filtered = []

        for s in signals:
            if s.index == 0:
                if any(sig.index == 2 and sig.time == s.time and sig.pair == s.pair for sig in signal_queue):
                    print(f"⏩ Melewati sinyal utama {s.time} karena sudah ada kompensasi.")
                    continue
            filtered.append(s)

        signal_queue.extend(filtered)
        print(f"📥 Queue sekarang: {[f'{s.pair}-{s.time}-idx{s.index}' for s in signal_queue]}")
        await klik_pair(filtered[0])

async def print_time_loop():
    while True:
        print(f"[⏰ {datetime.now().strftime('%H:%M:%S')}] Menunggu sinyal atau eksekusi...")
        await asyncio.sleep(1)

async def init_browser():
    global playwright_browser, playwright_page
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(storage_state="state.json")
    page = await context.new_page()
    await page.goto(SITE)
    print("🌐 Playwright siap, halaman broker terbuka.")
    playwright_browser = browser
    playwright_page = page


# === Jalankan bot dan scheduler ===
async def main():
    print("🤖 Bot siap menerima sinyal...")
    await client.start()
    await init_browser()
    await asyncio.gather(
        client.run_until_disconnected(), 
        scheduler_loop(), 
        print_time_loop())

if __name__ == "__main__":
    asyncio.run(main())
