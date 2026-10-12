"""Bot selection with explicit key grants; reuse mature transport implementations."""
from wechat_bridge.wechat.protocol import BridgeError
from wechat_bridge.channels.feishu.adapter import Feishu
from wechat_bridge.channels.registry import DEFAULT, FEISHU_DEFAULT
from wechat_bridge.wechat.pairing import Pairing
import asyncio


class Channels:
    def __init__(self, bridge, pairing=None, run_workers=False):
        self.wechat = bridge
        self.store,self.registry = bridge.store,bridge.store.bots
        self.run_workers = run_workers
        self.adapters = {DEFAULT:bridge}
        self.pairings = {DEFAULT:pairing or Pairing(bridge,run_workers=run_workers)}
        self.starts = {}

    @property
    def feishu(self):
        return self.adapter(FEISHU_DEFAULT)

    def adapter(self, bot_id):
        bot = self.registry.get(bot_id)
        if bot_id not in self.adapters:
            if bot['platform']=='feishu':
                self.adapters[bot_id] = Feishu(self.store,bot_id=bot_id)
            else:
                from wechat_bridge.services.bridge import Bridge
                from wechat_bridge.channels.wechat_store import WeChatStore
                self.adapters[bot_id] = Bridge(WeChatStore(self.store,bot_id))
                self.pairings[bot_id] = Pairing(self.adapters[bot_id],run_workers=self.run_workers and bool(bot['enabled']))
        return self.adapters[bot_id]

    def pairing(self, bot_id):
        self.adapter(bot_id)
        if bot_id not in self.pairings: raise BridgeError(422,'bot_is_not_wechat')
        return self.pairings[bot_id]

    async def send(self, channel=None,bot_id=None, **kwargs):
        bot = self.registry.select(kwargs['identity'],bot_id,channel)
        result = await self.adapter(bot['id']).send(**kwargs)
        return dict(result,bot_id=bot['id'],channel=bot['platform'])

    def delivery(self, channel, key, caller, cid,bot_id=None):
        bot = self.registry.select(caller,bot_id,channel,sending=False)
        adapter = self.adapter(bot['id'])
        if bot['platform']=='wechat':
            store = adapter.store
            if not store.account():
                return {'status': 'not_found'}
            row = store.client_receipt(key, caller, cid)
            return dict(adapter.public_receipt(row),bot_id=bot['id'],channel='wechat') if row else {'status':'not_found'}
        return adapter.delivery(key,caller,cid)

    def bots(self, identity=None):
        ids = self.registry.grants(identity.id)['bot_ids'] if identity else None
        result=[]
        for bot in self.registry.list():
            if ids is not None and bot['id'] not in ids: continue
            adapter = self.adapter(bot['id'])
            status = adapter.status() if bot['platform']=='feishu' else adapter.store.status()
            result.append(dict(bot,status=status))
        return result

    def status(self,identity=None):
        items = self.bots(identity)
        return {platform:next((item['status'] for item in items if item['platform']==platform),{'enabled':False})
                for platform in ('wechat','feishu')}

    def task_bot(self,cid,tid,identity=None):
        row = self.store.portal.tasks.row(cid,tid)
        message = self.store.db.execute('SELECT bot_id FROM chat_messages WHERE outgoing_key=?',(row['outgoing_key'],)).fetchone()
        bot_id = (message[0] if message else None) or DEFAULT
        if identity: self.registry.select(identity,bot_id,sending=False)
        return self.registry.get(bot_id)

    async def sync_task(self,cid,tid):
        bot = self.task_bot(cid,tid)
        return await self.adapter(bot['id']).sync_task(cid,tid) if bot['platform']=='feishu' else None

    async def reconcile(self):
        if not self.run_workers: return
        for bot in self.registry.list():
            if bot['platform']!='wechat': continue
            driver=self.adapter(bot['id'])
            self.pairings[bot['id']].run_workers=bool(bot['enabled'])
            if not bot['enabled']:
                start=self.starts.pop(bot['id'],None)
                if start: start.cancel(); await asyncio.gather(start,return_exceptions=True)
                await driver.stop_workers()
            elif not driver.tasks and (bot['id'] not in self.starts or self.starts[bot['id']].done()):
                async def start(driver=driver):
                    async with driver.lock: await driver.start()
                self.starts[bot['id']]=asyncio.create_task(start())

    async def close(self):
        for task in self.starts.values(): task.cancel()
        await asyncio.gather(*self.starts.values(),return_exceptions=True)
        for id,adapter in self.adapters.items():
            if id!=DEFAULT: await adapter.close()
        for id,pairing in self.pairings.items():
            if id!=DEFAULT: await pairing.close()
