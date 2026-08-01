# Deploying at the restaurant — "Release Yan Liu"

Goal: run dine-in + takeaway ordering, kitchen routing, and a guest TV board on
the hardware you already have — **Mac mini + iPads + Apple TV** — so the counter
no longer needs a person standing at the till during quiet hours.

## Your current setup → what changes

| You have now | Role after | Notes |
|---|---|---|
| **Wix site** (ichiban.biz) | **Replaced** | Wix is a brochure that can't take prepaid orders or route to the kitchen. Menu migrates into Vibe Business; keep the domain, point it at the new guest site. |
| **Zettle on iPad + Star printer** | **Kept** for staff/card-present + cash | Zettle still takes tap/chip cards at the counter and prints its receipt. We don't replace card hardware. |
| **Mac mini** | **The server** | Runs Vibe Business; serves every iPad and the Apple TV over the restaurant wifi. |
| **iPads** | Kiosk + kitchen screens | One at the counter (self-order kiosk), one per kitchen station (sushi bar / hot line). |
| **Apple TV** | Guest order board | Safari → the `/display` page; shows order numbers going Tillagas → Klar. |

## Payments — two clean lanes

1. **Self-service (phone / table QR / counter kiosk) → Stripe, prepaid.** Card,
   Swish, Apple Pay. Fully automated, no staff needed. *This is the lane that
   releases Yan* — the customer orders and pays themselves; the kitchen only
   ever sees paid orders.
2. **Staff-assisted / cash → Zettle, as today.** Nothing to change.

## First-time setup (once, on the Mac mini)

```bash
git clone https://github.com/bluehawana/vibe-business-llm.git
cd vibe-business-llm
cp .env.example .env          # add STRIPE_SECRET_KEY (test first), VIBE_MODEL
./run.sh                       # installs deps, prints the LAN address
```

`run.sh` binds to `0.0.0.0:8100` and prints something like
`http://192.168.1.50:8100`. That IP is what the iPads and Apple TV use.

## Assign each device (open the control panel first)

On the Mac mini open **`/panel/<project-id>`** — it lists every screen and which
device opens it. Then on each device open, replacing the host with the Mac mini's IP:

| Device | Open this |
|---|---|
| Counter iPad | `http://<ip>:8100/kiosk/<id>` |
| Sushi bar iPad | `http://<ip>:8100/kitchen/<id>?station=sushi` |
| Hot line iPad | `http://<ip>:8100/kitchen/<id>?station=kitchen` |
| Apple TV (Safari) | `http://<ip>:8100/display/<id>` |
| Table QR codes | `http://<ip>:8100/site/<id>?table=NR` (print one per table) |
| Guest phones | your domain → `/site/<id>` |

Add each iPad URL to the Home Screen (Safari → Share → "Lägg till på hemskärmen")
and it runs full-screen like an app. Use **Guided Access** on the kiosk iPad so
guests can't leave the page.

## Kitchen printing (optional)

The kitchen works off the **iPad screens** — no printer needed. If you want paper
bongs too, a **Star CloudPRNT-capable** printer (wifi/LAN) can poll the Mac mini
at `POST /api/cloudprnt/<id>` and print each paid order automatically — no driver,
no pairing. (A Bluetooth-only Star bonded to Zettle can't be driven this way; use
the on-screen kitchen display, or the browser-print receipt page.)

## Going live checklist

- [ ] Menu migrated from ichiban.biz and checked in the builder
- [ ] Stripe **test** key working: place a test order (`4242 4242 4242 4242`) →
      appears on the kitchen iPad only after payment
- [ ] Table QR codes printed and placed
- [ ] Kiosk iPad in Guided Access at the counter
- [ ] Apple TV showing the guest board
- [ ] Swap Stripe test key for the live key; do one real 1 kr order end-to-end
- [ ] **Before handling cash through the new flow:** confirm Skatteverket
      kassaregister / kontrollenhet requirements (card/Swish-prepaid may be
      exempt; cash is not). See open item in the project notes.
