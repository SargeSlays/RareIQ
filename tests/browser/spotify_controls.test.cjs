const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
function runtime(){
  const nodes=new Map();
  for(const id of ['spotifyDevice','spotifyTrackName','spotifyArtistName','spotifyAlbumArt','spotifyVolume','spotifyProgress']){
    nodes.set(id,{value:'',textContent:'',hidden:false,style:{},replaceChildren(...children){this.children=children;},removeAttribute(key){delete this[key];}});
  }
  let interval,playlistCalls=0;
  const context=vm.createContext({$:id=>nodes.get(id),document:{activeElement:null,hidden:false},
    spotifyState:{},spotifyRefreshTimer:0,Option:function(text,value){this.text=text;this.value=value;},
    spotifyTime:()=>'',setSpotifyAvailability(){},renderSpotifyError(){},renderSpotifySetup(){},renderSpotifyEnhancements(){},
    api:async()=>({connected:true}),loadSpotifyPlaylists:async()=>{playlistCalls++;},
    setInterval:fn=>{interval=fn;return 1;},clearInterval(){}});
  vm.runInContext(source.slice(source.indexOf('function spotifySelectedDevice('),source.indexOf('function renderSpotifyEnhancements(')),context);
  vm.runInContext(source.slice(source.indexOf('let spotifyStatusRequest='),source.indexOf('async function spotifyCommand(')),context);
  return {context,nodes,poll:()=>interval(),playlists:()=>playlistCalls};
}
test('active Spotify device wins over blank, stale, or previously selected IDs',()=>{
  const {context}=runtime();
  const devices=[{id:'speaker'},{id:'desktop',is_active:true}];
  for(const previous of ['', 'removed', 'speaker'])assert.equal(context.spotifySelectedDevice(devices,previous),'desktop');
  assert.equal(context.spotifySelectedDevice([{id:'one'},{id:'two'}],'two'),'two');
  assert.equal(context.spotifySelectedDevice([{id:'one'}],'removed'),'one');
  assert.equal(context.spotifySelectedDevice([]),'');
});
test('connected idle playback is not reported as disconnected; stale artwork clears',()=>{
  const app=runtime();app.nodes.get('spotifyAlbumArt').src='old.png';
  app.context.renderSpotify({configured:true,connected:true,devices:[{name:'Desktop',id:'desktop',is_active:true}]});
  assert.equal(app.nodes.get('spotifyDevice').value,'desktop');
  assert.equal(app.nodes.get('spotifyTrackName').textContent,'Nothing playing');
  assert.equal(app.nodes.get('spotifyAlbumArt').hidden,true);
  assert.equal(app.nodes.get('spotifyAlbumArt').src,undefined);
});
test('status rendering cannot fight an operator dragging the volume slider',()=>{
  const app=runtime(),volume=app.nodes.get('spotifyVolume');volume.value='83';
  app.context.document.activeElement=volume;
  app.context.renderSpotify({connected:true,playback:{device:{volume_percent:20}}});
  assert.equal(volume.value,'83');
  app.context.document.activeElement=null;
  app.context.renderSpotify({connected:true,playback:{device:{volume_percent:20}}});
  assert.equal(volume.value,'20');
});
test('Spotify polling is single-flight, recovers after errors, and does not refetch playlists every tick',async()=>{
  const app=runtime();let resolve,calls=0;
  app.context.api=()=>{calls++;return new Promise(yes=>{resolve=yes;});};
  const first=app.context.loadSpotify(),second=app.context.loadSpotify();
  assert.equal(first,second);assert.equal(calls,1);
  resolve({connected:true});await first;assert.equal(app.playlists(),1);
  app.context.api=async()=>({connected:true});app.poll();await app.context.loadSpotify({refreshPlaylists:false});
  assert.equal(app.playlists(),1);
  app.context.api=async()=>{throw new Error('offline');};
  await assert.rejects(app.context.loadSpotify(),/offline/);
  app.context.api=async()=>({connected:false});await app.context.loadSpotify();
});
