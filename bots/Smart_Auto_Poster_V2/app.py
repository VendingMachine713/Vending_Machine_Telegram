from pathlib import Path
import sys

BOT_DIR = Path(__file__).resolve().parent
ROOT = BOT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.vm_core.publisher import BotEventPublisher
from smart_autoposter.cli import main

publisher = BotEventPublisher("Smart_Auto_Poster_V2", ROOT)

if __name__ == "__main__":
    publisher.started(entrypoint="app.py")
    try:
        main()
    except KeyboardInterrupt:
        publisher.stopped("keyboard_interrupt")
        raise
    except BaseException as exc:
        publisher.incident(
            "process_crash",
            "Smart Auto Poster exited with an unhandled exception",
            severity="CRITICAL",
            error_type=type(exc).__name__,
        )
        raise
    else:
        publisher.stopped("normal")
