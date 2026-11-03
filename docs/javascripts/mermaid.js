// Zensical's Mermaid styles recolour edge labels for dark mode, but not the
// half-transparent backdrop that Mermaid draws behind each label, which then
// shows as a thin light outline. Zensical draws each diagram in a closed shadow
// root, so the site's CSS can't reach it: add the rule to the styles Zensical
// gives Mermaid instead, when it loads Mermaid and sets it up.
(() => {
  let mermaid = window.mermaid;
  Object.defineProperty(window, "mermaid", {
    configurable: true,
    get: () => mermaid,
    set(value) {
      if (typeof value?.initialize === "function") {
        const initialize = value.initialize.bind(value);
        value.initialize = (config = {}) =>
          initialize({
            ...config,
            themeCSS: `${config.themeCSS ?? ""}.labelBkg{background-color:transparent}`,
          });
      }
      mermaid = value;
    },
  });
})();
