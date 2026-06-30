# ChonkyFlipper Dashboard

The control dashboard for the ChonkyFlipper rig. Single-page app built with
Vite, Tailwind CSS v4 and DaisyUI v5, talking to the Flask backend over `/api`.

## Stack

- **Vite** -- dev server + production bundler
- **Tailwind CSS v4** -- styling (CSS-first config, no `tailwind.config.js`)
- **DaisyUI v5** -- components + the `chonky` / `chonky-dark` themes
- **tailwindcss-motion** (Rombo) -- entrance / toast animations
- **Font Awesome** -- icon set (no emoji)

Plain ES modules, no UI framework. Each hardware module is one file under
`src/modules/` that renders into the main view.

## Develop

### Prerequisites

- Node.js >= 20
- npm (ships with Node.js)

### Setup

```bash
cd frontend
npm install
```

### Run the dev server

The dev server runs at `http://localhost:5173` and proxies `/api` so the
dashboard can talk to the Flask backend.

To hit the Pi's backend directly (no need to run Flask locally):

```bash
CHONKY_API=http://192.168.178.78 npm run dev
```

Or if the Pi moves to a different address:

```bash
CHONKY_API=http://192.168.178.99 npm run dev
```

Without `CHONKY_API` the proxy defaults to `http://localhost:5000`, which is
useful if you run the Flask backend locally for pure-UI work.

## Build

```bash
npm run build      # outputs static files to dist/
npm run preview    # serve the production build locally
```

On the Pi, `update.sh` runs `npm run build` and copies `dist/` into
`/var/www/html`, where nginx serves it and proxies `/api` to gunicorn.

## Layout

```
src/
  main.js          app shell: header, sidebar, router, theme
  state.js         shared polling store (/status, /system, /network, /version)
  api.js           fetch wrappers (get / post / delete)
  toast.js         toast + long-running task notifications
  ui.js            shared presentational fragments
  util.js          escaping + small DOM/format helpers
  style.css        Tailwind entry, theme definitions, component classes
  modules/
    dashboard.js   overview (system, modules, network)
    wifi.js        scan, audit, probes, attack, capture
    bluetooth.js   BLE + Classic + Deep + Spoof + Capture (tabbed)
    ir.js          library browser + recorded signals (record/send/delete)
    subghz.js      CC1101 record / replay
    nfc.js         PN532 read / write / clone
    badusb.js      DuckyScript payloads
    zigbee.js      devices, events, bridge info
    settings.js    network, wifi connect, power, system update
```

## Themes

Two themes are defined in `src/style.css` via DaisyUI `@plugin` blocks and
derived from the mascot logo (orange `#f88828`, peach, ink). The header toggle
switches between them and persists the choice in `localStorage`.
