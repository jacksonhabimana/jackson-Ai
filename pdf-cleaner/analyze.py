import pymupdf,numpy as np,re
DPI=144; S=DPI/72
TOP=77.0; BOT=805.0
FRAME=None            # pymupdf.Rect, set by clean.py
OPENER_RE=r'^(UNIT|CHAPTER|Unit|Chapter)$'
def frame_of(p):
    for x in p.get_drawings():
        r=x['rect']
        if x['type'] in('f','fs') and x.get('fill') and tuple(round(c,2) for c in x['fill'])==(1.0,1.0,1.0) and 470<r.width<510 and r.height>650:
            return r, x.get('color')
    return None,None
def is_opener(p):
    for blk in p.get_text('dict')['blocks']:
        for l in blk.get('lines',[]):
            if re.match(OPENER_RE,''.join(sp['text'] for sp in l['spans']).strip()) and l['spans'][0]['origin'][1]<140: return True
    return False
def analyze_page(doc,pn,opener=False):
    p=doc[pn]
    fr,col=(FRAME,None) if FRAME is not None else frame_of(p)
    if fr is None: fr=pymupdf.Rect(79,75,568,806) if pn%2==0 else pymupdf.Rect(69,75,558,806)
    fx0,fx1=fr.x0,fr.x1
    pix=p.get_pixmap(dpi=DPI,colorspace=pymupdf.csGRAY,alpha=False)
    a=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width)
    cx0=int((fx0+6)*S); cx1=int((fx1-6)*S)
    r0=int(TOP*S); r1=int(BOT*S)
    sub=a[:, cx0:cx1]
    occ=((sub<238).sum(axis=1)>=2)|(np.median(sub,axis=1)<250)
    frac=(sub<200).mean(axis=1)
    # images force-occupied
    img_rects=[]
    PW=p.rect.width
    for info in p.get_image_info():
        b=pymupdf.Rect(info['bbox'])
        if b.x0<-2 or b.x1>PW+2 or b.y0<30 and not opener or b.y0<-2 or b.height>700 or b.x0>fx1 or b.x1<fx0 or (b.width>350 and b.height>350): continue
        if b.y1<TOP or b.y0>BOT: continue
        img_rects.append(b)
    opener_end=None
    if opener:
        # banner bottom: lowest non-decor image / title text bottom within y<430
        ys=[b.y1 for b in img_rects if b.y0<430]
        for blk in p.get_text('dict')['blocks']:
            for l in blk.get('lines',[]):
                sp=l['spans'][0]
                if sp['origin'][1]<200 and sp['text'].strip() and sp['origin'][1]>40: ys.append(sp['origin'][1]+6)
        opener_end=(max(ys) if ys else 200)+14
    pic=None; ttl=100.0
    if opener:
        pr=[b for b in img_rects if b.y0>100 and b.y0<opener_end and b.x1<fx1+30]
        if pr:
            pic=pymupdf.Rect(pr[0])
            for b in pr[1:]: pic|=b
        for blk in p.get_text('dict')['blocks']:
            for l in blk.get('lines',[]):
                sp=l['spans'][0]
                if 40<sp['origin'][1]<200 and sp['text'].strip(): ttl=max(ttl,l['bbox'][3] if l['bbox'][3]<200 else sp['origin'][1]+4)
    start_row=r0 if not opener else int(opener_end*S)
    for b in img_rects:
        if opener and b.y0<opener_end: continue
        occ[max(int(b.y0*S),0):int(b.y1*S)+1]=True
    rows=np.where(occ[start_row:r1])[0]+start_row
    runs=[]
    if len(rows):
        s=rows[0];prev=rows[0]
        for r in rows[1:]:
            if (r-prev)/S>1.5:
                runs.append((s/S,(prev+1)/S)); s=r
            prev=r
        runs.append((s/S,(prev+1)/S))
    # attributes
    out=[]
    for y0,y1 in runs:
        ra=int(y0*S);rb=int(y1*S)
        rule=(frac[ra:rb]>0.85).any()
        img=any(b.y1>y0 and b.y0<y1 for b in img_rects)
        ink=int((sub[ra:rb]<238).sum()); med=float(np.median(sub[ra:rb]))
        out.append(dict(y0=y0,y1=y1,rule=bool(rule),img=bool(img),ink=ink,med=med))
    # text per run
    spans=[]
    for blk in p.get_text('dict')['blocks']:
        for l in blk.get('lines',[]):
            for sp in l['spans']:
                if sp['text'].strip(): spans.append((sp['origin'][1],sp['origin'][0],sp['text'],sp['size'],sp['flags']))
    for r in out:
        ts=sorted([s for s in spans if r['y0']-1.5<=s[0]<=r['y1']+1.5],key=lambda s:(round(s[0]),s[1]))
        r['text']=' '.join(s[2].strip() for s in ts)
        r['size']=max([s[3] for s in ts],default=0)
        r['bold']=any(s[4]&16 for s in ts)
    return dict(pic=pic,ttl=ttl,fx0=fx0,fx1=fx1,col=col,runs=out,opener_end=opener_end,opener=opener)
