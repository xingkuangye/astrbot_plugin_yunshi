from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from datetime import datetime, timezone, timedelta
from astrbot.utils.logger import logger
from PIL import Image, ImageFile
from botpy.http import Route
from io import BytesIO
import urllib.request
import requests
import hashlib
import random
import json

def js_parse_int(hex_str):
    """精确模拟 JavaScript 的 parseInt(hex_str, 16) 行为"""
    full_int = int(hex_str, 16)
    exp = full_int.bit_length() - 1
    if exp <= 52:
        return float(full_int)
    ulp = 2 ** (exp - 52)
    q = full_int // ulp
    lower = q * ulp
    upper = (q + 1) * ulp
    dl, du = full_int - lower, upper - full_int
    if dl < du:      return float(lower)
    elif du < dl:    return float(upper)
    else:            return float(lower if (lower//ulp) % 2 == 0 else upper)

@register("yunshi", "星星旁の旷野 Alin", "今日运势插件", "1.1.1")
class yunshi(Star):
    def __init__(self, context: Context, config: dict=None):
        super().__init__(context)
        self.text = [str(g) for g in config.get("text", []) or []]
        self.text_origin = config.get("text_origin")
        self.beta_config = config.get("beta_config")

    @filter.command("get_origin_message")
    async def get_origin_message(self, event: AstrMessageEvent, message_id: str):
        """[测试]获取 jrys 原始消息内容"""
        if not self.beta_config:
            return

        message_str = event.message_str
        if not "jrys" in message_str:
            return

        message = await self.get_kv_data(f"{message_id}originmessage", None)
        if message is None:
            yield event.plain_result(f"未找到原始消息内容（ID: {message_id}）。")
            return

        chain = event.plain_result(f"原始消息内容（ID: {message_id}）：\n\n{message}")
        # 再手动关掉 markdown
        chain.use_markdown_ = False
        yield chain

    # 处理今日运势指令
    # @param event AstrMessageEvent 消息事件对象
    # @return MessageEventResult 消息事件处理结果
    @filter.command("jrys",alias={'今日运势', '运势'})
    async def jrys(self, event: AstrMessageEvent):
        """今日运势指令，获取用户的今日运势"""
        try: 

            # 获取 openid，用于发送消息，并在消息中显示测试ID -> openid
            try:
                openid = event.message_obj.raw_message.group_openid # 如果是群聊消息，则使用群组的 group_openid
            except AttributeError:
                openid = event.message_obj.raw_message.author.user_openid # 如果是私聊消息，则使用用户的 user_openid


            # ─── 运势索引计算（精确对齐 Koishi/JS 版） ───
            # 1. 取今日零点时间戳（秒，不是毫秒） -> etime
            tz = timezone(timedelta(hours=8))
            now = datetime.now(tz)
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            etime = int(midnight.timestamp())

            # 2. 用用户的 member_openid 生成 user_id -> user_id
            if event.is_private_chat():
                member_openid = event.message_obj.raw_message.author.user_openid
            else:
                member_openid = event.message_obj.raw_message.author.member_openid
            hash_hex = hashlib.sha256(member_openid.encode()).hexdigest()
            # ✨ 模拟 JS Number 精度丢失
            user_js = js_parse_int(hash_hex)
            user_id = user_js % 100000001

            # 3. Koishi 风格时间因子：MD5(秒) → JS parseInt → % 1000000001 → /1000 -> time_md5_num
            time_md5 = hashlib.md5(str(etime).encode()).hexdigest()
            # ✨ 模拟 JS Number 精度丢失
            time_md5_js = js_parse_int(time_md5)
            time_md5_num = time_md5_js % 1000000001

            # 4. 加载运势数据并计算索引 -> result
            with open(self.text_origin, "r", encoding="utf-8") as f:
                data = json.load(f)
            idx = int(((time_md5_num / 1000) + user_id) * 277 % len(data))
            if idx < 0:
                idx = 0
            result = data[idx]


            # 获取随机图片 -> img_url
            random_picture = random.randint(1, 244)
            img_url = f"https://als.cn-nb1.rains3.com/passImage/{random_picture}.jpg"


            # 计算并压缩图片的宽高，确保在 Markdown 中显示时不会过大 -> w, h
            max_w, max_h = 200, 280
            saved_size = await self.get_kv_data(f"img_size{random_picture}", None)
            if not saved_size:
                with urllib.request.urlopen(img_url) as resp:
                    data = resp.read(1024) # 只读取前 1024 字节获取图片头，降低带宽消耗
                p = ImageFile.Parser()
                p.feed(data)
                if p.image:
                    w, h = p.image.size
                else: # 头信息不够，下载全图
                    resp = requests.get(img_url, timeout=10)
                    img = Image.open(BytesIO(resp.content))
                    w, h = img.size
                if w > max_w or h > max_h:
                    ratio = min(max_w / w, max_h / h)
                    w = int(w * ratio)
                    h = int(h * ratio)
                await self.put_kv_data(f"img_size{random_picture}", (w, h))
            else:
                w, h = saved_size


            # 组装 Markdown 消息 (私聊会自动过滤 <@{member_openid}>，所以在私聊中不会显示 @用户) -> message
            message =f"""<@{member_openid}>\n"""
            if self.text:
                for t in self.text:
                    message += f"**{t}**\n"
            message += f"""**✨您的今日运势为：✨**
    **🎊{result['fortuneSummary']}🎊**
    **{result['luckyStar']}**
    ```运势签文
    <{result['signText']}>
    {result['unsignText']}
    图片源自网络|如有侵权|请反馈删除
    仅供娱乐|相信科学|请勿迷信
    ```
    > ![img #{w}px #{h}px]({img_url})"""
            if self.beta_config:
                msg_id = await self.get_kv_data("now msg_id", 0) + 1
                await self.put_kv_data("now msg_id", msg_id)
                message += f"""
    ***
    > 您当前正在使用测试版本的AL_1S机器人
    > 如果您遇到了问题，请点击<qqbot-cmd-input text="/反馈 jrys.{msg_id} [在这里填写你想要反馈的内容]" show="反馈" reference="true" />
    > 如果您看到了不良信息，请点击<qqbot-cmd-input text="/举报 jrys.{msg_id} [在这里填写你想要举报的原因]" show="举报" reference="true" />
    > 感谢您的支持~
    > _测试ID：{openid}_"""
                await self.put_kv_data("jrys." + str(msg_id) + "originmessage", message)

            

            # 构造消息 payload，用于发送带按钮的 Markdown 消息 -> payload
            payload = {
                "msg_type": 2,
                "msg_id": event.message_obj.message_id,
                "markdown": {
                    "content": message
                },
                "keyboard": {
                    "content": {
                        # ✨今日运势 📋 菜单
                        "rows": [
                            {
                                "buttons": [
                                    {
                                        # 指令按钮：✨今日运势 -> /今日运势
                                        # 使用权限：所有人
                                        "render_data": {"label": "✨今日运势", "style": 1},
                                        "action": {
                                            "type": 2,
                                            "permission": {"type": 2},
                                            "data": "/今日运势"
                                        }
                                    },
                                    {
                                        # 指令按钮：🎲群友老婆 -> /群友老婆
                                        # 使用权限：所有人
                                        "render_data": {"label": "🎲群友老婆", "style": 1},
                                        "action": {
                                            "type": 2,
                                            "permission": {"type": 2},
                                            "data": "/群友老婆"
                                        }
                                    },
                                    {
                                        # 指令按钮：📋菜单 -> /菜单
                                        # 使用权限：所有人
                                        "render_data": {"label": "📋菜单", "style": 1},
                                        "action": {
                                            "type": 2,
                                            "permission": {"type": 2},
                                            "data": "/菜单"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
            

            # 直接调用QQ官方API发送，不使用 Astrbot 封装的消息发送函数
            # 这样可以确保消息中包含按钮和 Markdown 格式
            if event.is_private_chat():
                # 私聊 - 用 api._http.request 发送 POST 请求
                route = Route("POST", f"/v2/users/{openid}/messages")
                await event.bot.api._http.request(
                    route, 
                    json={
                        **payload
                    }
                )
            else:
                # 群聊 - 用 api.post_group_message 发送 POST 请求
                await event.bot.api.post_group_message(
                    group_openid=openid,
                    **payload
                )
        except Exception as e:
            logger.error(f"处理今日运势指令时出错: {e}")
            yield event.plain_result(f"爱丽丝出现了错误，请稍后再试。\n> 错误已自动反馈！")