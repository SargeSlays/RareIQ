/* A guest's room view borrows camera tracks. Conversation audio has one separate owner. */
(function(host){
  'use strict';
  function roomPeople(room,self){
    const people=new Map();
    for(const person of room?.participants||[])if(person&&typeof person.id==='string'&&['waiting','admitted'].includes(person.state)&&!person.expired)people.set(person.id,person);
    if(self&&['waiting','admitted'].includes(self.state))people.set(self.id,self);
    return Array.from(people.values());
  }
  function mayWatch(self,person){return self?.state==='admitted'&&self.connected!==false&&person?.state==='admitted'&&person.connected===true;}
  function mount(container,{onRetry}={}){
    if(!container)return null;
    const doc=container.ownerDocument||host.document,tiles=new Map();
    container.className='guest-room-gallery';container.hidden=true;
    container.innerHTML='<header><div><span class="guest-eyebrow">YOUR CONVERSATION</span><h2>In the room</h2></div><span data-room-total></span></header><p data-room-guidance role="status" aria-live="polite"></p><button type="button" data-room-retry hidden>Retry room pictures</button><div class="guest-room-people" aria-label="Room participants"></div><div class="guest-room-waiting" hidden><strong>Waiting room</strong><p data-room-waiting></p></div>';
    const one=selector=>container.querySelector(selector);
    one('[data-room-retry]').addEventListener('click',()=>onRetry?.());
    function detach(tile){tile.video.pause();tile.video.srcObject=null;tile.track=null;}
    function remove(id,tile){detach(tile);tile.node.remove();tiles.delete(id);}
    function clear(message=''){
      for(const [id,tile] of tiles)remove(id,tile);
      one('[data-room-total]').textContent='';one('[data-room-guidance]').textContent=message;
      one('[data-room-retry]').hidden=true;
      one('[data-room-waiting]').textContent='';one('.guest-room-waiting').hidden=true;container.hidden=!message;
    }
    function update({room,self,localCamera=null,tracks=()=>({}),connected=true,working=false}={}){
      if(!self||!['waiting','admitted'].includes(self.state)){clear();return;}
      container.hidden=false;const people=roomPeople(room,self),admitted=people.filter(person=>person.state==='admitted'),waiting=people.filter(person=>person.state==='waiting');
      one('[data-room-retry]').hidden=connected||typeof onRetry!=='function';
      one('[data-room-retry]').disabled=working;one('[data-room-retry]').textContent=working?'Connecting pictures…':'Retry room pictures';one('[data-room-retry]').setAttribute('aria-busy',String(working));
      one('[data-room-total]').textContent=`${admitted.length} in room · ${waiting.length} waiting`;
      one('[data-room-guidance]').textContent=!connected?'Room pictures are reconnecting. Your camera controls and chat remain available.':self.state==='waiting'?'You are in the waiting room. You can use chat; room pictures and conversation open when the producer admits you.':'Talk with everyone backstage. These pictures stay off Program until the producer selects a source. Use headphones.';
      const visible=self.state==='admitted'?admitted:[self],wanted=new Set(visible.map(person=>person.id));
      for(const [id,tile] of tiles)if(!wanted.has(id))remove(id,tile);
      for(const person of visible){
        let tile=tiles.get(person.id);
        if(!tile){
          const node=doc.createElement('article');node.className='guest-room-person';node.dataset.roomParticipant=person.id;
          node.innerHTML='<div class="guest-room-picture"><video autoplay muted playsinline></video><div data-room-placeholder><span aria-hidden="true"></span><p></p></div></div><footer><strong></strong><span></span></footer>';
          tile={node,video:node.querySelector('video'),track:null};tiles.set(person.id,tile);one('.guest-room-people').append(node);
        }
        const own=person.id===self.id,name=typeof person.name==='string'?person.name.slice(0,60):'Guest';
        const candidate=own?localCamera:connected&&mayWatch(self,person)?tracks(person.id)?.camera:null;
        const track=candidate?.readyState==='live'&&candidate.enabled!==false&&!candidate.muted?candidate:null;
        const placeholder=tile.node.querySelector('[data-room-placeholder]');placeholder.hidden=Boolean(track);tile.video.hidden=!track;
        placeholder.querySelector('span').textContent=name.trim().slice(0,1).toLocaleUpperCase()||'?';
        placeholder.querySelector('p').textContent=!own&&!person.connected?'Disconnected':!own&&!connected?'Reconnecting picture':person.media?.camera&&!track?'Waiting for picture':'Camera off';
        tile.node.querySelector('footer strong').textContent=name+(own?' (you)':'');
        tile.node.querySelector('footer span').textContent=[person.state==='waiting'?'Waiting':!person.connected?'Disconnected':'Backstage',person.media?.microphone?'Mic on':'Mic off',person.media?.screen?'Sharing screen':''].filter(Boolean).join(' · ');
        if(tile.track!==track){detach(tile);tile.track=track;tile.video.muted=true;if(track){tile.video.srcObject=new host.MediaStream([track]);Promise.resolve(tile.video.play()).catch(()=>{if(tile.track===track){placeholder.hidden=false;placeholder.querySelector('p').textContent='Picture paused by browser';}});}}
      }
      one('.guest-room-waiting').hidden=!waiting.length;
      one('[data-room-waiting]').textContent=waiting.map(person=>(person.name||'Guest')+(person.id===self.id?' (you)':'')+(!person.connected?' · disconnected':'')).join(' · ');
    }
    return {update,clear,destroy(){clear();container.replaceChildren();}};
  }
  const api={mount,roomPeople,mayWatch};
  if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerGuestRoom=api;
})(typeof window==='object'?window:globalThis);
