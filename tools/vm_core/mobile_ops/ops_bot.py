from __future__ import annotations
import asyncio, logging, os, secrets, subprocess, time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ops_core import status_summary, offline_names

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STATE=HERE/"state"; STATE.mkdir(parents=True,exist_ok=True)
ENV=HERE/".env"
ADMIN=STATE/"admin_id.txt"
CLAIM=STATE/"claim_code.txt"
LOGDIR=ROOT/"shared"/"logs"/"VM_Core"; LOGDIR.mkdir(parents=True,exist_ok=True)

def load_env():
    out={}
    if ENV.exists():
        for raw in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k,v=raw.split("=",1); out[k.strip()]=v.strip().strip('"').strip("'")
    return out

TOKEN=load_env().get("BOT_TOKEN","")
if not TOKEN:
    raise SystemExit("VM Ops token not configured.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOGDIR/"mobile_ops.log",encoding="utf-8")]
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log=logging.getLogger("vm_mobile_ops")

def vm(*args: str, timeout=120) -> str:
    cp=subprocess.run(
        ["cmd.exe","/c",str(ROOT/"VM.cmd"),*args],
        cwd=ROOT,text=True,capture_output=True,timeout=timeout,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    )
    return (cp.stdout+"\n"+cp.stderr).strip()

def admin_id():
    try:return int(ADMIN.read_text().strip())
    except:return None

def claim_code():
    if CLAIM.exists(): return CLAIM.read_text().strip()
    c=secrets.token_hex(3).upper(); CLAIM.write_text(c); return c

def private_admin(update:Update)->bool:
    return bool(
        update.effective_chat and update.effective_chat.type=="private"
        and update.effective_user and admin_id()==update.effective_user.id
    )

async def deny(update):
    if update.effective_message:
        await update.effective_message.reply_text("Not authorised.")

async def claim(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type!="private": return
    if admin_id():
        await update.effective_message.reply_text("Admin already registered.")
        return
    supplied=" ".join(context.args).strip().upper()
    if supplied==claim_code():
        ADMIN.write_text(str(update.effective_user.id))
        CLAIM.unlink(missing_ok=True)
        await update.effective_message.reply_text("âœ… VM Ops Control claimed.\nUse /status to begin.")
    else:
        await update.effective_message.reply_text("Invalid claim code.")

async def status(update,context):
    if not private_admin(update): return await deny(update)
    await update.effective_message.reply_text(status_summary(await asyncio.to_thread(vm,"status")))

async def doctor(update,context):
    if not private_admin(update): return await deny(update)
    out=await asyncio.to_thread(vm,"doctor")
    await update.effective_message.reply_text(("ðŸ©º VM DOCTOR\n"+out)[-3900:])

async def restartfailed(update,context):
    if not private_admin(update): return await deny(update)
    await asyncio.to_thread(vm,"restart-failed")
    await asyncio.sleep(8)
    await update.effective_message.reply_text(status_summary(await asyncio.to_thread(vm,"status")))

async def startall(update,context):
    if not private_admin(update): return await deny(update)
    await asyncio.to_thread(vm,"start")
    await asyncio.sleep(8)
    await update.effective_message.reply_text(status_summary(await asyncio.to_thread(vm,"status")))

async def backup(update,context):
    if not private_admin(update): return await deny(update)
    out=await asyncio.to_thread(vm,"backup",timeout=300)
    await update.effective_message.reply_text(("ðŸ’¾ BACKUP\n"+out)[-3900:])

pending={}
async def restartall(update,context):
    if not private_admin(update): return await deny(update)
    code=secrets.token_hex(2).upper()
    pending[("restart",update.effective_user.id)]=(code,time.time()+60)
    await update.effective_message.reply_text(f"Confirm within 60 sec:\n/confirm_restart {code}")

async def confirm_restart(update,context):
    if not private_admin(update): return await deny(update)
    key=("restart",update.effective_user.id); item=pending.get(key)
    supplied=" ".join(context.args).strip().upper()
    if not item or time.time()>item[1] or supplied!=item[0]:
        return await update.effective_message.reply_text("Confirmation expired/invalid.")
    pending.pop(key,None)
    await asyncio.to_thread(vm,"stop")
    await asyncio.sleep(3)
    await asyncio.to_thread(vm,"start")
    await asyncio.sleep(10)
    await update.effective_message.reply_text(status_summary(await asyncio.to_thread(vm,"status")))

async def help_cmd(update,context):
    if not private_admin(update): return await deny(update)
    await update.effective_message.reply_text(
        "ðŸ“± VM OPS CONTROL\n"
        "/status â€” all bots\n"
        "/restartfailed â€” recover stopped bots\n"
        "/startall â€” start bots\n"
        "/restartall â€” confirmed full restart\n"
        "/doctor â€” diagnostics\n"
        "/backup â€” safe backup\n"
        "/help â€” this menu"
    )

last_alert={}
async def monitor(app:Application):
    await asyncio.sleep(15)
    while True:
        try:
            before=await asyncio.to_thread(vm,"status")
            offline=offline_names(before)
            if offline:
                await asyncio.to_thread(vm,"restart-failed")
                await asyncio.sleep(15)
                after=await asyncio.to_thread(vm,"status")
                remain=offline_names(after)
                aid=admin_id()
                now=time.time()
                if remain and aid:
                    key=",".join(sorted(remain))
                    if now-last_alert.get(key,0)>1800:
                        await app.bot.send_message(aid,"âš ï¸ VM AUTO-RECOVERY FAILED\n"+", ".join(remain)+" still offline.")
                        last_alert[key]=now
        except Exception as e:
            log.exception("monitor error")
        await asyncio.sleep(60)

async def post_init(app:Application):
    asyncio.create_task(monitor(app))

def main():
    app=Application.builder().token(TOKEN).post_init(post_init).build()
    for name,fn in [
        ("claim",claim),("status",status),("doctor",doctor),("restartfailed",restartfailed),
        ("startall",startall),("backup",backup),("restartall",restartall),
        ("confirm_restart",confirm_restart),("help",help_cmd),("start",help_cmd)
    ]:
        app.add_handler(CommandHandler(name,fn))
    if not admin_id():
        print(f"[CLAIM CODE] Send /claim {claim_code()} to your VM Ops Control bot.")
    print("[READY] VM Ops Control")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
