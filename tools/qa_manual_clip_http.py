# Nonpublic synthetic HTTP validation. Does not enter app lifespan or open media.
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json, time
from types import SimpleNamespace
import cv2, numpy as np
from starlette.testclient import TestClient
from rareiq.web import server
from rareiq.services.instant_replay_service import InstantReplayService
root=Path('.tmp/refinish/functional-clip-http').resolve()/str(time.time_ns());root.mkdir(parents=True,exist_ok=False)
replay=InstantReplayService(root/'clips',lambda _slot:None,lambda:1)
now=time.time()
for index in range(40):
 frame=np.full((360,640,3),(45,24,12),dtype=np.uint8)
 cv2.putText(frame,'NONPUBLIC SYNTHETIC TEST',(35,145),cv2.FONT_HERSHEY_SIMPLEX,.85,(240,240,240),2)
 cv2.putText(frame,f'Frame {index+1:02d} / 40 - no camera or audio',(40,205),cv2.FONT_HERSHEY_SIMPLEX,.65,(30,190,240),2)
 replay._frames.append((now-(39-index)/5,1,cv2.imencode('.jpg',frame)[1].tobytes()))
server.instant_replay=replay
client=TestClient(server.app,base_url='http://127.0.0.1',client=('127.0.0.1',50123))
request={'name':'Nonpublic synthetic pipeline test','seconds':15,'ending_at':now,'request_id':'http-test-'+str(time.time_ns()),'expires_at':now+90}
started=time.perf_counter();first=client.post('/api/production/replay/mark',json=request);payload=first.json();assert first.status_code==200,payload
second=client.post('/api/production/replay/mark',json=request);assert second.status_code==200
assert second.json()['highlight']['id']==payload['highlight']['id']
clip_id=payload['highlight']['id'];download=client.get(f'/api/production/replay/{clip_id}/download');assert download.status_code==200 and download.headers['content-type']=='video/mp4'
video_path=root/'verified-synthetic-clip.mp4';video_path.write_bytes(download.content)
capture=cv2.VideoCapture(str(video_path));count=0
while capture.read()[0]:count+=1
fps=capture.get(cv2.CAP_PROP_FPS);capture.release();assert count==40 and fps==5
invalid=client.post('/api/production/replay/mark',json={**request,'seconds':121});assert invalid.status_code==422
conflict=client.post('/api/production/replay/mark',json={**request,'name':'changed'});assert conflict.status_code==409
assert len(replay.snapshot()['highlights'])==1
report={'source':'synthetic frames; no media capture','http_save':first.status_code,'http_download':download.status_code,'duplicate_saved_once':True,'invalid_length_rejected':True,'conflicting_retry_rejected':True,'duration_seconds':count/fps,'audio_tracks':payload['highlight']['audio_tracks'],'shorter_than_requested':payload['shorter_than_requested'],'decoded_frames':count,'elapsed_seconds':round(time.perf_counter()-started,3),'video':str(video_path)}
(root/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');server.production_actions.close();client.close();print(json.dumps(report))
