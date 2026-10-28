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

# key -> (menu title, files)
TEMPLATES = {
    "starter": ("Starter game", {"main.py": STARTER_MAIN, "assets/readme.txt": ASSETS_README}),
    "keytest": ("Example: key tester", {"main.py": KEYTEST_MAIN}),
    "snake": ("Example: snake", {"main.py": SNAKE_MAIN}),
}


def new_project(template: str = "starter", name: str | None = None) -> Project:
    title, files = TEMPLATES[template]
    proj = Project(name or ("untitled" if template == "starter" else template))
    for path, text in files.items():
        proj.write_text(path, text)
    proj.dirty = False
    return proj
