const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
const renderer=source.slice(source.indexOf('const multiCardOverlayBindings='),source.indexOf('let singleCardPickerActive='));

function scene(){
  const listeners=new Map(),imageListeners=new Map(),frames=new Map(),observers=[];
  let serial=0;
  const stage={clientWidth:1000,clientHeight:800,clientLeft:0,clientTop:0,
    getBoundingClientRect(){return {left:40,top:60,width:this.clientWidth,height:this.clientHeight}}};
  const image={naturalWidth:1600,naturalHeight:900,fit:'contain',left:40,top:60,width:1000,height:800,
    getBoundingClientRect(){return {left:this.left,top:this.top,width:this.width,height:this.height}},
    addEventListener:(name,fn)=>imageListeners.set(name,fn),removeEventListener:name=>imageListeners.delete(name)};
  const overlay={parentElement:stage,hidden:true,attributes:{},children:[],
    setAttribute(name,value){this.attributes[name]=value},
    replaceChildren(){this.children=[]},appendChild(child){this.children.push(child)},
    get childElementCount(){return this.children.length}};
  const context=vm.createContext({$:id=>id==='cameraFeed'?image:overlay,studioXRecognitionMode:'six-card-grid',
    getComputedStyle:()=>({objectFit:image.fit}),
    requestAnimationFrame:fn=>{frames.set(++serial,fn);return serial},cancelAnimationFrame:id=>frames.delete(id),
    ResizeObserver:class {constructor(fn){this.fn=fn;this.targets=[];observers.push(this)}observe(target){this.targets.push(target)}disconnect(){this.disconnected=true}},
    window:{addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},
    document:{createElementNS:(_ns,tag)=>({tag,dataset:{},attributes:{},setAttribute(name,value){this.attributes[name]=value}})}});
  vm.runInContext(renderer,context);
  const slot={slot:1,status:'verified',polygon:[[.1,.2],[.4,.2],[.4,.8],[.1,.8]]};
  return {stage,image,overlay,context,slot,listeners,imageListeners,frames,observers,
    draw:()=>context.renderMultiCardCameraOverlay([slot]),
    flush(){const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn())},
    points:()=>overlay.children.find(node=>node.tag==='polygon')?.attributes.points.split(' ').map(p=>p.split(',').map(Number))};
}

test('camera regions include letterboxing and the actual image element offset',()=>{
  const app=scene();app.image.top=160;app.image.height=600;app.draw();
  assert.deepEqual(app.points(),[[100,231.25],[400,231.25],[400,568.75],[100,568.75]]);
  assert.equal(app.overlay.attributes.viewBox,'0 0 1000 800');
});

test('resizing the inspector redraws boxes with current camera dimensions',()=>{
  const app=scene();app.draw();
  app.stage.clientWidth=600;app.image.width=600;
  app.observers[0].fn();app.listeners.get('resize')();
  assert.equal(app.frames.size,1);
  app.flush();
  assert.deepEqual(app.points(),[[60,298.75],[240,298.75],[240,501.25],[60,501.25]]);
  assert.equal(app.overlay.attributes.viewBox,'0 0 600 800');
  assert.equal(app.observers.length,1);
  assert.equal(app.observers[0].targets.length,2);
});

test('initial image load never guesses the source aspect ratio',()=>{
  const app=scene();app.image.naturalWidth=0;app.image.naturalHeight=0;app.draw();
  assert.equal(app.overlay.hidden,true);
  assert.equal(app.overlay.childElementCount,0);
  app.image.naturalWidth=1600;app.image.naturalHeight=900;
  app.imageListeners.get('load')();app.flush();
  assert.equal(app.overlay.hidden,false);
  assert.deepEqual(app.points(),[[100,231.25],[400,231.25],[400,568.75],[100,568.75]]);
});

test('cover and fill map to the rendered image instead of assuming contain',()=>{
  const app=scene();app.image.fit='fill';app.draw();
  assert.deepEqual(app.points(),[[100,160],[400,160],[400,640],[100,640]]);
  app.image.fit='cover';app.context.refreshMultiCardCameraOverlay();app.flush();
  assert.ok(Math.abs(app.points()[0][0]-(-68.88888888888889))<.001);
  assert.equal(app.points()[0][1],160);
});

test('a queued resize cannot resurrect cleared regions or corrupt coordinates',()=>{
  const app=scene();app.draw();app.observers[0].fn();
  app.context.renderMultiCardCameraOverlay([]);app.flush();
  assert.equal(app.overlay.hidden,true);
  app.slot.polygon[0][0]=NaN;app.draw();
  assert.equal(app.overlay.childElementCount,0);
});

test('page teardown disconnects observers and cancels scheduled redraws',()=>{
  const app=scene();app.draw();app.observers[0].fn();
  app.listeners.get('pagehide')();
  assert.equal(app.frames.size,0);
  assert.equal(app.observers[0].disconnected,true);
  assert.equal(app.imageListeners.has('load'),false);
  assert.equal(app.listeners.has('resize'),false);
});
