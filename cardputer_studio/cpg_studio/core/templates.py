"""Starter project and examples shown in File > New."""
from __future__ import annotations

from .project import Project

STARTER_MAIN = '''\
# Cardputer game starter.
# Everything from the Cardputer engine (clear, rect, text, key_down, ...) is available here
# without importing anything. Open the Docs panel on the right for the full list.

x, y = 112.0, 60.0     # player position
speed = 80             # pixels per second


def setup():
    set_fps(30)
    print("game started")


def update(dt):
    global x, y
    if key_down("left"):
        x -= speed * dt
    if key_down("right"):
        x += speed * dt
    if key_down("up"):
        y -= speed * dt
    if key_down("down"):
        y += speed * dt
    x = max(0, min(WIDTH - 16, x))
    y = max(10, min(HEIGHT - 16, y))
    if key_pressed("space"):
        beep(880, 80)


def draw():
    clear(rgb(10, 10, 30))
    text("Arrows move, space beeps", 4, 1, GRAY)
    rect(int(x), int(y), 16, 16, ORANGE, fill=True)
'''

ASSETS_README = """\
Files in this folder travel inside your .cpg project.
While previewing, your game can read them with a normal relative path, e.g.

    with open("assets/readme.txt") as f:
        print(f.read())
"""

KEYTEST_MAIN = '''\
# Key tester: shows which keys the engine sees. Handy for checking the preview key mapping.

last_pressed = "-"


def update(dt):
    global last_pressed
    for k in keys_pressed():
        last_pressed = k


def draw():
    clear(BLACK)
    text("KEY TESTER", 4, 4, CYAN)
    text("last pressed: " + last_pressed, 4, 20, YELLOW)
    text("held:", 4, 40, GRAY)
    held = keys_down()
    for row in range(0, len(held), 6):
        text(" ".join(held[row:row + 6]), 4, 52 + 10 * (row // 6), WHITE)
'''

SNAKE_MAIN = '''\
# Snake. Arrow keys steer, Enter restarts after game over.
import random

CELL = 8
COLS = WIDTH // CELL              # 30
TOP = 16                          # space above the board for the score
ROWS = (HEIGHT - TOP) // CELL     # 14

snake = []
direction = (1, 0)
pending = (1, 0)
food = (0, 0)
score = 0
alive = True
timer = 0.0
STEP = 0.12                       # seconds per move


def reset():
    global snake, direction, pending, score, alive, timer
    snake = [(5, 7), (4, 7), (3, 7)]
    direction = pending = (1, 0)
    score = 0
    alive = True
    timer = 0.0
    spawn_food()


def spawn_food():
    global food
    free = [(cx, cy) for cx in range(COLS) for cy in range(ROWS) if (cx, cy) not in snake]
    if free:
        food = random.choice(free)


def setup():
    set_fps(30)
    reset()


def update(dt):
    global direction, pending, score, alive, timer, snake
    if not alive:
        if key_pressed("enter"):
            reset()
        return
    for name, d in (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
        if key_pressed(name) and (d[0] != -direction[0] or d[1] != -direction[1]):
            pending = d
    timer += dt
    if timer < STEP:
        return
    timer -= STEP
    direction = pending
    nx, ny = snake[0][0] + direction[0], snake[0][1] + direction[1]
    grow = (nx, ny) == food
    body = snake if grow else snake[:-1]
    if nx < 0 or ny < 0 or nx >= COLS or ny >= ROWS or (nx, ny) in body:
        alive = False
        return
    snake.insert(0, (nx, ny))
    if grow:
        score += 1
        spawn_food()
    else:
        snake.pop()


def draw():
    clear(BLACK)
    text("Score " + str(score), 2, 4, WHITE)
    rect(0, TOP - 1, WIDTH, ROWS * CELL + 2, GRAY)
    fx, fy = food
    rect(fx * CELL + 1, TOP + fy * CELL + 1, CELL - 2, CELL - 2, RED, fill=True)
    for i, (sx, sy) in enumerate(snake):
        rect(sx * CELL + 1, TOP + sy * CELL + 1, CELL - 2, CELL - 2, YELLOW if i == 0 else GREEN, fill=True)
    if not alive:
        text("GAME OVER", 84, 52, RED)
        text("Enter = restart", 68, 66, WHITE)
'''


PLATFORM_MAIN = '''\
# Sprites, a tilemap and sound. Open assets/ in the Workspace to edit them:
#   hero.png (a 4-frame sprite sheet)   tiles.png (the tileset)
#   level.map.json (the map)            jump.sfx.json / coin.sfx.json (sounds)

hero = load_sprite("assets/hero.png", 8, 8)
level = load_tilemap("assets/level.map.json")
jump_sound = load_sound("assets/jump.sfx.json")
coin_sound = load_sound("assets/coin.sfx.json")

x, y = 20.0, 40.0
vy = 0.0
facing_left = False
cam_x = 0.0
coins = 0


def setup():
    set_fps(30)


def solid_below(px, py):
    return level.solid_at(px + 1, py + 8) or level.solid_at(px + 6, py + 8)


def blocked(px, py):
    return level.solid_at(px + 1, py + 1) or level.solid_at(px + 6, py + 1) or \\
           level.solid_at(px + 1, py + 6) or level.solid_at(px + 6, py + 6)


def update(dt):
    global x, y, vy, facing_left, cam_x, coins
    dx = (key_down("right") - key_down("left")) * 60 * dt
    if dx and not blocked(x + dx, y):
        x += dx
        facing_left = dx < 0
    vy += 300 * dt
    next_y = y + vy * dt
    if vy >= 0 and solid_below(x, next_y):          # landed: stand on top of the tile
        vy = 0
        y = int((next_y + 8) // 8) * 8 - 8
        if key_pressed("space") or key_pressed("up"):
            vy = -110
            play_sound(jump_sound)
    else:
        y = next_y
    tx, ty = int((x + 4) // 8), int((y + 4) // 8)
    if level.get(tx, ty, "items") == 2:          # tile 2 is the coin
        level.set(tx, ty, -1, "items")
        coins += 1
        play_sound(coin_sound)
    if y > level.px_h:
        x, y, vy = 20.0, 40.0, 0.0
    cam_x = max(0, min(x - WIDTH / 2, level.px_w - WIDTH))


def draw():
    clear(rgb(40, 90, 160))
    draw_tilemap(level, cam_x, 0)
    frame = int(time_ms() / 120) % 2 if key_down("left") or key_down("right") else 0
    draw_sprite(hero, x - cam_x, y, frame, flip_x=facing_left)
    text("coins: %d" % coins, 4, 4, WHITE)
'''


def _platform_files() -> dict:
    """The sprite, tileset, map and sounds for the sprite/tilemap/sound example (built in code)."""
    from .pixelimage import PixelImage
    from .sounddoc import SoundDoc
    from .tilemap_doc import TilemapDoc

    def paint(img, ox, rows, palette):
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in palette:
                    img.set(ox + x, y, palette[ch] + (255,))

    hero = PixelImage(32, 8)
    body = {"r": (220, 50, 50), "s": (255, 205, 160), "k": (30, 30, 30), "b": (60, 90, 220)}
    stand = ["..rrrr..", ".rrrrrr.", ".ssssss.", ".sksskss", "..ssss..", ".bbbbbb.", ".bbbbbb.", "..b..b.."]
    step = ["..rrrr..", ".rrrrrr.", ".ssssss.", ".sksskss", "..ssss..", ".bbbbbb.", ".bbbbbb.", ".b....b."]
    for i, rows in enumerate((stand, step, stand, step)):
        paint(hero, i * 8, rows, body)
    tiles = PixelImage(32, 8)
    paint(tiles, 0, ["gggggggg", "gddgdddg", "dddddddd", "ddddddgd", "dgdddddd", "dddddddd", "dddgdddd", "dddddddd"],
          {"g": (60, 170, 60), "d": (120, 80, 40)})
    paint(tiles, 8, ["bbbbbbbb", "bwbbbbwb", "bbbbbbbb", "bbbwbbbb", "bbbbbbbb", "bbwbbbbb", "bbbbbbwb", "bbbbbbbb"],
          {"b": (150, 150, 160), "w": (110, 110, 120)})
    paint(tiles, 16, ["........", "..yyyy..", ".yyooyy.", ".yyooyy.", ".yyooyy.", ".yyooyy.", "..yyyy..", "........"],
          {"y": (255, 220, 40), "o": (230, 160, 20)})
    width, height = 60, 16
    doc = TilemapDoc.new("assets/tiles.png", 8, 8, width, height)
    doc.add_layer("items")
    for x in range(width):
        if not 22 <= x <= 25 and not 40 <= x <= 42:       # two gaps to jump over
            doc.set(0, x, 13, 0)
            doc.set(0, x, 14, 0 if x % 7 else 1)
            doc.set(0, x, 15, 1)
    for x, y in ((12, 9), (13, 9), (30, 9), (31, 9), (32, 9), (50, 8)):
        doc.set(0, x, y, 1)
        doc.set(1, x, y - 1, 2)
    doc.solid = {0, 1}
    return {"assets/hero.png": hero.to_png(), "assets/tiles.png": tiles.to_png(),
            "assets/level.map.json": doc.to_json(),
            "assets/jump.sfx.json": SoundDoc("square", 0.4, [["C5", 40], ["G5", 80]]).to_json(),
            "assets/coin.sfx.json": SoundDoc("triangle", 0.5, [["B5", 50], ["E6", 160]]).to_json()}


# key -> (menu title, files)
TEMPLATES = {
    "starter": ("Starter game", {"main.py": STARTER_MAIN, "assets/readme.txt": ASSETS_README}),
    "keytest": ("Example: key tester", {"main.py": KEYTEST_MAIN}),
    "snake": ("Example: snake", {"main.py": SNAKE_MAIN}),
    "platformer": ("Example: sprites, tilemap and sound", {"main.py": PLATFORM_MAIN}),
}


def new_project(template: str = "starter", name: str | None = None) -> Project:
    title, files = TEMPLATES[template]
    proj = Project(name or ("untitled" if template == "starter" else template))
    if template == "platformer":
        files = dict(files, **_platform_files())
    for path, content in files.items():
        if isinstance(content, bytes):
            proj.write_bytes(path, content)
        else:
            proj.write_text(path, content)
    proj.dirty = False
    return proj
