// Adds a "Download" button on pages that show a video, if enabled in the app's settings.
(() => {
  const ID = "idm-download-button";
  let enabled = true;

  function isVideoPage() {
    const { hostname, pathname } = location;
    if (/youtube\.com$/.test(hostname)) return pathname === "/watch" || pathname.startsWith("/shorts/");
    if (/youtu\.be$/.test(hostname)) return pathname.length > 1;
    return !!document.querySelector("video");
  }

  function sync() {
    const existing = document.getElementById(ID);
    if (!enabled || !isVideoPage()) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const button = document.createElement("button");
    button.id = ID;
    button.type = "button";
    button.textContent = "⬇ Download";
    button.title = "Download this video with Lavati Downloader";
    button.addEventListener("click", () => {
      button.textContent = "Sending…";
      chrome.runtime.sendMessage({ type: "add", url: location.href }, (reply) => {
        button.textContent = reply && reply.ok ? "✓ Sent" : "Could not reach the app";
        setTimeout(() => (button.textContent = "⬇ Download"), 2500);
      });
    });
    document.documentElement.appendChild(button);
  }

  chrome.runtime.sendMessage({ type: "config" }, (cfg) => {
    enabled = !cfg || cfg.videoButton !== false;
    sync();
  });
  // single-page sites change the URL without reloading
  let last = location.href;
  new MutationObserver(() => {
    if (location.href !== last) last = location.href;
    sync();
  }).observe(document, { subtree: true, childList: true });
})();
