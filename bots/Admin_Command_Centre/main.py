from __future__ import annotations
import json,secrets,sys,time,urllib.parse,urllib.request
from pathlib import Path
from admin_core import config,claim_admin,handle_command,parse_command,poster_progress_text

BOT_DIR=Path(__file__).resolve().parent
ROOT=BOT_DIR.parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from shared.vm_core.publisher import BotEventPublisher
publisher=BotEventPublisher("Admin_Command_Centre",ROOT)

MUTATING_COMMANDS={'backup','support','start','stop','restart','supervise','poster_start','poster_stop','poster_restart'}
API='https://api.telegram.org/bot{token}/{method}'
def api_call(token,method,payload=None,timeout=60):
    data=urllib.parse.urlencode(payload or {}).encode(); req=urllib.request.Request(API.format(token=token,method=method),data=data)
    with urllib.request.urlopen(req,timeout=timeout) as resp: return json.loads(resp.read().decode())
def send_message(token,chat_id,text): return api_call(token,'sendMessage',{'chat_id':chat_id,'text':text[:4000]},30)
def edit_message(token,chat_id,message_id,text): return api_call(token,'editMessageText',{'chat_id':chat_id,'message_id':message_id,'text':text[:4000]},30)
def self_test():
    cfg=config(); print('Admin Command Centre v0.3.0'); print('Token configured:',bool(cfg['token'])); print('Admin IDs configured:',bool(cfg['admin_ids'])); print('Mutations enabled:',cfg['allow_mutations']); return 0
def main():
    if '--self-test' in sys.argv: return self_test()
    cfg=config()
    if not cfg['token']: print('[CONFIG REQUIRED] VM_ADMIN_BOT_TOKEN is missing. Copy .env.example to .env and add the token locally.'); return 2
    me=api_call(cfg['token'],'getMe',{},30); username=me.get('result',{}).get('username','unknown'); print('[READY] VM Admin Command Centre @'+username)
    publisher.started(bot_username=username,mutations_enabled=cfg['allow_mutations'])
    claim_code=None
    if not cfg['admin_ids']:
        claim_code=secrets.token_hex(3).upper(); print('[CLAIM MODE] No admin is registered.'); print(f'[CLAIM CODE] Send /claim {claim_code} to @{username} from your Telegram account.'); print('[SECURITY] The claim code exists only for this local run.')
    print('[SECURITY] Mutations enabled:',cfg['allow_mutations'])
    offset=0; backoff=2
    progress_watch={}; progress_last={}
    while True:
        try:
            watch_active=bool(progress_watch)
            poll_timeout=3 if watch_active else 45
            result=api_call(cfg['token'],'getUpdates',{'timeout':poll_timeout,'offset':offset,'allowed_updates':json.dumps(['message'])},poll_timeout+10)
            for update in result.get('result',[]):
                offset=max(offset,int(update['update_id'])+1); msg=update.get('message') or {}; text=msg.get('text') or ''
                if not text.startswith('/'): continue
                uid=int((msg.get('from') or {}).get('id',0)); chat=int((msg.get('chat') or {}).get('id',0)); cmd,args=parse_command(text)
                if claim_code and cmd=='claim' and len(args)==1 and args[0].upper()==claim_code and (msg.get('chat') or {}).get('type')=='private':
                    claim_admin(uid); cfg=config(); claim_code=None
                    publisher.action('claim',actor_id=uid,target_type='service',target_id='Admin_Command_Centre',mutating=True,outcome='success')
                    send_message(cfg['token'],chat,'Admin access claimed successfully. Mutating commands remain disabled. Use /vm to begin.'); print('[CLAIMED] Admin Telegram user ID stored locally.'); continue
                response=handle_command(uid,text,cfg)
                target_id=args[0] if args and cmd in {'start','stop','restart'} else ('Smart_Auto_Poster_V2' if cmd.startswith('poster_') else 'Admin_Command_Centre')
                publisher.action(
                    cmd or 'unknown',
                    actor_id=uid,
                    target_type='service',
                    target_id=target_id,
                    mutating=cmd in MUTATING_COMMANDS,
                    outcome='denied' if response=='Access denied.' else ('blocked' if 'Mutating commands are disabled' in response else 'handled'),
                )
                sent=send_message(cfg['token'],chat,response)
                if response!='Access denied.' and cmd=='poster_progress':
                    message_id=int((sent.get('result') or {}).get('message_id') or 0)
                    if message_id:
                        progress_watch[chat]=message_id; progress_last[chat]=response
                elif response!='Access denied.' and cmd=='poster_progress_off':
                    progress_watch.pop(chat,None); progress_last.pop(chat,None)
            for chat,message_id in list(progress_watch.items()):
                text=poster_progress_text()
                if text!=progress_last.get(chat):
                    edit_message(cfg['token'],chat,message_id,text)
                    progress_last[chat]=text
                if '\nRun: COMPLETE' in text:
                    progress_watch.pop(chat,None); progress_last.pop(chat,None)
            backoff=2
        except KeyboardInterrupt:
            publisher.stopped('keyboard_interrupt')
            return 0
        except Exception as exc:
            publisher.incident('telegram_poll_error','Admin Command Centre polling error',severity='WARNING',error_type=type(exc).__name__)
            print('[WARN]',type(exc).__name__,exc); time.sleep(backoff); backoff=min(backoff*2,60)
if __name__=='__main__': raise SystemExit(main())
