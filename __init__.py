from enum import Flag
from json import load, dump, dumps, loads
from re import T
from nonebot import get_bot, on_command
from hoshino import priv
from hoshino.typing import NoticeSession
from .pcrclient import pcrclient, ApiException, bsdkclient
from asyncio import Lock
from os.path import dirname, join, exists
from copy import deepcopy
from traceback import format_exc
from .safeservice import SafeService
from hoshino.aiorequests import post, get
import asyncio
import time

ordd = "Farm"
house_name = "ebq的树屋"
bot_name = "ebq"

sv_help = f'''{bot_name}的农场（女生自用！）
*添加←{bot_name}为好友后开始白嫖装备！
指令列表：
[加入农场 <pcrid>] pcrid为(b服)个人简介内13位数字
[退出农场]

仅管理有效指令：
[今日捐赠]
[农场刷图 <bot编号> <要刷的图>] 若不指定编号则为全体农场号
[农场人员] 返回所有被授权人员的id和名字
[农场踢除 <pcrid>] 
[农场清空]'''

sv = SafeService('农场', help_=sv_help, bundle='农场', visible=False)


@sv.on_fullmatch('农场帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    await bot.send_private_msg(user_id=ev.user_id, message=sv_help)


curpath = dirname(__file__)
config = join(curpath, 'binds.json')
root = {"farm_bind": {}, "farm_quit": {}}

cache = {}
lck = Lock()

if exists(config):
    with open(config) as fp:
        root = load(fp)

binds = root["farm_bind"]  # {"1104356549126": "491673070"}
quits = root["farm_quit"]

captcha_lck = Lock()

with open(join(curpath, 'account.json')) as fp:
    acinfo = load(fp)


def save_acinfo():
    global acinfo
    with open(join(curpath, 'account.json'), 'w') as fp:
        dump(acinfo, fp, indent=4)


def save_binds():
    global root
    with open(config, 'w') as fp:
        dump(root, fp, indent=4)


f = False
for i, account in enumerate(acinfo["accounts"]):
    if "today_donate" not in account:
        acinfo["accounts"][i]["today_donate"] = 0
        save_acinfo()
    if "name" not in account:
        acinfo["accounts"][i]["name"] = f"_{bot_name}{i}"
        save_acinfo()
    if account["account"] == acinfo["account"]:
        f = True
if f == False:
    acinfo["accounts"].append({"account": acinfo["account"], "password": acinfo["password"], "today_donate": 0})
    save_acinfo()

bot = get_bot()
validate = None
validating = False
otto = True
acfirst = False


async def captchaVerifier(gt, challenge, userid):
    url = f"https://help.tencentbot.top/geetest/?captcha_type=1&challenge={challenge}&gt={gt}&userid={userid}&gs=1"
    global acfirst, validating
    global binds, lck, validate, captcha_lck

    if not otto:
        await bot.send_private_msg(
            user_id=acinfo['admin'],
            message=f'pcr账号登录需要验证码，请完成以下链接中的验证内容后将第1个方框的内容点击复制，并加上"validate{ordd} "前缀发送给机器人完成验证\n验证链接：{url}\n示例：validate{ordd} 123456789\n您也可以发送 validate{ordd} auto 命令bot自动过验证码')
        if not acfirst:
            await captcha_lck.acquire()
            acfirst = True
        validating = True
        await captcha_lck.acquire()
        validating = False
        return validate

    validate = ""
    header = {"Content-Type": "application/json"}
    succ = 0
    info = ""
    #await bot.send_private_msg(user_id=acinfo['admin'], message=f"thread{ordd}: Auto verifying\n欲手动过码，请发送 validate{ordd} manual")
    print(f"farm: Auto verifying")
    try:
        res = await (await post(url="http://pcrd.tencentbot.top/validate", data=dumps({"url": url}), headers=header)).content
        #if str(res.status_code) != "200":
        #    continue
        res = loads(res)
        uuid = res["uuid"]
        msg = [f"uuid={uuid}"]
        ccnt = 0
        while ccnt < 5 and succ == 0 and validate == "":
            ccnt += 1
            res = await (await get(url=f"https://pcrd.tencentbot.top/check/{uuid}")).content
            #if str(res.status_code) != "200":
            #    continue
            res = loads(res)
            if "queue_num" in res:
                nu = res["queue_num"]
                msg.append(f"queue_num={nu}")
                tim = min(int(nu), 3) * 20
                msg.append(f"sleep={tim}")
                #await bot.send_private_msg(user_id=acinfo['admin'], message=f"thread{ordd}: \n" + "\n".join(msg))
                print(f"farm:\n" + "\n".join(msg))
                msg = []
                await asyncio.sleep(tim)
            else:
                info = res["info"]
                if info in ["fail", "url invalid"]:
                    break
                elif info == "in running":
                    await asyncio.sleep(8)
                elif len(info) > 20:
                    succ = 1
    except:
        pass
    if succ:
        validate = info
    #await bot.send_private_msg(user_id=acinfo['admin'], message=f"thread{ordd}: succ={succ} validate={validate}")
    print(f"farm: succ={succ} validate={validate}")

    # captcha_lck.release()
    # await captcha_lck.acquire()
    return validate


async def errlogger(msg):
    #await bot.send_private_msg(user_id=acinfo['admin'], message=f'thread{ordd}: {msg}')
    print(f"farm: {msg}")


last_login = None
bclient = None
client = None
load_index = None
home_index = None

qlck = Lock()


def nowtime():
    return int(time.time())


async def get_equip(client, quest_id, current_currency_num, current_stamina_num, current_ticket_num):
    if current_currency_num <= 20 and current_stamina_num >= 1000:
        try:
            res = await client.callapi('/shop/recover_stamina', {"current_currency_num": current_currency_num})
            if "server_error" in res:
                return res["server_error"]["message"]
            current_stamina_num += 120
        except:
            return False

    quest_id = quest_id.split('-')
    quest_id = int(f"11{int(quest_id[0]):03d}{int(quest_id[1]):03d}")
    random_count = min(current_stamina_num // 10, current_ticket_num)
    try:
        res = await client.callapi('/quest/quest_skip', {"quest_id": quest_id, "random_count": random_count, "current_ticket_num": current_ticket_num})
        if "server_error" in res:
            return res["server_error"]["message"]
    except:
        return False
    return True
    # 重启以同步库存


async def remove(client, clan_id: int, pcrid: str):
    # 从公会中删除pcrid
    try:
        res = await client.callapi('/clan/remove', {'clan_id': int(clan_id), "remove_viewer_id": int(pcrid)})
        if "server_error" in res:
            return res["server_error"]["message"]
        return True
    except:
        return False


async def invite(client, id):
    try:
        res = await client.callapi('/clan/invite', {'invited_viewer_id': int(id), "invite_message": f"欢迎加入{house_name}！"})
        if "server_error" in res:
            return res["server_error"]["message"]
        return True
    except:
        return False


async def room(client):
    try:
        res = await client.callapi('/room/receive_all', {})  # 家园一键
        if "server_error" in res and res["server_error"]["message"] != "没有可收取的道具。":
            return res["server_error"]["message"]
        return True
    except:
        return False


async def mission(client):
    try:
        res = await client.callapi('/mission/accept', {"type": 1, "id": 0, "buy_id": 0})  # 日常任务一键
        # 日常领取失败会直接返回标题界面
        if "server_error" in res and res["server_error"]["message"] != "发生了错误。\\n回到标题界面。":
            return res["server_error"]["message"]
        return True
    except:
        return False


flag_over_limit = 0  # 写崩了


async def present(client):
    global flag_over_limit
    try:
        res = await client.callapi('/present/receive_all', {"time_filter": -1, "type_filter": 0, "desc_flag": True})  # 礼物一键
        if "server_error" in res:
            flag_over_limit = 0
        if "server_error" in res and res["server_error"]["message"] != "这件礼物已经收取。":
            return res["server_error"]["message"]
        flag_over_limit = res["flag_over_limit"]
        return True
    except:
        return False


async def accept(client, clan_id):
    return  # 暂不支持，只支持bot邀请
    # 检测加公会请求，若在binds中放行，否则拒绝
    # res = await client.callapi('/clan/join_request_accept', {"request_viewer_id": <pcrid>, "clan_id": clan_id})


async def profile(client, id):
    return (await client.callapi('/profile/get_profile', {'target_viewer_id': int(id)}))


async def get_donate_list(client, clan_id):
    return (await client.callapi('/clan/chat_info_list', {
        "clan_id": int(clan_id),
        "start_message_id": 0,
        "search_date": "2099-12-31",
        "direction": 1,
        "count": 10,
        "wait_interval": 3,
        "update_message_ids": [],
    }))


async def donate(client, clan_id, message_id, donation_num, current_equip_num):
    return (await client.callapi('/equipment/donate', {"clan_id": clan_id, "message_id": message_id, "donation_num": donation_num, "current_equip_num": current_equip_num}))


def make_acinfo(i):
    if i == -1:
        return {"account": acinfo["account"], "password": acinfo["password"], "platform": 2, "channel": 1, "admin": acinfo["admin"]}
    else:
        return {"account": acinfo["accounts"][i]["account"], "password": acinfo["accounts"][i]["password"], "platform": 2, "channel": 1, "admin": acinfo["admin"]}


async def query(info: str, account=-1, **args):
    await asyncio.sleep(1)
    if validating:
        raise ApiException('账号被风控，请联系管理员输入验证码并重新登录', -1)

    # global last_login, bclient, client
    # global load_index, home_index
    async with qlck:
        # if account != last_login or ("forced_login" in args and args["forced_login"] == True):
        #    bclient = bsdkclient(make_acinfo(account), captchaVerifier, errlogger)
        #    client = pcrclient(bclient)
        #    last_login = account
        bclient = bsdkclient(make_acinfo(account), captchaVerifier, errlogger)
        client = pcrclient(bclient)
        if client.shouldLogin:
            print(f"farm: try login / account={account}")
        while client.shouldLogin:
            await client.login()
        print(f"farm: login succeed / account={account}")
        load_index = await client.callapi('/load/index', {'carrier': 'OPPO'})
        home_index = await client.callapi('/home/index', {'message_id': 1, 'tips_id_list': [], 'is_first': 1, 'gold_history': 0})
        clan_id = home_index["user_clan"]["clan_id"]
        current_stamina = load_index["user_info"]["user_stamina"]
        user_name = load_index["user_info"]["user_name"]
        current_jewel = load_index["user_jewel"]["free_jewel"] + load_index["user_jewel"]["paid_jewel"]
        today_donation_num = home_index["user_clan"]["donation_num"]

        if account != -1 and ("name" not in acinfo["accounts"][account] or acinfo["accounts"][account]["name"] != user_name):
            acinfo["accounts"][account]["name"] = user_name
            save_acinfo()
        if account != -1 and acinfo["accounts"][account]["today_donate"] < today_donation_num:
            acinfo["accounts"][account]["today_donate"] = today_donation_num
            save_acinfo()

        item_list = {}
        for item in load_index["item_list"]:
            item_list[item["id"]] = item["stock"]
        current_ticket = item_list[23001]

        if info == "profile":
            return (await profile(client, args["pcrid"]))['user_info']
        if info == "invite":
            return await invite(client, args["pcrid"])
        if info == "remove":
            return await remove(client, clan_id, args["pcrid"])
        if info == "accept":
            return await accept(client, clan_id)
        if info == "room":
            return await room(client)
        if info == "mission":
            return await mission(client)
        if info == "present":
            return await present(client)
        if info == "get_donate_list":
            return await get_donate_list(client, clan_id)
        if info == "donate":
            return await donate(client, clan_id, args["message_id"], args["donation_num"], args["current_equip_num"])
        if info == "get_equip":
            equip_id = args["equip_id"]
            if type(equip_id) == str:
                return await get_equip(client, equip_id, current_jewel, current_stamina, current_ticket)
            elif equip_id == 114613:  # 贤者宝珠 14-12
                return await get_equip(client, "14-12", current_jewel, current_stamina, current_ticket)
            else:
                return None


ff_last = False


@sv.scheduled_job('interval', seconds=600)  # 十分钟轮询一次
@sv.on_fullmatch(('请求捐赠', '申请捐赠', '发起捐赠'))
async def on_farm_schedule(*args):
    global bot
    # print("farm: 轮询 / 公会申请审批")
    # await query("accept")  # 先登录担任会长的农场号，看看有无加公会请求
    print("farm: 轮询 / 捐赠计时")
    clock = [24, 8]
    for pcrid in binds:
        for i in clock:
            if nowtime() - binds[pcrid]["donate_last"] > i * 3600 and binds[pcrid]["donate_clock"] < i:
                await bot.send_private_msg(user_id=int(binds[pcrid]["qqid"]), message=f"来自 {house_name} 的消息：{binds[pcrid]['name']}可以发起新的捐赠了哦！\n距离上次捐赠已过{i}小时。")
                binds[pcrid]["donate_clock"] = i
                save_binds()
                break

    print("farm: 轮询 / 捐赠装备")
    # 对农场号按今日已捐数量排序，<10的拉去尝试捐东西
    donate = {}
    for i, account in enumerate(acinfo["accounts"]):
        try:
            donate[i] = len(account["today_donate"])
        except:
            donate[i] = 0
    donate = list(sorted(donate.items(), key=lambda x: x[1]))
    ff = False
    for account in donate:
        #if account[0] != 17:
        #    continue
        if account[1] >= 10:
            break
        res = await query("get_donate_list", account[0])
        #返回 clan_chat_message / users / equip_requests装备请求 / user_equip_data我的装备数量 / 其它（cooperation_data等）
        user = {}
        for i in res["users"]:
            user[i["viewer_id"]] = i["name"]
        equip_requests = res["equip_requests"]
        user_equip_data = {}
        for i in res["user_equip_data"]:
            user_equip_data[i["equip_id"]] = i["equip_count"]
        ff = False
        for equip in equip_requests:
            # await asyncio.sleep(5)
            if "history" in equip:
                continue  # 不响应自己的捐赠
            if equip["donation_num"] < equip["request_num"]:  # 还没捐满
                ff = True
                if str(equip['viewer_id']) in binds:
                    if equip["donation_num"] == 0:
                        if binds[str(equip['viewer_id'])]["donate_remind"] == False or binds[str(equip['viewer_id'])]["donate_last"] > 8 * 3600:
                            await bot.send_private_msg(user_id=int(binds[str(equip['viewer_id'])]["qqid"]), message=f"检测到 {user[equip['viewer_id']]} 的装备请求\n装备id={equip['equip_id']}")
                            binds[str(equip['viewer_id'])]["donate_last"] = nowtime()
                            binds[str(equip['viewer_id'])]["donate_remind"] == True
                            binds[str(equip['viewer_id'])]["donate_clock"] = 0
                        binds[str(equip['viewer_id'])]["donate_num"] = 0
                        binds[str(equip['viewer_id'])]["donate_bot"] = []
                        save_binds()

                if user_equip_data[equip["equip_id"]] < 30:  # 该装备已较少
                    msg = f"{acinfo['accounts'][account[0]]['name']}的装备{equip['equip_id']}存量较少，剩余{user_equip_data[equip['equip_id']]}。"
                    res = await query("get_equip", account[0], equip_id=equip['equip_id'])
                    if res != True:
                        msg += f"请发送[农场刷图 {account[0]} <要刷的图>]指定bot刷图"
                    if type(res) == str:
                        await bot.send_private_msg(user_id=acinfo["admin"], message=f"{acinfo['accounts'][account[0]]['name']}自动刷取装备{equip['equip_id']}时发生错误：{res}")
                    await bot.send_private_msg(user_id=acinfo["admin"], message=msg)

                donation_num = min(user_equip_data[equip["equip_id"]], 2 - equip["user_donation_num"])
                if donation_num > 0:
                    res = await query("donate", account[0], message_id=equip["message_id"], donation_num=donation_num, current_equip_num=user_equip_data[equip["equip_id"]])
                    if "server_error" not in res:
                        user_equip_data[equip["equip_id"]] -= donation_num
                        acinfo["accounts"][account[0]]["today_donate"] = int(res["donation_num"])
                        save_acinfo()
                        binds[str(equip['viewer_id'])]["donate_num"] += donation_num
                        binds[str(equip['viewer_id'])]["donate_bot"].append(acinfo["accounts"][account[0]]["name"])
                        save_binds()
                        if donation_num + equip["donation_num"] == equip["request_num"]:
                            await bot.send_private_msg(user_id=int(binds[str(equip['viewer_id'])]["qqid"]),
                                                       message=f"您的捐赠请求已完成！\n参与的{bot_name}有：" + f" ".join(binds[str(equip['viewer_id'])]['donate_bot']))
                            binds[str(equip['viewer_id'])]["donate_remind"] = False
                            binds[str(equip['viewer_id'])]["donate_num"] = 0
                            binds[str(equip['viewer_id'])]["donate_bot"] = []
                            save_binds()
                    else:
                        await bot.send_private_msg(user_id=acinfo["admin"], message=f"{acinfo['accounts'][account[0]]['name']}的装备捐赠失败：\n" + str(res))

        if ff == False:
            break
    global ff_last
    if ff == True and ff_last == False:
        await bot.send_private_msg(user_id=acinfo["admin"], message=f"存在无法完成的装备请求！请立即阅读以上信息并刷取装备！")
    ff_last = ff


@sv.scheduled_job('cron', hour='23')
# @sv.on_fullmatch('领取日常')
async def on_dayend(*args):  # 每天晚上23点领家园体、任务奖励、礼物箱
    global bot
    msg = []
    for i, account in enumerate(acinfo["accounts"]):
        res1 = await query("room", i)
        res2 = await query("mission", i)
        res3 = await query("present", i)
        if res1 == True and res2 == True and res3 == True:
            pass
        else:
            msg.append(f"{account['name']}\n家园：{res1}\n任务：{res2}\n礼物：{res3}\n")
        await brush(bot, i, "14-12")
    if msg != []:
        await bot.send_private_msg(user_id=acinfo["admin"], message="以下农场号领取家园体、任务奖励、礼物箱出现报错：\n" + "\n".join(msg))
    else:
        await bot.send_private_msg(user_id=acinfo["admin"], message="所有农场号领取家园体、任务奖励、礼物箱成功")


async def brush(bot, i, equip_id):
    global flag_over_limit
    f = True
    msg = f"{acinfo['accounts'][i]['name']}(No.{i}) {acinfo['accounts'][i]['account']} -> {equip_id}"
    flag_over_limit = 1
    while (flag_over_limit == 1):
        res = await query("get_equip", i, forced_login=True, equip_id=equip_id)
        if type(res) == str:
            msg += f"\nError: {res}\n可能是未三星通关，请手动刷取。\n{acinfo['accounts'][i]['account']} {acinfo['accounts'][i]['password']}"
            f = False
            break
        elif res == False:
            f = False
            break
        await query("present", i)
    if f == True:
        msg += "\nDone."
    await bot.send_private_msg(user_id=acinfo["admin"], message=msg)


@sv.on_prefix("农场刷图")
async def 农场刷图(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    msg = ev.message.extract_plain_text().strip().split(' ')
    i = -1
    equip_id = "14-12"
    if len(msg) >= 2:
        i = int(msg[0])
        equip_id = msg[1]
    elif msg != [""]:
        try:
            i = int(msg[0])
        except:
            equip_id = msg[0]

    await bot.send_private_msg(user_id=acinfo["admin"], message=f"account={i}, map={equip_id}")

    if i == -1:
        for i, account in enumerate(acinfo["accounts"]):
            await brush(bot, i, equip_id)
    else:
        await brush(bot, i, equip_id)


@on_command(f'validate{ordd}')
async def validate(session):
    global binds, lck, validate, validating, captcha_lck, otto
    if session.ctx['user_id'] == acinfo['admin']:
        validate = session.ctx['message'].extract_plain_text().replace(f"validate{ordd}", "").strip()
        if validate == "manual":
            otto = False
            await bot.send_private_msg(user_id=acinfo['admin'], message=f'thread{ordd}: Changed to manual')
        elif validate == "auto":
            otto = True
            await bot.send_private_msg(user_id=acinfo['admin'], message=f'thread{ordd}: Changed to auto')
        try:
            captcha_lck.release()
        except:
            pass


@sv.on_prefix(("加入农场"))
async def on_farm_bind(bot, ev):
    global binds, lck
    async with lck:
        qqid = str(ev['user_id'])
        pcrid = ev.message.extract_plain_text().strip()
        if pcrid == "":
            await bot.send_private_msg(user_id=ev.user_id, message=sv_help)
            return
        if pcrid[0] == "<" and pcrid[-1] == ">":
            pcrid = pcrid[1:-1]
        print(pcrid)
        nam = ""
        try:
            nam = (await query("profile", pcrid=pcrid))["user_name"]
        except:
            await bot.send_private_msg(user_id=ev.user_id, message="未找到玩家，请检查您的13位id！")
            return
        if pcrid in quits:
            quits.pop(pcrid)
            await bot.send_private_msg(user_id=ev.user_id, message=f"该账号曾请求退出农场，已删除旧请求。")
        if pcrid in binds:
            if binds[pcrid]["qqid"] != qqid:
                old_qqid = binds[pcrid]["qqid"]
                await bot.send_private_msg(user_id=ev.user_id, message=f"该账号曾被{old_qqid}绑定。为了防止恶意绑定，已拒绝您的本次请求。")
            else:
                await bot.send_private_msg(user_id=ev.user_id, message=f"该账号已提交过加入农场请求。")
        else:
            binds[pcrid] = {"qqid": qqid, "name": nam, 'donate_last': nowtime(), 'donate_remind': False, 'donate_clock': 0, 'donate_num': 0, 'donate_bot': []}
            save_binds()
            await bot.send_private_msg(user_id=ev.user_id, message=f"pcrid={pcrid}\nname={nam}\n申请成功！正在发起邀请...")
            res = await query("invite", pcrid=pcrid)
            if res == True:
                await bot.send_private_msg(user_id=ev.user_id, message=f"公会名：{house_name}\n已发起邀请，请接受！")
            elif type(res) == str:
                await bot.send_private_msg(user_id=ev.user_id, message=res)


@sv.on_prefix(("退出农场"))
async def delete_farm_sub(bot, ev):
    global binds, lck

    async with lck:
        qqid = str(ev['user_id'])
        pcrids = []
        for pcrid in binds:
            if binds[pcrid]["qqid"] == qqid:
                pcrids.append(pcrid)
                # binds.pop(pcrid)
                quits[pcrid] = qqid
        if pcrids == []:
            await bot.send_private_msg(user_id=ev.user_id, message=f"您尚未加入农场或已申请过退出农场，请耐心等待！")
        else:
            for pcrid in pcrids:
                binds.pop(pcrid)
            save_binds()
            await bot.send_private_msg(user_id=ev.user_id, message="以下账号成功申请退出农场：\n" + "\n".join(pcrids) + "\n请耐心等待")
            for pcrid in pcrids:
                if await query("remove", pcrid=pcrid):
                    quits.pop(pcrid)
                    save_binds()
                    await bot.send_private_msg(user_id=ev.user_id, message=f"{pcrid}已退出农场")


@sv.on_fullmatch(("今日捐赠", "查询捐赠"))
async def today_donate(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    donate = {}
    for i, account in enumerate(acinfo["accounts"]):
        try:
            donate[i] = account["today_donate"]
        except:
            donate[i] = 0
    donate = list(sorted(donate.items(), key=lambda x: x[1], reverse=True))
    # [(3, 11), (6, 9), (7, 6), (10, 5), (8, 2)]
    last = donate[0][1]
    if last == 0:
        await bot.send_private_msg(user_id=ev.user_id, message="今日所有bot均未产生捐赠！")
        return
    msg = f"{last:2d} :"
    for i in donate:
        if i[1] != last:
            last = i[1]
            msg += f"\n{last:2d} :"
        msg += f" {acinfo['accounts'][i[0]]['name']}({i[0]})"
    await bot.send_private_msg(user_id=ev.user_id, message=msg)


@sv.on_fullmatch(("农场成员", "农场人员", "查询农场", "查询农场人员", "查询农场成员", "查询农场信息", "农场名单"))
async def query_farm_info(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    msg = []
    for account in binds:
        msg.append(f"{account} / {binds[account]['qqid']} / {binds[account]['name']} / {(nowtime() - binds[account]['donate_last']) / 3600 :.1f}H")
    if msg != []:
        await bot.send_private_msg(user_id=ev.user_id, message="授权人员\npcrid / qqid / name / last\n" + "\n".join(msg))
    else:
        await bot.send_private_msg(user_id=ev.user_id, message="当前没有人被授权进入农场！")


@sv.on_prefix(("农场踢除", "踢除人员", "踢除成员", "移除成员", "移除人员", "农场移除"))
async def kick_from_farm(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    pcrid = ev.message.extract_plain_text().strip()
    if pcrid[0] == "<" and pcrid[-1] == ">":
        pcrid = pcrid[1:-1]

    if pcrid in binds:
        await bot.send_private_msg(user_id=ev.user_id, message=f"已发起退出农场请求：{pcrid}({binds[pcrid]['name']})")
        await bot.send_private_msg(user_id=int(binds[pcrid]["qqid"]), message=f"您的pcr账号{pcrid}({binds[pcrid]['name']})被农场主置为：即将移出")
        quits[pcrid] = binds[pcrid]["qqid"]
        binds.pop(pcrid)
        save_binds()

        if await query("remove", pcrid=pcrid):
            await bot.send_private_msg(user_id=ev.user_id, message=f"{pcrid}已退出农场")
            await bot.send_private_msg(user_id=int(quits[pcrid]), message=f"您的pcr账号{pcrid}已被移出农场")
            quits.pop(pcrid)
            save_binds()
    else:
        await bot.send_private_msg(user_id=ev.user_id, message=f"农场无该授权成员：{pcrid}\n请发送[农场人员]获取列表")


@sv.on_fullmatch(("清空农场", "农场清空"))
async def empty_farm(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    global binds, lck
    async with lck:
        pcrids = []
        for pcrid in binds:
            pcrids.append(pcrid)
            quits[pcrid] = binds[pcrid]["qqid"]
            await bot.send_private_msg(user_id=int(binds[pcrid]["qqid"]), message=f"您的pcr账号{pcrid}({binds[pcrid]['name']})被农场主置为：即将移出")
            # binds.pop(pcrid)
        if pcrids == []:
            await bot.send_private_msg(user_id=ev.user_id, message=f"农场已清空或正在清空，请耐心等待！")
        else:
            for pcrid in pcrids:
                binds.pop(pcrid)
            save_binds()
            await bot.send_private_msg(user_id=ev.user_id, message="以下账号即将移出农场：\n" + "\n".join(pcrids) + "\n请耐心等待")
            pcrids_failed = []
            for pcrid in pcrids:
                if await query("remove", pcrid=pcrid):
                    qqid = int(quits[pcrid])
                    quits.pop(pcrid)
                    save_binds()
                    await bot.send_private_msg(user_id=qqid, message=f"您的pcr账号{pcrid}已被移出农场")
                else:
                    pcrids_failed.append(pcrid)
            if pcrids_failed == []:
                await bot.send_private_msg(user_id=ev.user_id, message="所有账号移出农场成功")
            else:
                await bot.send_private_msg(user_id=ev.user_id, message="以下账号移出农场失败：\n" + "\n".join(pcrids_failed))


@sv.scheduled_job('cron', hour='0')
async def on_newday():
    for account in acinfo["accounts"]:
        account["today_donate"] = 0
    save_acinfo()