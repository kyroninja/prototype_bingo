"""
Prototype Bingo
===============

A small, fully working bingo board built with pygame.

Controls
--------
* Click a cell ............ mark / unmark it
* "Edit Text" button ...... toggle edit mode, then click any cell to retype its label
* "Background Image" ...... pick an image file to use as the background (needs tkinter)
* "Reset Marks" ........... clear all marks (the FREE centre stays marked)
* "Shuffle" .............. shuffle the cell labels once per app run and clear marks
* Keyboard shortcuts ...... E = edit mode, B = background, R = reset, Esc = leave edit mode

While the text-entry box is open:
    Enter  -> save
    Esc    -> cancel
    Delete -> clear the box
"""

import json
import math
import os
import random
import pygame

# --------------------------------------------------------------------------
# Optional tkinter (used only for the "choose background image" file dialog)
# --------------------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import filedialog
    TK_OK = True
except Exception:                                    # pragma: no cover
    TK_OK = False


# --------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------
BG_TOP          = (26, 28, 46)
BG_BOTTOM       = (11, 12, 20)
PANEL_ALPHA     = (8, 9, 16, 160)

CELL_FACE       = (244, 246, 252)
CELL_FACE_HOVER = (255, 255, 255)
CELL_MARKED     = (228, 66, 92)
CELL_MARKED_HOV = (250, 100, 122)
CELL_TEXT       = (28, 30, 44)
CELL_TEXT_MARK  = (255, 252, 252)

BUTTON          = (58, 78, 150)
BUTTON_HOVER    = (84, 108, 196)
BUTTON_EDIT     = (196, 132, 40)
BUTTON_EDIT_HOV = (224, 160, 62)

WHITE           = (255, 255, 255)
GOLD            = (255, 214, 74)

DISABLED       = (70, 74, 92)
DISABLED_TEXT  = (150, 155, 170)

MAX_CELL_CHARS  = 120

# Save file lives next to the script so it survives reruns
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bingo_save.json")

# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def wrap_text(text, font, max_width):
    """Break *text* into lines that fit inside *max_width* pixels."""
    max_width = max(1, max_width)
    lines = []

    for paragraph in str(text).split("\n"):
        words = paragraph.split(" ")
        current = ""

        for word in words:
            # A single word that is wider than the cell: chop it into pieces.
            while font.size(word)[0] > max_width and len(word) > 1:
                i = len(word) - 1
                while i > 1 and font.size(word[:i])[0] > max_width:
                    i -= 1
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:i])
                word = word[i:]

            trial = word if not current else current + " " + word
            if font.size(trial)[0] <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word

        lines.append(current)

    return lines or [""]


# --------------------------------------------------------------------------
# The game
# --------------------------------------------------------------------------
class BingoApp:
    def __init__(self):
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.init()
        pygame.display.set_caption("Prototype Bingo")
        self.screen = pygame.display.set_mode((760, 880), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.running = True

        # ---------------- board data ----------------
        letters = ["B", "I", "N", "G", "O"]
        starts = [1, 16, 31, 46, 61]
        self.texts = [[f"{letters[c]}{starts[c] + r}" for c in range(5)]
                      for r in range(5)]
        self.texts[2][2] = "FREE"

        self.marked = [[False] * 5 for _ in range(5)]
        self.marked[2][2] = True

        # ---------------- interaction state ----------------
        self.edit_mode = False
        self.editing = None            # (row, col) while the typing box is open
        self.input_text = ""
        self.shuffle_used = False

        # ---------------- background ----------------
        self.bg_image = None
        self._bg_scaled = None
        self._bg_size = None
        self._grad = None
        self._grad_size = None

        # ---------------- caches / layout ----------------
        self.font_cache = {}
        self.fit_cache = {}
        self.buttons = {}
        self.board_rect = pygame.Rect(0, 0, 0, 0)
        self.cell_size = 0.0
        self._layout_size = None

        self.toast_msg = ""
        self.toast_until = 0

        self._cursor_hand = False

        self.load_state()

        self.update_layout()

    # ======================================================================
    # Layout
    # ======================================================================
    def update_layout(self):
        W, H = self.screen.get_size()

        if self._layout_size != (W, H):
            self._layout_size = (W, H)
            self.fit_cache.clear()

        margin, gap, btn_h, status_h = 24, 12, 50, 46

        avail_w = W - 2 * margin
        top = margin + status_h + gap
        avail_h = H - top - margin - btn_h - gap

        size = int(max(120, min(avail_w, avail_h)))
        bx = (W - size) // 2
        by = top + max(0, (avail_h - size) // 2)

        self.board_rect = pygame.Rect(bx, by, size, size)
        self.cell_size = size / 5.0

        bw = (W - 2 * margin - 3 * gap) // 4
        y = H - margin - btn_h
        self.buttons = {
            "bg":    pygame.Rect(margin, y, bw, btn_h),
            "text":  pygame.Rect(margin + bw + gap, y, bw, btn_h),
            "reset": pygame.Rect(margin + 2 * (bw + gap), y, bw, btn_h),
            "shuffle": pygame.Rect(margin + 3 * (bw + gap), y, bw, btn_h),
        }

    def cell_rect(self, r, c):
        br, cs = self.board_rect, self.cell_size
        return pygame.Rect(br.x + c * cs + 3, br.y + r * cs + 3,
                           cs - 6, cs - 6)

    def cell_at(self, pos):
        br = self.board_rect
        if not br.collidepoint(pos):
            return None
        c = int((pos[0] - br.x) / self.cell_size)
        r = int((pos[1] - br.y) / self.cell_size)
        if 0 <= r < 5 and 0 <= c < 5:
            return (r, c)
        return None

    # ======================================================================
    # Fonts / text fitting
    # ======================================================================
    def get_font(self, size, bold=False):
        size = max(6, int(size))
        key = (size, bold)
        font = self.font_cache.get(key)
        if font is None:
            font = pygame.font.SysFont(
                "arial,helvetica,dejavusans,freesans", size, bold=bold)
            self.font_cache[key] = font
        return font

    def fit_text(self, text, max_w, max_h, max_size, min_size):
        """Largest font size at which *text* fits in the given box."""
        key = (text, int(max_w), int(max_h), int(max_size), int(min_size))
        cached = self.fit_cache.get(key)
        if cached is not None:
            return cached

        best = None
        for size in range(int(max_size), int(min_size) - 1, -1):
            font = self.get_font(size)
            lines = wrap_text(text, font, max_w)
            if len(lines) * font.get_linesize() <= max_h:
                best = (font, lines)
                break

        if best is None:
            font = self.get_font(min_size)
            best = (font, wrap_text(text, font, max_w))

        self.fit_cache[key] = best
        return best

    def render_fitted(self, text, max_w, start_size, color, bold=False):
        size = max(8, int(start_size))
        while size > 8:
            surf = self.get_font(size, bold).render(text, True, color)
            if surf.get_width() <= max_w:
                return surf
            size -= 1
        return self.get_font(8, bold).render(text, True, color)

    # ======================================================================
    # Bingo detection
    # ======================================================================
    def bingo_lines(self):
        m = self.marked
        lines = []
        for r in range(5):
            if all(m[r]):
                lines.append([(r, c) for c in range(5)])
        for c in range(5):
            if all(m[r][c] for r in range(5)):
                lines.append([(r, c) for r in range(5)])
        if all(m[i][i] for i in range(5)):
            lines.append([(i, i) for i in range(5)])
        if all(m[i][4 - i] for i in range(5)):
            lines.append([(i, 4 - i) for i in range(5)])
        return lines

    def bingo_cells(self):
        cells = set()
        for line in self.bingo_lines():
            cells.update(line)
        return cells

    # ======================================================================
    # Small utilities
    # ======================================================================
    def set_toast(self, msg, ms=2200):
        self.toast_msg = msg
        self.toast_until = pygame.time.get_ticks() + ms

    def reset_marks(self):
        self.marked = [[False] * 5 for _ in range(5)]
        self.marked[2][2] = True
        self.save_state()  
        self.set_toast("Marks cleared")

    def shuffle_blocks(self):
        positions = [(r, c) for r in range(5) for c in range(5)
                     if (r, c) != (2, 2)]
        labels = [self.texts[r][c] for r, c in positions]
        random.shuffle(labels)

        for (r, c), label in zip(positions, labels):
            self.texts[r][c] = label

        self.reset_marks()
        self.fit_cache.clear()
        self.shuffle_used = True
        self.set_toast("Blocks shuffled")

    # ======================================================================
    # Persistence
    # ======================================================================
    @staticmethod
    def _valid_grid(grid, typ):
        return (isinstance(grid, list) and len(grid) == 5 and
                all(isinstance(row, list) and len(row) == 5 and
                    all(isinstance(v, typ) for v in row) for row in grid))

    def save_state(self):
        data = {
            "version": 1,
            "texts": self.texts,
            "marked": self.marked,
        }
        try:
            tmp = SAVE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SAVE_FILE)     # atomic — never a half-written file
        except OSError as exc:
            self.set_toast(f"Could not save: {exc}", 3500)

    def load_state(self):
        if not os.path.exists(SAVE_FILE):
            return                          # first run — keep defaults

        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.set_toast(f"Save file unreadable, using defaults: {exc}", 4000)
            return

        texts = data.get("texts")
        marked = data.get("marked")

        if self._valid_grid(texts, str):
            self.texts = [[str(v) for v in row] for row in texts]
            self.fit_cache.clear()
        else:
            self.set_toast("Save file: texts were malformed — ignored", 4000)

        if self._valid_grid(marked, bool):
            self.marked = [[bool(v) for v in row] for row in marked]

    # ======================================================================
    # Actions
    # ======================================================================
    def on_button(self, key):
        if key == "bg":
            return
        elif key == "text":
            self.edit_mode = not self.edit_mode
            self.set_toast("Edit mode ON — click a cell to retype it"
                           if self.edit_mode else "Edit mode off")
        elif key == "reset":
            self.reset_marks()
        elif key == "shuffle" and not self.shuffle_used:
            self.shuffle_blocks()

    def begin_edit(self, cell):
        self.editing = cell
        self.input_text = self.texts[cell[0]][cell[1]]

    def choose_background(self):
        if not TK_OK:
            self.set_toast("tkinter not installed — can't open file dialog", 3500)
            return

        root = None
        path = None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askopenfilename(
                title="Choose a background image",
                filetypes=[
                    ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tga"),
                    ("All files", "*.*"),
                ],
            )
        except Exception as exc:
            self.set_toast(f"File dialog error: {exc}", 3500)
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

        if not path:
            return

        try:
            img = pygame.image.load(path)
            img = img.convert_alpha()
        except Exception as exc:
            self.set_toast(f"Could not load image: {exc}", 3500)
            return

        self.bg_image = img
        self._bg_size = None
        self.set_toast("Background: " + os.path.basename(path))

    # ======================================================================
    # Events
    # ======================================================================
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return

        # ---- typing box has priority --------------------------------
        if self.editing is not None:
            self.handle_typing(event)
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.edit_mode = False
            elif event.key == pygame.K_e:
                self.on_button("text")
            #elif event.key == pygame.K_b:
            #    self.on_button("bg")
            elif event.key == pygame.K_r:
                self.on_button("reset")
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos

            for key, rect in self.buttons.items():
                if rect.collidepoint(pos):
                    self.on_button(key)
                    return

            cell = self.cell_at(pos)
            if cell is not None:
                if self.edit_mode:
                    self.begin_edit(cell)
                else:
                    r, c = cell
                    self.marked[r][c] = not self.marked[r][c]
                    self.save_state()  

    def handle_typing(self, event):
        if event.type != pygame.KEYDOWN:
            return

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            r, c = self.editing
            new_text = self.input_text.strip()
            self.texts[r][c] = new_text
            self.editing = None
            self.fit_cache.clear()
            self.save_state()
            self.set_toast("Text updated")

        elif event.key == pygame.K_ESCAPE:
            self.editing = None

        elif event.key == pygame.K_BACKSPACE:
            self.input_text = self.input_text[:-1]

        elif event.key == pygame.K_DELETE:
            self.input_text = ""

        else:
            ch = getattr(event, "unicode", "")
            if ch and ch.isprintable() and len(self.input_text) < MAX_CELL_CHARS:
                self.input_text += ch

    # ======================================================================
    # Drawing
    # ======================================================================
    def draw(self):
        self.update_layout()
        self.draw_background()
        self.draw_board()
        self.draw_status()
        self.draw_buttons()
        if self.editing is not None:
            self.draw_input_overlay()
        self.update_cursor()
        pygame.display.flip()

    def draw_background(self):
        W, H = self.screen.get_size()

        if self.bg_image is not None:
            if self._bg_size != (W, H) or self._bg_scaled is None:
                iw, ih = self.bg_image.get_size()
                scale = max(W / iw, H / ih)
                self._bg_scaled = pygame.transform.smoothscale(
                    self.bg_image,
                    (max(1, int(iw * scale)), max(1, int(ih * scale))),
                )
                self._bg_size = (W, H)

            self.screen.blit(
                self._bg_scaled,
                ((W - self._bg_scaled.get_width()) // 2,
                 (H - self._bg_scaled.get_height()) // 2),
            )

            # darken so the board stays readable
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((10, 12, 22, 120))
            self.screen.blit(veil, (0, 0))

        else:
            if self._grad is None or self._grad_size != (W, H):
                self._grad = pygame.Surface((W, H)).convert()
                for y in range(H):
                    t = y / max(1, H - 1)
                    col = (
                        int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                        int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                        int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
                    )
                    pygame.draw.line(self._grad, col, (0, y), (W, y))
                self._grad_size = (W, H)
            self.screen.blit(self._grad, (0, 0))

    def draw_board(self):
        br = self.board_rect

        panel = pygame.Surface((br.w + 20, br.h + 20), pygame.SRCALPHA)
        pygame.draw.rect(panel, PANEL_ALPHA, panel.get_rect(), border_radius=22)
        self.screen.blit(panel, (br.x - 10, br.y - 10))

        win_cells = self.bingo_cells()
        mouse = pygame.mouse.get_pos()
        can_hover = self.editing is None

        for r in range(5):
            for c in range(5):
                rect = self.cell_rect(r, c)
                marked = self.marked[r][c]
                hover = can_hover and rect.collidepoint(mouse)

                if marked:
                    face = CELL_MARKED_HOV if hover else CELL_MARKED
                else:
                    face = CELL_FACE_HOVER if hover else CELL_FACE

                pygame.draw.rect(self.screen, face, rect, border_radius=12)

                if hover and self.edit_mode:
                    pygame.draw.rect(self.screen, GOLD, rect, width=3,
                                     border_radius=12)

                if (r, c) in win_cells:
                    pygame.draw.rect(self.screen, GOLD, rect, width=4,
                                     border_radius=12)

                self.draw_cell_text(rect, self.texts[r][c], marked)

    def draw_cell_text(self, rect, text, marked):
        if not text:
            return

        cs = self.cell_size
        max_size = max(9, int(cs * 0.30))
        min_size = max(7, int(cs * 0.09))

        font, lines = self.fit_text(text, rect.w - 16, rect.h - 14,
                                    max_size, min_size)

        color = CELL_TEXT_MARK if marked else CELL_TEXT
        line_h = font.get_linesize()
        y = rect.centery - (line_h * len(lines)) / 2

        for line in lines:
            surf = font.render(line, True, color)
            self.screen.blit(surf, (rect.centerx - surf.get_width() // 2, int(y)))
            y += line_h

    def draw_status(self):
        W = self.screen.get_width()
        cx = W // 2
        cy = self.board_rect.top - 26
        now = pygame.time.get_ticks()

        # toast message ------------------------------------------------
        if now < self.toast_until and self.toast_msg:
            surf = self.render_fitted(self.toast_msg, W - 120, 20, WHITE, True)
            pill = surf.get_rect(center=(cx, cy)).inflate(38, 16)
            bg = pygame.Surface(pill.size, pygame.SRCALPHA)
            pygame.draw.rect(bg, (0, 0, 0, 150), bg.get_rect(), border_radius=14)
            self.screen.blit(bg, pill.topleft)
            self.screen.blit(surf, surf.get_rect(center=(cx, cy)))
            return

        # BINGO! -------------------------------------------------------
        if self.bingo_lines():
            pulse = 0.5 + 0.5 * abs(math.sin(now / 1000.0 * 3.0))
            col = (255, int(180 + 60 * pulse), int(40 + 40 * pulse))
            font = self.get_font(40, True)
            shadow = font.render("B I N G O !", True, (0, 0, 0))
            surf = font.render("B I N G O !", True, col)
            rect = surf.get_rect(center=(cx, cy))
            self.screen.blit(shadow, rect.move(2, 2))
            self.screen.blit(surf, rect)
            return

        # hint ---------------------------------------------------------
        if self.edit_mode:
            hint = "EDIT MODE — click any cell to type new text"
        else:
            hint = "Click cells to mark them  •  Edit Text to change labels"

        surf = self.render_fitted(hint, W - 80, 20, (208, 214, 232))
        shadow = self.render_fitted(hint, W - 80, 20, (0, 0, 0))
        rect = surf.get_rect(center=(cx, cy))
        self.screen.blit(shadow, rect.move(2, 2))
        self.screen.blit(surf, rect)

    def draw_buttons(self):
        mouse = pygame.mouse.get_pos()
        can_hover = self.editing is None
        labels = {
            "bg": "Background Image",
            "text": "Done Editing" if self.edit_mode else "Edit Text",
            "reset": "Reset Marks",
            "shuffle": "Shuffle",
        }

        for key, rect in self.buttons.items():
            disabled = (key == "bg" or
                        (key == "shuffle" and self.shuffle_used))
            hover = (not disabled) and can_hover and rect.collidepoint(mouse)

            if disabled:
                color = DISABLED
            elif key == "text" and self.edit_mode:
                color = BUTTON_EDIT_HOV if hover else BUTTON_EDIT
            else:
                color = BUTTON_HOVER if hover else BUTTON

            pygame.draw.rect(self.screen, color, rect, border_radius=14)
            if hover:
                pygame.draw.rect(self.screen, (255, 255, 255), rect,
                                width=2, border_radius=14)

            text_color = DISABLED_TEXT if disabled else WHITE
            surf = self.render_fitted(labels[key], rect.w - 26,
                                    rect.h * 0.42, text_color, bold=True)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def draw_input_overlay(self):
        W, H = self.screen.get_size()

        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        self.screen.blit(veil, (0, 0))

        pw = min(600, W - 60)
        ph = 240
        panel = pygame.Rect((W - pw) // 2, (H - ph) // 2, pw, ph)
        pygame.draw.rect(self.screen, (30, 34, 52), panel, border_radius=18)
        pygame.draw.rect(self.screen, (96, 120, 200), panel, width=2,
                         border_radius=18)

        title = self.get_font(22, True).render("Edit cell text", True,
                                               (226, 231, 246))
        self.screen.blit(title, (panel.x + 24, panel.y + 22))

        box = pygame.Rect(panel.x + 24, panel.y + 70, panel.w - 48, 60)
        pygame.draw.rect(self.screen, (16, 18, 30), box, border_radius=10)
        pygame.draw.rect(self.screen, (70, 90, 150), box, width=2,
                         border_radius=10)

        tf = self.get_font(26)
        shown = self.input_text
        while shown and tf.size(shown)[0] > box.w - 28:
            shown = shown[1:]

        ts = tf.render(shown, True, WHITE)
        self.screen.blit(ts, (box.x + 14, box.centery - ts.get_height() // 2))

        # blinking cursor
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = box.x + 14 + ts.get_width() + 2
            pygame.draw.line(self.screen, GOLD,
                             (cx, box.centery - 14), (cx, box.centery + 14), 2)

        hint = self.get_font(17).render(
            "Enter = save     Esc = cancel     Delete = clear",
            True, (170, 178, 200))
        self.screen.blit(hint, (panel.x + 24, panel.y + ph - 46))

    def update_cursor(self):
        want = False
        if self.editing is None:
            mouse = pygame.mouse.get_pos()
            if self.cell_at(mouse) is not None:
                want = True
            else:
                for key, r in self.buttons.items():
                    if key != "bg" and r.collidepoint(mouse):
                        want = True
                        break

        if want != self._cursor_hand:
            self._cursor_hand = want
            try:
                pygame.mouse.set_cursor(
                    pygame.SYSTEM_CURSOR_HAND if want
                    else pygame.SYSTEM_CURSOR_ARROW)
            except Exception:
                pass

    # ======================================================================
    # Main loop
    # ======================================================================
    def run(self):
        while self.running:
            self.clock.tick(60)
            for event in pygame.event.get():
                self.handle_event(event)
            self.draw()
        pygame.quit()


def main():
    BingoApp().run()


if __name__ == "__main__":
    main()