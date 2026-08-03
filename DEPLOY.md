# Deploying at the restaurant — "Release Yan Liu"

Goal: **self-hosting mode.** The guest orders on an iPad at reception, pays there
(card/Swish on Stripe, or physically on the Zettle reader), gets a number on
paper and on the TV, and nobody stands at a till. Same flow whether they eat here
or take it away.

---

## 1. The flow, end to end

```
                       ┌── pays now (Stripe) ──────────► kitchen starts
guest at reception iPad│
  äta här / ta med ────┤                    ┌──► reception taps "Betald"
  picks food           └── pays at Zettle ──┤    (Zettle = the certified register)
  gets NUMBER          reader beside iPad   └──► kitchen starts
       │
       ├──► paper: guest slip (number) + kitchen ticket + bag label (takeaway)
       ├──► sushi iPad / hot-kitchen iPad — only their own dishes
       ├──► TV: number moves Tillagas → Klar
       └──► reception iPad: to table 4, or in a bag for "106 · Yan"
```

**"No kassa" means no cashier, not no cash register.** A card payment taken on
the premises must still go through a certified Swedish kassaregister — that is
what the Zettle reader is. Stripe is a payment processor, not a register. So:

| Lane | Who registers the sale | Staff needed |
|---|---|---|
| Pays on the iPad (Stripe) | Distance sale, we record it | **Nobody** |
| Pays on the Zettle reader | Zettle (certified) | One tap to confirm |

The Stripe lane is the one that actually releases Yan. Keep the Zettle reader for
guests who insist on paying physically — it costs one tap, not a person at a till.

⚠️ **Still open (5 minutes with your accountant):** a guest sitting *in* the
restaurant paying via Stripe on your own iPad is the grey zone in prop 2016/17:49
— it can be read as an on-premises sale that belongs in a certified register.
Takeaway prepaid online is clearly exempt. Until that's confirmed, you can switch
the lanes per shop: `services.pay_online` / `services.pay_in_store` in the spec.

---

## 2. Which machine is the server

You offered: Mac mini 2021, MacBook Pro 2015, Raspberry Pi 4, Dell Optiplex
Micro, and two VPS.

| Hardware | Verdict |
|---|---|
| **Mac mini 2021 (M1)** | ✅ **The server.** Silent, ~7 W, no fan noise in a dining room, real SSD, runs for years unattended. |
| **Dell Optiplex Micro** | ✅ **Cold spare.** Debian + same stack + last night's DB. Also where you test upgrades before touching the mini. |
| **VPS #1** | ✅ **Off-site backup target**, and later the host for the multi-tenant version when you sell this to other restaurants. |
| **VPS #2** | ✅ **Staging.** Same code, fake menu, safe to break. |
| **Raspberry Pi 4** | ❌ Not as the server. SD-card corruption on power loss is a normal restaurant event; you'd lose a service. Fine as a spare display driver. |
| **MacBook Pro 2015** | ❌ Retire. Swelling battery + lid/sleep behaviour make it the wrong thing to hide in a cupboard. |

### Why the Mac mini and not a VPS

The screens that must never fail are the in-store ones. On the mini they run over
your **LAN**, so if the broadband drops, the kiosk, both kitchen iPads, reception
and the TV keep working — you just can't take card payments until it's back.
Put the database on a VPS instead and a broadband blip blinds the kitchen mid-service.

The cost: guests ordering from home go through a Cloudflare Tunnel, so their
orders stop during an outage. That's the cheaper failure.

---

## 3. Network

- **Wire the Mac mini and the Star printer with ethernet.** Wifi for the server
  is the single most common cause of "the kitchen screen froze".
- **DHCP reservation** for the mini on the router, e.g. `192.168.1.50`. The iPads
  bookmark that address — it must never change.
- iPads and Apple TV on the **5 GHz** band. Put guest wifi on a separate SSID so
  a full dining room doesn't starve the kitchen.

## 4. Mac mini configuration

```bash
# never sleep, come back after a power cut
sudo pmset -a sleep 0 disksleep 0 displaysleep 0 autorestart 1 womp 1

git clone https://github.com/bluehawana/vibe-business-llm.git ~/Projects/vibe-business-llm
cd ~/Projects/vibe-business-llm
cp .env.example .env      # then edit — see §5
./run.sh                  # installs deps, binds 0.0.0.0:8100, prints the LAN URL
```

Run it as a service so it survives reboots — `~/Library/LaunchAgents/se.ichiban.vibe.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>se.ichiban.vibe</string>
  <key>ProgramArguments</key>
  <array><string>/Users/USER/Projects/vibe-business-llm/run.sh</string></array>
  <key>WorkingDirectory</key><string>/Users/USER/Projects/vibe-business-llm</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/tmp/vibe.err.log</string>
</dict></plist>
```

```bash
launchctl load -w ~/Library/LaunchAgents/se.ichiban.vibe.plist
```

## 5. Stripe keys — you add these, not me

Never paste a secret key into a chat. On the mini:

```bash
cd ~/Projects/vibe-business-llm && open -e .env
```

```
STRIPE_SECRET_KEY=sk_test_...        # test key first, always
STRIPE_WEBHOOK_SECRET=whsec_...
BASE_URL=https://order.ichiban.biz
```

Then in the Stripe Dashboard add a webhook endpoint. Three settings matter and
the rest is cosmetic:

| Field | Value | Why |
|---|---|---|
| Endpoint URL | `https://order.ichiban.biz/api/stripe/webhook` | must be public HTTPS — do the tunnel first |
| Events | **only `checkout.session.completed`** | the one event we act on; 233 events is noise |
| Payload style | **Snapshot** | a thin payload omits the object, so the order id never arrives |

**More than one signing secret?** Test mode and live mode have different ones,
and rotating a secret means accepting the old and new one for a while. Comma-separate
them — an event is accepted if any of them signed it:

```
STRIPE_WEBHOOK_SECRET=whsec_test_one,whsec_live_two
```

Enable Swish / Apple Pay / Klarna under Payment methods — dashboard toggles, no
code. Test with `4242 4242 4242 4242` before switching to `sk_live_`.

## 6. Public URL (Cloudflare Tunnel, free)

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create ichiban
cloudflared tunnel route dns ichiban order.ichiban.biz
cloudflared tunnel run --url http://localhost:8100 ichiban
```

Gives HTTPS on `order.ichiban.biz` with no port forwarding and no static IP.

Staff screens are behind a login, so the tunnel can expose everything safely.

## 6b. Staff login

One shared password per installation — `VIBE_STAFF_PASSWORD` in `.env`. `run.sh`
generates one on first start and prints it; each staff iPad logs in once and
stays logged in for 180 days. Changing the password logs every device out.

| Behind the login | Open to guests |
|---|---|
| `/panel` `/builder` `/kiosk` | `/site` and `/api/site/…/checkout` |
| `/kitchen` `/counter` `/pass` | `/site/…/success` |
| `/admin/…` and their APIs | `/receipt/<order-id>` (unguessable id) |
| | `/display` — the TV has no keyboard, and shows only numbers |

**With no password set the staff screens return 503** rather than serving. They
fail closed on purpose: "I'll set it later" is how a kitchen display ends up on
the open internet.

The thermal printer can't fill in a login form, so it gets its own key derived
from the same password. The exact URL is shown on `/panel` — rotating the
password rotates the printer key too.

## 7. Assign the devices

Open `/panel/<project-id>` on the mini — it lists every screen with its URL.

| Device | URL | Notes |
|---|---|---|
| **iPad 1 — reception (ordering)** | `/kiosk/<id>` | Guided Access on, Home-Screen app |
| **iPad 1 — Zettle hand-off** | `/counter/<id>` | Shows the amount to charge, one tap = paid |
| **iPad 2 — reception (hand-out)** | `/pass/<id>` | To table 4 · or bag "106 · Yan" |
| **iPad 3 — sushi bar** | `/kitchen/<id>?station=sushi` | Sushi dishes only |
| **iPad 4 — hot kitchen** | `/kitchen/<id>?station=kitchen` | Hot dishes only |
| **TV** (see §7b) | `/display/<id>` | Preparing → Ready, Max-style |
| **Table QR codes** | `/site/<id>?table=NR` | Skips the eat-in question |
| **Guest phones** | `https://order.ichiban.biz/site/<id>` | |

Add each to the Home Screen (Share → "Lägg till på hemskärmen") so it runs
full-screen. Use **Guided Access** on the kiosk so guests can't wander off the page.

## 7b. Getting the board onto the TV

**Apple TV cannot do this.** tvOS has no web browser and never has — don't plan
around one. Pick one of these instead:

| Option | Cost | Notes |
|---|---|---|
| **Raspberry Pi 4 → HDMI** | owned | ✅ Recommended. Boots into the board, survives power cuts, no one touches it again. |
| Smart TV's own browser | free | Samsung/LG have one. Most forget the page on power-cycle, so someone re-opens it daily. |
| Fire TV Stick 4K + Silk | ~500 kr | Plug-and-play, remembers its page. Buy this if you'd rather not touch Linux. |
| Apple TV + AirPlay mirroring | owned | Works, but burns an iPad as a video source and drops when it sleeps. Demo only. |

Raspberry Pi setup — Raspberry Pi OS Desktop, autologin to desktop:

```bash
sudo apt install -y chromium-browser unclutter
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/vibe-display.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Vibe order board
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble --check-for-update-interval=31536000 \
  http://192.168.1.50:8100/display/<project-id>
X-GNOME-Autostart-enabled=true
EOF
```

Then `sudo raspi-config` → Display → Screen Blanking → **off**. Power the Pi from
the TV's USB port so it comes up with the TV.

`/display` is deliberately outside the staff login — a signage box has no
keyboard to type a password on, and the board shows nothing but order numbers.

## 8. Printing

A **Star CloudPRNT** printer at reception polls the mini and prints, per order:

1. **Guest slip** — the big number, what they ordered, and whether to pay at the reader
2. **Kitchen ticket** — number, station items, table or takeaway
3. **Bag label** (takeaway only) — number + first name, to stick on the bag

| Printer | Poll URL |
|---|---|
| Reception (one printer, everything) | `http://192.168.1.50:8100/api/cloudprnt/<id>` |
| Kitchen-only printer | `…/api/cloudprnt/<id>?role=kitchen` |
| Guest-slip-only printer | `…/api/cloudprnt/<id>?role=guest` |

No driver, no printer IP to configure on our side — the printer calls us.
A Bluetooth-only Star bonded to Zettle can't do this; use `/receipt/<order-id>`
and the browser print dialog until you have a network Star.

## 9. Backups

The whole business is one SQLite file, `data/vibe.db`.

```bash
# hourly local snapshot
sqlite3 data/vibe.db ".backup $HOME/backups/vibe-$(date +%H).db"
# nightly off-site
rsync -az ~/backups/ vps1:/srv/ichiban-backups/
```

Put both in `crontab -e`. Restoring is copying the file back — that's the whole
disaster-recovery plan, and the Dell can be serving within ten minutes.

## 10. Going live checklist

- [ ] Menu seeded and checked (`python -m scripts.seed_ichiban`, then `/builder/<id>`)
- [ ] Mac mini on ethernet with a reserved IP, sleep disabled, launchd service up
- [ ] Stripe **test** key: order → pay → appears on the kitchen iPad only after payment
- [ ] Zettle lane: order → appears on `/counter` with the right amount → tap → kitchen
- [ ] Printer emits all three documents; numbers match the TV
- [ ] Staff paths protected (see §6) **before** the tunnel is public
- [ ] Backups running and one restore rehearsed
- [ ] Accountant has confirmed the eat-in-pays-on-iPad question (§1)
- [ ] Swap in the live Stripe key; do one real 1 kr order end to end
