from engine import Game, WHITE, BLACK, GREEN


class Game(Game):
    """Shows raw key names so you can fill in KEYMAP in engine/hal_cardputer.py."""

    def draw(self, e):
        e.clear(BLACK)
        e.text("keytest: hold keys", 4, 4, GREEN)
        keys = sorted(e.down)
        for i in range(0, len(keys), 4):
            e.text(" ".join(keys[i:i + 4]), 4, 20 + 10 * (i // 4), WHITE)
