import pymupdf,sys,re,json,pickle
sys.path.insert(0,'.')
from analyze import analyze_page,is_opener,frame_of
TOPY=84.0; BOTY=802.0; PAR_GAP=8.0; HEAD_GAP=12.0; CONT_GAP=3.5
OPEN_TITLES={}
def _wrap(t,w=455,s=19):
    import pymupdf as m
    out=[];cur=''
    for wd in t.split():
        c=(cur+' '+wd).strip()
        if m.get_text_length(c,fontname='hebo',fontsize=s)>w and cur: out.append(cur);cur=wd
        else: cur=c
    if cur: out.append(cur)
    return out
def analyze_all(doc,first,last):
    res={}
    for pn in range(first,last):
        res[pn]=analyze_page(doc,pn,opener=is_opener(doc[pn]))
    return res
def make_bands(doc,res,first,last):
    bands=[]
    for pn in range(first,last):
        a=res[pn]
        if a['opener']:
            import pymupdf as _m
            tt=OPEN_TITLES.get(pn,('','','UNIT'))
            tl_=_wrap(tt[1]); hdr=30+24*len(tl_)+12; picr=None; tot=hdr
            bands.append(dict(kind='banner',pn=pn,label=(tt[2] if len(tt)>2 else 'UNIT'),num=tt[0],tlines=tl_,y0=0.0,y1=tot,hdr=hdr,pic=picr,opener_end=a['opener_end'],runs=[dict(y0=0.0,y1=a['opener_end'],text='UNIT '+' '.join(r for r in [])),],atomic=True,gap_nat=None,first_on_page=True,text='',fx0=a['fx0'],fx1=a['fx1']))
        runs=[];dropped=None
        for r in a['runs']:
            if 'file:///' in r['text']: dropped=r; continue
            if r['img'] and not r['text'] and r['ink']<300 and not r['rule']:
                dropped=r; continue
            if dropped is not None and r['y0']-dropped['y1']<80 and re.match(r'^\(?\s*(source|sources)\b',r['text'],re.I):
                dropped=r; continue
            dropped=None
            if r['text'] or r['img'] or r['rule'] or r['med']<250 or r['ink']>3000: runs.append(r)
        cur=None;prev=None
        for r in runs:
            g=None if prev is None else r['y0']-prev['y1']
            if cur is None or g is None or g>=7.0:
                cur=dict(kind='text',pn=pn,runs=[],gap_nat=g,first_on_page=(prev is None),fx0=a['fx0'],fx1=a['fx1'])
                bands.append(cur)
                r['gap']=0
            else: r['gap']=g
            cur['runs'].append(r); prev=r
        # finalize props
    for b in bands:
        if b['kind']=='banner': continue
        rs=b['runs']
        b['y0']=rs[0]['y0']; b['y1']=rs[-1]['y1']
        b['text']=' '.join(r['text'] for r in rs).strip()
        b['atomic']=any(r['img'] or r['rule'] for r in rs)
        b['h']=b['y1']-b['y0']
    for b in bands:
        if b['kind']=='banner': b['h']=b['y1']-b['y0']
    return bands
def heading_like(b):
    if b['kind']!='text' or b['atomic']: return False
    return len(b['runs'])<=2 and b['h']<34 and 0<len(b['text'])<110 and not re.search(r'[\.\?!:;,]$',b['text'].strip()) or (b['kind']=='text' and not b['atomic'] and len(b['runs'])==1 and re.match(r'^\d+\.\d+(\.\d+)*\.?\s',b['text']))
def continues(prev,b):
    if prev is None or prev['pn']==b['pn'] or b['kind']!='text': return False
    if prev['kind']!='text' or prev['atomic'] or b['atomic']: return False
    if heading_like(b) or heading_like(prev): return False
    pt=prev['text'].strip(); bt=b['text'].strip()
    return bool(pt) and bool(bt) and not re.search(r'[\.\?!:;\)”"]$',pt) and bt[0].islower()
def pack(bands):
    pages=[[]]   # each: list of placements dict(band,ri,dy,src_y0,src_y1,pn)
    state=dict(y=TOPY)
    def newpage():
        pages.append([]); state['y']=TOPY
    def place(b,ri,gap):
        r=b['runs'][ri] if b['kind']!='banner' else dict(y0=b['y0'],y1=b['y1'])
        y=state['y']+(0 if not pages[-1] else gap)
        pages[-1].append(dict(band=b,ri=ri,dy=y,y0=r['y0'],y1=r['y1'],pn=b['pn']))
        state['y']=y+(r['y1']-r['y0'])
    prev=None
    for bi,b in enumerate(bands):
        nxt=bands[bi+1] if bi+1<len(bands) else None
        if b['kind']=='banner':
            if pages[-1]: newpage()
            state['y']=TOPY
            place(b,0,0); state['y']+=6.0; prev=b; continue
        # gap before
        if b['first_on_page'] and continues(prev,b): gb=CONT_GAP
        elif heading_like(b): gb=min(b['gap_nat'] if b['gap_nat'] else HEAD_GAP,HEAD_GAP) if b['gap_nat'] else HEAD_GAP
        else: gb=min(b['gap_nat'],PAR_GAP) if b['gap_nat'] else PAR_GAP
        if not pages[-1]: gb=0
        # keep-with-next
        need=gb+b['h']
        if (heading_like(b) or (b['atomic'] and nxt and nxt['kind']=='text' and not nxt['atomic'] and len(nxt['runs'])<=2 and nxt['text'][:6].lower() in ('figure','fig.','fig ','source'))) and nxt and nxt['kind']=='text':
            nr=nxt['runs']
            take=nr[:2] if not nxt['atomic'] else nr
            need+=PAR_GAP+(take[-1]['y1']-take[0]['y0'])
        if b['atomic'] or b['kind']=='banner':
            if pages[-1] and state['y']+need>BOTY and b['h']<=BOTY-TOPY:
                newpage(); gb=0
            # place all runs preserving natural spacing
            for ri,r in enumerate(b['runs']):
                place(b,ri,gb if ri==0 else r['gap'])
            prev=b; continue
        if pages[-1] and state['y']+need>BOTY and (heading_like(b)):
            newpage(); gb=0
        n=len(b['runs'])
        ri=0
        while ri<n:
            r=b['runs'][ri]; gap=gb if ri==0 else r['gap']
            h=r['y1']-r['y0']
            if pages[-1] and state['y']+gap+h>BOTY:
                if ri==0:
                    newpage(); gap=0
                else:
                    placed=0
                    for pl in reversed(pages[-1]):
                        if pl['band'] is b: placed+=1
                        else: break
                    remaining=n-ri
                    pop=0
                    if placed==1 and n>=3: pop=1
                    elif remaining==1 and placed>=3: pop=1
                    elif remaining==1 and placed==2 and False: pop=1
                    popped=[]
                    for _ in range(pop):
                        popped.append(pages[-1].pop())
                    if popped: ri-=pop
                    newpage(); gap=0
                    if popped:
                        # restart from popped index
                        r=b['runs'][ri]; h=r['y1']-r['y0']
                    if not pages[-2] and not popped and False: pass
            if not pages[-1]: gap=0
            place(b,ri,gap)
            ri+=1
        prev=b
    if not pages[-1]: pages.pop()
    return pages
def chunks_of(page):
    out=[]
    for pl in page:
        if out:
            c=out[-1]
            if c['pn']==pl['pn'] and abs((pl['dy']-pl['y0'])-(c['dy']-c['y0']))<0.4 and pl['y0']>=c['y1']-0.01 and pl['y0']-c['y1']<7.0 and c['kind']==pl['band']['kind']:
                c['y1']=pl['y1']; c['texts'].append(pl['band']['runs'][pl['ri']]['text'] if pl['band']['kind']!='banner' else ''); continue
        out.append(dict(band=pl['band'],pn=pl['pn'],y0=pl['y0'],y1=pl['y1'],dy=pl['dy'],kind=pl['band']['kind'],texts=[pl['band']['runs'][pl['ri']]['text'] if pl['band']['kind']!='banner' else ''],fx0=pl['band']['fx0'],fx1=pl['band']['fx1']))
    return out
