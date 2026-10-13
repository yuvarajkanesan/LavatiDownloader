// Talks to the Lavati Downloader app through its native-messaging host (idm-native-host.exe).
const HOST = "com.lavati.idm_downloader";

function ask(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(HOST, message, (reply) => {
      if (chrome.runtime.lastError || !reply) {
        resolve({ ok: false, error: chrome.runtime.lastError?.message || "no reply from Lavati Downloader" });
      } else {
        resolve(reply);
      }
    });
  });
}

async function config() {
  const reply = await ask({ type: "config" });
  // the app not running just means "use the defaults"; adding a download starts it
  return { videoButton: true, captureDownloads: true, ...(reply.ok ? reply : {}) };
}

function badge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
}

async function send(payload) {
  const reply = await ask({ type: "add", ...payload });
  badge(reply.ok ? "✓" : "!", reply.ok ? "#1e8e3e" : "#d93025");
  return reply;
}

// 1. File downloads started in the browser are handed over to the app.
chrome.downloads.onCreated.addListener(async (item) => {
  const cfg = await config();
  if (!cfg.captureDownloads) return;
  const url = item.finalUrl || item.url;
  if (!/^https?:/i.test(url)) return;  // blob:, data:, file: stay with the browser
  chrome.downloads.cancel(item.id, () => chrome.downloads.erase({ id: item.id }));
  const reply = await send({ kind: "file", url, referrer: item.referrer || "", filename: (item.filename || "").split(/[\\/]/).pop() });
  if (!reply.ok) {
    // could not reach the app: give the file back to the browser
    chrome.downloads.download({ url });
  }
});

// 2. Messages from the page button, and the toolbar / context menu entries.
chrome.runtime.onMessage.addListener((msg, _sender, respond) => {
  if (msg.type === "config") {
    config().then(respond);
  } else if (msg.type === "add") {
    send({ kind: "video", url: msg.url }).then(respond);
  } else {
    return false;
  }
  return true;
});

chrome.action.onClicked.addListener((tab) => tab.url && send({ kind: "video", url: tab.url }));

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "idm-link", title: "Download link with Lavati Downloader", contexts: ["link", "video", "audio"] });
});
chrome.contextMenus.onClicked.addListener((info) => {
  const url = info.linkUrl || info.srcUrl;
  if (url) send({ kind: "file", url });
});
