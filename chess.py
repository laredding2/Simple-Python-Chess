#!/usr/bin/env python3
"""
Stockfish Chess - play against Stockfish with adjustable ELO.

Requires:  pip install chess
Plus a Stockfish binary: https://stockfishchess.org/download/
"""

import glob
import json
import os
import queue
import random
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import chess
import chess.engine

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

SQ = 72                      # square size in pixels
BOARD_PX = SQ * 8
LIGHT, DARK = "#f0d9b5", "#b58863"
LAST_LIGHT, LAST_DARK = "#cdd26a", "#aaa23a"
SEL_COLOR = "#7fa650"
CHECK_COLOR = "#e05050"
DOT_COLOR = "#3a5a2a"

GLYPHS = {
    chess.KING: "\u265A", chess.QUEEN: "\u265B", chess.ROOK: "\u265C",
    chess.BISHOP: "\u265D", chess.KNIGHT: "\u265E", chess.PAWN: "\u265F",
}

APPROX_MIN_ELO = 600         # below Stockfish's native floor we approximate
PRESETS = [("Beginner", 800), ("Casual", 1200), ("Club", 1600),
           ("Expert", 2000), ("Master", 2400), ("GM", 2800)]

COMMON_PATHS = [
    "/usr/games/stockfish", "/usr/bin/stockfish", "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
]


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
def load_settings():
    defaults = {"stockfish_path": "", "elo": 1500, "full_strength": False,
                "think_time": 1.0, "color": "White"}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            defaults.update(json.load(f))
    except (OSError, ValueError):
        pass
    return defaults


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def find_stockfish():
    """Try to locate a Stockfish binary automatically."""
    found = shutil.which("stockfish")
    if found:
        return found
    for p in COMMON_PATHS:
        if os.path.isfile(p):
            return p
    for p in glob.glob(os.path.join(APP_DIR, "stockfish*")):
        if os.path.isfile(p) and (p.endswith(".exe") or os.access(p, os.X_OK)):
            return p
    return ""


# ----------------------------------------------------------------------------
# Engine wrapper
# ----------------------------------------------------------------------------
class EngineManager:
    def __init__(self):
        self.engine = None
        self.path = ""
        self.name = ""
        self.elo_min, self.elo_max = 1320, 3190
        self._lock = threading.Lock()

    @property
    def loaded(self):
        return self.engine is not None

    def load(self, path):
        self.close()
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self.path = path
        self.name = self.engine.id.get("name", os.path.basename(path))
        opt = self.engine.options.get("UCI_Elo")
        if opt is not None:
            self.elo_min, self.elo_max = int(opt.min), int(opt.max)

    def close(self):
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        self.engine = None

    def _configure(self, elo, full_strength):
        opts = self.engine.options
        cfg = {}
        if full_strength:
            if "UCI_LimitStrength" in opts:
                cfg["UCI_LimitStrength"] = False
            if "Skill Level" in opts:
                cfg["Skill Level"] = 20
        elif elo >= self.elo_min and "UCI_Elo" in opts:
            # Stockfish's own calibrated ELO limiter
            cfg["UCI_LimitStrength"] = True
            cfg["UCI_Elo"] = int(elo)
            if "Skill Level" in opts:
                cfg["Skill Level"] = 20
        else:
            # Below the native floor: Skill Level + shallow depth (approximate)
            if "UCI_LimitStrength" in opts:
                cfg["UCI_LimitStrength"] = False
            if "Skill Level" in opts:
                cfg["Skill Level"] = self._sub_floor_skill(elo)
        self.engine.configure(cfg)

    def _sub_floor_fraction(self, elo):
        span = max(1, self.elo_min - APPROX_MIN_ELO)
        return min(1.0, max(0.0, (elo - APPROX_MIN_ELO) / span))

    def _sub_floor_skill(self, elo):
        return round(self._sub_floor_fraction(elo) * 5)          # 0..5

    def _limit(self, elo, full_strength, think_time):
        if not full_strength and elo < self.elo_min:
            depth = 1 + round(self._sub_floor_fraction(elo) * 4)  # 1..5
            return chess.engine.Limit(time=min(think_time, 0.5), depth=depth)
        return chess.engine.Limit(time=think_time)

    def best_move(self, board, elo, full_strength, think_time):
        with self._lock:
            if self.engine is None:
                raise RuntimeError("No engine loaded")
            self._configure(elo, full_strength)
            result = self.engine.play(board, self._limit(elo, full_strength, think_time))
            return result.move


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class ChessApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Stockfish Chess")
        self.root.resizable(False, False)

        self.settings = load_settings()
        self.em = EngineManager()
        self.board = chess.Board()
        self.player_color = chess.WHITE
        self.flipped = False
        self.selected = None
        self.thinking = False
        self.game_id = 0
        self.results = queue.Queue()

        self.piece_font = self._pick_piece_font()
        self._build_ui()
        self._try_autoload()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._poll_results)
        self.new_game()

    # ---------- setup ----------
    def _pick_piece_font(self):
        families = set(tkfont.families(self.root))
        for name in ("Segoe UI Symbol", "DejaVu Sans", "Noto Sans Symbols2",
                     "Arial Unicode MS", "FreeSerif", "Symbola"):
            if name in families:
                return (name, int(SQ * 0.62))
        return ("TkDefaultFont", int(SQ * 0.62))

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid()

        self.canvas = tk.Canvas(main, width=BOARD_PX, height=BOARD_PX,
                                highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="n")
        self.canvas.bind("<Button-1>", self.on_click)

        side = ttk.Frame(main, padding=(12, 0, 0, 0))
        side.grid(row=0, column=1, sticky="n")

        # Engine
        eng = ttk.LabelFrame(side, text="Engine", padding=8)
        eng.grid(sticky="ew", pady=(0, 8))
        self.engine_label = ttk.Label(eng, text="No engine loaded", width=32)
        self.engine_label.grid(row=0, column=0, sticky="w")
        ttk.Button(eng, text="Load Stockfish...", command=self.choose_engine)\
            .grid(row=1, column=0, sticky="w", pady=(6, 0))

        # Difficulty
        diff = ttk.LabelFrame(side, text="Difficulty", padding=8)
        diff.grid(sticky="ew", pady=(0, 8))
        self.elo_var = tk.IntVar(value=int(self.settings["elo"]))
        self.full_var = tk.BooleanVar(value=bool(self.settings["full_strength"]))
        self.elo_text = ttk.Label(diff, text="", font=("TkDefaultFont", 11, "bold"))
        self.elo_text.grid(row=0, column=0, columnspan=3, sticky="w")
        self.elo_scale = tk.Scale(diff, from_=APPROX_MIN_ELO, to=3190,
                                  orient="horizontal", resolution=50,
                                  showvalue=False, length=240,
                                  variable=self.elo_var,
                                  command=lambda _=None: self._update_elo_label())
        self.elo_scale.grid(row=1, column=0, columnspan=3, sticky="ew")
        for i, (name, elo) in enumerate(PRESETS):
            ttk.Button(diff, text=f"{name}\n{elo}", width=9,
                       command=lambda e=elo: self._set_elo(e))\
                .grid(row=2 + i // 3, column=i % 3, padx=1, pady=1)
        ttk.Checkbutton(diff, text="Full strength (no limit)",
                        variable=self.full_var,
                        command=self._update_elo_label)\
            .grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(diff, text="Think time per move (s):")\
            .grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.time_var = tk.DoubleVar(value=float(self.settings["think_time"]))
        tk.Scale(diff, from_=0.1, to=5.0, resolution=0.1, orient="horizontal",
                 length=240, variable=self.time_var)\
            .grid(row=6, column=0, columnspan=3, sticky="ew")

        # Game
        game = ttk.LabelFrame(side, text="Game", padding=8)
        game.grid(sticky="ew", pady=(0, 8))
        self.color_var = tk.StringVar(value=self.settings["color"])
        for i, c in enumerate(("White", "Black", "Random")):
            ttk.Radiobutton(game, text=c, value=c, variable=self.color_var)\
                .grid(row=0, column=i, sticky="w")
        btns = ttk.Frame(game)
        btns.grid(row=1, column=0, columnspan=3, pady=(6, 0))
        ttk.Button(btns, text="New Game", command=self.new_game).grid(row=0, column=0, padx=2)
        ttk.Button(btns, text="Undo", command=self.undo).grid(row=0, column=1, padx=2)
        ttk.Button(btns, text="Flip", command=self.flip).grid(row=0, column=2, padx=2)

        # Status + moves
        self.status = ttk.Label(side, text="", wraplength=260,
                                font=("TkDefaultFont", 10, "bold"))
        self.status.grid(sticky="w", pady=(0, 6))
        self.moves_text = tk.Text(side, width=34, height=10, state="disabled",
                                  font=("Courier", 10), wrap="word")
        self.moves_text.grid(sticky="ew")

        self._update_elo_label()

    def _try_autoload(self):
        path = self.settings.get("stockfish_path") or ""
        if not (path and os.path.isfile(path)):
            path = find_stockfish()
        if path:
            self._load_engine(path, quiet=True)

    # ---------- engine ----------
    def choose_engine(self):
        ftypes = [("Executables", "*.exe"), ("All files", "*")] if os.name == "nt" \
            else [("All files", "*")]
        path = filedialog.askopenfilename(title="Select Stockfish binary",
                                          filetypes=ftypes)
        if path:
            self._load_engine(path)
            if self.em.loaded and not self.thinking:
                self._maybe_engine_turn()

    def _load_engine(self, path, quiet=False):
        self._cancel_thinking()
        try:
            self.em.load(path)
        except Exception as ex:
            self.em.close()
            self.engine_label.config(text="No engine loaded")
            if not quiet:
                messagebox.showerror("Engine error", f"Couldn't start engine:\n{ex}")
            return
        self.settings["stockfish_path"] = path
        self.engine_label.config(text=self.em.name)
        self.elo_scale.config(to=self.em.elo_max)
        if self.elo_var.get() > self.em.elo_max:
            self.elo_var.set(self.em.elo_max)
        self._update_elo_label()
        self._update_status()

    def _set_elo(self, elo):
        self.full_var.set(False)
        self.elo_var.set(min(elo, self.em.elo_max))
        self._update_elo_label()

    def _update_elo_label(self):
        if self.full_var.get():
            self.elo_text.config(text="ELO: Full strength")
            self.elo_scale.config(state="disabled")
            return
        self.elo_scale.config(state="normal")
        elo = self.elo_var.get()
        approx = "\u2248" if elo < self.em.elo_min else ""
        self.elo_text.config(text=f"ELO: {approx}{elo}")

    # ---------- game flow ----------
    def new_game(self):
        self._cancel_thinking()
        self.board.reset()
        self.selected = None
        choice = self.color_var.get()
        if choice == "Random":
            self.player_color = random.choice([chess.WHITE, chess.BLACK])
        else:
            self.player_color = chess.WHITE if choice == "White" else chess.BLACK
        self.flipped = self.player_color == chess.BLACK
        self.refresh()
        self._maybe_engine_turn()

    def undo(self):
        self._cancel_thinking()
        if not self.board.move_stack:
            return
        self.board.pop()
        while self.board.move_stack and self.board.turn != self.player_color:
            self.board.pop()
        self.selected = None
        self.refresh()
        self._maybe_engine_turn()

    def flip(self):
        self.flipped = not self.flipped
        self.draw_board()

    def _cancel_thinking(self):
        self.game_id += 1           # any in-flight engine result becomes stale
        self.thinking = False

    def _maybe_engine_turn(self):
        if (self.em.loaded and not self.board.is_game_over(claim_draw=True)
                and self.board.turn != self.player_color):
            self._start_engine()

    def _start_engine(self):
        self.thinking = True
        self._update_status()
        args = (self.game_id, self.board.copy(), self.elo_var.get(),
                self.full_var.get(), float(self.time_var.get()))
        threading.Thread(target=self._engine_worker, args=args, daemon=True).start()

    def _engine_worker(self, gid, board, elo, full, think_time):
        try:
            move = self.em.best_move(board, elo, full, think_time)
            self.results.put(("move", gid, move))
        except Exception as ex:
            self.results.put(("error", gid, str(ex)))

    def _poll_results(self):
        try:
            while True:
                kind, gid, payload = self.results.get_nowait()
                if gid != self.game_id:
                    continue        # stale (new game / undo happened)
                self.thinking = False
                if kind == "move" and payload in self.board.legal_moves:
                    self.board.push(payload)
                elif kind == "error":
                    messagebox.showerror("Engine error", payload)
                self.refresh()
        except queue.Empty:
            pass
        self.root.after(50, self._poll_results)

    # ---------- input ----------
    def on_click(self, event):
        if self.thinking or self.board.is_game_over(claim_draw=True):
            return
        if not self.em.loaded:
            self.status.config(text="Load a Stockfish binary to start playing.")
            return
        if self.board.turn != self.player_color:
            return
        sq = self.square_at(event.x, event.y)
        if sq is None:
            return
        piece = self.board.piece_at(sq)

        if self.selected is None or sq == self.selected:
            self.selected = sq if (sq != self.selected and piece
                                   and piece.color == self.player_color) else None
            self.draw_board()
            return
        if piece and piece.color == self.player_color:
            self.selected = sq
            self.draw_board()
            return

        move = chess.Move(self.selected, sq)
        moving = self.board.piece_at(self.selected)
        if (moving and moving.piece_type == chess.PAWN
                and chess.square_rank(sq) in (0, 7)
                and chess.Move(self.selected, sq, promotion=chess.QUEEN) in self.board.legal_moves):
            promo = self.ask_promotion()
            if promo is None:
                return
            move = chess.Move(self.selected, sq, promotion=promo)

        self.selected = None
        if move in self.board.legal_moves:
            self.board.push(move)
            self.refresh()
            self._maybe_engine_turn()
        else:
            self.draw_board()

    def ask_promotion(self):
        win = tk.Toplevel(self.root)
        win.title("Promote to")
        win.transient(self.root)
        win.resizable(False, False)
        choice = {"piece": None}

        def pick(pt):
            choice["piece"] = pt
            win.destroy()

        for i, pt in enumerate((chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)):
            tk.Button(win, text=GLYPHS[pt], font=(self.piece_font[0], 32), width=2,
                      command=lambda p=pt: pick(p)).grid(row=0, column=i, padx=4, pady=6)
        win.grab_set()
        self.root.wait_window(win)
        return choice["piece"]

    # ---------- coordinates ----------
    def square_at(self, x, y):
        f, r = x // SQ, 7 - y // SQ
        if not (0 <= f < 8 and 0 <= r < 8):
            return None
        if self.flipped:
            f, r = 7 - f, 7 - r
        return chess.square(f, r)

    def square_xy(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        if self.flipped:
            f, r = 7 - f, 7 - r
        return f * SQ, (7 - r) * SQ

    # ---------- drawing ----------
    def refresh(self):
        self.draw_board()
        self._update_moves()
        self._update_status()

    def draw_board(self):
        c = self.canvas
        c.delete("all")
        last = self.board.peek() if self.board.move_stack else None
        check_sq = self.board.king(self.board.turn) if self.board.is_check() else None
        targets = set()
        if self.selected is not None:
            targets = {m.to_square for m in self.board.legal_moves
                       if m.from_square == self.selected}

        for sq in chess.SQUARES:
            x, y = self.square_xy(sq)
            light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
            color = LIGHT if light else DARK
            if last and sq in (last.from_square, last.to_square):
                color = LAST_LIGHT if light else LAST_DARK
            if sq == self.selected:
                color = SEL_COLOR
            if sq == check_sq:
                color = CHECK_COLOR
            c.create_rectangle(x, y, x + SQ, y + SQ, fill=color, outline="")

        # coordinates
        for i in range(8):
            f = 7 - i if self.flipped else i
            r = i if self.flipped else 7 - i
            c.create_text(i * SQ + SQ - 6, BOARD_PX - 8, text="abcdefgh"[f],
                          font=("TkDefaultFont", 8, "bold"), fill="#5a4630")
            c.create_text(6, i * SQ + 9, text=str(r + 1),
                          font=("TkDefaultFont", 8, "bold"), fill="#5a4630")

        # pieces
        for sq, piece in self.board.piece_map().items():
            x, y = self.square_xy(sq)
            cx, cy = x + SQ / 2, y + SQ / 2 + 2
            glyph = GLYPHS[piece.piece_type]
            fill, edge = ("#ffffff", "#222222") if piece.color else ("#111111", "#dddddd")
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                c.create_text(cx + dx, cy + dy, text=glyph, font=self.piece_font, fill=edge)
            c.create_text(cx, cy, text=glyph, font=self.piece_font, fill=fill)

        # legal move markers
        for sq in targets:
            x, y = self.square_xy(sq)
            if self.board.piece_at(sq) or sq == self.board.ep_square:
                c.create_oval(x + 3, y + 3, x + SQ - 3, y + SQ - 3,
                              outline=DOT_COLOR, width=4)
            else:
                r = SQ * 0.15
                c.create_oval(x + SQ / 2 - r, y + SQ / 2 - r, x + SQ / 2 + r,
                              y + SQ / 2 + r, fill=DOT_COLOR, outline="")

    def _update_moves(self):
        b = chess.Board()
        parts = []
        for i, m in enumerate(self.board.move_stack):
            if i % 2 == 0:
                parts.append(f"{i // 2 + 1}.")
            parts.append(b.san(m))
            b.push(m)
        self.moves_text.config(state="normal")
        self.moves_text.delete("1.0", "end")
        self.moves_text.insert("1.0", " ".join(parts))
        self.moves_text.see("end")
        self.moves_text.config(state="disabled")

    def _update_status(self):
        outcome = self.board.outcome(claim_draw=True)
        if outcome:
            if outcome.winner is None:
                reason = outcome.termination.name.replace("_", " ").title()
                text = f"Draw - {reason}"
            else:
                who = "You win" if outcome.winner == self.player_color else "Stockfish wins"
                text = f"Checkmate! {who}."
        elif not self.em.loaded:
            text = "Load a Stockfish binary to start playing."
        elif self.thinking:
            text = "Stockfish is thinking..."
        elif self.board.turn == self.player_color:
            text = "Your move" + (" - you're in check!" if self.board.is_check() else "")
        else:
            text = "Stockfish to move"
        self.status.config(text=text)

    # ---------- shutdown ----------
    def on_close(self):
        self.settings.update({
            "elo": self.elo_var.get(), "full_strength": self.full_var.get(),
            "think_time": round(float(self.time_var.get()), 1),
            "color": self.color_var.get(),
        })
        save_settings(self.settings)
        self._cancel_thinking()
        self.em.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    ChessApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
