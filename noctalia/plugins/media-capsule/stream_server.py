import array,fcntl,mmap,os,select,socket,struct,time
SCALE=2

def serve(factory,state,name,max_width,height,headless=False):
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=open(state/(name+'.lock'),'w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    path=state/(name+'.sock');path.unlink(missing_ok=True)
    server=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);server.bind(str(path));os.chmod(path,0o600);server.listen(8)
    clients={};bar=factory();last=time.monotonic();next_frame=last;last_paint=0;frame=None;generation=0
    def close(conn):
        item=clients.pop(conn)
        conn.close();item['pixels'].close();os.close(item['fd'])
    while True:
        ready,_,_=select.select([server]+list(clients),[],[],1/120 if clients else .5)
        for conn in ready:
            if conn is server:
                peer,_=server.accept();fd=os.memfd_create('media-capsule',os.MFD_ALLOW_SEALING)
                os.ftruncate(fd,max_width*SCALE*height*SCALE*4);fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_SHRINK)
                clients[peer]=dict(fd=fd,pixels=mmap.mmap(fd,max_width*SCALE*height*SCALE*4),pending=False,width=0,hello=False,last_generation=-1)
                continue
            try:
                msg=conn.recv(128)
                if not msg:close(conn);continue
                kind,value=struct.unpack('<II',msg[:8])
                if kind==1:
                    if value!=1:close(conn);continue
                    clients[conn]['hello']=True
                elif kind==2:clients[conn]['pending']=True
            except (OSError,ValueError,struct.error):close(conn)
        current=time.monotonic()
        moving=bar.step(current-last,time.time());last=current
        if (clients or headless) and current>=next_frame and ((clients and moving) or current-last_paint>.5 or frame is None):
            frame=bar.paint();generation+=1;last_paint=current;next_frame=current+1/60
        for conn,item in list(clients.items()):
            if not item['hello'] or frame is None:continue
            width,pixels=frame
            try:
                if item['width']==0 or (item['pending'] and item['width']!=width):
                    conn.sendmsg([struct.pack('<IIII',1,0,width*SCALE,height*SCALE)],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[item['fd']]))]);item['width']=width
                if item['pending'] and item['last_generation'] != generation:
                    item['last_generation'] = generation
                    item['pixels'].seek(0);item['pixels'].write(pixels)
                    conn.send(struct.pack('<II',2,0));item['pending']=False
            except OSError:close(conn)
