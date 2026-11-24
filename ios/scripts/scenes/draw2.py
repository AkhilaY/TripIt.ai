import math, random
exec(open('draw.py').read().split('# ---------- London')[0])

def eiffel(s, cx, base, top, ink, sky_behind):
    H_ = base-top                      # ~270
    y1 = base-0.17*H_                  # first platform
    y2 = base-0.38*H_                  # second platform
    y3 = top+0.07*H_                   # top cabin
    bw = 0.27*H_                       # half width at the ground
    # legs below the first platform: four legs seen as two, each a curved pillar
    for sgn in (-1,1):
        ox, ix = cx+sgn*bw, cx+sgn*(bw-0.09*H_)
        ox1, ix1 = cx+sgn*0.15*H_, cx+sgn*0.10*H_
        s.path(f'M{ox:.1f} {base} Q{cx+sgn*0.19*H_:.1f} {(base+y1)/2:.1f} {ox1:.1f} {y1:.1f} L{ix1:.1f} {y1:.1f} Q{cx+sgn*0.15*H_:.1f} {(base+y1)/2+8:.1f} {ix:.1f} {base} Z', ink)
        # lattice hint inside each leg
        for k in range(1,5):
            t=k/5; y=base-(base-y1)*t
            s.line(f'M{ox+(ox1-ox)*t:.1f} {y:.1f} L{ix+(ix1-ix)*t:.1f} {y-6:.1f}', sky_behind, .6, .35)
    # the great arch between the legs
    ai = bw-0.09*H_
    s.line(f'M{cx-ai:.1f} {base} Q{cx:.1f} {y1-0.02*H_:.1f} {cx+ai:.1f} {base}', ink, 3.2)
    # first platform with its frieze of little arches
    pw = 0.17*H_
    s.rect(cx-pw, y1-9, 2*pw, 11, ink)
    n=12
    for i in range(n):
        x=cx-pw+3+i*(2*pw-6)/n
        s.path(f'M{x:.1f} {y1} L{x:.1f} {y1-4} Q{x+(2*pw-6)/n/2:.1f} {y1-8} {x+(2*pw-6)/n:.1f} {y1-4} L{x+(2*pw-6)/n:.1f} {y1} Z', sky_behind, .5)
    # middle section: two converging legs with the open space between
    w1, w2 = 0.135*H_, 0.065*H_        # outer half-widths at platform 1 and 2
    g1, g2 = 0.06*H_, 0.012*H_         # half-width of the opening
    s.evenodd(f'M{cx-w1:.1f} {y1-9} L{cx-w2:.1f} {y2} L{cx+w2:.1f} {y2} L{cx+w1:.1f} {y1-9} Z '
              f'M{cx-g1:.1f} {y1-9} L{cx-g2:.1f} {y2+14} Q{cx:.1f} {y2+6} {cx+g2:.1f} {y2+14} L{cx+g1:.1f} {y1-9} Z', ink)
    for k in range(1,4):
        t=k/4; y=y1-9-(y1-9-y2)*t; wo=w1+(w2-w1)*t; wi=g1+(g2-g1)*t
        for sgn in (-1,1):
            s.line(f'M{cx+sgn*wo:.1f} {y+8:.1f} L{cx+sgn*wi:.1f} {y-8:.1f}', sky_behind, .6, .3)
    # second platform
    s.rect(cx-w2-5, y2-6, 2*(w2+5), 7, ink)
    # the long upper section, curving in towards the top
    wt = 0.012*H_
    s.path(f'M{cx-w2+1:.1f} {y2-6} Q{cx-0.03*H_:.1f} {(y2+y3)/2:.1f} {cx-wt:.1f} {y3} L{cx+wt:.1f} {y3} Q{cx+0.03*H_:.1f} {(y2+y3)/2:.1f} {cx+w2-1:.1f} {y2-6} Z', ink)
    for k in range(1,6):
        y=y2-6-(y2-6-y3)*k/6; s.line(f'M{cx-6+k:.1f} {y:.1f} L{cx+6-k:.1f} {y:.1f}', sky_behind, .5, .3)
    # top cabin, dome and antenna
    s.rect(cx-6, y3-8, 12, 9, ink); s.path(f'M{cx-5} {y3-8} Q{cx} {y3-16} {cx+5} {y3-8} Z', ink)
    s.rect(cx-1, top-10, 2, y3-top+2, ink)
    # golden lights along the tower (they twinkle in the app)
    r=random.Random(5)
    for i in range(70):
        y=top+12+r.random()*(base-top-14)
        if y>y1: t=(base-y)/(base-y1); half=bw+(0.15*H_-bw)*t
        elif y>y2: t=(y1-y)/(y1-y2); half=w1+(w2-w1)*t
        else: t=(y2-y)/(y2-y3); half=w2+(wt-w2)*t
        side=r.choice((-1,1)); x=cx+side*half*(0.85+r.random()*0.15)
        s.twinkle(x,y,.9,'#FFE6A6',.55+r.random()*.45)
    s.glow(cx, top-10, 12, '#FFE7A8', .7)

def paris():
    s=S(); s.sky([(0,'#232548'),(.45,'#55497A'),(.78,'#C2858F'),(1,'#EAB596')])
    s.stars(40,150); s.glow(200,320,170,'#FFC9A0',.35)
    ink='#1F1D33'
    r=random.Random(7)
    def roofs(x0,x1,base=332):
        x=x0
        while x<x1:
            w=26+r.random()*14; h=55+r.random()*22; top=base-h
            s.rect(x,top,w,h,ink); s.path(f'M{x-2} {top} L{x+5} {top-12} L{x+w-5} {top-12} L{x+w+2} {top} Z',ink)
            for c in (x+6,x+w-9): s.rect(c,top-18,3,7,ink)
            for k in range(3):
                for j in range(int(w//9)):
                    if r.random()<.55: s.rect(x+4+j*9,top+8+k*16,4,7,'#FFD58A',.7)
            x+=w+1
    eiffel(s, 196, 332, 62, ink, '#C98B93')
    roofs(-6,92); roofs(300,396)
    s.water(332,'#4A4568','#1C1B2E','#FFD58A',60)
    s.rect(0,350,W,6,ink)
    a=0
    while a<W:
        s.path(f'M{a} 356 L{a+78} 356 L{a+78} 378 Q{a+39} 358 {a} 378 Z',ink); s.disc(a+39,345,2,'#FFD58A'); s.glow(a+39,345,9,'#FFD58A',.35); a+=78
    return s

def amalfi():
    s=S(); s.sky([(0,'#79ACD3'),(.55,'#C9DFEC'),(1,'#F4E6D2')])
    s.glow(310,80,90,'#FFF6DE',.85); s.birds(4,40,60,90,'#5A6A7A')
    # high rocky ridges behind, hazy
    s.path('M0 175 L30 120 L70 140 L110 90 L150 120 L190 70 L230 110 L270 85 L320 125 L360 100 L390 130 L390 300 L0 300 Z','#A9B2AE')
    s.path('M0 175 L30 120 L70 140 L110 90 L150 120 L190 70 L230 110 L270 85 L320 125 L360 100 L390 130 L390 150 L0 200 Z','#FFFFFF',.18)
    # the hillside the town is built on, then the two sides of the gorge coming down to the beach
    s.path('M0 205 Q100 168 195 178 Q290 160 390 158 L390 338 L0 338 Z','#7A9268')
    s.path('M0 190 Q70 200 120 250 Q160 300 185 338 L0 338 Z','#6F8A63')
    s.path('M390 165 Q300 185 255 245 Q225 290 210 338 L390 338 Z','#647F59')
    s.path('M0 190 Q70 200 120 250 Q160 300 185 338 L150 338 Q120 290 60 250 Q30 232 0 228 Z','#5A7350',.5)
    r=random.Random(23)
    colours=['#F5D3AE','#EE9B78','#F7E7C6','#F2BE8E','#FCF1DE','#E7A985','#F1D88A','#F6C9C0']
    def house(x,y,w,h,fade):
        c=colours[r.randrange(len(colours))]
        s.rect(x,y,w,h,c,1-fade*.35); s.rect(x,y,w,1.2,'#FFFFFF',.45)
        if w>9:
            s.path(f'M{x+2.5:.1f} {y+h-1:.1f} L{x+2.5:.1f} {y+4:.1f} Q{x+4.2:.1f} {y+2:.1f} {x+5.9:.1f} {y+4:.1f} L{x+5.9:.1f} {y+h-1:.1f} Z','#6A5650',.7-fade*.3)
            if r.random()<.6: s.rect(x+w-5,y+3.5,2.6,3.2,'#6A5650',.6-fade*.3)
        else:
            s.rect(x+w/2-1.2,y+3,2.4,3,'#6A5650',.6-fade*.3)
        if r.random()<.25: s.rect(x-.5,y-1.3,w+1,1.3,'#C2694B',.8)
    # houses climb both sides of the gorge: packed near the beach, thinning and breaking up towards the top,
    # with the green slope showing between them
    def top_edge(x):  # a ragged upper limit, higher in the middle of the gorge
        return 205 + 28*math.sin(x/37) + 18*math.sin(x/13+1) + abs(x-200)*0.12
    for y in range(176,326,9):
        t=(y-176)/150
        left=0 if y<235 else (y-235)*0.9
        right=390-max(0,(y-210)*0.75)
        x=left+r.random()*6
        while x<right-6:
            w=8+r.random()*9; h=7+r.random()*4
            if y < top_edge(x):
                if r.random()<.12: house(x,y-h,w,h,1)
                elif r.random()<.25: s.disc(x+w/2,y-4,2.5+r.random()*2,'#4E6E40',.85)
            else:
                dense=.55+.42*t
                if r.random()<dense: house(x,y-h,w,h,1-t)
                elif r.random()<.35: s.disc(x+w/2,y-4,2.5+r.random()*2,'#4E6E40',.85)
            x+=w+.8
    # cypresses and pines
    for i in range(9):
        x=r.random()*390; y=190+r.random()*70
        s.ellipse(x,y,2.4,8,'#3E5A34',.9)
    # Santa Maria Assunta by the beach: green-and-yellow majolica dome with its lantern, and the bell tower
    dx,dy=202,318
    s.rect(dx-20,dy,40,18,'#F6E9D4'); s.rect(dx-14,dy-6,28,7,'#F1DFC3')
    s.path(f'M{dx-16} {dy-6} Q{dx-15} {dy-34} {dx} {dy-36} Q{dx+15} {dy-34} {dx+16} {dy-6} Z','#2F8A5B')
    for i in range(-3,4):
        s.line(f'M{dx+i*4.5:.1f} {dy-6} Q{dx+i*3.6:.1f} {dy-26} {dx} {dy-35}','#F1C94A',1.3,.95)
    s.line(f'M{dx-16} {dy-12} Q{dx} {dy-15} {dx+16} {dy-12}','#F1C94A',1.2)
    s.rect(dx-2.5,dy-42,5,7,'#F6E9D4'); s.disc(dx,dy-43,2.2,'#2F8A5B')
    s.rect(dx+24,dy-30,11,48,'#F0DCC0'); s.path(f'M{dx+22} {dy-30} L{dx+29.5} {dy-42} L{dx+37} {dy-30} Z','#2F8A5B'); s.rect(dx+27,dy-24,5,7,'#6A5650')
    # the beach: grey sand with rows of orange and blue umbrellas
    s.path('M120 338 Q200 330 300 338 L300 346 L120 346 Z','#D9CDB6')
    for row,yy in ((0,334),(1,340)):
        for i in range(11):
            ux=140+i*15+row*7; c=['#E86A3C','#2F7FB5','#F2B544'][(i+row)%3]
            s.path(f'M{ux-6} {yy} Q{ux} {yy-6} {ux+6} {yy} Z',c)
    s.water(344,'#2C8EAE','#0F4D6B','#FFFFFF',70,5)
    for bx_,by_ in ((70,384),(190,414),(310,376)):
        s.path(f'M{bx_-12} {by_} L{bx_+12} {by_} L{bx_+8} {by_+5} L{bx_-8} {by_+5} Z','#F8F4EC'); s.rect(bx_-4,by_-4,8,4,'#F8F4EC')
        s.line(f'M{bx_-30} {by_+7} L{bx_-14} {by_+5}','#FFFFFF',.8,.6)
    return s

for name,f in (('paris2',paris),('amalfi2',amalfi)):
    open(f'{name}.svg','w').write(f().svg())
print('ok')
