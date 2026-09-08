/* Producer, Please + RareIQ Motion 1.0.0
 * Presentation only. No commands, network, device access, timers that imply success,
 * dependencies, theme replacement, or automatic initialization. See docs/API.md.
 */
(function (global) {
  'use strict';
  const VERSION = '1.0.0';
  const roots = new WeakMap();
  const MODES = Object.freeze(['expressive', 'studio', 'reduced', 'off']);
  const STATES = Object.freeze(['idle','unavailable','listening','understanding','executing','complete','attention','error','scanning','found','no-match','selected','preview','on-air','busy','offline']);
  const EASE = 'cubic-bezier(.16,1,.3,1)';
  const PRESETS = Object.freeze({
    press: { duration: 260, frames: [{transform:'scale(1)'},{transform:'scale(.965)',offset:.28},{transform:'scale(1)'}] },
    lift: { duration: 300, frames: [{transform:'translateY(0)'},{transform:'translateY(-3px)',offset:.4},{transform:'translateY(0)'}] },
    reveal: { duration: 300, frames: [{opacity:0,transform:'translateY(10px) scale(.99)'},{opacity:1,transform:'translateY(0) scale(1)'}] },
    drawer: { duration: 300, frames: [{opacity:0,transform:'translateX(18px)'},{opacity:1,transform:'translateX(0)'}] },
    toast: { duration: 300, frames: [{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}] },
    select: { duration: 300, frames: [{opacity:.45,transform:'scale(.96)'},{opacity:1,transform:'scale(1)'}] },
    confirm: { duration: 380, frames: [{transform:'scale(1)'},{transform:'scale(1.075)',offset:.42},{transform:'scale(1)'}] },
    attention: { duration: 300, frames: [{transform:'translateX(0)'},{transform:'translateX(-2px)',offset:.25},{transform:'translateX(2px)',offset:.6},{transform:'translateX(0)'}] },
    nod: { duration: 520, frames: [{transform:'translateY(0) rotate(0)'},{transform:'translateY(-6px) rotate(-3deg)',offset:.38},{transform:'translateY(0) rotate(0)'}] },
    listen: { duration: 1100, frames: [{opacity:.8,transform:'scale(1)'},{opacity:1,transform:'scale(1.045)',offset:.5},{opacity:.8,transform:'scale(1)'}] },
    scan: { duration: 1100, frames: [{opacity:0,transform:'translateY(-45%)'},{opacity:1,offset:.15},{opacity:1,offset:.8},{opacity:0,transform:'translateY(210%)'}] },
    sweep: { duration: 600, frames: [{opacity:0,transform:'translateX(-105%) skewX(-16deg)'},{opacity:.6,offset:.3},{opacity:0,transform:'translateX(160%) skewX(-16deg)'}] },
    spin: { duration: 360, frames: [{transform:'rotate(0deg)'},{transform:'rotate(70deg)'}] },
    layers: { duration: 380, frames: [{transform:'translateX(0)'},{transform:'translateX(3px)',offset:.3},{transform:'translateX(-2px)',offset:.65},{transform:'translateX(0)'}] },
    snip: { duration: 380, frames: [{transform:'rotate(0)'},{transform:'rotate(-17deg) scale(.9)',offset:.3},{transform:'rotate(6deg)',offset:.65},{transform:'rotate(0) scale(1)'}] },
    signal: { duration: 420, frames: [{opacity:1,transform:'scale(1)'},{opacity:.55,transform:'scale(.85)',offset:.3},{opacity:1,transform:'scale(1.06)',offset:.65},{opacity:1,transform:'scale(1)'}] },
    icon: { duration: 320, frames: [{transform:'scale(1)'},{transform:'scale(.86) rotate(-9deg)',offset:.35},{transform:'scale(1)'}] }
  });
  const validMode = value => MODES.includes(value);
  function create(root, options) {
    options = options || {};
    if (!(root instanceof global.HTMLElement) || !root.hasAttribute('data-pp-motion-root')) {
      throw new TypeError('PPMotion.create requires an explicit [data-pp-motion-root] HTMLElement.');
    }
    if (root.closest('[data-pp-motion-exclude]') || /^(VIDEO|CANVAS|IFRAME)$/.test(root.tagName)) {
      throw new TypeError('A protected output cannot be a motion root.');
    }
    if (roots.has(root)) return roots.get(root);
    const media = global.matchMedia ? global.matchMedia('(prefers-reduced-motion: reduce)') : {matches:false};
    const key = typeof options.storageKey === 'string' ? options.storageKey : 'producerplease.operator.motion.v1';
    const persist = options.persist !== false;
    let preferred = validMode(options.defaultMode) ? options.defaultMode : 'expressive', persisted = false;
    if (persist) { try { const saved = global.localStorage.getItem(key); if (validMode(saved)) { preferred = saved; persisted = true; } } catch (_) {} }
    let onAir = false, destroyed = false, effective = preferred;
    const active = new Set(), channels = new WeakMap(), listeners = [], pendingLevels = new Map(), originals = new Map();
    const rootAttrs = ['data-ppm-mode','data-ppm-preference','data-ppm-hidden'];
    const before = new Map(rootAttrs.map(k => [k, root.getAttribute(k)]));
    let frame = null, lastLevelFrame = 0, levelTimer = null;
    const maxAnimations = Number.isFinite(options.maxAnimations) ? Math.min(32,Math.max(1,options.maxAnimations)) : 20;
    let observer = null;
    if ('IntersectionObserver' in global) {
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) if (!entry.isIntersecting) {
          for (const record of Array.from(active)) if (record.element === entry.target) record.animation.cancel();
        }
      });
    }
    function listen(target, event, handler, settings) {
      target.addEventListener(event, handler, settings); listeners.push(() => target.removeEventListener(event,handler,settings));
    }
    function owns(element) {
      return !destroyed && element instanceof global.Element && element !== root && root.contains(element)
        && element.closest('[data-pp-motion-root]') === root
        && !element.closest('[data-pp-motion-exclude]')
        && !/^(VIDEO|CANVAS|IFRAME|IMG|PICTURE)$/.test(element.tagName)
        && !element.querySelector('video, canvas, iframe, img, picture, [data-pp-motion-exclude]');
    }
    function visible(element) {
      if (document.hidden || !element.isConnected || element.closest('[hidden],[inert]')) return false;
      const r=element.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < global.innerHeight && r.left < global.innerWidth;
    }
    function mode() {
      if (preferred === 'off') return 'off';
      if (media.matches || preferred === 'reduced') return 'reduced';
      return onAir && preferred === 'expressive' ? 'studio' : preferred;
    }
    function clearLevels() {
      if (frame !== null) global.cancelAnimationFrame(frame); frame=null;
      if (levelTimer !== null) global.clearTimeout(levelTimer); levelTimer=null;
      pendingLevels.clear();
      originals.forEach((original,el) => {
        if (original) el.style.setProperty('transform',original); else el.style.removeProperty('transform');
      });
      originals.clear();
    }
    function cancelAll() {
      for (const record of Array.from(active)) record.animation.cancel();
      clearLevels();
    }
    function refresh() {
      const next=mode(); if (effective !== next) cancelAll(); effective=next;
      root.setAttribute('data-ppm-mode',effective); root.setAttribute('data-ppm-preference',preferred);
      root.setAttribute('data-ppm-hidden',String(document.hidden));
      root.dispatchEvent(new CustomEvent('pp:motionmode',{bubbles:false}));
    }
    function run(element, frames, duration, settings, channel) {
      settings = settings || {};
      if (!owns(element) || !visible(element) || effective === 'off' || effective === 'reduced' || typeof element.animate !== 'function') return Promise.resolve(false);
      const byName=channels.get(element) || new Map();
      const old=byName.get(channel); if (old) old.cancel();
      if (active.size >= maxAnimations) return Promise.resolve(false);
      let animation;
      try {
        animation=element.animate(frames, {duration, easing:settings.easing || EASE, iterations:Math.min(effective==='studio'?1:3,Math.max(1,settings.iterations || 1)), fill:'none'});
      } catch (_) { return Promise.resolve(false); }
      byName.set(channel,animation); channels.set(element,byName);
      const record={animation,element}; active.add(record); if (observer) observer.observe(element);
      return animation.finished.then(() => true, () => false).finally(() => {
        active.delete(record); if (byName.get(channel)===animation) byName.delete(channel);
        if (observer && !Array.from(active).some(r=>r.element===element)) observer.unobserve(element);
      });
    }
    function play(element, name, settings) {
      if (!PRESETS[name] || !owns(element)) return Promise.resolve(false);
      const p=PRESETS[name];
      if (effective==='studio' && ['nod','listen','sweep','spin','lift','scan'].includes(name)) return Promise.resolve(false);
      return run(element,p.frames,effective==='studio'?Math.min(p.duration,180):p.duration,settings,name);
    }
    function ripple(element, x, y) {
      if (!owns(element) || effective!=='expressive' || !visible(element) || !element.hasAttribute('data-ppm-ripple')) return;
      const r=element.getBoundingClientRect();
      if (element.querySelectorAll('.ppm-ripple').length >= 2) return;
      const dot=document.createElement('span'); dot.className='ppm-ripple'; dot.setAttribute('aria-hidden','true');
      const d=Math.max(r.width,r.height)*2;
      dot.style.width=d+'px'; dot.style.height=d+'px';
      dot.style.left=((Number.isFinite(x)?x:r.width/2)-d/2)+'px'; dot.style.top=((Number.isFinite(y)?y:r.height/2)-d/2)+'px';
      element.appendChild(dot);
      run(dot,[{transform:'scale(.02)',opacity:.24},{transform:'scale(1)',opacity:0}],480,{},'ripple').finally(()=>dot.remove());
    }
    function setState(element,state,settings) {
      if (!owns(element) || !STATES.includes(state)) return false;
      settings=settings || {};
      const old=element.getAttribute('data-ppm-state');
      element.setAttribute('data-ppm-state',state);
      if (typeof settings.label==='string') {
        const label=element.querySelector('[data-ppm-label]'); if (label) label.textContent=settings.label;
      }
      if (old===state) return true; // polling the same state never retriggers motion
      for (const record of Array.from(active)) if (record.element===element || element.contains(record.element)) record.animation.cancel();
      const avatar=element.querySelector('[data-ppm-avatar]');
      const result=element.querySelector('[data-ppm-result]');
      const glyph=element.querySelector('[data-ppm-state-icon]');
      if (state==='listening') { if (avatar) play(avatar,'listen',{iterations:2}); }
      else if (state==='scanning') { const rail=element.querySelector('[data-ppm-scan-rail]'); if (rail) play(rail,'scan',{iterations:3}); }
      else if (state==='found' || state==='complete') { if (avatar) play(avatar,'nod'); if (result) play(result,'reveal'); if (glyph) play(glyph,'confirm'); }
      else if (state==='error' || state==='attention' || state==='no-match') { if (glyph) play(glyph,'attention'); }
      else if (state==='executing' || state==='understanding' || state==='busy') { if (glyph) play(glyph,'icon'); }
      if (state!=='listening') {
        element.querySelectorAll('[data-ppm-bar]').forEach(bar => {bar.style.removeProperty('transform'); originals.delete(bar);});
        pendingLevels.delete(element);
      }
      root.dispatchEvent(new CustomEvent('pp:motionstate',{detail:{element,state,previous:old},bubbles:false}));
      return true;
    }
    // The host supplies real normalized levels. This function never acquires a microphone,
    // creates a fake signal, or schedules recurring sampling work.
    function updateLevel(element,values) {
      if (!owns(element) || element.getAttribute('data-ppm-state')!=='listening' || !visible(element) || ['reduced','off'].includes(effective)) return false;
      const list=typeof values==='number'?[values]:(Array.isArray(values)||ArrayBuffer.isView(values)?Array.from(values):[]);
      if (!list.length) return false;
      const safe=list.map(v => Number.isFinite(v)?Math.max(0,Math.min(1,v)):0).slice(0,128);
      pendingLevels.set(element,safe);
      if (frame===null && levelTimer===null) {
        const delay=Math.max(0,34-(global.performance.now()-lastLevelFrame));
        levelTimer=global.setTimeout(()=>{levelTimer=null;frame=global.requestAnimationFrame(flushLevels);},delay);
      }
      return true;
    }
    function flushLevels(now) {
      frame=null; lastLevelFrame=now;
      pendingLevels.forEach((values,element) => {
        if (!owns(element) || !visible(element) || element.getAttribute('data-ppm-state')!=='listening' || ['reduced','off'].includes(effective)) return;
        element.querySelectorAll('[data-ppm-bar]').forEach((bar,i) => {
          if (!originals.has(bar)) originals.set(bar,bar.style.getPropertyValue('transform'));
          bar.style.transform='scaleY('+Math.max(.12,values[i%values.length])+')';
        });
      }); pendingLevels.clear();
    }
    function setMode(name) {
      if (destroyed || !validMode(name)) return false;
      preferred=name; persisted=false; if (persist) {try{global.localStorage.setItem(key,name);persisted=true;}catch(_){}}
      refresh();return true;
    }
    function setOnAir(value) { if (destroyed || typeof value!=='boolean') return false; onAir=value;refresh();return true; }
    function status() {return Object.freeze({version:VERSION,preferred,effective,persisted,onAir,systemReduced:!!media.matches,hidden:document.hidden,activeAnimations:active.size,pendingLevelUpdates:pendingLevels.size,destroyed});}
    function destroy() {
      if (destroyed) return; cancelAll();destroyed=true;
      listeners.forEach(fn=>fn()); if(observer) observer.disconnect();
      before.forEach((v,k)=>v===null?root.removeAttribute(k):root.setAttribute(k,v));
      roots.delete(root);
    }
    listen(root,'click',event=>{
      const target=event.target instanceof Element ? event.target.closest('[data-ppm="button"],[data-ppm="icon-button"],[data-ppm="card"]') : null;
      if (!owns(target) || target.matches(':disabled,[aria-disabled="true"]') || target.closest('[inert]')) return;
      const face=target.querySelector('[data-ppm-face]');
      if (face) play(face,'press');
      const icon=target.querySelector('[data-ppm-icon]'); if (icon) { const kind=icon.getAttribute('data-ppm-icon'); play(icon,['spin','layers','snip','signal','nod'].includes(kind)?kind:'icon'); }
      const r=target.getBoundingClientRect();ripple(target,event.detail?event.clientX-r.left:undefined,event.detail?event.clientY-r.top:undefined);
      // No preventDefault, propagation change, command execution, or auto-success.
    },{capture:true}); // Observe enabled activation before the existing handler enters its busy state.
    listen(document,'visibilitychange',()=>{if(document.hidden)cancelAll();refresh();});
    if (media.addEventListener) listen(media,'change',refresh);
    else if (media.addListener) {media.addListener(refresh);listeners.push(()=>media.removeListener(refresh));}
    if (persist) listen(global,'storage',event=>{if(event.key===key){persisted=validMode(event.newValue);preferred=persisted?event.newValue:'expressive';refresh();}});
    refresh();
    const api=Object.freeze({play,ripple,setState,updateLevel,setMode,setOnAir,status,cancelAll,destroy,root});
    roots.set(root,api);return api;
  }
  global.PPMotion=Object.freeze({create,version:VERSION,modes:MODES,states:STATES,presets:Object.freeze(Object.keys(PRESETS))});
})(window);
