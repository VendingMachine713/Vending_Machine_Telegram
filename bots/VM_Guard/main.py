import logging, secrets, json, sys
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from envutil import load_env
from core import score_message, FloodTracker

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from shared.vm_core.publisher import BotEventPublisher
from shared.vm_core.security import owner_authorized, central_owner_ids
publisher=BotEventPublisher("VM_Guard",ROOT)

ENV=load_env(BASE/".env")
TOKEN=ENV.get("BOT_TOKEN","").strip()
if not TOKEN:
    raise SystemExit("BOT_TOKEN missing. Run CONFIGURE_MISSING_BOTS.bat from the project root.")
STATE=BASE/"state"; STATE.mkdir(exist_ok=True)
ADMIN_FILE=STATE/"admin_id.txt"; CLAIM_FILE=STATE/"claim_code.txt"
CONFIG_FILE=STATE/"config.json"
flood=FloodTracker()

def config():
    if CONFIG_FILE.exists():
        try: return json.loads(CONFIG_FILE.read_text())
        except: pass
    return {"mutations_enabled":False,"risk_threshold":60,"flood_delete":False}
def save_config(c): CONFIG_FILE.write_text(json.dumps(c,indent=2))
def admin_id():
    try:return int(ADMIN_FILE.read_text().strip())
    except:return None
def claim_code():
    if CLAIM_FILE.exists():return CLAIM_FILE.read_text().strip()
    c=secrets.token_hex(3).upper(); CLAIM_FILE.write_text(c); return c

def is_admin(update):
    if not update.effective_user:
        return False
    uid=update.effective_user.id
    return bool((admin_id() and uid==admin_id()) or owner_authorized(uid,ROOT))

def private_admin(update):
    return bool(
        update.effective_chat and update.effective_chat.type=="private"
        and is_admin(update)
    )

async def deny(update):
    if update.effective_chat and update.effective_chat.type=="private" and update.effective_message:
        await update.effective_message.reply_text("Not authorised.")

async def claim(update,context):
    if not update.effective_chat or update.effective_chat.type!="private":
        return
    if central_owner_ids(ROOT):
        await update.effective_message.reply_text("Central VM owner identity is configured; local claim is disabled.")
        return
    if admin_id():
        await update.effective_message.reply_text("Admin already claimed.")
        return
    if not update.effective_user:
        return
    if " ".join(context.args).strip().upper()==claim_code():
        ADMIN_FILE.write_text(str(update.effective_user.id)); CLAIM_FILE.unlink(missing_ok=True)
        await update.effective_message.reply_text("✅ VM Guard admin claimed. Safe monitor mode is ON.")
    else: await update.effective_message.reply_text("Invalid claim code.")

async def guard(update,context):
    if not private_admin(update): return await deny(update)
    c=config()
    await update.effective_message.reply_text(
        f"🛡 VM Guard v1.2\nMode: {'ACTIVE' if c['mutations_enabled'] else 'MONITOR ONLY'}\nRisk threshold: {c['risk_threshold']}"
    )
async def enable(update,context):
    if not private_admin(update): return await deny(update)
    c=config(); c["mutations_enabled"]=True; save_config(c)
    await update.effective_message.reply_text("⚠️ Active moderation enabled.")
async def disable(update,context):
    if not private_admin(update): return await deny(update)
    c=config(); c["mutations_enabled"]=False; save_config(c)
    await update.effective_message.reply_text("✅ Monitor-only mode enabled.")
async def health(update,context):
    if not private_admin(update): return await deny(update)
    await guard(update,context)

async def inspect(update,context):
    m=update.effective_message; u=update.effective_user; chat=update.effective_chat
    if not m or not u or not chat or u.is_bot: return
    text=m.text or m.caption or ""
    risk,reasons=score_message(text)
    flooded,count=flood.hit(chat.id,u.id)
    if flooded: risk=max(risk,70); reasons.append(f"flood ({count} msgs)")
    c=config()
    if risk < c.get("risk_threshold",60): return
    publisher.signal(
        "guard_risk_elevated",
        subject_type="chat",
        subject_id=chat.id,
        score=risk,
        confidence=0.9,
        rationale="VM Guard risk threshold exceeded",
        evidence={"reason_codes": list(reasons), "message_id": m.message_id},
        flooded=bool(flooded),
    )
    recipients=set(central_owner_ids(ROOT))
    if admin_id(): recipients.add(admin_id())
    who="@"+u.username if u.username else u.full_name
    preview=text.replace("\n"," ")[:280]
    for aid in recipients:
        try:
            await context.bot.send_message(aid, f"⚠️ VM Guard alert\nChat: {getattr(chat,'title',chat.id)}\nUser: {who}\nRisk: {risk}/100\nReasons: {', '.join(reasons)}\n\n{preview}")
        except: pass
    if c.get("mutations_enabled"):
        try: await m.delete()
        except: pass

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("claim",claim))
    app.add_handler(CommandHandler("guard",guard))
    app.add_handler(CommandHandler("guard_on",enable))
    app.add_handler(CommandHandler("guard_off",disable))
    app.add_handler(CommandHandler("health",health))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,inspect))
    if not admin_id() and not central_owner_ids(ROOT): print(f"[CLAIM CODE] Send /claim {claim_code()} to this bot in a PRIVATE chat from your Telegram account.")
    print("[READY] VM Guard v1.2 — passive in groups, central/private-owner control only")
    publisher.started(mode="active" if config().get("mutations_enabled") else "monitor_only",control_scope="private_owner_only",central_owner_configured=bool(central_owner_ids(ROOT)))
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except BaseException as exc:
        publisher.incident("process_crash","VM Guard exited unexpectedly",severity="CRITICAL",error_type=type(exc).__name__)
        raise
    finally:
        publisher.stopped("polling_stopped")

if __name__=="__main__": main()
