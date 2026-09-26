"""Low-cost outlined-light-text features; no video/OpenCV shared libraries."""
import numpy as np

def python_text_mask(image):
    g=np.asarray(image.convert('L'));dark=g<90
    # Separable boolean dilation; avoids a costly rank filter or OpenCV in decoder.
    h,w=g.shape;p=np.pad(dark,((0,0),(3,3)));near=np.zeros_like(dark)
    for offset in range(7):near|=p[:,offset:offset+w]
    p=np.pad(near,((3,3),(0,0)));near=np.zeros_like(dark)
    for offset in range(7):near|=p[offset:offset+h,:]
    binary=(g>210)&near
    # Connected components using horizontal runs (8-connected). Keep glyph-size
    # components, removing large bright scenery. This is specific to light text.
    runs=[];parents=[];previous=[]
    def root(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for y,line in enumerate(binary):
        edge=np.diff(np.pad(line.astype(np.int8),(1,1)));starts=np.flatnonzero(edge==1);ends=np.flatnonzero(edge==-1)
        current=[];k=0
        for x1,x2 in zip(starts.tolist(),ends.tolist()):
            i=len(runs);parents.append(i);runs.append((y,x1,x2));current.append(i)
            while k<len(previous) and runs[previous[k]][2]<x1:k+=1
            j=k
            while j<len(previous) and runs[previous[j]][1]<=x2:
                a=root(i);b=root(previous[j]);parents[a]=b;j+=1
        previous=current
    stats={}
    for i,(y,x1,x2) in enumerate(runs):
        r=root(i)
        if r not in stats:stats[r]=[x1,y,x2,y+1,x2-x1]
        else:
            s=stats[r];s[0]=min(s[0],x1);s[2]=max(s[2],x2);s[3]=y+1;s[4]+=x2-x1
    limit=max(1,w/522);valid={r for r,(x1,y1,x2,y2,area) in stats.items() if 2<=area<650*limit**2 and y2-y1<35*limit and x2-x1<50*limit}
    mask=np.zeros_like(binary)
    for i,(y,x1,x2) in enumerate(runs):
        if root(i) in valid:mask[y,x1:x2]=True
    return mask

def changed(a,b):
    if a.shape!=b.shape:return True
    diff=a^b;n=np.count_nonzero(diff)
    if n>max(4,np.count_nonzero(a|b)*.08):return True
    h,w=diff.shape
    # Detect a short new word even alongside a long unchanged line.
    tile=np.pad(diff,((0,(-h)%24),(0,(-w)%48)))
    counts=tile.reshape(tile.shape[0]//24,24,tile.shape[1]//48,48).sum(axis=(1,3))
    return bool(np.any(counts>18))

try:
    import glyph_features
except ImportError:
    import sys
    if getattr(sys,"frozen",False):raise RuntimeError("安装包缺少原生帧比较组件，请重新安装完整版本。")
    glyph_features=None

def text_mask(image):
    if glyph_features is None:return python_text_mask(image)
    gray=image.convert('L');data=glyph_features.mask(gray.tobytes(),gray.width,gray.height)
    return np.frombuffer(data,dtype=np.bool_).reshape(gray.height,gray.width)
