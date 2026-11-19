"""Original rehearsal service/router with isolated state; no hardware/providers."""
import os,sys,socket,json,asyncio
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
import uvicorn
from rareiq.services.rehearsal_service import RehearsalService,RehearsalError
from rareiq.web.rehearsal import create_rehearsal_router
from rareiq.web.desktop_lifecycle import NativeEncodingState
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False)
encoding=NativeEncodingState()
room=RehearsalService(root/'rehearsal.json',idle_provider=lambda:{'ready':not encoding.snapshot()['active']},exit_idle_provider=lambda:{'ready':not encoding.snapshot()['active']})
app=FastAPI();app.include_router(create_rehearsal_router(room,lambda _:True))
@app.get('/__qa__/identity')
def identity():return {'pid':os.getpid(),'server_session_id':'isolated-rehearsal','isolated':True,'hardware':False,'providers':False}
@app.post('/api/desktop/encoding-status')
async def claim(request:Request):
 value=await request.json()
 if value.get('pid')!=os.getpid() or value.get('server_session_id')!='isolated-rehearsal':return {'ok':False,'reason':'identity_mismatch'}
 if value.get('active') is True:
  if value.get('mode')!='rehearsal':return {'ok':False,'reason':'rehearsal_generation_conflict'}
  with room.local_encoding_lease(value.get('rehearsal_generation')):
   return encoding.update(active=True,owner_pid=value.get('owner_pid'),mode='rehearsal',rehearsal_generation=value.get('rehearsal_generation'))
 return encoding.update(active=value.get('active'),owner_pid=value.get('owner_pid'),mode=value.get('mode'),rehearsal_generation=value.get('rehearsal_generation'))
@app.exception_handler(RehearsalError)
async def error(_,exc):return JSONResponse({'ok':False,'reason':exc.reason},status_code=exc.status)
listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
print(json.dumps({'port':listener.getsockname()[1]}),flush=True)
asyncio.run(uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False)).serve(sockets=[listener]))
