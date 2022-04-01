from json import load, dump, dumps, loads
from nonebot import get_bot, on_command
import nonebot

from hoshino.modules.farm.enums import eInventoryType
from .pcrclient import pcrclient, ApiException, bsdkclient
from asyncio import Lock
from os.path import dirname, join, exists
from .safeservice import SafeService
from .common import *
from hoshino.aiorequests import post, get
import asyncio
import time

free = 1

ordd = "Farm"
house_name = "ebq的树屋"
bot_name = "ebq"

sv_help = f'''{bot_name}的{"免费" if free else "付费"}农场！
*{"" if free else "向bot主人咨询事宜，随后"}添加←{bot_name}为好友后开始{"白嫖" if free else "获取"}装备！
指令列表：
[加入农场 <pcrid>] pcrid为(b服)个人简介内13位数字
[退出农场]

仅管理有效指令：
[今日捐赠]
[农场刷图 <bot编号> <要刷的图>] 若不指定编号则为全体农场号
{"" if free else "[农场充值 <pcrid> <捐赠装备额度>]"}
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
    with open(config, encoding='utf-8') as fp:
        root = load(fp)

binds = root["farm_bind"]  # {"1104356549126": "491673070"}
quits = root["farm_quit"]
binds_accept_pcrid = None
if free != 1:
    binds_accept_pcrid = root["farm_accept"]

captcha_lck = Lock()

with open(join(curpath, 'account.json'), encoding='utf-8') as fp:
    acinfo = load(fp)

with open(join(curpath, 'equip_name.json'), "r", encoding="utf-8") as fp:
    equip2name = load(fp)

with open(join(curpath, 'equip_list.json'), encoding='utf-8') as fp:
    equip2list = load(fp)


def save_acinfo():
    global acinfo
    with open(join(curpath, 'account.json'), 'w', encoding='utf-8') as fp:
        dump(acinfo, fp, indent=4, ensure_ascii=False)


def save_binds():
    global root
    with open(config, 'w', encoding='utf-8') as fp:
        dump(root, fp, indent=4, ensure_ascii=False)


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
    global binds, validate, captcha_lck
    global otto
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
        while ccnt < 10 and succ == 0 and validate == "":
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
            if ccnt >= 10:
                otto = False
                await bot.send_private_msg(user_id=acinfo['admin'], message=f'thread{ordd}: 自动过码多次尝试失败，可能为服务器错误，自动切换为手动。\n确实服务器无误后，可发送 validate{ordd} auto重新触发自动过码。')
                await bot.send_private_msg(user_id=acinfo['admin'], message=f'thread{ordd}: Changed to manual')
    except:
        pass
    if succ:
        validate = info
    #await bot.send_private_msg(user_id=acinfo['admin'], message=f"thread{ordd}: succ={succ} validate={validate}")
    print(f"farm: succ={succ} validate={validate}")

    # captcha_lck.release()
    # await captcha_lck.acquire()
    return validate

def nowtime():
    return int(time.time())

master = pcrclient(account = {
    "account": acinfo["account"],
    "password": acinfo["password"],
    "platform": 2,
    "channel": 1
}, validator = captchaVerifier)
slaves = [pcrclient(account = {
    "account": info["account"],
    "password": info["password"],
    "platform": 2,
    "channel": 1
}, validator = captchaVerifier) for info in acinfo["accounts"]]

def equip2quest(equip_id):
    if type(equip_id) == str:
        quest_id = equip_id.split('-')
        quest_id = int(f"11{int(quest_id[0]):03d}{int(quest_id[1]):03d}")
        return [quest_id]
    elif str(equip_id) in equip2list:
        equip_map_list = equip2list[str(equip_id)]
        return equip_map_list

@sv.scheduled_job('interval', seconds=600)  # 十分钟轮询一次
@sv.on_fullmatch(('请求捐赠', '申请捐赠', '发起捐赠'))
async def on_farm_schedule(*args):
    global bot
    print("farm: 轮询 / 公会申请审批")
    # await query("accept")  # 先登录担任会长的农场号，看看有无加公会请求
    '''
    print("farm: 轮询 / 捐赠计时")
    clock = ([24] if free else [24, 8])
    for pcrid in binds:
        for i in clock:
            if nowtime() - binds[pcrid]["donate_last"] > i * 3600 and binds[pcrid]["donate_clock"] < i:
                await bot.send_private_msg(user_id=int(binds[pcrid]["qqid"]), message=f"来自 {house_name} 的消息：{binds[pcrid]['name']}可以发起新的捐赠了哦！\n距离上次捐赠已过{i}小时。")
                binds[pcrid]["donate_clock"] = i
                save_binds()
                break
    '''

    await master.refresh()
    print("farm: 轮询 / 捐赠装备")
    for slave in slaves:
        await slave.refresh()
        if slave.clan == 0:
            await master.invite_to_clan2(slave)
        elif slave.clan != master.clan:
            await bot.send_private_msg(user_id=acinfo["admin"], message=f'{slave.name}不在工会内')
            continue
        for equip in await slave.get_requests():
            if equip.viewer_id == slave.viewer_id: continue # 不响应自己的捐赠
            vid = str(equip.viewer_id)
            # if vid not in binds: continue  # 不响应不明人员
            if equip.donation_num >= equip.request_num: continue # 还没捐满
            
            equip_name = equip2name[str(100000 + int(equip.equip_id) % 10000)]
            # await bot.send_private_msg(user_id=int(binds[str(equip['viewer_id'])]["qqid"]), message=f"检测到 {equip.viewer_id} 的装备请求：{equip_name}({equip['equip_id']})")

            myinv = slave.get_inventory((eInventoryType.Equip, equip.equip_id))
            if myinv >= 2 and equip.user_donation_num == 0 and slave.donation_num <= 8:
                await slave.donate_equip(equip, 2)
                await bot.send_private_msg(user_id=acinfo["admin"], message=f'{slave.name}的装备{equip_name}已捐赠')
            if myinv < 30:
                msg = [f"{slave.name}的装备{equip_name}({equip['equip_id']})存量较少，剩余{myinv}。"]
                for quest in equip2quest(equip.equip_id):
                    if quest in slave.finishedQuest:
                        await slave.quest_skip_aware(quest, 1)
                myinv = slave.get_inventory((eInventoryType.Equip, equip.equip_id))
                msg.append(f"{slave.name}的装备{equip_name}({equip['equip_id']})刷取完成，剩余{myinv}。")
                await bot.send_private_msg(user_id=acinfo["admin"], message='\n'.join(msg))

@sv.scheduled_job('cron', hour='5')
async def on_nextday(*args):
    master._logged = False
    for slave in slaves:
        slave._logged = False

@sv.scheduled_job('cron', hour='23')
async def on_dayend(*args):  # 每天晚上23点领家园体、任务奖励、礼物箱
    global bot
    await _today_donate()
    for slave in slaves:
        await slave.receive_all()

'''
async def brush(bot, i, equip_id, ret=0):
    global flag_over_limit
    f = True
    msg = f"{acinfo['accounts'][i]['name']}(No.{i}) {acinfo['accounts'][i]['account']} -> {equip_id}"
    flag_over_limit = 1
    while (flag_over_limit == 1):
        res = await query("get_equip", i, forced_login=True, equip_id=equip_id)
        if type(res) == str:
            msg += f"\nFailed: {res}\n{acinfo['accounts'][i]['account']} {acinfo['accounts'][i]['password']}"
            f = False
            break
        elif res != True:
            msg += f"\nFailed"
            f = False
            break
        await query("present", i)
    if f == True:
        msg += "\nDone."
    if ret:
        return msg
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
'''

@on_command(f'validate{ordd}')
async def validate(session):
    global binds, validate, validating, captcha_lck, otto
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


@sv.on_prefix(("农场充值"))
async def on_farm_pay(bot, ev):
    if free:
        return
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    global binds, lck
    async with lck:
        qqid = str(ev['user_id'])
        pcrid = ev.message.extract_plain_text().strip().split()[0]
        value = int(ev.message.extract_plain_text().strip().split()[1])
        if pcrid == "":
            await bot.send_private_msg(user_id=ev.user_id, message=sv_help)
            return
        if pcrid[0] == "<" and pcrid[-1] == ">":
            pcrid = pcrid[1:-1]
        nam = ""
        try:
            nam = (await master.get_profile(pcrid)).user_info.user_name
        except:
            await bot.send_private_msg(user_id=ev.user_id, message="未找到玩家，请检查您的13位id！")
            return
        print(pcrid, value, nam)
        if pcrid in quits:
            quits.pop(pcrid)
            await bot.send_private_msg(user_id=ev.user_id, message=f"该账号曾请求退出农场，已删除旧请求。")

        if pcrid in binds_accept_pcrid:
            binds_accept_pcrid[pcrid] += value
        else:
            binds_accept_pcrid[pcrid] = value
        save_binds()

        await bot.send_private_msg(user_id=ev.user_id, message=f"pcrid={pcrid}\nname={nam}\n充值成功！当前捐赠装备余额：{binds_accept_pcrid[pcrid]}")


@sv.on_prefix(("加入农场"))
async def on_farm_bind(bot, ev):
    global binds
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
        nam = (await master.get_profile(pcrid)).user_info.user_name
    except:
        await bot.send_private_msg(user_id=ev.user_id, message="未找到玩家，请检查您的13位id！")
        return
    if not free:
        if pcrid not in binds_accept_pcrid:
            await bot.send_private_msg(user_id=ev.user_id, message=f"本农场为付费农场，请向主人获取授权！\n若需免费农场，请转向ebq申请。")
            return
        if binds_accept_pcrid[pcrid] <= 0:
            await bot.send_private_msg(user_id=ev.user_id, message="您的捐赠额度已用尽，请向主人重新购买！")
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
        await bot.send_private_msg(user_id=ev.user_id, message=f"pcrid={pcrid}\nname={nam}\n申请成功！" + "" if free else f"\n您的装备捐赠余额为 {binds_accept_pcrid[pcrid]} 个。\n" + "正在发起邀请...")
        await master.invite_to_clan(pcrid, '哈哈哈哈，寄汤来咯')

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
                await master.remove_member(pcrid)
                quits.pop(pcrid)
                save_binds()
                await bot.send_private_msg(user_id=ev.user_id, message=f"{pcrid}已退出农场")

async def _today_donate():
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
        await bot.send_private_msg(user_id=int(acinfo["admin"]), message="今日所有bot均未产生捐赠！")
        return
    msg = f"{last:2d} :"
    for i in donate:
        if i[1] != last:
            last = i[1]
            msg += f"\n{last:2d} :"
        msg += f" {acinfo['accounts'][i[0]]['name']}({i[0]})"
    await bot.send_private_msg(user_id=int(acinfo["admin"]), message=msg)


@sv.on_fullmatch(("今日捐赠", "查询捐赠"))
async def today_donate(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    await _today_donate()


@sv.on_fullmatch(("农场成员", "农场人员", "查询农场", "查询农场人员", "查询农场成员", "查询农场信息", "农场名单"))
async def query_farm_info(bot, ev):
    if str(ev.user_id) != str(acinfo["admin"]):
        return
    msg = []
    for account in binds:
        msg.append(f"{account} / {binds[account]['qqid']} / {binds[account]['name']} / {'' if free else binds_accept_pcrid[account]} / {(nowtime() - binds[account]['donate_last']) / 3600 :.1f}H")
    if not free:
        for account in binds_accept_pcrid:
            if account not in binds:
                msg.append(f"{account}(未进入农场) balance={binds_accept_pcrid[account]}")
    if msg != []:
        await bot.send_private_msg(user_id=ev.user_id, message=f'授权人员\npcrid / qqid / name /{"" if free else " balance /"} last\n' + "\n".join(msg))
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
        try:
            await master.remove_member(pcrid)
        except:
            pass
        else:
            await bot.send_private_msg(user_id=ev.user_id, message=f"{pcrid}已退出农场")
            await bot.send_private_msg(user_id=int(quits[pcrid]), message=f"您的pcr账号{pcrid}已被移出农场")
            quits.pop(pcrid)
            save_binds()
    else:
        try:
            await master.remove_member(pcrid)
        except:
            pass
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
                try:
                    await master.remove_member(pcrid)
                except:
                    pcrids_failed.append(pcrid)
                else:
                    qqid = int(quits[pcrid])
                    quits.pop(pcrid)
                    save_binds()
                    await bot.send_private_msg(user_id=qqid, message=f"您的pcr账号{pcrid}已被移出农场")
            if pcrids_failed == []:
                await bot.send_private_msg(user_id=ev.user_id, message="所有账号移出农场成功")
            else:
                await bot.send_private_msg(user_id=ev.user_id, message="以下账号移出农场失败：\n" + "\n".join(pcrids_failed))


@sv.scheduled_job('cron', hour='0')
async def on_newday():
    for account in acinfo["accounts"]:
        account["today_donate"] = 0
    save_acinfo()
