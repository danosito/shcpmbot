import asyncio
import datetime
import itertools
import re
import logging
import sqlite3

import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.types import BotCommand, MenuButtonCommands
from aiogram.filters import Command

import crypter
import solver
from config import TOKEN, db_data

logging.basicConfig(level=logging.DEBUG, filename='logs/' + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.log', filemode='a',
                    format='%(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

allcommands = [{'/start': 'help'}, {'/login': 'login'}, {'/settings': 'change settings'}]

async def set_commands(bot: Bot):
    commands = [BotCommand(command=list(i.keys())[0], description=list(i.values())[0]) for i in allcommands]
    await bot.set_my_commands(commands)

def is_valid_credentials(login, password):
    return bool(login and password)

def contains_sql_injection_chars(input_str):
    sql_injection_chars = ["'", ";", "--", "/*", "*/"]
    return any(char in input_str for char in sql_injection_chars)

async def find_token(message):
    conn = sqlite3.connect("legacy-maindb.db")
    userid = message.from_user.id
    cursor = conn.cursor()
    cursor.execute(f'SELECT token, expires, login, password FROM users WHERE userid = {userid}')
    resp = cursor.fetchone()
    if not resp:
        return None
    logging.debug(resp)
    token, expires, email, password = resp
    if datetime.datetime.now() > datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S"):
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.matetech.ru/api/public/companies/3/login",
                                    json={"email": email, "password": password}) as response:
                data = await response.json()

        if "data" not in data or "access_token" not in data["data"]:
            await message.reply("Неправильный логин или пароль. Залогиньтесь снова")
            return

        access_token = data["data"]["access_token"]
        expires = data["data"]["expires_at"]
        cursor.execute("UPDATE users SET token=?, expires=? WHERE userid=?", (access_token, expires, userid))
        conn.commit()
    return token

async def username_by_id(message: types.Message):
    userid = message.from_user.id
    conn = sqlite3.connect("legacy-maindb.db")
    cursor = conn.cursor()
    cursor.execute(f'SELECT username FROM users WHERE userid = {userid}')
    resp = cursor.fetchone()
    us = resp[0] if resp else None
    if not us:
        user = await bot.get_chat_member(userid, userid)
        us = user.user.username
        cursor.execute('UPDATE users SET username = ? WHERE userid = ?', (us, userid))
        conn.commit()
    return us

async def danlogger(message: types.Message, name=None):
    if name is None:
        name = await username_by_id(message)
    msg = " ".join([str(i) for i in [datetime.datetime.now(), name, message.text]])
    print(msg)
    logging.info(msg)

async def solve_question(cursor, solve_results, message, attempt_id, i, token, data, datas, c, p, msg, answers):
    logging.debug("QUESTION: " + str(i))
    cursor.execute(f"SELECT h_ans, a_ids FROM sharing WHERE q_id = {i['id']}")
    b = cursor.fetchone()
    if not b:
        ans = "У БОТА В БАЗЕ НЕТ ЭТОГО ВОПРОСА"
        solve_results[c][p] = ans
    else:
        b, machine = b
        ans = b.replace("<br>", "\n")
        cursor.execute(f"SELECT html_mode FROM users WHERE userid='{message.from_user.id}'")
        mode = str(cursor.fetchone()[0])
        if mode == '0':
            ans = re.sub(r'<.*?>', '', ans)
        if any(i in ans for i in ["UNSUPPORTED", "DONE"]):
            ans = "БОТ СЛИШКОМ ГЛУП ЧТОБЫ ЭТО РЕШИТЬ"
            solve_results[p][c] = ans
        else:
            async with aiohttp.ClientSession() as session:
                solve_results[p][c] = (await solver.solve(message, attempt_id, i['id'], machine, token, session))
    logging.debug("ANSWER: " + ans)
    answers.append(f"{c + 1}.\n" + ans)
    await bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id,
                                text=f'решаю, решено {c + 1} из {len(data)}, часть {p + 1} из {len(datas)}')

@router.message(Command(commands=['start']))
async def start(message: types.Message):
    await bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=MenuButtonCommands())
    await message.reply("Привет мир! Для входа введите /login логин пароль.")

@router.message(Command(commands=['login']))
async def login(message: types.Message):
    if message.text.count(" ") != 2:
        await message.reply("Неправильный формат логина или пароля. (/login login password)")
        return
    _, login, password = message.text.split()
    logging.debug(login + password)
    if contains_sql_injection_chars(login) or contains_sql_injection_chars(password):
        await message.reply("Неправильный формат логина или пароля. (/login login password), не пытайтесь взломать систему:)")
        return
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.matetech.ru/api/public/companies/3/login",
                                json={"email": login, "password": password}) as response:
            if response.status != 200:
                await message.reply("Неправильный логин или пароль.")
                return
            data = await response.json()

    if "data" not in data or "access_token" not in data["data"]:
        await message.reply("Неправильный логин или пароль.")
        return

    access_token = data["data"]["access_token"]
    expires = data["data"]["expires_at"]

    hashed_password = password

    user_id = message.from_user.id
    user_name = (await bot.get_chat_member(user_id, user_id)).user.username
    conn = sqlite3.connect("legacy-maindb.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE userid=?", [user_id])
    cursor.execute("INSERT INTO users (login, password, userid, expires, token, username) VALUES (?, ?, ?, ?, ?, ?)",
                   (login, hashed_password, user_id, expires, access_token, user_name))
    await message.reply(f"Логин {login} успешно зарегистрирован.")
    conn.commit()
    await danlogger(message, name=user_name)

@router.message(Command(commands=['settings']))
async def settings(message: types.Message):
    conn = sqlite3.connect("legacy-maindb.db")
    cur = conn.cursor()
    msg = message.text.split(" ")
    if len(msg) == 3:
        if msg[1] == 'html_mode':
            cur.execute("UPDATE users SET html_mode = ? WHERE userid=?", (msg[2], message.from_user.id))
            conn.commit()
            conn.close()
            await message.reply("success")
        else:
            await message.reply("такого параметра пока нет")
    else:
        await message.reply("/settings параметр значение")

@router.message(lambda message: re.match(r'(https://xn--80asehdb.xn----7sb3aehik9cm.xn--p1ai|https://онлайн.школа-цпм.рф)/courses/(\d+)/lesson/(\d+)/test/(\d+)\?attempt_id=(\d+)', message.text))
async def handle_link(message: types.Message):
    token = await find_token(message)
    if not token:
        await message.reply("Для этого вы должны залогиниться (/login)")
        return
    await danlogger(message)
    try:
        attempt_id = message.text.split("=")[1].split("&")[0]
    except IndexError:
        await message.reply("Кривая ссылка")
        return
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.matetech.ru/api/public/companies/3/test_attempts/{attempt_id}", headers=headers) as response:
            if response.status != 200:
                await message.reply("Ссылка кривая/ попробуйте перелогиниться. Failed to fetch data. Status code: " + str(response.status))
                return
            data = await response.json()

    msg = await message.reply("Ищу ответы, подождите...")
    conn = sqlite3.connect("legacy-maindb.db")
    cursor = conn.cursor()
    datas = data['data']['questions']
    logging.debug(datas)
    datas = crypter.decrypt(datas)
    res_to_send = ""
    solve_results = {}
    part_masks = []
    for p, data in enumerate(datas):
        if type(data) == str and data.isdigit():
            data = datas[data]
        answers = []
        tasks = []
        part_masks.append(len(data))
        for c, question in enumerate(data):
            solve_results[p] = {}
            tasks.append(solve_question(cursor, solve_results, message, attempt_id, question, token, data, datas, c, p, msg, answers))
        await asyncio.gather(*tasks)
        res_to_send += "\n\n".join(answers) + "\n\n"
    res_all = [res_to_send[i * 4096:(i + 1) * 4096] for i in range(len(res_to_send) // 4096 + 1)]
    await bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=res_all[0])
    for res in res_all[1:]:
        if res:
            await message.reply(res)
    solved = []
    for i in sorted(solve_results):
        for j in sorted(solve_results[i]):
            solved.append(f"{i + 1}-{j + 1} : {solve_results[i][j]}")
    await message.reply(f"советуем перепроверить, в тест введено {"".join(solved).count("все ок")} из {len(solved)} ответов\n" + "\n".join(solved))

@router.message()
async def handle_invalid_links(message: types.Message):
    await message.reply("Неправильный формат ссылки.")

async def main():
    await set_commands(bot)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
