# Neon Tetris

A browser-based Tetris clone built with plain HTML, CSS, and JavaScript. It runs entirely in the browser with no backend or build step.

## Features

- Falling tetromino gameplay on a 10x20 board
- Left/right movement, rotation, soft drop, and hard drop
- Line clearing with classic-style scoring
- Level and speed progression every 10 cleared lines
- Next piece preview
- Pause, game over detection, and restart
- Responsive neon arcade UI with documented controls

## Run locally

Install the development dependency and start the local dev server:

```bash
cd tetris
npm install
npm run dev
```

Then open the URL printed by Vite, usually <http://localhost:5173>.

You can also open `index.html` directly in a browser, or serve the directory with any static file server:

```bash
python3 -m http.server 8000
```

Then visit <http://localhost:8000>.

## Controls

- `←` / `→`: Move piece
- `↑` or `X`: Rotate piece
- `↓`: Soft drop
- `Space`: Hard drop / start game
- `P`: Pause / resume
