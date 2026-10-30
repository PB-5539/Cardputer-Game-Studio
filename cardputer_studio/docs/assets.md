# Sprites, tilemaps and sound

Everything is an ordinary file in the project. Games load them by path; the IDE has an editor for each type.

## File formats

| Kind | File | Format |
|------|------|--------|
| Sprite / sprite sheet / tileset | `.png` | Any PNG. Magenta `(255,0,255)` and transparent pixels are see-through. |
| Tilemap | `.map.json` | `tileset` (a PNG path), `tile_w`, `tile_h`, `width`, `height`, `layers` (each `name` + `data`, one number per tile, `-1` = empty), `solid` (list of tile numbers). One row of tiles per line so version control diffs stay readable. |
| Sound (tones) | `.sfx.json` | `kind: "tones"`, `wave` (square / triangle / saw / noise), `volume` 0-1, `notes`: `[[note or Hz, milliseconds], ...]`, `"rest"` for silence. |
| Sound (sampled) | `.wav` | Any PCM WAV. Converted when loaded to 8-bit mono, at most 11025 Hz, max 30 seconds. |

A PNG does not store a frame size, so the game passes it: `load_sprite("assets/hero.png", 8, 8)`. The sprite editor
shows the exact call for the frame size you set.

## Runtime classes (`runtime/assets.py`)

**Sprite.** Loading decodes the PNG (`png.py`) and converts to RGB565, using `0xF81F` (magenta) as the "transparent"
value. Drawing needs to skip transparent pixels fast, so `Sprite.runs(frame, flip_x, flip_y)` precomputes, for each
row, the list of `(x offset, bytes)` stretches of visible pixels and caches it. `FrameBuffer.blit_runs` then copies
each stretch with one slice assignment and clips at the screen edges. Python-level loops over pixels would be far
too slow; slice copies are not.

**Tilemap.** Holds the tileset Sprite, the layer data and the solid set. `draw` only visits the tiles the camera can
see, and draws each layer's tiles with the cached tile runs. `solid_at(x, y)` takes pixel positions and
`is_solid(tx, ty)` takes tile positions; anything outside the map counts as solid so characters can't walk off.
`tilemap_from_json` validates everything and raises `AssetError` with a message that says what to fix.

**Sound.** Either `tones` (a list of `(frequency, ms)`) or `pcm` (unsigned 8-bit samples + rate). `note_freq("A4")`
gives 440; note names are converted with the MIDI formula `440 * 2^((midi-69)/12)`. Every sound gets a unique id (`uid`)
so the audio messages can refer to it without resending its data.

Loaders are cached by path in the game's state, so calling `load_sprite` twice returns the same object.

## PNG reader (`runtime/png.py`)

A small decoder so the engine needs no imaging library. It supports every colour type and bit depth (greyscale, RGB,
palette, with alpha, 1 to 16 bits), the five scanline filters, and `tRNS` transparency; it rejects interlaced files
with a clear message. The test suite compares it against Pillow on generated images of every type. `encode` writes
8-bit RGBA, which is all the sprite editor needs.

## The editors (`ui/asset_editors.py`)

Each has the same shape: a **model** with no Qt (in `core/`), a **canvas/list widget** that edits the model, and
a `changed(path, data)` signal. The main window writes that data into the project.

- **SpriteEditor**: model is `PixelImage` (a bytearray of RGBA + `line`, `rect`, `ellipse`, `flood_fill`, `resized`,
  `flipped`, `shifted`). `History` stores whole-image snapshots (images are small, so that is simplest and can't get
  out of sync). Shape tools work on a copy of the image from before the drag, redrawn on each mouse move.
- **TilemapEditor**: model is `TilemapDoc` (layers, `set`, `fill_rect`, `flood_fill`, `resize`, layer operations,
  `snapshot`/`restore` for undo). The tile palette is the tileset image; clicking picks a tile. Changing the tileset or
  tile size removes tiles that no longer exist (`clamp_to_tileset`).
- **SoundEditor**: model is `SoundDoc` (wave, volume, notes). The piano buttons both play a note and add it. Play
  sends the same audio messages a running game would, through the main window's `AudioPlayer`.
- **WavViewer**: plays a WAV exactly as the game would hear it after conversion.

## The mixer (`core/mixer.py`) and speakers (`ui/audio_player.py`)

The mixer is plain Python so it can be tested. It keeps a dict of loaded sounds and a list of playing *voices* (max
8; the oldest is cut off). `render(n)` returns `n` 16-bit mono samples at 22050 Hz: for each voice it adds either a
generated wave (tones) or resampled PCM, then clips to the 16-bit range instead of letting it wrap around (wrapping
would be a loud crack). Waves: square, triangle, saw and noise (a new random value each cycle).

`AudioPlayer` is the only Qt part: a `QAudioSink` in push mode plus a 25 ms timer that asks the mixer for the next
chunk whenever the sink has room. It starts lazily, so a project that never plays sound never opens an audio device,
and if no audio device exists the preview is simply silent.

## Audio messages

One JSON line, optionally followed by `\n` and raw bytes:
`load` (a sound's notes or PCM samples, sent once), `play` (id, loop, volume), `stop` (id or null for everything),
`tone` (a one-off `beep`). Malformed messages are ignored, never fatal.
