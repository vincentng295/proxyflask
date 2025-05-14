(function () {
  /**
   * PROXY CONFIGURATION
   * Current Host: e.g., youtube.com.localhost:1337
   */
  const PROXY_SUFFIX = ".localhost:1337";
  const PROXY_PORT = "1337";
  const PROXY_HOST = location.host; // api.x.com.localhost:1337

  // Save original references to prevent infinite recursion
  const OriginalURL = window.URL;
  const OriginalFetch = window.fetch;
  const OriginalXHR = window.XMLHttpRequest;
  const OriginalWS = window.WebSocket;
  const OriginalSendBeacon = navigator.sendBeacon;

  /**
   * Core logic to determine if a URL should be ignored
   */
  const shouldSkip = (url) => {
    if (!url || typeof url !== "string") return true;
    const lowerUrl = url.toLowerCase();
    if (
      lowerUrl.startsWith("data:") ||
      lowerUrl.startsWith("blob:") ||
      lowerUrl.startsWith("javascript:")
    ) return true;

    try {
      const u = new OriginalURL(url, location.href);
      // Skip if already proxied
      return u.host.endsWith(PROXY_SUFFIX) || (u.hostname === "localhost" && u.port === PROXY_PORT);
    } catch (e) {
      return true;
    }
  };

  /**
   * Logic to transform any URL into a proxy URL
   */
  const rewriteURL = (url) => {
    if (!url) return url;
    try {
      let urlStr = url.toString();

      if (shouldSkip(urlStr)) return urlStr;

      // 1. Handle Protocol-relative (//example.com)
      if (urlStr.startsWith("//")) {
        urlStr = location.protocol + urlStr;
      }

      // 2. Handle Relative Paths (/api/v1)
      if (urlStr.startsWith("/") && !urlStr.startsWith("//")) {
        // If we are already on a proxied page, the root is the proxy host
        return `${location.protocol}//${PROXY_HOST}${urlStr}`;
      }

      // 3. Handle Absolute URLs
      if (/^https?:\/\//.test(urlStr)) {
        const parsed = new OriginalURL(urlStr);
        // Transform: example.com -> example.com.localhost:1337
        const newHost = parsed.host + PROXY_SUFFIX;
        return `http://${newHost}${parsed.pathname}${parsed.search}${parsed.hash}`;
      }

      return urlStr;
    } catch (e) {
      return url;
    }
  };

  // =========================
  // 1. URL CONSTRUCTOR (Fixed Recursion)
  // =========================
  function PatchedURL(url, base) {
    const fullUrl = base ? new OriginalURL(url, base).href : url;
    const rewritten = rewriteURL(fullUrl);
    return new OriginalURL(rewritten);
  }
  PatchedURL.prototype = OriginalURL.prototype;
  Object.getOwnPropertyNames(OriginalURL).forEach((key) => {
    if (!(key in PatchedURL)) {
      try {
        PatchedURL[key] = OriginalURL[key];
      } catch (e) {}
    }
  });
  window.URL = PatchedURL;

  // =========================
  // 2. FETCH (Cloning Request Objects)
  // =========================
  window.fetch = async function (resource, config) {
    let input = resource;
    try {
      if (resource instanceof Request) {
        // Use the Request constructor to clone and change URL safely
        input = new Request(rewriteURL(resource.url), resource);
      } else if (typeof resource === "string") {
        input = rewriteURL(resource);
      }
    } catch (e) {
      console.error("[fetch-interceptor-error]", e);
    }
    return OriginalFetch.call(window, input, config);
  };

  // =========================
  // 3. XHR
  // =========================
  window.XMLHttpRequest = function () {
    const xhr = new OriginalXHR();
    const origOpen = xhr.open;
    xhr.open = function (method, url, ...rest) {
      return origOpen.call(this, method, rewriteURL(url), ...rest);
    };
    return xhr;
  };
  window.XMLHttpRequest.prototype = OriginalXHR.prototype;
  Object.keys(OriginalXHR).forEach((key) => {
    window.XMLHttpRequest[key] = OriginalXHR[key];
  });

  // =========================
  // 4. WEBSOCKET
  // =========================
  window.WebSocket = function (url, protocols) {
    const rewritten = rewriteURL(url);
    // Ensure WS protocol is preserved
    const wsUrl = rewritten.replace(/^http/, "ws");
    return new OriginalWS(wsUrl, protocols);
  };
  window.WebSocket.prototype = OriginalWS.prototype;

  // =========================
  // 5. DOM ATTRIBUTES (src, href, action)
  // =========================
  const patchAttribute = (tags, attr) => {
    tags.forEach((tag) => {
      const proto = window[tag]?.prototype;
      if (!proto) return;
      const desc = Object.getOwnPropertyDescriptor(proto, attr);
      if (!desc || !desc.set) return;

      Object.defineProperty(proto, attr, {
        set(value) {
          return desc.set.call(this, rewriteURL(value));
        },
        get: desc.get,
        configurable: true,
      });
    });
  };

  patchAttribute(["HTMLScriptElement", "HTMLImageElement", "HTMLIFrameElement", "HTMLVideoElement", "HTMLAudioElement", "HTMLSourceElement"], "src");
  patchAttribute(["HTMLLinkElement", "HTMLAnchorElement"], "href");
  patchAttribute(["HTMLFormElement"], "action");

  // =========================
  // 6. SET ATTRIBUTE (Dynamic calls)
  // =========================
  const origSetAttr = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (typeof value === "string" && ["src", "href", "action", "data"].includes(name.toLowerCase())) {
      value = rewriteURL(value);
    }
    return origSetAttr.call(this, name, value);
  };

  // =========================
  // 7. BEACON (Analytics/Tracking)
  // =========================
  if (navigator.sendBeacon) {
    navigator.sendBeacon = function (url, data) {
      return OriginalSendBeacon.call(this, rewriteURL(url), data);
    };
  }

  // =========================
  // 8. LOCATION REDIRECTS
  // =========================
  const patchLocation = (obj) => {
    const methods = ["assign", "replace"];
    methods.forEach((m) => {
      const orig = obj[m];
      obj[m] = function (url) {
        return orig.call(this, rewriteURL(url));
      };
    });
  };
  patchLocation(window.location);

  // =========================
  // 9. TRUSTED TYPES
  // =========================
  if (window.trustedTypes?.createPolicy) {
    try {
      window.trustedTypes.createPolicy("default", {
        createScriptURL: (url) => rewriteURL(url),
        createHTML: (html) => html,
        createScript: (script) => script,
      });
    } catch (e) {
      console.warn("TrustedTypes default policy already exists.");
    }
  }

  console.log("URL Redirect Hook Active: Routing through", PROXY_SUFFIX);
})();