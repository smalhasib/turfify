# Cloudflare Tunnel — Demo workflow

Use this to expose the locally-running stack to a client over real HTTPS
under `demo.turf.smalhasib.com` and `api.demo.turf.smalhasib.com` without
deploying to the VPS.

## One-time setup

1. Install cloudflared:
   ```bash
   brew install cloudflared
   ```

2. Authenticate (browser flow):
   ```bash
   cloudflared tunnel login
   ```

3. Create the tunnel (records the UUID + credentials file path):
   ```bash
   cloudflared tunnel create turf-demo
   ```

4. Copy the example config and fill in your tunnel UUID + credentials path:
   ```bash
   mkdir -p ~/.cloudflared
   cp scripts/cloudflared/turf-demo.yml.example ~/.cloudflared/turf-demo.yml
   $EDITOR ~/.cloudflared/turf-demo.yml
   ```

5. Add DNS records at Cloudflare for `smalhasib.com`:
   - `demo.turf.smalhasib.com` → CNAME `<uuid>.cfargotunnel.com` (proxied)
   - `api.demo.turf.smalhasib.com` → CNAME `<uuid>.cfargotunnel.com` (proxied)

6. Add `demo.turf.smalhasib.com` to **Firebase Console → Authentication →
   Settings → Authorized domains** so OTP works during the demo.

## Per-demo run

```bash
make demo            # boots backend, frontend, seeds demo state
cloudflared tunnel run turf-demo   # in another terminal
```

The client opens `https://demo.turf.smalhasib.com` from anywhere, hitting
your laptop. When done, Ctrl-C the tunnel; the local stack keeps running.

## Tear down

If you regenerate the tunnel:
```bash
cloudflared tunnel delete turf-demo
```
DNS records can stay; they'll go silent until the tunnel is recreated.
