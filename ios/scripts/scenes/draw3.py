import math, random
exec(open('draw.py').read().split('# ---------- London')[0])

def santorini():
    s=S(); s.sky([(0,'#5E6FA8'),(.45,'#C98FAE'),(.75,'#F3B48C'),(1,'#F8D7A6')])
    s.glow(80,250,120,'#FFD9A8',.8); s.disc(80,250,16,'#FFF0D2',.95)
    s.water(250,'#4A6FA5','#1E3A6B','#FFD9A8',50,9)
    # far islands of the caldera
    s.path('M0 252 Q60 238 120 250 L130 252 Z','#6B5A7A',.7)
    # the caldera cliff: red and dark volcanic layers
    s.path('M150 460 L150 300 Q170 230 230 200 Q300 175 390 170 L390 460 Z','#8A5A4C')
    for i,c in enumerate(('#6E463E','#A0684F','#5A3B36')):
        s.path(f'M{150+i*6} {330+i*30} Q{240} {300+i*30-20} 390 {290+i*30} L390 {300+i*30} Q240 {312+i*30-20} {150+i*6} {342+i*30} Z',c,.7)
    r=random.Random(31)
    # whitewashed houses on the cliff top, cascading, with blue doors
    def cube(x,y,w,h):
        s.rect(x,y,w,h,'#FBF8F2'); s.rect(x,y,w,1.4,'#FFFFFF')
        s.rect(x+w,y+2,2,h-2,'#D9D3CC')  # shadow side
        if r.random()<.5: s.path(f'M{x+2} {y+h} L{x+2} {y+h-5} Q{x+3.8} {y+h-7.5} {x+5.6} {y+h-5} L{x+5.6} {y+h} Z','#3E7FC4')
        if r.random()<.4: s.rect(x+w-5,y+3,2.6,2.6,'#3E7FC4')
    for row in range(10):
        y=180+row*12; x0=215-row*7 if row<5 else 180+r.random()*6
        x=x0+r.random()*6
        while x<388:
            w=10+r.random()*10; h=8+r.random()*4
            if r.random()<.85: cube(x,y-h,w,h)
            x+=w+1.2+r.random()*2
    # the famous blue domes with white crosses, and a bell tower
    for dx,dy,rr in ((268,186,10),(310,214,8),(232,236,7)):
        s.rect(dx-rr,dy,rr*2,10,'#FBF8F2')
        s.path(f'M{dx-rr} {dy} Q{dx-rr} {dy-rr*1.3} {dx} {dy-rr*1.35} Q{dx+rr} {dy-rr*1.3} {dx+rr} {dy} Z','#2F6FC0')
        s.line(f'M{dx} {dy-rr*1.35-6} L{dx} {dy-rr*1.35} M{dx-2.5} {dy-rr*1.35-4} L{dx+2.5} {dy-rr*1.35-4}','#FFFFFF',1.2)
    s.rect(290,174,12,22,'#FBF8F2'); s.path('M290 174 Q296 164 302 174 Z','#2F6FC0'); s.path('M293 186 L293 180 Q296 177 299 180 L299 186 Z','#E7C76A')
    # the windmill on the point
    s.path('M178 252 L192 252 L190 222 L180 222 Z','#FBF8F2'); s.path('M178 222 Q185 212 192 222 Z','#9A6A4A')
    for a in (20,110,200,290):
        x2=185+22*math.cos(math.radians(a)); y2=218+22*math.sin(math.radians(a))
        s.line(f'M185 218 L{x2:.1f} {y2:.1f}','#5A4038',1.2); s.path(f'M185 218 L{x2:.1f} {y2:.1f} L{185+20*math.cos(math.radians(a+18)):.1f} {218+20*math.sin(math.radians(a+18)):.1f} Z','#F3EDE2',.85)
    # sailboat in the caldera
    s.path('M60 300 L96 300 L90 306 L66 306 Z','#F8F4EC'); s.path('M78 300 L78 266 L94 298 Z','#FFFFFF')
    s.birds(3,90,120,80,'#6A5A7A')
    return s

def monaco():
    s=S(); s.sky([(0,'#5AA0D8'),(.6,'#BFDDF0'),(1,'#F0EBDF')])
    s.glow(320,70,80,'#FFF6DE',.8)
    # the mountain behind Monte Carlo
    s.path('M0 170 Q80 110 170 130 Q260 90 390 120 L390 260 L0 260 Z','#8FA38A')
    s.path('M0 170 Q80 110 170 130 Q260 90 390 120 L390 150 Q200 140 0 200 Z','#FFFFFF',.15)
    r=random.Random(41)
    cols=['#F4E2C4','#EED5AE','#F7EEDD','#E8C9A0','#F2D9C2','#DCC6A6']
    # apartment blocks climbing the hill in uneven terraces, with gardens between
    for row in range(6):
        base_y=262-row*20; x=-4+r.random()*10
        while x<392:
            w=16+r.random()*24; h=18+r.random()*16+(5-row)*3
            if r.random()<.82:
                c=cols[r.randrange(len(cols))]
                y=base_y-h
                s.rect(x,y,w,h+row*20,c); s.rect(x,y,w,1.5,'#FFFFFF',.5); s.rect(x,y-2,w,2,'#C27B5A',.55)
                for k in range(int((w-2)//6)):
                    for j in range(int(h//8)):
                        s.rect(x+3+k*6,y+4+j*8,3,4,'#6E8496',.55)
            else:
                s.disc(x+w/2,base_y-8,8,'#5E7F52',.9)
            x+=w+1+r.random()*3
    # the Casino: belle-époque front with twin towers and a green-grey dome
    cx=96
    s.rect(cx-34,236,68,24,'#F2E4CC'); s.rect(cx-40,228,12,32,'#F2E4CC'); s.rect(cx+28,228,12,32,'#F2E4CC')
    s.path(f'M{cx-40} 228 Q{cx-34} 216 {cx-28} 228 Z','#7E9A8E'); s.path(f'M{cx+28} 228 Q{cx+34} 216 {cx+40} 228 Z','#7E9A8E')
    s.path(f'M{cx-12} 236 Q{cx} 218 {cx+12} 236 Z','#7E9A8E')
    for k in range(6): s.path(f'M{cx-28+k*10} 258 L{cx-28+k*10} 246 Q{cx-24+k*10} 241 {cx-20+k*10} 246 L{cx-20+k*10} 258 Z','#8A7A68',.6)
    # palms along the harbour road
    for px in (30,160,240,350):
        s.line(f'M{px} 272 Q{px+3} 255 {px+1} 240','#6A5440',2)
        for dx,dy in ((-12,4),(-9,-5),(0,-8),(9,-5),(12,4)): s.line(f'M{px+1} 240 Q{px+1+dx/2} {240+dy-5} {px+1+dx} {240+dy}','#3F6A3A',1.8)
    # the track along the harbour: red-and-white kerbs, barriers, and two F1 cars
    s.rect(0,272,W,22,'#4A4D55')
    for i in range(0,W,12): s.rect(i,292,6,4,'#D6342C'); s.rect(i+6,292,6,4,'#F5F5F5')
    for i in range(0,W,12): s.rect(i,270,6,3,'#D6342C'); s.rect(i+6,270,6,3,'#F5F5F5')
    s.rect(0,264,W,6,'#C9CDD2'); s.rect(0,264,W,1.5,'#9EA4AA')  # armco barrier
    s.line('M0 283 L390 283','#FFFFFF',.8,.6)
    def f1(x,y,body,accent):
        # low single-seater in profile: nose, sidepod, airbox, front and rear wings, four wheels
        s.path(f'M{x} {y} L{x+8} {y-3} L{x+30} {y-4} L{x+38} {y-9} L{x+46} {y-9} L{x+50} {y-4} L{x+58} {y-4} L{x+58} {y} Z',body)
        s.rect(x-4,y-1,8,2,accent); s.rect(x+55,y-11,6,8,accent)   # wings
        s.path(f'M{x+36} {y-9} Q{x+39} {y-13} {x+43} {y-9} Z','#222')  # halo / driver
        for wx,wr in ((x+10,4.4),(x+50,5.2)): s.disc(wx,y+1,wr,'#18191C'); s.disc(wx,y+1,1.6,'#7A7A7A')
        s.line(f'M{x+64} {y-6} L{x+96} {y-6} M{x+64} {y-1} L{x+88} {y-1}','#FFFFFF',.8,.5)  # speed lines behind
    f1(150,287,'#D2281F','#F5F5F5'); f1(268,287,'#C9CED6','#1F8A8A')
    s.water(296,'#2E7FB8','#124B7A','#FFFFFF',60,3)
    # superyachts in Port Hercule
    for yx,yy,ln in ((40,330,70),(150,350,90),(280,326,60),(250,392,80)):
        s.path(f'M{yx} {yy} L{yx+ln} {yy} L{yx+ln-8} {yy+8} L{yx+6} {yy+8} Z','#FBFBF8')
        s.rect(yx+ln*.25,yy-7,ln*.45,7,'#FBFBF8'); s.rect(yx+ln*.33,yy-12,ln*.25,5,'#FBFBF8')
        s.rect(yx+ln*.27,yy-5,ln*.4,2,'#2A3A4A',.7)
    # a chequered flag
    fx,fy=350,212
    s.line(f'M{fx} {fy} L{fx} {fy+50}','#3A3A3A',1.5)
    for i in range(4):
        for j in range(3): s.rect(fx+1+i*5,fy+j*5,5,5,'#111' if (i+j)%2==0 else '#FFF')
    return s

def giza():
    s=S(); s.sky([(0,'#4F78A8'),(.5,'#E5B98E'),(.8,'#F4CF96'),(1,'#F7DFAE')])
    s.glow(300,210,140,'#FFE7B8',.85); s.disc(300,210,18,'#FFF4D8',.95)
    s.path('M0 300 Q120 290 240 298 Q330 304 390 296 L390 460 L0 460 Z','#E2B47C')
    def pyramid(cx,base,half,h,lit,shade):
        s.path(f'M{cx-half} {base} L{cx} {base-h} L{cx+half} {base} Z',lit)
        s.path(f'M{cx} {base-h} L{cx+half} {base} L{cx+half*0.2} {base} Z',shade)
        for k in range(1,14):  # stone courses
            y=base-h*k/14; w=half*(1-k/14)
            s.line(f'M{cx-w:.1f} {y:.1f} L{cx+w*0.2:.1f} {y:.1f}','#B88A58',.5,.5)
        return
    pyramid(70,300,70,92,'#D9A46A','#B4804E')     # Menkaure (far)
    pyramid(250,300,120,170,'#E0AE73','#BC8752')  # Khafre with its casing cap
    s.path('M250 130 L238 150 L262 150 Z','#EFD2A6')
    pyramid(150,304,95,128,'#DDAA6F','#B7834F')   # Khufu (nearer)
    # the Sphinx in front: lion body, paws forward, head with the nemes headdress
    sx,sy=96,372
    s.path(f'M{sx} {sy} L{sx} {sy-18} Q{sx+8} {sy-28} {sx+30} {sy-26} L{sx+90} {sy-22} Q{sx+104} {sy-18} {sx+104} {sy} Z','#C99A63')
    s.rect(sx-26,sy-6,30,6,'#C99A63')  # paws
    s.path(f'M{sx-2} {sy-18} L{sx-6} {sy-40} Q{sx+4} {sy-58} {sx+18} {sy-50} L{sx+24} {sy-28} Z','#C99A63')  # head + nemes
    s.path(f'M{sx-6} {sy-40} L{sx-10} {sy-24} L{sx-2} {sy-20} Z','#B4844F')  # headdress lappet
    s.path(f'M{sx+2} {sy-44} L{sx+10} {sy-44} L{sx+8} {sy-36} L{sx+2} {sy-38} Z','#A87A48')  # face shadow
    s.rect(sx+40,sy-14,40,1,'#A87A48',.6)
    # palms and a few dunes in front
    s.path('M0 410 Q120 392 230 404 Q320 414 390 398 L390 460 L0 460 Z','#D7A46A')
    for px,ph in ((330,70),(352,56),(372,64)):
        top=360-ph; s.line(f'M{px} 362 Q{px+4} {top+ph/2} {px+1} {top}','#5A4030',2.4)
        for dx,dy in ((-14,8),(-11,-5),(0,-10),(11,-5),(14,8)): s.line(f'M{px+1} {top} Q{px+1+dx/2} {top+dy-6} {px+1+dx} {top+dy}','#4A5A30',2)
    s.birds(3,40,90,90,'#6A5A4A')
    return s

def colosseum():
    s=S(); s.sky([(0,'#6E9FD0'),(.6,'#E7C9A8'),(1,'#F4DDBE')])
    s.glow(80,140,100,'#FFF0D6',.8)
    stone='#E2BE8E'; shade='#B98F62'; dark='#6E5038'
    # the oval drum: four storeys, the top one broken away on the right
    x0,x1,base=40,350,330
    tiers=[(base,52),(base-52,46),(base-98,44),(base-142,30)]
    for i,(y,h) in enumerate(tiers):
        right = x1 if i<2 else x1-40-(i-2)*70
        s.rect(x0,y-h,right-x0,h,stone)
        s.rect(x0,y-h,right-x0,3,'#F2D8B0')
        if i<3:
            n=int((right-x0)//26)
            for k in range(n):
                ax=x0+8+k*26
                s.path(f'M{ax} {y-4} L{ax} {y-h+18} Q{ax+8} {y-h+6} {ax+16} {y-h+18} L{ax+16} {y-4} Z',dark,.85)
                s.rect(ax-5,y-h+4,3,h-6,shade,.6)   # columns between the arches
        else:
            for k in range(int((right-x0)//26)):
                s.rect(x0+10+k*26,y-h+10,8,10,dark,.75)   # attic windows
    # the broken edge, stepping down in stone where the outer ring is gone
    s.path(f'M{x1-40} {base-98} L{x1-40} {base-110} L{x1-24} {base-110} L{x1-24} {base-98} Z',stone)
    s.path(f'M{x1-110} {base-142} L{x1-110} {base-150} L{x1-90} {base-150} L{x1-90} {base-142} Z',stone)
    # curve shading on every storey, so the drum reads as an oval
    g=nid('cv'); s.defs.append(f'<linearGradient id="{g}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset=".35" stop-color="#000" stop-opacity="0"/><stop offset=".75" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".25"/></linearGradient>')
    for i,(y,h) in enumerate(tiers):
        right = x1 if i<2 else x1-40-(i-2)*70
        s.add(f'<rect x="{x0}" y="{y-h}" width="{right-x0}" height="{h}" fill="url(#{g})"/>')
    # the inner ring seen through the broken part
    s.rect(x1-40,base-98-30,30,30,'#C9A27A'); 
    for k in range(2): s.path(f'M{x1-36+k*14} {base-100} L{x1-36+k*14} {base-118} Q{x1-31+k*14} {base-124} {x1-26+k*14} {base-118} L{x1-26+k*14} {base-100} Z',dark,.7)
    # ground, umbrella pines and cypresses
    s.rect(0,base,W,H-base,'#CDB48C'); s.rect(0,base,W,4,'#BFA27A')
    for px,py in ((20,300),(372,296)):
        s.line(f'M{px} {base} L{px} {py}','#5A4030',2.4)
        s.add(f'<ellipse cx="{px}" cy="{py-6}" rx="28" ry="10" fill="#4B6A3A"/>')
    for cx_ in (8,388):
        s.add(f'<ellipse cx="{cx_}" cy="{base-26}" rx="6" ry="26" fill="#3E5A34"/>')
    s.birds(4,200,80,120,'#6A5A4A')
    # a Vespa on the street
    vx,vy=170,370
    s.path(f'M{vx} {vy} Q{vx+6} {vy-14} {vx+20} {vy-12} L{vx+30} {vy-12} Q{vx+36} {vy-4} {vx+34} {vy} Z','#7FB8A8')
    s.disc(vx+4,vy+2,5,'#2A2A2A'); s.disc(vx+30,vy+2,5,'#2A2A2A'); s.line(f'M{vx+26} {vy-12} L{vx+22} {vy-22} L{vx+16} {vy-22}','#3A3A3A',1.4)
    return s

def goldengate():
    s=S(); s.sky([(0,'#6C8DC4'),(.5,'#E5A98C'),(.8,'#F4C28E'),(1,'#F8DDB0')])
    s.glow(300,250,140,'#FFE3B0',.8)
    # Marin headlands with fog rolling over
    s.path('M0 270 Q60 230 140 246 Q220 214 300 236 Q350 226 390 240 L390 300 L0 300 Z','#7C7A6A')
    s.path('M0 250 Q70 222 150 236 Q230 210 320 228 Q360 220 390 232 L390 248 Q300 246 200 250 Q90 256 0 262 Z','#FFFFFF',.55)
    s.water(298,'#5E7FA6','#22385A','#FFE3B0',70,12)
    orange='#C0362C'; dark='#8E2620'
    deck=318
    def tower(tx,top):
        for sgn in (-1,1):
            s.path(f'M{tx+sgn*12-4} 400 L{tx+sgn*9-3} {top} L{tx+sgn*9+3} {top} L{tx+sgn*12+4} 400 Z',orange)
        # art-deco cross portals between the legs
        for yy,hh in ((top+8,10),(top+40,10),(top+74,10),(deck-24,10)):
            s.rect(tx-10,yy,20,hh,orange); s.rect(tx-6,yy+3,12,hh-6,dark,.6)
        for k in range(3):
            s.line(f'M{tx-11} {top+20+k*28} L{tx+11} {top+20+k*28}',dark,.8,.6)
    tower(110,150); tower(330,150)
    # main cables and suspenders
    def cab(x0,y0,x1,y1,sag):
        s.line(f'M{x0} {y0} Q{(x0+x1)/2} {y1+sag} {x1} {y1}',orange,2)
    cab(110,152,330,152,190)
    s.line(f'M110 152 Q60 240 -10 {deck}',orange,2); s.line(f'M330 152 Q370 230 400 {deck}',orange,2)
    for i in range(1,30):
        x=110+i*220/30; t=i/30; yc=(1-t)**2*152+2*(1-t)*t*(152+190)+t*t*152
        s.line(f'M{x:.1f} {yc:.1f} L{x:.1f} {deck}',orange,.7,.8)
    def side(p0,p1,p2):
        for k in range(1,10):
            t=k/10; x=(1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0]; y=(1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1]
            if 0<x<W and y<deck: s.line(f'M{x:.1f} {y:.1f} L{x:.1f} {deck}',orange,.7,.8)
    side((110,152),(60,240),(-10,deck)); side((330,152),(370,230),(400,deck))
    # the deck with its truss
    s.rect(-5,deck,W+10,7,orange); s.rect(-5,deck+7,W+10,5,dark)
    for x in range(0,W,10): s.line(f'M{x} {deck+7} L{x+5} {deck+12} L{x+10} {deck+7}','#5E1A16',.6)
    for lx in range(6,W,26): s.disc(lx,deck-2,1.4,'#FFE3A0')
    # a sailboat and a ferry
    s.path('M60 372 L96 372 L90 378 L66 378 Z','#F8F4EC'); s.path('M78 372 L78 340 L94 370 Z','#FFFFFF')
    s.path('M250 392 L320 392 L312 400 L256 400 Z','#F2F0EA'); s.rect(262,384,40,8,'#F2F0EA'); s.rect(266,386,32,2,'#3A4A5A',.7)
    s.birds(4,180,90,120,'#6A5A6A')
    return s

names=[('santorini',santorini),('monaco',monaco),('giza',giza),('colosseum',colosseum),('goldengate',goldengate)]
for n,f in names: open(f'{n}.svg','w').write(f().svg())
print('ok')
