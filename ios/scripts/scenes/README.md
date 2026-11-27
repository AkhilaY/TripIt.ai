# Drawn scenes

The Home header's illustrated places are drawn in Python (`draw*.py`), which writes an SVG preview of each scene
and a compact script of drawing steps. `python3 gen.py` turns the approved scenes into
`TripIt/Design/SceneScripts.swift`, which the app reads with `SceneScript`; lights (`T`, `Y`), stars (`X`), water
glints (`Q`) and birds (`B`) are tagged so the header animates them.

Run from this folder: `python3 draw.py && python3 draw2.py && python3 draw3.py` for previews, then `python3 gen.py`
and copy `SceneScripts.swift` into `TripIt/Design/`.
