import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DATABASE = "reminders.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Добавь токен бота в переменные окружения."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
tz = ZoneInfo(TIMEZONE)


class ReminderStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_datetime = State()


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить напоминание",
                    callback_data="add_reminder",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Мои напоминания",
                    callback_data="my_reminders",
                )
            ],
        ]
    )


def cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_creation",
                )
            ]
        ]
    )


def reminder_list_keyboard(reminders):
    buttons = []

    for reminder_id, text, remind_at in reminders:
        short_text = text[:25]
        if len(text) > 25:
            short_text += "..."

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"❌ {short_text}",
                    callback_data=f"delete_{reminder_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Главное меню",
                callback_data="back_to_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def add_reminder(user_id: int, text: str, remind_at: datetime):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders
            (user_id, text, remind_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                text,
                remind_at.isoformat(),
                datetime.now(tz).isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_reminders(user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute(
            """
            SELECT id, text, remind_at
            FROM reminders
            WHERE user_id = ?
            ORDER BY remind_at
            """,
            (user_id,),
        )
        return await cursor.fetchall()


async def get_due_reminders():
    now = datetime.now(tz)

    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute(
            """
            SELECT id, user_id, text, remind_at
            FROM reminders
            WHERE remind_at <= ?
            ORDER BY remind_at
            """,
            (now.isoformat(),),
        )
        return await cursor.fetchall()


async def delete_reminder(reminder_id: int, user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            """
            DELETE FROM reminders
            WHERE id = ? AND user_id = ?
            """,
            (reminder_id, user_id),
        )
        await db.commit()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я бот-напоминалка.\n"
        "Я помогу тебе не забывать о важных делах.\n\n"
        "Нажми кнопку ниже, чтобы создать первое напоминание.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "ℹ️ <b>Как пользоваться ботом</b>\n\n"
        "1️⃣ Нажми «Добавить напоминание».\n"
        "2️⃣ Напиши, о чём тебе нужно напомнить.\n"
        "3️⃣ Укажи дату и время.\n\n"
        "Формат даты:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Пример:\n"
        "<code>30.08.2026 18:30</code>\n\n"
        "/cancel — отменить действие.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "add_reminder")
async def add_reminder_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(ReminderStates.waiting_for_text)

    await callback.message.edit_text(
        "📝 <b>О чём тебе напомнить?</b>\n\n"
        "Например:\n"
        "Позвонить маме\n"
        "Купить продукты\n"
        "Оплатить интернет",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@dp.message(ReminderStates.waiting_for_text)
async def reminder_text_handler(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь текстовое сообщение.")
        return

    text = message.text.strip()

    if not text:
        await message.answer("❌ Текст не может быть пустым.")
        return

    if len(text) > 1000:
        await message.answer(
            "❌ Текст слишком длинный. Максимальная длина — 1000 символов."
        )
        return

    await state.update_data(reminder_text=text)
    await state.set_state(ReminderStates.waiting_for_datetime)

    await message.answer(
        "⏰ <b>Когда напомнить?</b>\n\n"
        "Введи дату и время в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Например:\n"
        "<code>30.08.2026 18:30</code>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@dp.message(ReminderStates.waiting_for_datetime)
async def reminder_datetime_handler(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Пожалуйста, отправь дату и время текстом.")
        return

    try:
        naive_datetime = datetime.strptime(
            message.text.strip(),
            "%d.%m.%Y %H:%M",
        )
        remind_at = naive_datetime.replace(tzinfo=tz)
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты.\n\n"
            "Используй:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Например:\n"
            "<code>30.08.2026 18:30</code>",
            parse_mode="HTML",
        )
        return

    if remind_at <= datetime.now(tz):
        await message.answer(
            "❌ Эта дата уже прошла.\n\nУкажи будущее время."
        )
        return

    data = await state.get_data()
    reminder_text = data["reminder_text"]

    reminder_id = await add_reminder(
        user_id=message.from_user.id,
        text=reminder_text,
        remind_at=remind_at,
    )

    await state.clear()

    await message.answer(
        "✅ <b>Напоминание создано!</b>\n\n"
        f"📝 {reminder_text}\n"
        f"⏰ {remind_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🔢 Номер: {reminder_id}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "cancel_creation")
async def cancel_creation(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()

    await callback.message.edit_text(
        "❌ Создание напоминания отменено.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_keyboard(),
    )


@dp.callback_query(F.data == "my_reminders")
async def my_reminders_handler(callback: CallbackQuery):
    await callback.answer()

    reminders = await get_user_reminders(callback.from_user.id)

    if not reminders:
        await callback.message.edit_text(
            "📋 <b>У тебя пока нет напоминаний.</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    text = "📋 <b>Твои напоминания:</b>\n\n"

    for reminder_id, reminder_text, remind_at in reminders:
        dt = datetime.fromisoformat(remind_at)
        text += (
            f"🔔 <b>{reminder_text}</b>\n"
            f"⏰ {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
        )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=reminder_list_keyboard(reminders),
    )


@dp.callback_query(F.data.startswith("delete_"))
async def delete_reminder_handler(callback: CallbackQuery):
    reminder_id = int(callback.data.replace("delete_", ""))

    await delete_reminder(reminder_id, callback.from_user.id)
    await callback.answer("✅ Напоминание удалено.")

    reminders = await get_user_reminders(callback.from_user.id)

    if not reminders:
        await callback.message.edit_text(
            "📋 <b>У тебя больше нет напоминаний.</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    text = "📋 <b>Твои напоминания:</b>\n\n"

    for reminder_id, reminder_text, remind_at in reminders:
        dt = datetime.fromisoformat(remind_at)
        text += (
            f"🔔 <b>{reminder_text}</b>\n"
            f"⏰ {dt.strftime('%d.%m.%Y %H:%M')}\n\n"
        )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=reminder_list_keyboard(reminders),
    )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def reminder_worker():
    while True:
        try:
            reminders = await get_due_reminders()

            for reminder_id, user_id, text, remind_at in reminders:
                try:
                    await bot.send_message(
                        user_id,
                        "🔔 <b>НАПОМИНАНИЕ</b>\n\n"
                        f"📝 {text}",
                        parse_mode="HTML",
                    )

                    await delete_reminder(reminder_id, user_id)

                except Exception as error:
                    logging.error(
                        f"Ошибка отправки пользователю {user_id}: {error}"
                    )

        except Exception as error:
            logging.error(f"Ошибка reminder_worker: {error}")

        await asyncio.sleep(5)


async def main():
    await init_db()
    asyncio.create_task(reminder_worker())

    logging.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
