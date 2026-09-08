/* One operator appearance state for first paint and runtime. No audience output. */
(function (root) {
  "use strict";
  const KEY = "rareiq.studiox.appearance.v2";
  const LEGACY_KEY = "rareiq.studiox.theme.v1";
  const SKINS = ["ignite", "afterdark", "voltage", "ember", "daylight"];
  function normalize(value) {
    if (!value || value.version !== 2 || !SKINS.includes(value.skin) || typeof value.followSystem !== "boolean") return null;
    return {version: 2, skin: value.skin, followSystem: value.followSystem};
  }
  function create(host) {
    const media = host.matchMedia("(prefers-color-scheme: light)");
    let state = null;
    let persisted = false;
    try { state = normalize(JSON.parse(host.localStorage.getItem(KEY))); persisted = Boolean(state); } catch (_) { /* Recover below. */ }
    if (!state) {
      let legacy;
      try { legacy = host.localStorage.getItem(LEGACY_KEY); } catch (_) { /* In-memory default. */ }
      state = {version: 2, skin: legacy === "light" ? "daylight" : "ignite", followSystem: legacy === "system"};
      try { host.localStorage.setItem(KEY, JSON.stringify(state)); persisted = true; } catch (_) { /* Never overwrite legacy data. */ }
    }
    function snapshot() {
      const skin = state.followSystem ? (media.matches ? "daylight" : "ignite") : state.skin;
      return {...state, resolvedSkin: skin, theme: skin === "daylight" ? "light" : "dark", persisted};
    }
    function apply() {
      const current = snapshot();
      const data = host.document.documentElement.dataset;
      data.operatorSkin = current.resolvedSkin;
      data.theme = current.theme;
      data.themePreference = current.followSystem ? "system" : current.theme;
      return current;
    }
    function select(choice, save = false) {
      const previous = JSON.stringify(state);
      if (choice === "system") state = {...state, followSystem: true};
      else {
        const skin = choice === "light" ? "daylight" : choice === "dark" ? "ignite" : choice;
        state = {version: 2, skin: SKINS.includes(skin) ? skin : "ignite", followSystem: false};
      }
      if (previous !== JSON.stringify(state)) persisted = false;
      if (save) {
        persisted = false;
        try { host.localStorage.setItem(KEY, JSON.stringify(state)); persisted = true; } catch (_) { /* Applied in memory. */ }
      }
      return apply();
    }
    apply();
    return {apply, select, snapshot, media};
  }
  if (typeof module === "object" && module.exports) module.exports = {create, normalize, KEY, LEGACY_KEY};
  else root.StudioAppearance = create(root);
})(typeof window === "undefined" ? globalThis : window);
