# Smart Auto Poster V3.3.0 - Fast Pass Production

## Goal
Post to healthy production destinations as quickly as Telegram safely allows, while moving slow/error destinations out of the clean first pass instead of letting one problem hold up the whole cycle.

## Changes
- Production campaign spread defaults to **0 minutes** instead of 20 minutes.
- Queue claim order is now **pending first**, then deferred/retry problem work.
- Successful sends use the configured `MIN_SEND_GAP_SECONDS` (default **3 seconds**) as an intentional inter-send pace rather than causing the next healthy destination to be deferred for pacing.
- Added `SEND_TIMEOUT_SECONDS` (default **45 seconds**). If Telegram does not return a conclusive acknowledgement inside the bound, the job becomes `UNCERTAIN` and the worker continues with untouched destinations.
- Send-timeout uncertainty never auto-retries and does not penalize destination/account health.
- Existing FloodWait, SlowMode, ambiguous acknowledgement, quarantine, circuit-breaker and authorization protections remain active.
- Production bootstrap and `SETUP_MAIN_PRODUCTION.ps1` now use zero spread by default.

## Operating behavior
A normal cycle is queued immediately. Healthy destinations are attempted one after another with a few seconds of pacing. Slow mode, cooldown, retry, deferred or ambiguous destinations leave the clean fast lane and are handled after untouched destinations according to their safe due times.
