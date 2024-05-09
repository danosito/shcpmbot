import datetime
import itertools
import re
import logging
import sqlite3

# import mysql.connector
import requests
import telebot
from telebot import types

import crypter
import solver
from config import TOKEN, db_data


logging.basicConfig(level=logging.DEBUG, filename='logs/' + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.log', filemode='a',
                    format='%(levelname)s - %(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')
bot = telebot.TeleBot(TOKEN)
allcommands = [{'/start': 'help'}, {'/login': 'login'}, {'/settings': 'change settings'}]
bot.set_my_commands([types.BotCommand(command=list(i.keys())[0], description=list(i.values())[0]) for i in allcommands])
# conn = mysql.connector.connect(**db_data)



def is_valid_credentials(login, password):
    if login and password:
        return True
    return False


def contains_sql_injection_chars(input_str):
    # Проверка на наличие запрещенных символов
    sql_injection_chars = ["'", ";", "--", "/*", "*/"]
    for char in sql_injection_chars:
        if char in input_str:
            return True
    if input_str:
        return False
    return True


def find_token(message):
    conn = sqlite3.connect("legacy-maindb.db")
    userid = message.from_user.id
    cursor = conn.cursor()
    cursor.execute(f'SELECT token, expires, login, password FROM users WHERE userid = {userid}')
    resp = cursor.fetchone()
    if not (resp):
        return None
    logging.debug(resp)
    token, expires, email, password = resp
    if datetime.datetime.now() > datetime.datetime.strptime(expires, "%Y-%m-%d %H:%M:%S"):

        response = requests.post("https://api.matetech.ru/api/public/companies/3/login",
                                 json={"email": email, "password": password})

        data = response.json()
        if "data" not in data or "access_token" not in data["data"]:
            bot.reply_to(message, "Неправильный логин или пароль. залогиньтесь снова")
            return

        access_token = data["data"]["access_token"]
        expires = data["data"]["expires_at"]
        cursor.execute("UPDATE users SET (token, expires) = (?, ?) WHERE userid=?", (access_token, expires, userid))
        conn.commit()
    return token




def username_by_id(message: types.Message):
    userid = message.from_user.id
    conn = sqlite3.connect("legacy-maindb.db")
    cursor = conn.cursor()
    cursor.execute(f'SELECT username FROM users WHERE userid = {userid}')
    resp = cursor.fetchone()[0]
    us = resp
    if not resp:
        us = bot.get_chat_member(userid, userid).user.username
        cursor.execute('UPDATE users SET username = ? WHERE userid = ?', (us, userid))
        conn.commit()
    return us


def danlogger(message: types.Message, name=None):
    msg = ""
    for i in [str(i) for i in [datetime.datetime.now(), name if name else username_by_id(message), message.text]]:
        msg += i + ' '
    print(msg)
    logging.info(msg)



@bot.message_handler(
    regexp=r'(https://xn--80asehdb.xn----7sb3aehik9cm.xn--p1ai|https://онлайн.школа-цпм.рф)/courses/(\d+)/lesson/(\d+)/test/(\d+)\?attempt_id=(\d+)')
def handle_link(message):
    token = find_token(message)
    if not token:
        bot.reply_to(message, "для этого вы должны залогиниться (/login)")
        return
    danlogger(message)
    try:
        attempt_id = message.text.split("=")[1].split("&")[0]
    except IndexError:
        bot.reply_to(message, "кривая ссылка")
        return
    url = f"https://api.matetech.ru/api/public/companies/3/test_attempts/{attempt_id}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        msg = bot.reply_to(message, "Ищу ответы, подождите...")
        conn = sqlite3.connect("legacy-maindb.db")
        cursor = conn.cursor()
        datas = response.json()['data']['questions']
        logging.debug(datas)
        datas = crypter.decrypt(datas)
        logging.debug("DECRYPTED: " + str(datas))
        res_to_send = ""
        solve_results = []
        part_masks = []
        for p, data in enumerate(datas, start=1):
            if type(data) == str and data.isdigit():
                data = datas[data]
            part_masks.append(len(data))
            logging.debug(p)
            answers = []
            for c, i in enumerate(data):
                logging.debug("QUESTION: " + str(i))
                cursor.execute(f"SELECT exact, machine FROM answers WHERE id = {i['id']}")
                b = cursor.fetchone()
                if not b:
                    ans = "У БОТА В БАЗЕ НЕТ ЭТОГО ВОПРОСА"
                    solve_results.append(ans)
                else:
                    b, machine = b
                    ans = b.replace("<br>", "\n")
                    cursor.execute(f"SELECT html_mode FROM users WHERE userid='{message.from_user.id}'")
                    mode = str(cursor.fetchone()[0])
                    if mode == '0':
                        ans = re.sub(r'<.*?>', '', ans)
                    if (any([i in ans for i in ["UNSUPPORTED", "DONE"]])):
                        ans = "БОТ СЛИШКОМ ГЛУП ЧТОБЫ ЭТО РЕШИТЬ"
                        solve_results.append(ans)
                    else:
                        solve_results.append(solver.solve(message, attempt_id, i['id'], machine, token))
                logging.debug("ANSWER: " + ans)
                answers.append(f"{c + 1}.\n" + ans)
                bot.edit_message_text(chat_id=message.chat.id, message_id=msg.id, text=f'решаю, решено {c + 1} из {len(data)}, часть {p} из {len(datas)}')
            logging.debug(answers)
            if (len(datas) > 1):
                res_to_send += str(p) + " Часть.\n"
            ansres = "\n\n\n".join(answers)
            res_to_send += ansres
        ansres = res_to_send
        ansrr = [ansres[i * 1000:(i + 1) * 1000] for i in range((len(ansres) + 999) // 1000)]
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.id, text=ansrr[0])
        for i in ansrr[1:]:
            if(i):
                bot.reply_to(message, i)
        masked = [i == "все ок" for i in solve_results]
        logging.debug(solve_results)
        part_masks = list(itertools.accumulate(part_masks))
        solved = []
        for i, j in enumerate(solve_results, start=1):
            k = 0
            while(part_masks[k] < i):
                k += 1
            solved.append(f"{k + 1}-{i} : {j}")
        bot.reply_to(message, f"советуем перепроверить, в тест введено {masked.count(True)} из {len(masked)} ответов\n" + "\n".join(solved))
        cursor.execute(f"UPDATE users set lastQuery='{datetime.datetime.now()}' WHERE userid='{message.from_user.id}'")
        conn.commit()
    else:
        bot.reply_to(message,
                     "ссылка кривая/ попробуйте перелогиниться. Failed to fetch data. Status code: " + str(response.status_code))


@bot.message_handler(commands=['start'])
def start(message):
    bot.set_chat_menu_button(message.chat.id, types.MenuButtonCommands('commands'))
    bot.reply_to(message, "Привет мир! Для входа введите /login логин пароль.")


@bot.message_handler(commands=['login'])
def login(message):
    if message.text.count(" ") != 2:
        bot.reply_to(message, "Неправильный формат логина или пароля. (/login login password)")
        return
    _, login, password = message.text.split()
    logging.debug(login + password)
    if contains_sql_injection_chars(login) or contains_sql_injection_chars(password):
        bot.reply_to(message,
                     "Неправильный формат логина или пароля. (/login login password), не пытайтесь взломать систему:)")
        return
    response = requests.post("https://api.matetech.ru/api/public/companies/3/login",
                             json={"email": login, "password": password})
    logging.debug(response)
    if response.status_code != 200:
        bot.reply_to(message, "Неправильный логин или пароль.")
        return
    data = response.json()
    if "data" not in data or "access_token" not in data["data"]:
        bot.reply_to(message, "Неправильный логин или пароль.")
        return

    access_token = data["data"]["access_token"]
    expires = data["data"]["expires_at"]

    hashed_password = password

    # Получаем user_id
    user_id = message.from_user.id
    user_name = bot.get_chat_member(user_id, user_id).user.username
    conn = sqlite3.connect("legacy-maindb.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE userid=?", [user_id])
    cursor.execute("INSERT INTO users (login, password, userid, expires, token, username) VALUES (?, ?, ?, ?, ?, ?)",
                   (login, hashed_password, user_id, expires, access_token, user_name))
    bot.reply_to(message, f"Логин {login} успешно зарегистрирован.")
    conn.commit()
    danlogger(message, name=user_name)




@bot.message_handler(commands=['settings'])
def settings(message):
    conn = sqlite3.connect("legacy-maindb.db")
    cur = conn.cursor()
    msg = message.text.split(" ")
    if (len(msg) == 3):
        if (msg[1] == 'html_mode'):
            cur.execute(f"UPDATE users SET html_mode = ? WHERE userid=?", (msg[2], message.from_user.id))
            conn.commit()
            conn.close()
            bot.reply_to(message, "success")
        else:
            bot.reply_to(message, "такого параметра пока нет")
    else:
        bot.reply_to(message, "/settings параметр значение")


@bot.message_handler(func=lambda message: True)
def handle_invalid_links(message):
    bot.reply_to(message, "Неправильный формат ссылки.")


bot.infinity_polling()
