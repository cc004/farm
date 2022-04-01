from typing import overload
from .clientbase import *

class pcrclient(dataclient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def get_profile(self, user: int):
        req = ProfileGetRequest()
        req.target_viewer_id = user
        return await self._request(req)
    
    async def accept_clan_invitation(self, clan: int, page: 0):
        req = UserInviteClanListRequest()
        req.page = page
        for inv in (await self._request(req)).list:
            if inv.clan_id == clan:
                req = ClanJoinRequest()
                req.clan_id = clan
                req.from_invite = inv.invite_id
                return await self._request(req)
        else:
            return None

    async def remove_member(self, user: int):
        req = ClanRemoveRequest()
        req.clan_id = self.clan
        req.viewer_id = user
        return await self._request(req)
    
    @overload
    async def invite_to_clan(self, user: int, msg: str = ''):
        req = ClanInviteRequest()
        req.invite_message = msg
        req.invited_viewer_id = user
        return await self._request(req)
    
    @overload
    async def invite_to_clan(self, other: "pcrclient"):
        await self.invite_to_clan(other.viewer_id)
        for page in range(5):
            if await other.accept_clan_invitation(self.clan, page):
                return
    
    async def create_clan(self, name: str = "默认名字", description: str = "默认描述", 
        cond: eClanJoinCondition = eClanJoinCondition.ONLY_INVITATION,
        guildLine: eClanActivityGuideline = eClanActivityGuideline.GUIDELINE_1):
        req = ClanCreateRequest()
        req.activity = guildLine
        req.clan_battle_mode = 0
        req.clan_name = name
        req.description = description
        req.join_condition = cond
        await self._request(req)

    async def get_clan_info(self):
        if self.clan == 0: return None
        req = ClanInfoRequest()
        req.clan_id = self.clan
        req.get_user_equip = 0
        return (await self._request(req)).clan
    
    async def donate_equip(self, request: EquipRequests, times: int):
        req = EquipDonateRequest()
        req.clan_id = self.clan
        req.current_equip_num = self.get_inventoy((eInventoryType.Equip, request.equip_id))
        req.donation_num = times
        req.message_id = request.message_id
        return await self._request(req)
    
    async def quest_skip(self, quest: int, times: int):
        req = QuestSkipRequest()
        req.current_ticket_num = self.get_inventoy((eInventoryType.Item, 23001)),
        req.quest_id = quest,
        req.random_count = times
        return await self._request(req)
    
    async def get_requests(self):
        req = ClanChatInfoListRequest()
        req.clan_id = self.clan
        req.count = 100
        req.direction = 1 # RequestDirection.UP
        req.search_date = "2099-12-31"
        req.start_message_id = 0
        req.update_message_ids = []
        req.wait_interval = 3
        return (await self._request(req)).equip_requests
    
    async def recover_stamina(self):
        req = ShopRecoverStaminaRequest()
        req.current_currency_num = self.jewel
        return await self._request(req)
    
    async def receive_all(self):
        await self._request(RoomReceiveItemAllRequest())
        req = PresentReceiveAllRequest()
        req.time_filter = -1
        await self._request(req)
        req = MissionAcceptRequest()
        req.type = 1
        await self._request(req)
    
    async def quest_skip_aware(self, quest: int, times: int):
        if self.stamina < 80:
            await self.recover_stamina()
        await self.quest_skip(quest, times)