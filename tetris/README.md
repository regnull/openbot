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

Open `index.html` directly in a browser, or serve the directory with any static file server:

```bash
cd tetris
python3 -m http.server 8000
```

Then visit <http://localhost:8000>.

## Controls

- `←` / `→`: Move piece
- `↑` or `X`: Rotate piece
- `↓`: Soft drop
- `Space`: Hard drop / start game
- `P`: Pause / resume
