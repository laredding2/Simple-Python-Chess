# Simple Python Chess

A desktop chess game in Python where you play against the [Stockfish](https://stockfishchess.org/) engine, with difficulty set by ELO rating.

## Features

- Click-to-move board with legal-move hints, last-move and check highlighting
- Load any Stockfish binary (auto-detected if it's on your PATH)
- Difficulty slider from **≈600 to 3190 ELO**, plus one-click presets (Beginner → GM) and a full-strength mode
- Adjustable engine think time
- Play as White, Black, or Random
- Undo, board flip, promotion picker, move list in SAN
- Detects checkmate, stalemate, repetition, 50-move rule and insufficient material
- Remembers your engine path and settings between sessions

## How the ELO setting works

| ELO range | Method |
|---|---|
| Stockfish's native range (1320–3190 on SF 16+) | Stockfish's built-in calibrated limiter (`UCI_LimitStrength` + `UCI_Elo`) |
| Below the native floor (shown with ≈) | Approximation using `Skill Level` 0–5 and a shallow search depth |
| Full strength | No limit |

The exact native range is read from the engine you load, so older Stockfish versions adjust automatically. ELO changes take effect on the engine's next move.

## Setup

1. Install Python 3.9+ and the dependency:
   ```bash
   pip install -r requirements.txt
   ```
   On Linux you may also need Tk: `sudo apt install python3-tk`
2. Download Stockfish for your OS from <https://stockfishchess.org/download/> and unzip it anywhere
   (or drop the binary in this folder, or install it via `brew install stockfish` / `apt install stockfish`).
3. Run:
   ```bash
   python chess.py
   ```
4. If Stockfish wasn't found automatically, click **Load Stockfish...** and pick the executable.

## License

MIT
