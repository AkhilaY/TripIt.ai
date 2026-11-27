import math, random
exec(open('draw.py').read().split('# ---------- London')[0])

def lerp(a, b, t): return a + (b - a) * t

# ---------- San Francisco: the Golden Gate from Baker Beach at sunset ----------
def goldengate():
    s = S()
    s.sky([(0, '#40568F'), (.38, '#9B7FA6'), (.62, '#E8A788'), (.8, '#F6C996'), (1, '#F9DEB6')])
    s.glow(318, 262, 150, '#FFE1AE', .75); s.disc(318, 262, 15, '#FFF3DA', .95)
    s.cloud(-10, 84, 190, '#F7D2BC', 0.8); s.cloud(200, 58, 200, '#F5C9B6', 0.75); s.cloud(150, 140, 120, '#FADCC6', 0.75)
    # Marin Headlands: three layers, the far ones hazier
    s.path('M0 262 Q40 238 90 244 Q150 222 210 236 Q262 226 300 238 L300 300 L0 300 Z', '#8E8796')
    s.path('M0 276 Q50 250 110 258 Q170 240 230 256 Q260 252 290 262 L290 300 L0 300 Z', '#6F6A72')
    # fog spilling over the ridge
    s.gpath('M-10 270 Q40 250 95 258 Q150 246 210 254 Q250 252 300 262 L300 280 Q200 274 100 280 Q40 283 -10 286 Z',
            [(0, '#FFFFFF'), (1, '#FFFFFF')], 0, 250, 0, 286, .7)
    # the city far right, small and pale
    r = random.Random(3)
    x = 330
    while x < 392:
        w = 5 + r.random() * 6; h = 8 + r.random() * 22
        s.rect(x, 300 - h, w, h, '#B19AA8', .8); x += w + 1
    s.water(300, '#6F84A8', '#203556', '#FFDDA8', 90, 12)
    # sun's path on the water
    for i in range(16):
        y = 304 + i * 9 + r.random() * 4; w = 6 + (16 - i) * 1.4 + r.random() * 8
        s.rect(318 - w / 2 + (r.random() - .5) * 10, y, w, 1.3, '#FFE3B0', .55 - i * .025, kind='Q')
    orange, deep, shade = '#C4422F', '#8E2A1F', '#A9372A'
    water_y, deck = 330, 286
    towers = (100, 292)
    top = 120
    # towers: two tapering legs, stepped art-deco top, four portals with recessed panels
    def tower(tx):
        for sgn in (-1, 1):
            d = (f'M{tx + sgn * 15} {water_y + 4} L{tx + sgn * 12} {top + 14} L{tx + sgn * 11} {top} '
                 f'L{tx + sgn * 6} {top} L{tx + sgn * 7} {top + 14} L{tx + sgn * 9} {water_y + 4} Z')
            s.path(d, orange if sgn < 0 else shade)
        s.rect(tx - 12, top - 6, 24, 7, orange); s.rect(tx - 9, top - 11, 18, 6, orange); s.rect(tx - 5, top - 15, 10, 5, orange)
        for k, (yy, hh) in enumerate(((top + 16, 16), (top + 52, 14), (top + 86, 14), (deck - 30, 14))):
            s.rect(tx - 9, yy, 18, hh, orange)
            for j in range(3):
                s.rect(tx - 7 + j * 5, yy + 3, 3.4, hh - 6, deep, .85)
        s.rect(tx - 16, water_y - 2, 32, 10, '#8A7F78')  # concrete pier
    for tx in towers: tower(tx)
    # main span cable and the side spans down to the anchorages
    a, b = towers
    s.line(f'M{a - 9} {top + 2} Q{(a + b) / 2} {deck + 34} {b - 9} {top + 2}', orange, 1.8)
    s.line(f'M{a + 9} {top + 2} Q{(a + b) / 2} {deck + 34} {b + 9} {top + 2}', orange, 1.8)
    def qpt(p0, p1, p2, t):
        return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
    main = ((a, top + 2), ((a + b) / 2, deck + 34), (b, top + 2))
    for i in range(1, 32):
        x, y = qpt(*main, i / 32)
        if y < deck: s.line(f'M{x:.1f} {y:.1f} L{x:.1f} {deck}', orange, .55, .85)
    for side in (((a, top + 2), (a - 50, 230), (-12, deck + 4)), ((b, top + 2), (b + 50, 230), (402, deck + 4))):
        s.line(f'M{side[0][0]} {side[0][1]} Q{side[1][0]} {side[1][1]} {side[2][0]} {side[2][1]}', orange, 1.8)
        for i in range(1, 12):
            x, y = qpt(*side, i / 12)
            if y < deck and 0 < x < W: s.line(f'M{x:.1f} {y:.1f} L{x:.1f} {deck}', orange, .55, .85)
    # deck with its stiffening truss and the evening traffic
    s.rect(-5, deck, W + 10, 4, orange)
    s.rect(-5, deck + 4, W + 10, 7, deep)
    for x in range(-4, W, 8):
        s.line(f'M{x} {deck + 4} L{x + 4} {deck + 11} L{x + 8} {deck + 4}', '#5E1A14', .6, .9)
    for i in range(18):
        x = r.random() * W
        s.disc(x, deck - .8, .9, '#FFE7A8' if r.random() < .5 else '#FF8A70', .9, kind='Y')
    # the approach viaduct on the left, down to the shore
    for x in range(-10, a - 20, 22):
        s.rect(x, deck + 11, 5, water_y - deck - 8, '#7D2A20', .9)
    # boats: a sailboat close in, another further out, a container ship crossing
    def sail(x, y, k):
        s.path(f'M{x - 12 * k} {y} L{x + 12 * k} {y} L{x + 8 * k} {y + 4 * k} L{x - 9 * k} {y + 4 * k} Z', '#F4F1EA')
        s.path(f'M{x} {y - 1} L{x} {y - 30 * k} L{x + 11 * k} {y - 2 * k} Z', '#FFFFFF')
        s.path(f'M{x - 1} {y - 3 * k} L{x - 1} {y - 24 * k} L{x - 9 * k} {y - 4 * k} Z', '#F2E6D6')
    sail(78, 392, 1); sail(250, 350, .55)
    s.path('M150 338 L222 338 L216 345 L156 345 Z', '#3F4552')
    for i in range(6): s.rect(160 + i * 9, 331, 8, 7, ['#B4533C', '#3D6E8C', '#C9A25A'][i % 3])
    s.rect(212, 326, 7, 12, '#E9E6E0')
    # rocks and a strip of Baker Beach in the foreground
    s.path('M0 420 Q60 408 120 418 Q200 430 260 420 Q330 410 390 424 L390 460 L0 460 Z', '#C7AE8E')
    s.path('M0 440 Q90 430 200 442 Q300 452 390 440 L390 460 L0 460 Z', '#B39A7A')
    for (x, y, rr) in ((24, 418, 10), (44, 422, 6), (352, 420, 12), (370, 426, 7)):
        s.path(f'M{x - rr} {y + 4} Q{x - rr * .6} {y - rr} {x} {y - rr * .8} Q{x + rr * .8} {y - rr * .7} {x + rr} {y + 4} Z', '#5E5248')
    s.line('M0 418 Q60 406 120 416 Q200 428 260 418 Q330 408 390 422', '#FFFFFF', 1.2, .55)
    s.birds(4, 190, 150, 90, '#5C4E62', 5)
    return s

# ---------- Rome: the Colosseum, its curve and its broken ring ----------
def colosseum():
    s = S()
    s.sky([(0, '#5D93C9'), (.55, '#AFCBE2'), (.8, '#EAD9C2'), (1, '#F2E2C8')])
    s.glow(70, 110, 110, '#FFF4DE', .7)
    s.cloud(150, 70, 200, '#FFFFFF', 0.9); s.cloud(-30, 140, 170, '#FFFFFF', 0.8500000000000001); s.cloud(260, 180, 140, '#FFFFFF', 0.8)
    r = random.Random(13)
    cx, R = 195, 168            # centre and half-width of the visible front of the ellipse
    base, levels = 352, [(0, 54), (54, 50), (104, 48), (152, 34)]   # storeys from the ground: offset, height
    t0 = 1.18                   # how far round the oval we see on each side
    stone, light, dark, deep = '#E0BE90', '#F1D7AF', '#B48C60', '#5A3F2C'
    def X(t): return cx + R * math.sin(t)
    def lift(t): return 10 * math.cos(t)          # the top line arcs: nearer is lower in the frame
    ncols = 22
    ts = [-t0 + 2 * t0 * i / ncols for i in range(ncols + 1)]
    # how much of each storey survives: the outer ring's upper storeys are gone on the right
    def survives(level, t):
        if level <= 1: return True
        if level == 2: return t < 0.86
        return t < 0.52
    # the inner ring, seen where the outer wall has fallen
    for i in range(ncols):
        ta, tb = ts[i], ts[i + 1]
        if ta < 0.5: continue
        xa, xb = X(ta), X(tb)
        y0 = base - 104 + lift(ta) * .6
        s.rect(xa, y0 - 54, xb - xa + .5, 54, '#C9A47A')
        w = (xb - xa) * .5
        s.path(f'M{xa + w * .5:.1f} {y0 - 6:.1f} L{xa + w * .5:.1f} {y0 - 34:.1f} Q{xa + w:.1f} {y0 - 44:.1f} {xa + w * 1.5:.1f} {y0 - 34:.1f} L{xa + w * 1.5:.1f} {y0 - 6:.1f} Z', '#7A5A40', .8)
    for lvl, (off, h) in enumerate(levels):
        for i in range(ncols):
            ta, tb = ts[i], ts[i + 1]
            tm = (ta + tb) / 2
            if not survives(lvl, tm): continue
            xa, xb = X(ta), X(tb)
            ya_b = base - off + lift(ta) - 10; yb_b = base - off + lift(tb) - 10
            ya_t, yb_t = ya_b - h, yb_b - h
            facing = math.cos(tm)                 # 1 facing us, less towards the edges
            col = stone if facing > .45 else ('#D2AE80' if facing > .25 else dark)
            s.path(f'M{xa:.1f} {ya_b:.1f} L{xb + .4:.1f} {yb_b:.1f} L{xb + .4:.1f} {yb_t:.1f} L{xa:.1f} {ya_t:.1f} Z', col)
            wbay = xb - xa
            if lvl < 3:
                # an arch between two half-columns, narrowing towards the edges
                ax0, ax1 = xa + wbay * .22, xb - wbay * .22
                ymid_b = (ya_b + yb_b) / 2 - 4; spring = ymid_b - h * .58
                s.path(f'M{ax0:.1f} {ymid_b:.1f} L{ax0:.1f} {spring:.1f} Q{(ax0 + ax1) / 2:.1f} {spring - h * .28:.1f} {ax1:.1f} {spring:.1f} L{ax1:.1f} {ymid_b:.1f} Z', deep, .78 + .2 * (1 - facing))
                # the half-column with its capital
                s.rect(xa - wbay * .06, (ya_t + ya_b) / 2 - h / 2 + 4, max(1, wbay * .12), h - 8, light if facing > .4 else stone, .75)
                s.rect(xa - wbay * .1, ya_t + 4, max(1.2, wbay * .2), 2, light, .8)
            else:
                # the attic: blank wall with small square windows and the corbels for the awning
                s.rect(xa + wbay * .35, ya_t + 12, wbay * .3, 7, deep, .7)
                s.rect(xa + wbay * .45, ya_t + 2, wbay * .1, 3, dark, .6)
            # cornice under each storey
            s.path(f'M{xa:.1f} {ya_t + 1:.1f} L{xb + .4:.1f} {yb_t + 1:.1f} L{xb + .4:.1f} {yb_t + 4:.1f} L{xa:.1f} {ya_t + 4:.1f} Z', light, .85)
    # the jagged edge where the outer ring breaks off, stepping down
    for (t, lvl) in ((0.52, 3), (0.86, 2)):
        x = X(t); yt = base - levels[lvl][0] + lift(t) - 10 - levels[lvl][1]
        s.path(f'M{x - 2:.1f} {yt:.1f} L{x + 5:.1f} {yt + 8:.1f} L{x + 2:.1f} {yt + 16:.1f} L{x + 8:.1f} {yt + 28:.1f} L{x - 2:.1f} {yt + 40:.1f} Z', dark)
    # weathering: the famous holes and darker blocks
    for i in range(70):
        t = (r.random() * 2 - 1) * t0; lvl = r.randrange(4)
        if not survives(lvl, t): continue
        x = X(t); y = base - levels[lvl][0] + lift(t) - 10 - r.random() * levels[lvl][1]
        s.disc(x, y, .7 + r.random() * .8, '#6E5038', .5)
    for i in range(40):
        t = (r.random() * 2 - 1) * t0; lvl = r.randrange(2)
        x = X(t); y = base - levels[lvl][0] + lift(t) - 10 - r.random() * levels[lvl][1]
        s.rect(x, y, 4 + r.random() * 5, 2, '#C79F72', .45)
    # the piazza and the street in front
    s.gpath('M0 352 L390 352 L390 460 L0 460 Z', [(0, '#CFB894'), (1, '#B9A07C')], 0, 352, 0, 460)
    for y in range(362, 460, 12):
        s.line(f'M0 {y} L390 {y + 2}', '#A88E6A', .5, .5)
    # umbrella pines and cypresses, at the right size beside a 48 m wall
    def pine(x, y, w):
        s.line(f'M{x} {y} Q{x + 4} {y - 40} {x - 2} {y - 62}', '#5A4232', 2.6)
        for k, (dx, dy, rx, ry) in enumerate(((0, -66, w, 11), (-w * .35, -60, w * .55, 8), (w * .4, -61, w * .5, 8))):
            s.ellipse(x + dx, y + dy, rx, ry, '#3F5F36' if k == 0 else '#4A6B3E')
    pine(28, 352, 30); pine(368, 352, 28)
    s.ellipse(58, 330, 6, 24, '#38552F'); s.ellipse(336, 332, 5, 22, '#38552F')
    # a few people, to show the scale
    for i in range(12):
        x = 70 + r.random() * 250; y = 380 + r.random() * 50
        s.rect(x, y - 7, 2.2, 7, ['#3A4A6A', '#8A3A3A', '#2E2E2E', '#6A7A4A'][i % 4]); s.disc(x + 1.1, y - 8.5, 1.3, '#4A3A2E')
    # a Vespa parked by the kerb
    vx, vy = 250, 420
    s.path(f'M{vx} {vy} Q{vx + 4} {vy - 12} {vx + 16} {vy - 11} L{vx + 26} {vy - 11} Q{vx + 32} {vy - 4} {vx + 30} {vy} Z', '#8CC4B4')
    s.disc(vx + 4, vy + 2, 4.2, '#2A2A2A'); s.disc(vx + 26, vy + 2, 4.2, '#2A2A2A')
    s.line(f'M{vx + 23} {vy - 11} L{vx + 20} {vy - 19} L{vx + 14} {vy - 20}', '#3A3A3A', 1.3)
    s.birds(5, 210, 60, 130, '#5A5A6A', 7)
    return s

# ---------- Santorini: Oia on the caldera rim at sunset ----------
def santorini():
    s = S()
    s.sky([(0, '#3F4F8C'), (.3, '#8E79A8'), (.5, '#E39A9A'), (.62, '#F6B98C'), (1, '#F9D9A8')])
    sun_x, horizon = 66, 262
    s.glow(sun_x, horizon - 30, 150, '#FFD9A0', .85); s.disc(sun_x, horizon - 30, 13, '#FFF1D0', .95)
    s.cloud(150, 70, 200, '#F6C2B2', 0.8500000000000001); s.cloud(-30, 128, 170, '#FAD2B8', 0.8); s.cloud(250, 150, 130, '#F2B6B0', 0.75)
    # Thirassia across the caldera, and the little volcano
    s.path(f'M0 {horizon} L0 {horizon - 14} Q40 {horizon - 24} 90 {horizon - 16} Q120 {horizon - 12} 140 {horizon} Z', '#7A6A8E')
    s.path(f'M150 {horizon} Q175 {horizon - 8} 205 {horizon} Z', '#6E5F84')
    s.water(horizon, '#5A6FA2', '#1F3361', '#FFD49A', 70, 21)
    r = random.Random(77)
    for i in range(22):  # the sun's path on the sea
        y = horizon + 3 + i * 8 + r.random() * 3; w = 4 + (22 - i) * .9 + r.random() * 8
        s.rect(sun_x - w / 2 + (r.random() - .5) * 8, y, w, 1.3, '#FFDCA4', .6 - i * .022, kind='Q')
    # the caldera cliff: a long rim falling to the sea in red, black and cream bands
    rim = 'M118 460 L118 300 Q138 238 178 214 Q236 186 300 180 Q350 176 392 178 L392 460 Z'
    s.gpath(rim, [(0, '#8C5A48'), (.5, '#6E4438'), (1, '#4E3230')], 0, 200, 0, 460)
    bands = [(296, '#A86A50', .8), (322, '#3E2B2A', .7), (346, '#C49A78', .55), (372, '#5E3C34', .7), (404, '#9A5E46', .6)]
    for y0, c, o in bands:
        s.path(f'M{124 + (y0 - 296) * .02:.0f} {y0} Q230 {y0 - 34} 392 {y0 - 48} L392 {y0 - 40} Q230 {y0 - 24} {124:.0f} {y0 + 10} Z', c, o)
    for i in range(60):  # rock texture
        x = 125 + r.random() * 265; y = 260 + r.random() * 190
        if y > 300 - (x - 125) * .35: s.rect(x, y, 2 + r.random() * 6, 1, '#2E1E1C', .3)
    # Oia: whitewashed houses following the rim in terraces, cave houses with vaulted fronts, a few in ochre and
    # peach, terraces with blue rails and small pools
    def rim_y(x): return 214 - (x - 178) * .2 if x > 178 else 214 + (178 - x) * 1.1
    houses = []
    for row in range(7):
        x = 150 + row * 4 + r.random() * 6
        while x < 392:
            w = 9 + r.random() * 10; h = 7 + r.random() * 5
            y = rim_y(x) - 18 + row * 11 + r.random() * 3
            if y + h < rim_y(x) + 70 and r.random() < .86:
                houses.append((x, y, w, h, row))
            x += w + 2.5 + r.random() * 4
    for x, y, w, h, row in sorted(houses, key=lambda t: t[1]):
        tint = '#FBF7F0' if r.random() < .82 else r.choice(['#F2D3A8', '#F4C4A6', '#EADFC8'])
        if r.random() < .3:   # cave house: vaulted roof
            s.path(f'M{x:.1f} {y + h:.1f} L{x:.1f} {y + 3:.1f} Q{x + w / 2:.1f} {y - 3:.1f} {x + w:.1f} {y + 3:.1f} L{x + w:.1f} {y + h:.1f} Z', tint)
        else:
            s.rect(x, y, w, h, tint); s.rect(x - .6, y - 1, w + 1.2, 1.4, '#FFFFFF')
        s.rect(x + w - 2, y + 1, 2, h - 1, '#D8D0C6', .8)   # shaded side
        if r.random() < .6:
            s.path(f'M{x + 2:.1f} {y + h:.1f} L{x + 2:.1f} {y + h - 4.5:.1f} Q{x + 3.6:.1f} {y + h - 6.5:.1f} {x + 5.2:.1f} {y + h - 4.5:.1f} L{x + 5.2:.1f} {y + h:.1f} Z',
                   r.choice(['#2E6EB4', '#2E6EB4', '#3A8C8C', '#8A4A3A']))
        if r.random() < .45: s.rect(x + w - 6, y + 2.5, 2.4, 2.4, '#2E6EB4', .85)
        if r.random() < .25:   # terrace with a blue rail, sometimes a pool
            s.rect(x - 1, y + h, w + 2, 1.6, '#F2EDE4'); s.line(f'M{x - 1:.1f} {y + h - 1.5:.1f} L{x + w + 1:.1f} {y + h - 1.5:.1f}', '#2E6EB4', .6)
            if r.random() < .4: s.rect(x + 1, y + h + 1.6, w - 2, 2.2, '#5FC4CF')
    # zig-zag steps down the cliff
    s.line('M232 262 L246 270 L234 278 L250 288 L238 298', '#F3EDE2', .9, .8)
    # the blue domes, each on its white church, with crosses; the largest with a bell tower of arches
    def church(dx, dy, rr):
        s.rect(dx - rr - 2, dy, (rr + 2) * 2, rr * 1.1, '#FBF7F0'); s.rect(dx + rr - 1, dy + 1, 3, rr * 1.1 - 1, '#D8D0C6')
        s.gpath(f'M{dx - rr} {dy} Q{dx - rr} {dy - rr * 1.25} {dx} {dy - rr * 1.3} Q{dx + rr} {dy - rr * 1.25} {dx + rr} {dy} Z',
                [(0, '#4A8EDA'), (1, '#1F58A6')], dx - rr, 0, dx + rr, 0)
        s.rect(dx - rr - 1, dy - 1, (rr + 1) * 2, 2, '#FFFFFF')
        top = dy - rr * 1.3
        s.line(f'M{dx} {top - 7} L{dx} {top} M{dx - 2.6} {top - 4.5} L{dx + 2.6} {top - 4.5}', '#FFFFFF', 1.1)
    church(262, 196, 11); church(318, 222, 8.5); church(214, 238, 7.5)
    bx, by = 282, 166
    s.rect(bx, by, 14, 30, '#FBF7F0'); s.rect(bx + 12, by + 1, 2, 29, '#D8D0C6')
    for k in range(2):
        s.path(f'M{bx + 2 + k * 6} {by + 12} L{bx + 2 + k * 6} {by + 6} Q{bx + 4 + k * 6} {by + 3} {bx + 6 + k * 6} {by + 6} L{bx + 6 + k * 6} {by + 12} Z', '#3B3B48')
        s.disc(bx + 4 + k * 6, by + 8, 1.3, '#D9B24A')
    s.path(f'M{bx - 1} {by} Q{bx + 7} {by - 9} {bx + 15} {by} Z', '#2E6EB4'); s.line(f'M{bx + 7} {by - 13} L{bx + 7} {by - 7} M{bx + 5} {by - 11} L{bx + 9} {by - 11}', '#FFFFFF', 1)
    # the windmill on the point, with its thatched cap and six lattice sails
    mx, my = 152, 254
    s.path(f'M{mx - 8} {my + 22} L{mx + 8} {my + 22} L{mx + 6} {my} L{mx - 6} {my} Z', '#FBF7F0'); s.rect(mx + 4, my + 1, 2.5, 21, '#D8D0C6')
    s.path(f'M{mx - 7.5} {my} Q{mx} {my - 12} {mx + 7.5} {my} Z', '#9C7650')
    s.rect(mx - 1.5, my + 12, 3, 6, '#3A6EA8')
    for k in range(6):
        a = math.radians(15 + k * 60); ex, ey = mx + 21 * math.cos(a), my - 3 + 21 * math.sin(a)
        s.line(f'M{mx} {my - 3} L{ex:.1f} {ey:.1f}', '#5A4636', 1)
        a2 = a + math.radians(14); fx, fy = mx + 19 * math.cos(a2), my - 3 + 19 * math.sin(a2)
        s.path(f'M{mx + 5 * math.cos(a):.1f} {my - 3 + 5 * math.sin(a):.1f} L{ex:.1f} {ey:.1f} L{fx:.1f} {fy:.1f} L{mx + 5 * math.cos(a2):.1f} {my - 3 + 5 * math.sin(a2):.1f} Z', '#F3E8D6', .8)
    s.disc(mx, my - 3, 1.8, '#5A4636')
    # boats in the caldera: a traditional caique and a sailing yacht
    s.path('M40 318 L84 318 L78 326 L46 326 Z', '#F4F0E8'); s.path('M62 317 L62 280 L80 316 Z', '#FFFFFF'); s.path('M61 314 L61 286 L48 314 Z', '#F2E4D2')
    s.path('M20 386 L50 386 Q48 392 44 393 L26 393 Q22 392 20 386 Z', '#C66A3A'); s.rect(30, 380, 9, 6, '#F2EDE4')
    s.birds(4, 90, 140, 90, '#5C4A6A', 8)
    return s

# ---------- Monaco: the Grand Prix along the harbour ----------
def monaco():
    s = S()
    s.sky([(0, '#3E86C8'), (.55, '#9CC8E8'), (1, '#E6EEF0')])
    s.glow(330, 60, 70, '#FFFBEA', .85)
    s.cloud(10, 60, 200, '#FFFFFF', 0.9); s.cloud(220, 96, 160, '#FFFFFF', 0.8999999999999999)
    r = random.Random(51)
    # the mountains behind (Tête de Chien), rock and scrub, in haze
    s.path('M0 150 L40 118 L80 126 L130 96 L170 110 L220 88 L270 104 L320 92 L390 112 L390 220 L0 220 Z', '#A3AAA4')
    s.path('M0 168 Q90 132 180 150 Q270 128 390 140 L390 230 L0 230 Z', '#7E9078')
    # Monte Carlo: buildings climbing the hill in layers, smaller and paler further back
    cols = ['#F3E4C8', '#EAD2AE', '#F6EDDC', '#E2C49C', '#F0D8C2', '#D8C3A3', '#EEE5D3']
    for layer, (yb, hmin, hmax, wmin, wmax, haze) in enumerate(((176, 10, 18, 8, 14, .45), (196, 14, 26, 10, 18, .25), (220, 18, 36, 12, 22, .1))):
        x = 120 + layer * 4 + r.random() * 6
        while x < 392:
            w = wmin + r.random() * (wmax - wmin); h = hmin + r.random() * (hmax - hmin)
            if r.random() < .85:
                c = r.choice(cols); y = yb - h
                s.rect(x, y, w, h + 30, c)
                if layer == 2 and r.random() < .5:  # belle-époque mansard roof
                    s.path(f'M{x - 1:.1f} {y:.1f} L{x + 2:.1f} {y - 4:.1f} L{x + w - 2:.1f} {y - 4:.1f} L{x + w + 1:.1f} {y:.1f} Z', '#7A7F88')
                for k in range(int((w - 2) // 4)):
                    for j in range(int(h // 5)):
                        s.rect(x + 2 + k * 4, y + 2 + j * 5, 1.8, 2.6, '#71889C', .55)
                s.rect(x, y, w, h + 30, '#FFFFFF', haze)
            else:
                s.ellipse(x + w / 2, yb - 4, w * .6, 6, '#5F7F52', .9)
            x += w + 1 + r.random() * 2
    # Tour Odéon, the tall twin tower on the hill
    s.rect(348, 120, 9, 80, '#D9DEE2'); s.rect(358, 116, 9, 84, '#C9D0D6')
    for j in range(16): s.rect(349, 123 + j * 5, 17, 1, '#8FA2B2', .7)
    # the Rock on the left with the Prince's Palace and the cathedral
    s.path('M0 236 L0 168 Q30 156 70 160 Q100 164 116 178 L122 236 Z', '#8E8574')
    s.path('M0 236 L0 196 Q40 186 80 192 Q104 196 122 210 L122 236 Z', '#776E60')
    s.rect(10, 150, 60, 16, '#EBD9B6'); s.rect(18, 140, 10, 12, '#EBD9B6'); s.rect(52, 138, 12, 14, '#EBD9B6')
    for k in range(9): s.rect(11 + k * 7, 147, 3.5, 3, '#EBD9B6')  # crenellations
    for k in range(6): s.rect(14 + k * 9, 154, 3, 5, '#8A7A62', .7)
    s.rect(78, 146, 22, 14, '#EFE6D6'); s.path('M80 146 Q89 134 98 146 Z', '#B6B0A4')
    s.ellipse(110, 168, 10, 5, '#5F7F52'); s.ellipse(6, 176, 8, 4, '#5F7F52')
    # Port Hercule: calm water with piers and yachts, smaller in the distance
    s.water(236, '#3A86B8', '#1A5A88', '#FFFFFF', 50, 4)
    s.rect(0, 262, 260, 2.5, '#E8E4DA'); s.rect(150, 236, 2.5, 28, '#E8E4DA')
    def yacht(x, y, ln, k=1):
        s.path(f'M{x} {y} L{x + ln} {y} L{x + ln - 6 * k} {y + 6 * k} L{x + 4 * k} {y + 6 * k} Z', '#FBFBF8')
        s.rect(x + ln * .22, y - 5 * k, ln * .5, 5 * k, '#FBFBF8'); s.rect(x + ln * .3, y - 9 * k, ln * .28, 4 * k, '#F3F3F0')
        s.rect(x + ln * .24, y - 3.4 * k, ln * .46, 1.6 * k, '#26384A', .8); s.rect(x + ln * .32, y - 7.6 * k, ln * .24, 1.2 * k, '#26384A', .8)
    for i, (x, y, ln, k) in enumerate(((10, 250, 30, .55), (48, 252, 24, .5), (80, 250, 34, .6), (180, 248, 28, .5), (220, 252, 36, .6),
                                       (270, 250, 26, .5), (30, 280, 54, .9), (120, 284, 64, 1), (260, 278, 50, .85))):
        yacht(x, y, ln, k)
    # the track along the quay, nearest to us: barriers with sponsor boards, kerbs, the swimming-pool section
    s.rect(0, 312, W, 8, '#D9DCDF')                                  # catch fencing base
    for x in range(0, W, 26):
        s.rect(x + 1, 313, 24, 6, r.choice(['#1F4E8C', '#C8202A', '#111111', '#F2F2F2', '#E9B22A']))
    s.line('M0 304 L390 304', '#9AA0A6', .6, .8)
    for x in range(0, W, 13): s.line(f'M{x} 304 L{x} 312', '#9AA0A6', .5, .8)
    s.gpath('M0 320 L390 320 L390 396 L0 396 Z', [(0, '#55585F'), (1, '#3F4249')], 0, 320, 0, 396)
    for x in range(0, W, 14):
        s.rect(x, 320, 7, 4, '#D3262B'); s.rect(x + 7, 320, 7, 4, '#F4F4F4')
        s.rect(x, 392, 7, 4, '#D3262B'); s.rect(x + 7, 392, 7, 4, '#F4F4F4')
    s.line('M0 358 L390 358', '#FFFFFF', .8, .35)
    # two Formula 1 cars, side on, moving right: wings, nose, halo, sidepods, engine cover, wheels with rims
    def f1(x, y, body, accent, k=1):
        def P(d): return d
        s.path(f'M{x} {y} L{x + 6 * k} {y - 5 * k} L{x + 40 * k} {y - 7 * k} L{x + 54 * k} {y - 12 * k} L{x + 70 * k} {y - 16 * k} '
               f'L{x + 86 * k} {y - 17 * k} L{x + 94 * k} {y - 10 * k} L{x + 112 * k} {y - 9 * k} L{x + 114 * k} {y} Z', body)
        s.path(f'M{x + 40 * k} {y - 3 * k} L{x + 92 * k} {y - 5 * k} L{x + 92 * k} {y - 1 * k} L{x + 40 * k} {y} Z', accent, .9)  # sidepod stripe
        s.path(f'M{x + 62 * k} {y - 14 * k} Q{x + 70 * k} {y - 22 * k} {x + 80 * k} {y - 17 * k}', 'none')
        s.line(f'M{x + 60 * k} {y - 13 * k} Q{x + 69 * k} {y - 23 * k} {x + 80 * k} {y - 16 * k}', '#1A1A1A', 2 * k)  # halo
        s.disc(x + 66 * k, y - 15 * k, 2.6 * k, accent)                                                   # helmet
        s.rect(x + 104 * k, y - 22 * k, 12 * k, 3 * k, body); s.rect(x + 108 * k, y - 20 * k, 2 * k, 11 * k, '#222')  # rear wing
        s.rect(x + 112 * k, y - 24 * k, 4 * k, 15 * k, accent)
        s.rect(x - 8 * k, y - 2.5 * k, 14 * k, 3 * k, accent); s.rect(x - 9 * k, y - 6 * k, 3 * k, 6 * k, body)  # front wing
        for wx, wr in ((x + 20 * k, 8 * k), (x + 96 * k, 9 * k)):
            s.disc(wx, y + 1, wr, '#151619'); s.disc(wx, y + 1, wr * .55, '#3A3D44'); s.ring(wx, y + 1, wr * .55, accent, .8 * k)
        for i in range(4):
            s.line(f'M{x - 14 * k - i * 10} {y - 8 * k + i * 3} L{x - 40 * k - i * 14} {y - 8 * k + i * 3}', '#FFFFFF', .8, .35)
    f1(36, 352, '#D0231C', '#F2F2F2', .95); f1(220, 384, '#BFC6CF', '#1A9C8E', 1.0)
    # the grandstand in the foreground corner, full of people
    s.path('M0 396 L390 396 L390 460 L0 460 Z', '#2B2F38')
    for row in range(5):
        y = 404 + row * 11
        s.rect(0, y + 6, W, 2, '#4A505C')
        for i in range(70):
            x = i * 5.6 + (row % 2) * 2.5 + r.random()
            s.disc(x, y + 3, 1.8, r.choice(['#E8C9A8', '#C99A78', '#8A5A40', '#F2DEC4']))
            s.rect(x - 1.6, y + 4.4, 3.2, 2.4, r.choice(['#D3262B', '#FFFFFF', '#1F4E8C', '#F2C230', '#2A2A2A']))
    # the chequered flag at the line
    fx, fy = 350, 268
    s.line(f'M{fx} {fy} L{fx} {fy + 44}', '#3A3A3A', 1.4)
    for i in range(5):
        for j in range(4): s.rect(fx + 1 + i * 4, fy + j * 4, 4, 4, '#111111' if (i + j) % 2 == 0 else '#FFFFFF')
    s.birds(3, 150, 40, 80, '#4A5A6A', 9)
    return s

# ---------- Giza: the three pyramids, their queens, and the Sphinx ----------
def giza():
    s = S()
    s.sky([(0, '#5A80B4'), (.42, '#C8B49C'), (.62, '#EDC08C'), (1, '#F6D9A6')])
    s.glow(316, 220, 160, '#FFE4B0', .8); s.disc(316, 220, 16, '#FFF4D8', .95)
    s.cloud(20, 80, 180, '#FCEBD6', 0.8500000000000001); s.cloud(210, 118, 150, '#FCE2C6', 0.75)
    r = random.Random(61)
    horizon = 282
    # far Cairo in the haze along the horizon
    x = 0
    while x < W:
        w = 4 + r.random() * 8; h = 3 + r.random() * 10
        s.rect(x, horizon - h, w, h, '#C9B398', .6); x += w + r.random() * 3
    s.gpath(f'M0 {horizon} L390 {horizon} L390 460 L0 460 Z', [(0, '#E6BE88'), (1, '#D29E64')], 0, horizon, 0, 460)
    def pyramid(cx, base, half, h, lit, shade, courses, cap=None):
        apex = (cx - half * .12, base - h)
        # a slightly ragged outline: the casing stones are gone, leaving steps
        left = [(cx - half, base), apex]
        right_base = (cx + half, base)
        s.path(f'M{cx - half} {base} L{apex[0]:.1f} {apex[1]:.1f} L{cx + half * .2:.1f} {base} Z', lit)
        s.path(f'M{apex[0]:.1f} {apex[1]:.1f} L{cx + half} {base} L{cx + half * .2:.1f} {base} Z', shade)
        for k in range(1, courses):
            t = k / courses; y = base - h * t
            xl = lerp(cx - half, apex[0], t); xm = lerp(cx + half * .2, apex[0], t); xr = lerp(cx + half, apex[0], t)
            s.line(f'M{xl:.1f} {y:.1f} L{xm:.1f} {y:.1f}', '#B98A58', .45, .55)
            s.line(f'M{xm:.1f} {y:.1f} L{xr:.1f} {y:.1f}', '#9A6E44', .45, .45)
            if k % 3 == 0:  # broken edge steps
                s.rect(xr - 1.5, y - 1, 2, 1.6, '#B98A58', .7)
        if cap:
            t = .82
            s.path(f'M{lerp(cx - half, apex[0], t):.1f} {base - h * t:.1f} L{apex[0]:.1f} {apex[1]:.1f} L{lerp(cx + half, apex[0], t):.1f} {base - h * t:.1f} Z', cap)
    # back to front: Menkaure and its queens (smaller, right), Khafre (centre, on higher ground), Khufu (left, nearer)
    for qx, qh in ((350, 22), (368, 18), (384, 16)):
        pyramid(qx, horizon + 2, qh * .9, qh, '#D9A770', '#B8834F', 6)
    pyramid(296, horizon + 2, 52, 64, '#DDAA70', '#B98450', 16)
    pyramid(206, horizon + 4, 108, 140, '#E2B077', '#BE8853', 30, cap='#EFD3A8')
    pyramid(86, horizon + 10, 112, 132, '#DDA96F', '#B7824E', 30)
    # the Sphinx, lying in its enclosure before Khafre: about a third of the pyramid's width, as it really is
    s.path('M120 362 L262 362 L254 346 L128 346 Z', '#C08E58')                 # the rock-cut enclosure
    s.path('M128 346 L254 346 L252 350 L130 350 Z', '#A87A48', .6)
    x0, y0 = 134, 358                                                          # front of the forepaws
    body = (f'M{x0} {y0} L{x0} {y0 - 6} L{x0 + 26} {y0 - 6} L{x0 + 30} {y0 - 20} '      # paws, chest
            f'L{x0 + 52} {y0 - 22} Q{x0 + 90} {y0 - 20} {x0 + 112} {y0 - 17} '          # back
            f'Q{x0 + 122} {y0 - 15} {x0 + 124} {y0 - 7} L{x0 + 124} {y0} Z')             # haunch
    s.gpath(body, [(0, '#DDB07A'), (1, '#B98650')], 0, y0 - 22, 0, y0)
    # the head and nemes headdress, flaring to the shoulders, with its stripes; the worn face in profile
    head = (f'M{x0 + 28} {y0 - 20} L{x0 + 30} {y0 - 40} Q{x0 + 32} {y0 - 50} {x0 + 42} {y0 - 50} '
            f'Q{x0 + 50} {y0 - 49} {x0 + 51} {y0 - 40} L{x0 + 56} {y0 - 20} Z')
    s.gpath(head, [(0, '#E2B680'), (1, '#BC8A54')], x0 + 28, 0, x0 + 56, 0)
    for k in range(6):
        y = y0 - 44 + k * 4
        s.line(f'M{x0 + 31 + k * .4:.1f} {y} L{x0 + 51 + k * .9:.1f} {y + 1}', '#A9784A', .55, .75)
    s.path(f'M{x0 + 28} {y0 - 42} L{x0 + 25} {y0 - 37} L{x0 + 27} {y0 - 34} L{x0 + 26} {y0 - 30} L{x0 + 30} {y0 - 27} L{x0 + 31} {y0 - 42} Z', '#C99A64')  # face
    s.disc(x0 + 30, y0 - 38, .9, '#7A5636')                                     # eye
    s.line(f'M{x0 + 4} {y0 - 3} L{x0 + 24} {y0 - 3}', '#A9784A', .6)          # paws' line
    s.line(f'M{x0 + 60} {y0 - 12} Q{x0 + 90} {y0 - 10} {x0 + 116} {y0 - 10}', '#A9784A', .7, .7)  # flank
    s.path(f'M{x0 + 104} {y0} Q{x0 + 108} {y0 - 8} {x0 + 118} {y0 - 6} L{x0 + 120} {y0} Z', '#B98650')   # hind paw
    # dunes in front with soft shadow, and a camel caravan on the ridge, small against the plateau
    s.gpath('M0 400 Q90 372 190 388 Q290 404 390 380 L390 460 L0 460 Z', [(0, '#E2B27A'), (1, '#C9925A')], 0, 380, 0, 460)
    s.path('M190 388 Q290 404 390 380 L390 392 Q300 412 200 398 Z', '#B9844E', .5)
    for k, cx_ in enumerate((84, 104, 124)):
        y = 380 - (cx_ - 84) * .05
        s.path(f'M{cx_} {y} Q{cx_ + 3} {y - 7} {cx_ + 7} {y - 6} Q{cx_ + 10} {y - 10} {cx_ + 13} {y - 6} L{cx_ + 16} {y - 9} L{cx_ + 17} {y - 7} L{cx_ + 14} {y - 3} L{cx_ + 14} {y + 5} L{cx_ + 12.5} {y + 5} L{cx_ + 12} {y} L{cx_ + 3} {y} L{cx_ + 2} {y + 5} L{cx_ + .5} {y + 5} Z', '#5A3E2C')
        s.rect(cx_ + 6, y - 11, 2.6, 5, '#3A4A6A' if k != 1 else '#8A3A2E'); s.disc(cx_ + 7.3, y - 12, 1.4, '#3A2A22')
    # date palms, clustered, at the edge of the cultivation
    for px, ph in ((318, 64), (334, 52), (350, 70), (368, 56), (380, 62)):
        top = 392 - ph
        s.line(f'M{px} 394 Q{px + 3} {top + ph / 2} {px + 1} {top}', '#5E4432', 2.4)
        for k in range(1, 6): s.line(f'M{px - 1} {top + k * ph / 7:.1f} L{px + 3} {top + k * ph / 7 - 1:.1f}', '#3E2C20', .6, .6)
        for dx, dy in ((-15, 9), (-12, -4), (-4, -10), (5, -10), (13, -4), (16, 9)):
            s.line(f'M{px + 1} {top} Q{px + 1 + dx / 2} {top + dy - 6} {px + 1 + dx} {top + dy}', '#4E6034', 2)
    s.birds(3, 210, 120, 70, '#6A5848', 4)
    return s

if __name__ == '__main__':
    import sys
    for name in sys.argv[1:] or ['goldengate', 'colosseum']:
        open(f'{name}.svg', 'w').write(globals()[name]().svg())
    print('ok')
