# Mening Hisobchim

Telegram bot: daromad, xarajat, balans, oylik hisobot, PDF va diagrammalar.

## Server sozlamasi

- Python: 3.12
- Install/build command: `pip install -r requirements.txt`
- Start command: `python -u bot.py`
- Environment variable: `BOT_TOKEN` = BotFather bergan yangi bot tokeni

**Tokenni hech qachon kodga yoki GitHub fayliga yozmang.**
`hisobchi.db` SQLite bazasi bot ishlagan katalogda yaratiladi. Server tanlashda
doimiy disk (persistent storage) borligini tekshiring; bo'lmasa server qayta
ishga tushganda moliyaviy ma'lumotlar yo'qolishi mumkin.
