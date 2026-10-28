from engine import Game, rgb, WHITE, BLACK, YELLOW


class Game(Game):
    """Bouncing square; tapping any key makes it change color."""

    def setup(self, e):
        self.x, self.y = 20.0, 20.0
        self.vx, self.vy = 70.0, 50.0
        self.size = 16
        self.color = YELLOW
        self.frames = 0

    def update(self, e, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < 0 or self.x > e.W - self.size:
            self.vx = -self.vx
            self.x = max(0, min(self.x, e.W - self.size))
        if self.y < 0 or self.y > e.H - self.size:
            self.vy = -self.vy
            self.y = max(0, min(self.y, e.H - self.size))
        if e.pressed:
            self.color = rgb(self.frames * 7 & 255, 255 - (self.frames * 3 & 255), 200)
        self.frames += 1

    def draw(self, e):
        e.clear(BLACK)
        e.rect(int(self.x), int(self.y), self.size, self.size, self.color)
        e.text("cardputer engine", 4, 4, WHITE)
        e.text("frame %d" % self.frames, 4, e.H - 12, WHITE)
