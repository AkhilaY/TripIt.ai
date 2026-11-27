import math, random
W, H = 390, 460
_id = [0]
def nid(p): _id[0] += 1; return f"{p}{_id[0]}"

def _c(c): return c.lstrip('#').upper()
def _n(v): return f"{v:.2f}".rstrip('0').rstrip('.') if isinstance(v,float) else str(v)

class S:
    def __init__(s): s.defs=[]; s.body=[]; s.ops=[]; s.mirroring=False
    def add(s, x): s.body.append(x)
    def op(s, *parts): s.ops.append(' '.join(_n(p) if isinstance(p,(int,float)) else str(p) for p in parts))
    def ring(s,cx,cy,r,c,w=1,o=1):
        s.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c}" stroke-width="{w}" opacity="{o}"/>'); s.op('O',cx,cy,r,_c(c),w,o)
    def ellipse(s,cx,cy,rx,ry,c,o=1):
        s.add(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx}" ry="{ry}" fill="{c}" opacity="{o}"/>'); s.op('E',cx,cy,rx,ry,_c(c),o)
    def evenodd(s,d,c,o=1):
        s.add(f'<path fill-rule="evenodd" d="{d}" fill="{c}" opacity="{o}"/>'); s.op('F',_c(c),o,d)
    def mirror(s,axis,o):
        s.add(f'<g transform="translate(0 {axis*2}) scale(1 -1)" opacity="{o}">'); s.op('M',axis,o); s.mirroring=True
    def unmirror(s): s.add('</g>'); s.op('m'); s.mirroring=False
    def gpath(s,d,stops,x1=0,y1=0,x2=0,y2=1,o=1):
        """A shape filled with a linear gradient between two points (in scene units)."""
        g=nid('gp')
        s.defs.append(f'<linearGradient id="{g}" gradientUnits="userSpaceOnUse" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'+''.join(f'<stop offset="{so}" stop-color="{c}"/>' for so,c in stops)+'</linearGradient>')
        s.add(f'<path d="{d}" fill="url(#{g})" opacity="{o}"/>')
        s.op('H',len(stops),x1,y1,x2,y2,o,*[x for so,c in stops for x in (so,_c(c))],d)
    def cloud(s,x,y,w,c,o=1):
        """A soft cloud with a flat base; drifts in the app."""
        parts=[(0.28,0,.28,.05),(0.52,-.035,.34,.075),(0.76,.005,.24,.045),(0.46,.03,.42,.04),(0.66,-.06,.16,.04)]
        s.add(f'<g opacity="{o}">'+''.join(f'<ellipse cx="{x+w*px:.1f}" cy="{y+w*py:.1f}" rx="{w*rx:.1f}" ry="{w*ry:.1f}" fill="{c}"/>' for px,py,rx,ry in parts)+'</g>')
        s.op('K',x,y,w,_c(c),o)
    def twinkle(s,x,y,r,c,o=1):
        s.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}" opacity="{o}"/>'); s.op('C' if s.mirroring else 'Y',x,y,r,_c(c),o)
    def sky(s, stops):
        g=nid('sky'); s.defs.append(f'<linearGradient id="{g}" x1="0" y1="0" x2="0" y2="1">'+''.join(f'<stop offset="{o}" stop-color="{c}"/>' for o,c in stops)+'</linearGradient>')
        s.add(f'<rect width="{W}" height="{H}" fill="url(#{g})"/>'); s.op('S',*[x for o,c in stops for x in (o,_c(c))])
    def glow(s,x,y,r,c,o=1):
        g=nid('g'); s.defs.append(f'<radialGradient id="{g}"><stop offset="0" stop-color="{c}" stop-opacity="{o}"/><stop offset=".3" stop-color="{c}" stop-opacity="{o*.5}"/><stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>')
        s.add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#{g})"/>'); s.op('G',x,y,r,_c(c),o)
    def rect(s,x,y,w,h,c,o=1,rx=0,kind='R'):
        s.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{c}" opacity="{o}"/>')
        if rx: s.op('U',x,y,w,h,rx,_c(c),o)
        else: s.op('R' if s.mirroring else kind,x,y,w,h,_c(c),o)
    def path(s,d,c,o=1):
        s.add(f'<path d="{d}" fill="{c}" opacity="{o}"/>')
        if c!='none' and o>0: s.op('P',_c(c),o,d)
    def line(s,d,c,w=1,o=1): s.add(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" opacity="{o}" stroke-linecap="round"/>'); s.op('L',_c(c),w,o,d)
    def disc(s,x,y,r,c,o=1,kind='C'): s.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}" opacity="{o}"/>'); s.op('C' if s.mirroring else kind,x,y,r,_c(c),o)
    def water(s,y,top,bot,shim,n=60,seed=1):
        g=nid('w'); s.defs.append(f'<linearGradient id="{g}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bot}"/></linearGradient>')
        s.add(f'<rect x="0" y="{y}" width="{W}" height="{H-y}" fill="url(#{g})"/>'); s.op('V',y,_c(top),_c(bot))
        r=random.Random(seed)
        for i in range(n):
            yy=y+3+r.random()*(H-y-6); w=4+r.random()*30
            s.rect(r.random()*W,yy,w,.9,shim,.1+r.random()*.35,kind='Q')
    def stars(s,n,ymax,seed=2):
        r=random.Random(seed)
        for i in range(n): s.disc(r.random()*W,r.random()*ymax,.5+r.random()*.9,'#ffffff',.3+r.random()*.6,kind='X')
    def birds(s,n,x0,y0,spread,c,seed=3):
        r=random.Random(seed)
        for i in range(n):
            x=x0+r.random()*spread; y=y0+r.random()*spread*.3; k=2+r.random()*3
            s.add(f'<path d="M{x-k} {y} q{k/2} {-k/2} {k} 0 q{k/2} {-k/2} {k} 0" fill="none" stroke="{c}" stroke-width=".9" opacity=".7" stroke-linecap="round"/>')
            s.op('B',x,y,k,_c(c))
    def windows(s,x,y,w,h,c,lit,dens=.45,seed=4,cw=2.2,ch=3,gx=5,gy=7):
        r=random.Random(seed); yy=y+4
        while yy<y+h-4:
            xx=x+3
            while xx<x+w-3:
                if r.random()<dens: s.rect(xx,yy,cw,ch,lit,.55+r.random()*.4,kind='T')
                xx+=gx
            yy+=gy
    def svg(s, scale=2):
        noise=nid('n')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W*scale}" height="{H*scale}" viewBox="0 0 {W} {H}"><defs>'+''.join(s.defs)+
                f'<filter id="{noise}"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .08 0"/></filter></defs>'
                +''.join(s.body)+f'<rect width="{W}" height="{H}" filter="url(#{noise})"/></svg>')
    def script(s): return '\n'.join(s.ops+['N'])

# ---------- London: Westminster at dusk, red double-decker on the bridge ----------
def london():
    s=S(); s.sky([(0,'#3E4A66'),(.5,'#8E93A6'),(.8,'#D9B29A'),(1,'#E8C49E')])
    s.glow(310,250,120,'#FFD9AA',.55); s.birds(5,40,70,120,'#2E3442')
    ink='#2F3440'
    def parl(q):
        q.rect(0,248,232,64,ink)
        x=4
        while x<226:
            q.path(f'M{x} 248 L{x+3} 234 L{x+6} 248 Z',ink); q.rect(x+1,258,3,9,'#FFD58A',.75); q.rect(x+1,274,3,9,'#FFD58A',.45); x+=10
        q.rect(60,220,22,30,ink); q.path('M58 222 L71 200 L84 222 Z',ink)  # central tower
        # Elizabeth Tower (Big Ben)
        q.rect(232,138,34,174,ink); q.rect(229,138,40,8,ink)
        q.disc(249,165,12,'#F6E6B8'); q.line('M249 165 L249 157 M249 165 L255 168',ink,1.3)
        q.rect(236,182,26,3,'#FFD58A',.5)
        q.path('M229 138 L231 120 L267 120 L269 138 Z',ink); q.path('M231 120 L249 82 L267 120 Z',ink); q.rect(248,66,2,18,ink)
        # London Eye
        cx,cy,r=330,212,58
        q.rect(278,298,112,12,ink); q.line(f'M{cx} {cy} L{cx-24} 300 M{cx} {cy} L{cx+20} 300',ink,3)
        for i in range(16):
            a=i*math.pi/8; q.line(f'M{cx} {cy} L{cx+r*math.cos(a):.1f} {cy+r*math.sin(a):.1f}',ink,.6,.55)
        for rr in (r,r-5): q.ring(cx,cy,rr,ink,1.4)
        for i in range(32):
            a=i*math.pi/16; q.rect(cx+(r+3)*math.cos(a)-2.6,cy+(r+3)*math.sin(a)-1.8,5.2,3.6,ink,1,1.5)
        q.disc(cx,cy,4,ink)
    parl(s)
    s.water(310,'#5C6574','#222833','#FFD58A',70)
    s.mirror(310,.22); parl(s); s.unmirror()
    # Westminster Bridge with lamps
    s.rect(0,350,W,8,ink); s.rect(0,346,W,2,ink)
    a=-20
    while a<W:
        s.path(f'M{a} 358 L{a+60} 358 L{a+60} 382 Q{a+30} 362 {a} 382 Z',ink)
        s.rect(a+26,332,1.6,15,ink); s.disc(a+26.8,331,2.4,'#FFD58A'); s.glow(a+26.8,331,10,'#FFD58A',.35); a+=60
    # Red double-decker bus on the bridge
    bx,by=118,312
    s.path(f'M{bx} {by+34} L{bx} {by+6} Q{bx} {by} {bx+6} {by} L{bx+70} {by} Q{bx+76} {by} {bx+76} {by+6} L{bx+76} {by+34} Z','#C8312A')
    s.rect(bx+4,by+5,68,9,'#FFE2B8',.9); s.rect(bx+4,by+20,58,8,'#FFE2B8',.9)  # window bands
    for i in range(1,8): s.rect(bx+4+i*8.5,by+5,1.2,9,'#C8312A'); 
    for i in range(1,7): s.rect(bx+4+i*8.3,by+20,1.2,8,'#C8312A')
    s.rect(bx+64,by+19,8,15,'#7A1E19')  # door
    s.rect(bx,by+16.5,76,1.4,'#8F231E')
    for wx in (bx+14,bx+60): s.disc(wx,by+35,4.2,'#1E1E22'); s.disc(wx,by+35,1.6,'#8A8A8A')
    s.disc(bx+75,by+30,1.6,'#FFE9B0'); s.glow(bx+76,by+30,9,'#FFE9B0',.5)
    return s

# ---------- Paris: Eiffel Tower over the Seine at dusk ----------
def paris():
    s=S(); s.sky([(0,'#24264A'),(.45,'#5A4E7E'),(.8,'#C98B93'),(1,'#EBB89A')])
    s.stars(40,160); s.glow(200,330,160,'#FFC9A0',.35)
    ink='#1F1D33'
    # Haussmann rooftops left and right
    r=random.Random(7)
    def roofs(x0,x1):
        x=x0
        while x<x1:
            w=26+r.random()*14; h=60+r.random()*25; top=330-h
            s.rect(x,top,w,h,ink); s.path(f'M{x-2} {top} L{x+5} {top-12} L{x+w-5} {top-12} L{x+w+2} {top} Z',ink)
            for cx_ in (x+6,x+w-9): s.rect(cx_,top-18,3,7,ink)
            for k in range(3):
                for j in range(int(w//9)):
                    if r.random()<.55: s.rect(x+4+j*9,top+8+k*16,4,7,'#FFD58A',.7)
            x+=w+1
    roofs(-6,112); roofs(282,396)
    # Eiffel Tower: legs, arch, platforms, lattice, spire
    cx=197
    def tw(y): # half-width at height y (from 330 base up to 70)
        t=(330-y)/260
        return 62*(1-t)**2.2+1.2
    pts_l=[];pts_r=[]
    for i in range(0,61):
        y=330-i*260/60; w=tw(y); pts_l.append((cx-w,y)); pts_r.append((cx+w,y))
    d='M'+' L'.join(f'{x:.1f} {y:.1f}' for x,y in pts_l)+' L'+' L'.join(f'{x:.1f} {y:.1f}' for x,y in reversed(pts_r))+' Z'
    tid=nid('tw'); s.defs.append(f'<clipPath id="{tid}"><path d="{d}"/></clipPath>')
    s.path(d,ink,.0)
    # lattice drawn inside clip
    lat=[]
    for k in range(-60,60):
        x=cx+k*5
        lat.append(f'M{x} 330 L{x+60} 70 M{x} 330 L{x-60} 70')
    s.add(f'<g clip-path="url(#{tid})"><rect x="0" y="0" width="{W}" height="{H}" fill="{ink}" opacity=".55"/><path d="{" ".join(lat)}" stroke="{ink}" stroke-width="1.3" fill="none"/></g>')
    s.add(f'<path d="{d}" fill="none" stroke="{ink}" stroke-width="2"/>')
    # the big arch between the legs
    w0=tw(330); s.path(f'M{cx-w0+10} 330 Q{cx} 262 {cx+w0-10} 330 Z','#C98B93')
    s.add(f'<path d="M{cx-w0+10} 330 Q{cx} 262 {cx+w0-10} 330" fill="none" stroke="{ink}" stroke-width="3"/>')
    # platforms
    for y,ext in ((278,10),(208,6),(140,3)):
        w=tw(y)+ext; s.rect(cx-w,y-4,2*w,6,ink)
    s.rect(cx-1.2,52,2.4,22,ink)  # antenna
    # sparkle lights on the tower (twinkle)
    rr=random.Random(9)
    for i in range(40):
        y=70+rr.random()*255; w=tw(y)*.9; x=cx+(rr.random()*2-1)*w
        s.disc(x,y,.9,'#FFF2C4',.5+rr.random()*.5)
    s.glow(cx,60,14,'#FFE7A8',.6)
    # Seine with a bridge
    s.water(330,'#4A4568','#1C1B2E','#FFD58A',60)
    s.rect(0,350,W,6,ink)
    a=0
    while a<W:
        s.path(f'M{a} 356 L{a+78} 356 L{a+78} 378 Q{a+39} 358 {a} 378 Z',ink); s.disc(a+39,345,2,'#FFD58A'); s.glow(a+39,345,9,'#FFD58A',.35); a+=78
    return s

# ---------- New York: Manhattan skyline at night, Brooklyn Bridge in front ----------
def nyc():
    s=S(); s.sky([(0,'#141936'),(.55,'#2E3466'),(.85,'#6B5B8E'),(1,'#B77F8E')])
    s.stars(50,170)
    far='#2A2D52'; ink='#151731'
    r=random.Random(11)
    # far skyline
    x=-5
    while x<W:
        w=14+r.random()*20; h=60+r.random()*80; s.rect(x,300-h,w,h,far); s.windows(x,300-h,w,h,far,'#FFD98A',.3,int(x)+1,1.6,2.2,4,6); x+=w+1
    def bld(x,w,h,top=None):
        s.rect(x,300-h,w,h,ink); s.windows(x,300-h,w,h,ink,'#FFD98A',.5,int(x*3),1.8,2.6,4.5,6.5)
    # Empire State Building (stepped with spire)
    ex=150
    s.rect(ex,140,40,160,ink); s.rect(ex+6,118,28,24,ink); s.rect(ex+12,100,16,20,ink); s.rect(ex+16,86,8,16,ink); s.rect(ex+19,58,2,30,ink)
    s.windows(ex,140,40,160,ink,'#FFD98A',.55,21,1.8,2.6,4.5,6.5); s.glow(ex+20,100,18,'#FFC9D6',.5)
    # Chrysler Building (art-deco crown)
    cx_=232
    s.rect(cx_,170,28,130,ink); s.windows(cx_,170,28,130,ink,'#FFD98A',.5,33)
    for i in range(5):
        y=170-i*9; w=28-i*5; s.path(f'M{cx_+14-w/2} {y} Q{cx_+14} {y-16} {cx_+14+w/2} {y} Z',ink)
        s.path(f'M{cx_+14-w/2+3} {y-2} Q{cx_+14} {y-12} {cx_+14+w/2-3} {y-2}','none'); s.line(f'M{cx_+14-w/2+3} {y-2} Q{cx_+14} {y-13} {cx_+14+w/2-3} {y-2}','#E9D9A8',.8,.8)
    s.rect(cx_+13,112,2,20,ink)
    # One World Trade Center (tapered, far left)
    s.path('M40 300 L44 130 L70 130 L74 300 Z',ink); s.line('M44 130 L74 300 M70 130 L40 300','#3A3F70',.6)
    s.rect(56,96,2,36,ink); s.windows(44,140,28,160,ink,'#BFD9FF',.35,44,1.6,2.4,4,6)
    for x_,w_,h_ in ((80,26,120),(108,30,150),(196,28,110),(266,24,140),(292,30,100),(326,22,160),(350,40,120)): bld(x_,w_,h_)
    s.water(300,'#232850','#0C0E20','#FFD98A',80)
    # Brooklyn Bridge: gothic stone towers with twin pointed arches, cables
    tower='#3A3346'
    for tx in (60,290):
        s.rect(tx,230,46,150,tower); s.rect(tx-3,226,52,8,tower)
        for ax in (tx+7,tx+27):
            s.path(f'M{ax} 300 L{ax} 262 Q{ax+6} 246 {ax+12} 262 L{ax+12} 300 Z','#1A1F3E')
        s.rect(tx,300,46,6,tower)
    deck=330
    s.rect(-5,deck,W+10,7,tower)
    # main cables (sag between towers, down to the ends)
    def cable(y_top):
        s.line(f'M83 {y_top} Q196 {deck-6} 313 {y_top}', '#5A5370', 1.6)
        s.line(f'M83 {y_top} Q30 {deck-40} -10 {deck}', '#5A5370', 1.6)
        s.line(f'M313 {y_top} Q370 {deck-40} 400 {deck}', '#5A5370', 1.6)
    cable(232)
    # suspenders + diagonal stays
    for i in range(1,24):
        x=83+i*(230/24); t=(x-83)/230; y=232+(deck-6-232)*4*t*(1-t)*.98+ (1-4*t*(1-t))*0
        yc=(1-t)**2*232+2*(1-t)*t*(deck-6)+t*t*232
        s.line(f'M{x:.1f} {yc:.1f} L{x:.1f} {deck}','#5A5370',.5,.8)
    for i in range(1,9):
        s.line(f'M83 236 L{83+i*13} {deck}','#5A5370',.45,.7); s.line(f'M313 236 L{313-i*13} {deck}','#5A5370',.45,.7)
    for lx in range(10,W,30): s.disc(lx,deck-2,1.5,'#FFD58A'); s.glow(lx,deck-2,7,'#FFD58A',.3)
    return s

# ---------- Positano, Amalfi Coast ----------
def amalfi():
    s=S(); s.sky([(0,'#7FB2D6'),(.6,'#CFE3EE'),(1,'#F6E7D2')])
    s.glow(320,90,90,'#FFF6DE',.8); s.birds(4,60,60,90,'#5A6A7A')
    # distant headland
    s.path('M0 250 Q80 200 160 230 Q240 255 390 215 L390 300 L0 300 Z','#9DB3A6')
    # main cliff
    s.path('M120 330 Q150 200 230 150 Q300 110 390 120 L390 330 Z','#6E8B5E')
    s.path('M120 330 Q150 200 230 150 Q260 135 280 140 Q220 200 200 330 Z','#5F7B52',.6)
    r=random.Random(17)
    colours=['#F4C9A0','#E98B6D','#F6E2B8','#F2B48A','#FCEFD8','#E5A07A','#F0D27A']
    # cascading houses: rows hugging the slope, with arched windows, little balconies
    for row in range(9):
        y=165+row*19
        x0=230-row*10; x1=380
        x=x0+r.random()*8
        while x<x1:
            w=16+r.random()*10; h=15+r.random()*5
            if y+h>330: break
            c=colours[r.randrange(len(colours))]
            s.rect(x,y,w,h,c); s.rect(x,y,w,2,'#FFFFFF',.35)
            s.path(f'M{x+3} {y+h-3} L{x+3} {y+6} Q{x+5.5} {y+3} {x+8} {y+6} L{x+8} {y+h-3} Z','#5A4A44',.75)
            if r.random()<.5: s.rect(x+w-7,y+5,4,5,'#5A4A44',.7)
            if r.random()<.3: s.rect(x-1,y-2,w+2,2,'#B65A3E')  # terracotta roof edge
            x+=w+2
        # bougainvillea and lemon trees between rows
        for k in range(3):
            s.disc(x0+r.random()*(x1-x0),y+r.random()*6,3+r.random()*3,'#C8508A' if r.random()<.4 else '#4F7A3E',.85)
    # Santa Maria Assunta: majolica dome (green and yellow tiles) + bell tower, by the beach
    dx,dy=250,292
    s.rect(dx-22,dy,44,30,'#F6E7CF'); s.path(f'M{dx-20} {dy} Q{dx} {dy-34} {dx+20} {dy} Z','#3E8A5E')
    for i in range(-3,4): s.line(f'M{dx+i*5} {dy-1} Q{dx+i*3} {dy-22} {dx} {dy-30}','#E8C547',1.4,.9)
    s.disc(dx,dy-31,2.6,'#E8C547')
    s.rect(dx+26,dy-26,12,56,'#F2DCC0'); s.path(f'M{dx+24} {dy-26} L{dx+32} {dy-40} L{dx+40} {dy-26} Z','#3E8A5E'); s.rect(dx+30,dy-18,4,7,'#5A4A44')
    # beach with umbrellas
    s.path('M150 340 Q250 322 390 330 L390 346 L150 346 Z','#E9D3A8')
    for i in range(9):
        ux=180+i*22; c=['#E36A4A','#F2C14E','#3A8FB7'][i%3]
        s.path(f'M{ux-8} 331 Q{ux} 322 {ux+8} 331 Z',c); s.line(f'M{ux} 331 L{ux} 338','#6A5A4A',.8)
    s.water(342,'#2F8FB0','#11506E','#FFFFFF',70,5)
    # boats
    for bx_,by_ in ((90,380),(200,410),(300,372)):
        s.path(f'M{bx_-12} {by_} L{bx_+12} {by_} L{bx_+8} {by_+5} L{bx_-8} {by_+5} Z','#F8F4EC'); s.rect(bx_-4,by_-4,8,4,'#F8F4EC')
        s.line(f'M{bx_-30} {by_+7} L{bx_-14} {by_+5}','#FFFFFF',.8,.6)
    return s

# ---------- Dubai: Burj Khalifa and Burj Al Arab at dusk ----------
def dubai():
    s=S(); s.sky([(0,'#3B2F5C'),(.5,'#9A5F86'),(.8,'#E4A07A'),(1,'#F2C58E')])
    s.glow(300,300,140,'#FFD9A0',.6); s.stars(20,120)
    ink='#2A2238'
    r=random.Random(21)
    x=-5
    while x<W:
        w=14+r.random()*18; h=40+r.random()*70; s.rect(x,330-h,w,h,'#3D3150'); s.windows(x,330-h,w,h,'#3D3150','#FFD39A',.3,int(x)+5,1.6,2.2,4,6); x+=w+1
    # Burj Khalifa: Y-shaped stepped setbacks to a long spire
    bx=150
    tiers=[(330,34),(280,30),(240,26),(205,22),(175,18),(150,14),(128,10),(110,7),(96,5)]
    for (y,w),(y2,_) in zip(tiers,tiers[1:]+[(84,0)]):
        s.rect(bx-w/2,y2,w,y-y2,ink)
        s.rect(bx-w/2-3,y-10,3,10,ink); s.rect(bx+w/2,y-14,3,14,ink)  # setback fins
    s.path(f'M{bx-3} 84 L{bx} 22 L{bx+3} 84 Z',ink)
    s.windows(bx-15,100,30,230,ink,'#FFE3B0',.35,31,1.4,2,3.5,5)
    s.disc(bx,22,1.6,'#FF6B6B'); s.glow(bx,22,8,'#FF6B6B',.6)
    # Burj Al Arab sail on its island
    ax=318
    s.path(f'M{ax} 330 L{ax} 200 Q{ax+52} 230 {ax+42} 330 Z','#EDE5EF'); s.line(f'M{ax} 200 Q{ax+52} 230 {ax+42} 330','#B9A9C8',1.2)
    for i in range(6): s.line(f'M{ax+4} {215+i*20} Q{ax+30} {222+i*20} {ax+44} {230+i*20}','#C7B8D4',.6)
    s.rect(ax-4,190,4,140,ink); s.rect(ax-8,186,12,4,ink); s.path(f'M{ax-2} 186 L{ax} 170 L{ax+2} 186 Z',ink)
    s.path(f'M{ax+18} 250 L{ax+42} 250 L{ax+40} 256 L{ax+20} 256 Z','#6A5A7A')
    s.water(330,'#7C5C7A','#2C2038','#FFD39A',60,8)
    # dhow
    s.path('M40 370 L96 370 L88 378 L48 378 Z','#4A3328'); s.path('M66 370 L66 338 L90 366 Z','#F3E3C8')
    return s

for name,f in (('london',london),('paris',paris),('nyc',nyc),('amalfi',amalfi),('dubai',dubai)):
    open(f'{name}.svg','w').write(f().svg())
print('ok')
