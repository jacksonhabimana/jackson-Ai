import re,pymupdf
WS=b' \t\r\n\x0c\x00'
DELIM=b'()<>[]{}/%'
def tokenize(s):
    i=0;n=len(s);out=[]  # (type,text,start,end)
    while i<n:
        c=s[i:i+1]
        if c in WS: i+=1; continue
        st=i
        if c==b'%':
            while i<n and s[i:i+1] not in b'\r\n': i+=1
            continue
        if c==b'(':
            depth=1;i+=1
            while i<n and depth:
                ch=s[i:i+1]
                if ch==b'\\': i+=2; continue
                if ch==b'(': depth+=1
                elif ch==b')': depth-=1
                i+=1
            out.append(('str',s[st:i],st,i)); continue
        if c==b'<':
            if s[i+1:i+2]==b'<': out.append(('op',b'<<',st,i+2)); i+=2; continue
            j=s.index(b'>',i); i=j+1; out.append(('hex',s[st:i],st,i)); continue
        if c==b'>':
            if s[i+1:i+2]==b'>': out.append(('op',b'>>',st,i+2)); i+=2; continue
            i+=1; continue
        if c in b'[]': out.append(('op',c,st,i+1)); i+=1; continue
        if c==b'/':
            i+=1
            while i<n and s[i:i+1] not in WS and s[i:i+1] not in DELIM: i+=1
            out.append(('name',s[st:i],st,i)); continue
        while i<n and s[i:i+1] not in WS and s[i:i+1] not in DELIM: i+=1
        w=s[st:i]
        try: float(w); out.append(('num',w,st,i))
        except ValueError: out.append(('op',w,st,i))
    return out
def strip_text(page, rects):
    """remove text-show operators whose origin falls in any rect (page coords). returns count removed"""
    doc=page.parent
    page.clean_contents()
    xr=page.get_contents()
    assert len(xr)==1, xr
    xref=xr[0]
    s=doc.xref_stream(xref)
    toks=tokenize(s)
    T=page.transformation_matrix
    ctm=pymupdf.Matrix(1,0,0,1,0,0); stack=[]
    tm=pymupdf.Matrix(1,0,0,1,0,0); tlm=pymupdf.Matrix(1,0,0,1,0,0); tl=0.0
    operands=[]; arr_start=None
    cuts=[]; last=None; unpositioned=0; shows=0
    positioned=True
    def origin():
        pt=pymupdf.Point(tm.e,tm.f)*ctm*T
        return pt
    def inside(pt):
        return any(r.x0-2<=pt.x<=r.x1+2 and r.y0<=pt.y<=r.y1 for r in rects)
    k=0
    # group tokens into operand lists until operator
    ops=[]  # (operator_token, operands(list of tokens), first_token_start)
    cur=[]
    depth=0
    for t in toks:
        typ,txt,a,b=t
        if typ=='op' and txt==b'[': depth+=1; cur.append(t); continue
        if typ=='op' and txt==b']': depth-=1; cur.append(t); continue
        if depth>0: cur.append(t); continue
        if typ=='op' and txt not in (b'<<',b'>>'):
            ops.append((t,cur)); cur=[]
        else: cur.append(t)
    def nums(opnds): return [float(x[1]) for x in opnds if x[0]=='num']
    for opt,opnds in ops:
        op=opt[1]
        v=nums(opnds)
        if op==b'q': stack.append((ctm,tl))
        elif op==b'Q':
            if stack: ctm,tl=stack.pop()
        elif op==b'cm' and len(v)==6: ctm=pymupdf.Matrix(*v)*ctm
        elif op==b'BT': tm=pymupdf.Matrix(1,0,0,1,0,0); tlm=pymupdf.Matrix(1,0,0,1,0,0); positioned=True
        elif op==b'Tm' and len(v)==6: tm=pymupdf.Matrix(*v); tlm=pymupdf.Matrix(*v); positioned=True
        elif op==b'Td' and len(v)==2: tlm=pymupdf.Matrix(1,0,0,1,v[0],v[1])*tlm; tm=tlm; positioned=True
        elif op==b'TD' and len(v)==2: tl=-v[1]; tlm=pymupdf.Matrix(1,0,0,1,v[0],v[1])*tlm; tm=tlm; positioned=True
        elif op==b'TL' and v: tl=v[0]
        elif op==b'T*': tlm=pymupdf.Matrix(1,0,0,1,0,-tl)*tlm; tm=tlm; positioned=True
        elif op in (b'Tj',b'TJ',b"'",b'"'):
            if op in (b"'",b'"'):
                tlm=pymupdf.Matrix(1,0,0,1,0,-tl)*tlm; tm=tlm; positioned=True
            shows+=1
            if not positioned: unpositioned+=1
            pt=origin()
            if inside(pt):
                start=opnds[0][2] if opnds else opt[2]
                cuts.append((start,opt[3]))
            positioned=False
    out=bytearray(); pos=0
    for a,b in cuts:
        out+=s[pos:a]; pos=b
    out+=s[pos:]
    doc.update_stream(xref,bytes(out))
    return len(cuts),shows,unpositioned
