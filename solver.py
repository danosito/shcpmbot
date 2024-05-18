import requests
import crypter
import aiohttp

async def solve(message, a_id, q_id, ans, token, session):
    headers = {'Authorization': 'Bearer ' + token}
    resp = await session.get(
        f"https://api.matetech.ru/api/public/companies/3/test_attempts/{crypter.encrypt(a_id)}/question/{crypter.encrypt(q_id)}",
        headers=headers)
    quest_data = await resp.json()
    if 'error' in quest_data:
        return "ошибка на нашей стороне, перешлите @danosito"
    if 'data' not in quest_data:
        return "скорее всего тест завершен, перешлите @danosito эту информацию: " + str(quest_data)
    q_a_id = crypter.encrypt(quest_data['data']['current_attempt']['id'])
    if quest_data['data']['type'] in ['radio', 'checkbox', 'sort']:
        if (ans[-1] == " "): ans = ans[:-1]
        ans = ans.split(" ")
        res = {"answer": {}}
        try:
            for i in ans:
                res["answer"][int(i)] = i
            return "все ок" if (await session.post(f"https://api.matetech.ru/api/public/companies/3/question_attempts/{q_a_id}/answer", json=res, headers=headers)).status == 200 else "все плохо, пишите @danosito"
        except Exception as e:
            return "возникла ошибка, перешлите @danosito\n" + str(e)
    elif quest_data['data']['type'] in ['input', 'numeric_input']:
        ans_id = crypter.decrypt(quest_data['data']['answers'])[0]['id']
        res = {"answer": {}}
        res["answer"][ans_id] = ans
        return "все ок" if (await session.post(f"https://api.matetech.ru/api/public/companies/3/question_attempts/{q_a_id}/answer", json=res, headers=headers)).status == 200 else "все плохо, пишите @danosito"
    else:
        return "мой бот пока не умеет вводить в тест такой тип вопросов:( ВАЖНО киньте пожалуйста скрин вопроса @danosito"