(function () {
  const rewriteURL = (url) => {
    if (typeof url === 'string' && /^https?:\/\//.test(url)) {
    return url.replace(/^https?:\/\/([^\/]+)(\/.*)?$/, (_, domain, path = '') => {
      // Kiểm tra nếu domain chưa kết thúc bằng "localhost:1337"
      if (!domain.endsWith(".localhost:1337")) {
      return `https://${domain}.localhost:1337${path}`;
      }
      return url; // Nếu domain đã có "localhost:1337", trả về url gốc
    });
    }
    return url;
  };
  // === PATCH: fetch ===
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    let [resource, config] = args;
    let url = resource instanceof Request ? resource.url : resource.toString();
    if (/^https?:\/\//.test(url)) {
      url = rewriteURL(url);
      resource = resource instanceof Request ? new Request(url, resource) : url;
      console.log('[fetch] Redirected to:', url);
    }
    return originalFetch(resource, config);
  };

  // === PATCH: XMLHttpRequest ===
  const OriginalXHR = window.XMLHttpRequest;
  function PatchedXHR() {
    const xhr = new OriginalXHR();
    const originalOpen = xhr.open;
    xhr.open = function (method, url, ...rest) {
      if (typeof url === 'string' && /^https?:\/\//.test(url)) {
        url = rewriteURL(url);
        console.log('[XHR] Redirected to:', url);
      }
      return originalOpen.call(this, method, url, ...rest);
    };
    return xhr;
  }
  window.XMLHttpRequest = PatchedXHR;

  // === PATCH: WebSocket ===
  const OriginalWebSocket = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    if (typeof url === 'string') {
      url = url.replace(/^wss?:\/\/([^\/]+)(\/.*)?$/, (_, domain, path = '') => {
        return `ws://${domain}.localhost:1337${path}`;
      });
      console.log('[WebSocket] Rewritten to:', url);
    }
    const ws = new OriginalWebSocket(url, protocols);
    return ws;
  };

  // === PATCH: HTML element property rewrites (src, href) ===
  const elementsToHook = [
    'HTMLImageElement',
    'HTMLScriptElement',
    'HTMLLinkElement',
    'HTMLIFrameElement',
    'HTMLAnchorElement',
  ];
  ['src', 'href'].forEach((attr) => {
    for (const tag of elementsToHook) {
      const proto = window[tag]?.prototype;
      if (!proto) continue;
      const descriptor = Object.getOwnPropertyDescriptor(proto, attr);
      if (!descriptor || typeof descriptor.set !== 'function') continue;
      Object.defineProperty(proto, attr, {
        set(value) {
          const newValue = rewriteURL(value);
          console.log(`[${tag}] ${attr} set:`, value, '→', newValue);
          return descriptor.set.call(this, newValue);
        },
        get: descriptor.get,
        configurable: true,
        enumerable: true,
      });
    }
  });

  // === PATCH: setAttribute for src and href ===
  const originalSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if ((name === 'src' || name === 'href') && typeof value === 'string') {
      const newValue = rewriteURL(value);
      console.log(`[setAttribute] ${name}:`, value, '→', newValue);
      return originalSetAttribute.call(this, name, newValue);
    }
    return originalSetAttribute.call(this, name, value);
  };

  // === PATCH: form.action + setAttribute('action') ===
  const formActionDesc = Object.getOwnPropertyDescriptor(HTMLFormElement.prototype, 'action');
  Object.defineProperty(HTMLFormElement.prototype, 'action', {
    get() {
      return formActionDesc.get.call(this);
    },
    set(value) {
      const newValue = rewriteURL(value);
      console.log('[form.action] Set:', value, '→', newValue);
      return formActionDesc.set.call(this, newValue);
    },
    configurable: true,
    enumerable: true,
  });

  const formSetAttr = HTMLFormElement.prototype.setAttribute;
  HTMLFormElement.prototype.setAttribute = function (name, value) {
    if (name === 'action' && typeof value === 'string') {
      const newValue = rewriteURL(value);
      console.log('[form.setAttribute] action:', value, '→', newValue);
      return formSetAttr.call(this, name, newValue);
    }
    return formSetAttr.call(this, name, value);
  };
})();
