/* Operator presentation only: existing handlers retain all command authority. */
(function (host) {
  "use strict";
  let motion = null;
  const names = {expressive:"Expressive", studio:"Studio", reduced:"Reduced", off:"Off"};
  function render() {
    if (!motion) return;
    const state = motion.status();
    host.document.querySelectorAll("[data-studio-motion]").forEach(button => {
      const selected = button.dataset.studioMotion === state.preferred;
      button.setAttribute("aria-checked", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    const status = host.document.getElementById("studioMotionStatus");
    if (status) status.textContent = `${names[state.preferred]} selected · ${names[state.effective]} active${state.systemReduced ? " · system reduced motion" : state.onAir ? " · encoder streaming limit" : ""}${state.persisted ? " · saved on this device" : " · applied in this window; preference is not saved"}.`;
  }
  function init() {
    if (motion || !host.PPMotion) return motion;
    const root = host.document.querySelector("body.pp-shell[data-pp-motion-root]");
    if (!root) return null;
    motion = host.PPMotion.create(root);
    root.addEventListener("pp:motionmode", render);
    const choices = Array.from(root.querySelectorAll("[data-studio-motion]"));
    choices.forEach((button,index) => {
      button.addEventListener("click", () => motion.setMode(button.dataset.studioMotion));
      button.addEventListener("keydown", event => {
        const next = {ArrowRight:(index+1)%choices.length,ArrowDown:(index+1)%choices.length,ArrowLeft:(index+choices.length-1)%choices.length,ArrowUp:(index+choices.length-1)%choices.length,Home:0,End:choices.length-1}[event.key];
        if (next === undefined) return;
        event.preventDefault(); choices[next].focus(); motion.setMode(choices[next].dataset.studioMotion);
      });
    });
    // Only the established icon face moves; native targets and child IDs stay put.
    root.querySelectorAll(".nav-button .nav-app-icon").forEach(face => {
      face.setAttribute("data-ppm-face", "");
      face.parentElement.setAttribute("data-ppm", "button");
    });
    const protectedContent = "video,canvas,iframe,img,picture,[data-pp-motion-exclude]";
    function annotate(button) {
      if (button.closest("[data-pp-motion-root]") !== root || button.closest("[data-pp-motion-exclude]") || button.querySelector(protectedContent)) return;
      if (!button.hasAttribute("data-ppm")) button.setAttribute("data-ppm", "button");
      if (!button.hasAttribute("data-ppm-ripple")) button.setAttribute("data-ppm-ripple", "");
    }
    function annotateBranch(branch) {
      if (!(branch instanceof host.Element)) return;
      if (branch.matches("button")) annotate(branch);
      branch.querySelectorAll("button").forEach(annotate);
    }
    // Existing command handlers stay untouched. Newly rendered scene/dock controls
    // receive only data markers; the runtime retains its one delegated click listener.
    annotateBranch(root);
    const controls = new host.MutationObserver(records => {
      records.forEach(record => record.addedNodes.forEach(annotateBranch));
    });
    controls.observe(root,{childList:true,subtree:true});
    host.addEventListener("pagehide",()=>controls.disconnect(),{once:true});
    render();
    return motion;
  }
  function state(id, value) {
    const element = host.document.getElementById(id);
    return Boolean(motion && element && motion.setState(element,value));
  }
  function recognition(key) {
    const states = {"exact-match":"found",error:"error",ready:"idle",detecting:"scanning",scanning:"scanning","no-match":"no-match","needs-review":"attention"};
    return state("recognitionStatePanel", states[key] || "understanding");
  }
  function advisor(id, value) {
    const element = host.document.getElementById(id);
    const previous = element?.getAttribute("data-ppm-state");
    const applied = state(id,value);
    if (applied && previous !== value) motion.play(element,value === "error" || value === "attention" ? "attention" : value === "complete" ? "confirm" : "icon");
    return applied;
  }
  function notification(element) {
    if (!motion || !element) return;
    element.setAttribute("data-ppm-notification", "");
    motion.play(element,"toast");
  }
  function onAir(value) { if (motion && typeof value === "boolean") motion.setOnAir(value); }
  host.StudioMotion = Object.freeze({init,recognition,advisor,notification,onAir,status:()=>motion?.status()||null});
})(window);
