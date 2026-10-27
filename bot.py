import os
import sqlite3
from datetime import datetime, date
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from telegram import (
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Tokenni kodga yozmang. BOT_TOKEN muhit o'zgaruvchisidan olinadi.
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. Avval BOT_TOKEN muhit o'zgaruvchisiga token kiriting."
    )

DB_NAME = "hisobchi.db"
AMOUNT, INCOME_TYPE, EXPENSE_TYPE = range(3)

MENU = [
    ["💰 Daromad qo'shish", "💸 Xarajat qo'shish"],
    ["🏦 Umumiy balans", "📊 Bugungi hisobot"],
    ["📅 Oylik hisobot", "📄 Oylik PDF yuklab olish"],
    ["📈 Diagrammali hisobot", "🗑️ Operatsiyani o'chirish"],
    ["❌ Bekor qilish"],
]


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                amount INTEGER NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)


def add_transaction(user_id, kind, category, amount, note=""):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO transactions
            (user_id, kind, category, amount, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            kind,
            category,
            amount,
            note,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ))


def get_transactions(user_id, start=None):
    query = """
        SELECT kind, category, amount, created_at
        FROM transactions
        WHERE user_id = ?
    """
    params = [user_id]
    if start:
        query += " AND created_at >= ?"
        params.append(start)
    query += " ORDER BY created_at"
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(query, params).fetchall()


def get_recent_transactions(user_id, limit=10):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("""
            SELECT id, kind, category, amount, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()


def delete_transaction(user_id, transaction_id):
    # Faqat aynan shu foydalanuvchiga tegishli yozuv o'chiriladi.
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, user_id),
        )
        return cur.rowcount > 0


def format_money(amount):
    return f"{amount:,}".replace(",", " ") + " so'm"


def totals(rows):
    income = sum(row[2] for row in rows if row[0] == "income")
    expense = sum(row[2] for row in rows if row[0] == "expense")
    return income, expense


def current_month_rows(user_id):
    month = datetime.now().astimezone().strftime("%Y-%m")
    rows = [r for r in get_transactions(user_id) if r[3].startswith(month)]
    return month, rows


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(MENU, resize_keyboard=True)
    await update.message.reply_text(
        "Assalomu alaykum! 💰\n"
        "*Mening Hisobchim* botiga xush kelibsiz.\n\n"
        "Daromad va xarajatlaringizni kiriting — bot balans va hisobotlarni hisoblaydi.",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def begin_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["kind"] = "income"
    await update.message.reply_text("💰 Qancha daromad oldingiz?\nMasalan: 2000000")
    return AMOUNT


async def begin_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["kind"] = "expense"
    await update.message.reply_text("💸 Qancha xarajat qildingiz?\nMasalan: 50000")
    return AMOUNT


async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(" ", "").replace(",", "").replace("_", "")
    if not raw.isdigit() or int(raw) <= 0:
        await update.message.reply_text("Summani musbat butun son bilan kiriting. Masalan: 2000000")
        return AMOUNT

    context.user_data["amount"] = int(raw)
    if context.user_data.get("kind") == "income":
        await update.message.reply_text(
            "Daromad turini yozing.\nMasalan: Oylik, qo'shimcha dars, sovg'a."
        )
        return INCOME_TYPE

    await update.message.reply_text(
        "Xarajat turini yozing.\nMasalan: Oziq-ovqat, transport, bolalar."
    )
    return EXPENSE_TYPE


async def save_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text.strip()
    if category in {"❌ Bekor qilish", "💰 Daromad qo'shish", "💸 Xarajat qo'shish"}:
        await update.message.reply_text("Daromad turini matn bilan kiriting.")
        return INCOME_TYPE

    amount = context.user_data["amount"]
    add_transaction(update.effective_user.id, "income", category, amount)
    await update.message.reply_text(
        f"✅ Daromad saqlandi!\nTuri: {category}\nSumma: {format_money(amount)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def save_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text.strip()
    if category in {"❌ Bekor qilish", "💰 Daromad qo'shish", "💸 Xarajat qo'shish"}:
        await update.message.reply_text("Xarajat turini matn bilan kiriting.")
        return EXPENSE_TYPE

    amount = context.user_data["amount"]
    add_transaction(update.effective_user.id, "expense", category, amount)
    await update.message.reply_text(
        f"✅ Xarajat saqlandi!\nTuri: {category}\nSumma: {format_money(amount)}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_transactions(update.effective_user.id)
    income, expense = totals(rows)
    await update.message.reply_text(
        "🏦 UMUMIY BALANS\n\n"
        f"💰 Jami daromad: {format_money(income)}\n"
        f"💸 Jami xarajat: {format_money(expense)}\n"
        "━━━━━━━━━━━━\n"
        f"💵 Qolgan pul: {format_money(income - expense)}"
    )


async def today_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    rows = [r for r in get_transactions(update.effective_user.id) if r[3][:10] == today]
    income, expense = totals(rows)
    await update.message.reply_text(
        f"📊 BUGUNGI HISOBOT ({today})\n\n"
        f"💰 Daromad: {format_money(income)}\n"
        f"💸 Xarajat: {format_money(expense)}\n"
        f"💵 Kunlik farq: {format_money(income - expense)}"
    )


async def month_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month, rows = current_month_rows(update.effective_user.id)
    income, expense = totals(rows)
    lines = [
        f"📅 OYLIK HISOBOT — {month}",
        "",
        f"💰 Daromad: {format_money(income)}",
        f"💸 Xarajat: {format_money(expense)}",
        f"💵 Qolgan pul: {format_money(income - expense)}",
        "",
        "🧾 OY DAVOMIDAGI OPERATSIYALAR:",
    ]
    if not rows:
        lines.append("Bu oy uchun hali ma'lumot kiritilmagan.")
    else:
        for kind, category, amount, created_at in rows[-15:]:
            mark = "➕" if kind == "income" else "➖"
            day = created_at[8:10] + "." + created_at[5:7]
            lines.append(f"{day} {mark} {category}: {format_money(amount)}")
        if len(rows) > 15:
            lines.append(f"... jami {len(rows)} ta operatsiya. To'liq ro'yxat PDF faylda.")

    await update.message.reply_text("\n".join(lines))


def build_month_pdf(user_id):
    month, rows = current_month_rows(user_id)
    income, expense = totals(rows)
    buffer = BytesIO()

    # DejaVu Sans o'zbekcha belgilarni qo'llab-quvvatlaydi.
    font_path = font_manager.findfont("DejaVu Sans")
    pdfmetrics.registerFont(TTFont("DejaVu", font_path))

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=17 * mm, leftMargin=17 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Mening Hisobchim - {month}",
        author="Mening Hisobchim",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "UzTitle", parent=styles["Title"], fontName="DejaVu",
        fontSize=17, leading=22, alignment=TA_CENTER, textColor=colors.HexColor("#17365D")
    )
    normal_style = ParagraphStyle(
        "UzNormal", parent=styles["Normal"], fontName="DejaVu", fontSize=9, leading=13
    )
    small_style = ParagraphStyle(
        "UzSmall", parent=normal_style, fontSize=8, leading=10
    )

    story = [
        Paragraph("MENING HISOBCHIM", title_style),
        Paragraph(f"Oylik moliyaviy hisobot: {month}", ParagraphStyle(
            "SubTitle", parent=normal_style, alignment=TA_CENTER, fontSize=11
        )),
        Spacer(1, 7 * mm),
    ]
    summary_data = [
        ["Ko'rsatkich", "Summa"],
        ["Jami daromad", format_money(income)],
        ["Jami xarajat", format_money(expense)],
        ["Qolgan pul", format_money(income - expense)],
        ["Operatsiyalar soni", str(len(rows))],
    ]
    summary_table = Table(summary_data, colWidths=[80 * mm, 75 * mm], repeatRows=1)
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C9D6")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F5F8FA")),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary_table, Spacer(1, 8 * mm), Paragraph("Operatsiyalar tafsiloti", styles["Heading2"])])

    table_data = [["Sana", "Turi", "Kategoriya", "Summa"]]
    for kind, category, amount, created_at in rows:
        date_text = created_at[8:10] + "." + created_at[5:7] + "." + created_at[:4]
        kind_text = "Daromad" if kind == "income" else "Xarajat"
        table_data.append([
            Paragraph(date_text, small_style),
            Paragraph(kind_text, small_style),
            Paragraph(str(category).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), small_style),
            Paragraph(format_money(amount), small_style),
        ])
    if not rows:
        table_data.append(["—", "—", "Bu oy uchun ma'lumot yo'q", "—"])

    detail_table = Table(table_data, colWidths=[24 * mm, 28 * mm, 67 * mm, 43 * mm], repeatRows=1)
    detail_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F75B5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F8")]),
    ]))
    story.extend([detail_table, Spacer(1, 5 * mm), Paragraph(
        f"Hisobot yaratilgan vaqt: {datetime.now().astimezone().strftime('%d.%m.%Y %H:%M')}", small_style
    )])
    doc.build(story)
    buffer.seek(0)
    return buffer, month


async def month_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pdf_buffer, month = build_month_pdf(update.effective_user.id)
    await update.message.reply_document(
        document=pdf_buffer,
        filename=f"oylik_hisobot_{month}.pdf",
        caption=f"📄 {month} oyi uchun oylik hisobot."
    )


async def chart_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    month, rows = current_month_rows(user_id)
    income, expense = totals(rows)

    if not rows:
        await update.message.reply_text(
            "📈 Joriy oy uchun ma'lumot topilmadi. Avval daromad yoki xarajat kiriting."
        )
        return

    expense_categories = {}
    for kind, category, amount, created_at in rows:
        if kind == "expense":
            expense_categories[category] = expense_categories.get(category, 0) + amount

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle(f"Mening Hisobchim — {month}", fontsize=15, fontweight="bold")
    axes[0].bar(["Daromad", "Xarajat"], [income, expense])
    axes[0].set_title("Daromad va xarajat")
    axes[0].set_ylabel("So'm")
    axes[0].ticklabel_format(axis="y", style="plain")
    axes[0].grid(axis="y", alpha=0.25)

    if expense_categories:
        sorted_items = sorted(expense_categories.items(), key=lambda x: x[1], reverse=True)[:7]
        axes[1].pie([x[1] for x in sorted_items], labels=[x[0] for x in sorted_items], autopct="%1.0f%%", startangle=90)
        axes[1].set_title("Xarajatlar toifalar bo'yicha")
    else:
        axes[1].text(0.5, 0.5, "Hozircha xarajat yo'q", ha="center", va="center")
        axes[1].set_title("Xarajatlar toifalar bo'yicha")
        axes[1].axis("off")

    fig.tight_layout(rect=[0, 0, 1, 0.92])
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    caption = (
        f"📈 OYLIK DIAGRAMMALI HISOBOT — {month}\n\n"
        f"💰 Daromad: {format_money(income)}\n"
        f"💸 Xarajat: {format_money(expense)}\n"
        f"💵 Balans: {format_money(income - expense)}"
    )
    await update.message.reply_photo(photo=image_buffer, caption=caption)


async def delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_recent_transactions(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("O'chirish uchun hali operatsiya yo'q.")
        return

    keyboard = []
    for tx_id, kind, category, amount, created_at in rows:
        mark = "➕" if kind == "income" else "➖"
        day = created_at[8:10] + "." + created_at[5:7]
        label = f"{mark} {day} {category}: {format_money(amount)}"
        keyboard.append([InlineKeyboardButton(label[:60], callback_data=f"delete_pick:{tx_id}")])
    await update.message.reply_text(
        "🗑️ O'chirmoqchi bo'lgan operatsiyani tanlang (oxirgi 10 ta):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        tx_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Noto'g'ri tanlov. Menyudan qayta urinib ko'ring.")
        return

    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT kind, category, amount, created_at FROM transactions WHERE id = ? AND user_id = ?",
            (tx_id, query.from_user.id),
        ).fetchone()
    if not row:
        await query.edit_message_text("Bu operatsiya topilmadi yoki avval o'chirilgan.")
        return

    kind, category, amount, created_at = row
    label_kind = "Daromad" if kind == "income" else "Xarajat"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ha, o'chir", callback_data=f"delete_confirm:{tx_id}"),
         InlineKeyboardButton("↩️ Bekor qilish", callback_data="delete_cancel")]
    ])
    await query.edit_message_text(
        f"Quyidagi operatsiyani o'chiraymi?\n\n{label_kind}: {category}\n"
        f"Summa: {format_money(amount)}\nSana: {created_at[:10]}",
        reply_markup=keyboard,
    )


async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        tx_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Noto'g'ri tanlov.")
        return

    if delete_transaction(query.from_user.id, tx_id):
        await query.edit_message_text("✅ Operatsiya o'chirildi. Balans hisobotlarda avtomatik yangilanadi.")
    else:
        await query.edit_message_text("Operatsiya topilmadi yoki avval o'chirilgan.")


async def delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("O'chirish bekor qilindi.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Amal bekor qilindi.")
    return ConversationHandler.END


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^💰 Daromad qo'shish$"), begin_income),
            MessageHandler(filters.Regex(r"^💸 Xarajat qo'shish$"), begin_expense),
        ],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            INCOME_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_income)],
            EXPENSE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_expense)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"^❌ Bekor qilish$"), cancel),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conversation)
    app.add_handler(MessageHandler(filters.Regex(r"^🏦 Umumiy balans$"), balance))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Bugungi hisobot$"), today_report))
    app.add_handler(MessageHandler(filters.Regex(r"^📅 Oylik hisobot$"), month_report))
    app.add_handler(MessageHandler(filters.Regex(r"^📄 Oylik PDF yuklab olish$"), month_pdf_report))
    app.add_handler(MessageHandler(filters.Regex(r"^📈 Diagrammali hisobot$"), chart_report))
    app.add_handler(MessageHandler(filters.Regex(r"^🗑️ Operatsiyani o'chirish$"), delete_menu))
    app.add_handler(CallbackQueryHandler(delete_pick, pattern=r"^delete_pick:\d+$"))
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern=r"^delete_confirm:\d+$"))
    app.add_handler(CallbackQueryHandler(delete_cancel, pattern=r"^delete_cancel$"))

    print("Mening Hisobchim ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
