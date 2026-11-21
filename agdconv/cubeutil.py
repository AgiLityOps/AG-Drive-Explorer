import numpy as np
# GL cubemap convention. faces order +X,-X,+Y,-Y,+Z,-Z
def face_uv_to_dir(f,u,v):
    sc=2*u-1; tc=2*v-1; o=np.ones_like(sc)
    if f==0: d=(o,-tc,-sc)
    elif f==1: d=(-o,-tc,sc)
    elif f==2: d=(sc,o,tc)
    elif f==3: d=(sc,-o,-tc)
    elif f==4: d=(sc,-tc,o)
    else: d=(-sc,-tc,-o)
    d=np.stack(d,-1); return d/np.linalg.norm(d,axis=-1,keepdims=True)
def dir_to_face_uv(d):
    x,y,z=d[...,0],d[...,1],d[...,2]; ax,ay,az=abs(x),abs(y),abs(z)
    f=np.where((ax>=ay)&(ax>=az),np.where(x>0,0,1),np.where(ay>=az,np.where(y>0,2,3),np.where(z>0,4,5)))
    sc=np.select([f==0,f==1,f==2,f==3,f==4,f==5],[-z,z,x,x,x,-x]); tc=np.select([f==0,f==1,f==2,f==3,f==4,f==5],[-y,-y,z,-z,-y,-y])
    ma=np.select([f<2,f<4,f>=4],[ax,ay,az])
    return f,(sc/ma+1)/2,(tc/ma+1)/2
def sample(faces,d):
    """faces: list of 6 HxWxC float arrays; bilinear sampling"""
    f,u,v=dir_to_face_uv(d); H,W=faces[0].shape[:2]; out=np.zeros(d.shape[:-1]+(faces[0].shape[2],),np.float32)
    for i in range(6):
        m=f==i
        if not m.any(): continue
        x=np.clip(u[m]*W-0.5,0,W-1); y=np.clip(v[m]*H-0.5,0,H-1)
        x0=np.floor(x).astype(int); y0=np.floor(y).astype(int); x1=np.minimum(x0+1,W-1); y1=np.minimum(y0+1,H-1)
        fx=(x-x0)[:,None]; fy=(y-y0)[:,None]; F=faces[i]
        out[m]=(F[y0,x0]*(1-fx)+F[y0,x1]*fx)*(1-fy)+(F[y1,x0]*(1-fx)+F[y1,x1]*fx)*fy
    return out
