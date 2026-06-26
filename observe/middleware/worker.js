export function wrap(handler, cfg) {
  return async (request, env, ctx) => {
    const url = new URL(request.url);
    const path = url.pathname;

    // Serve shim files
    if (path === "/__observe__/observe.js") {
      return serveShim("observe.js", request);
    }
    if (path === "/__observe__/observe.sw.js") {
      return serveShim("observe.sw.js", request);
    }

    // Config endpoint
    if (path === "/__observe__/config") {
      return Response.json({
        endpoint: cfg.endpoint,
        feedbackLabel: cfg.feedbackLabel,
        enrichHook: cfg.enrichHook,
        registerSw: cfg.registerSw,
      });
    }

    // Feedback endpoint
    if (path === "/__observe__/feedback" && request.method === "POST") {
      const data = await request.json();
      await pushFeedback(data, cfg);
      return Response.json({});
    }

    // OTLP endpoint (relay profile)
    if (path.startsWith("/__observe__/otlp") && request.method === "POST") {
      const contentType = request.headers.get("content-type") || "";
      if (contentType.includes("json")) {
        const data = await request.json();
        await parseOtlpJson(data, cfg);
      }
      return Response.json({});
    }

    // Pass through to wrapped handler
    const response = await handler(request, env, ctx);

    // Inject script into HTML responses
    if (response.headers.get("content-type")?.includes("text/html")) {
      return injectScript(response, cfg);
    }

    return response;
  };
}

async function serveShim(name, request) {
  const url = new URL(`../shim/${name}`, import.meta.url);
  const res = await fetch(url);
  const body = await res.text();
  return new Response(body, {
    headers: {
      "Content-Type": "application/javascript",
      "Cache-Control": "public, max-age=3600",
    },
  });
}

async function pushFeedback(data, cfg) {
  if (cfg.sink && cfg.sink.pushFeedback) {
    cfg.sink.pushFeedback({
      message: data.message || "",
      timestamp: data.timestamp || new Date().toISOString(),
      context: data.context || {},
      user: data.user || {},
    });
  }
}

async function parseOtlpJson(data, cfg) {
  for (const span of data.resourceSpans || []) {
    const resource = span.resource || {};
    for (const scope of span.scopeSpans || []) {
      for (const sp of scope.spans || []) {
        if (cfg.sink && cfg.sink.pushError) {
          cfg.sink.pushError({
            message: sp.name || "otel span",
            level: (sp.attributes || {}).level || "error",
            timestamp: String(sp.startTimeUnixNano || ""),
            context: sp.attributes || {},
            trace_id: sp.traceId || null,
            span_id: sp.spanId || null,
          });
        }
      }
    }
  }
}

async function injectScript(response, cfg) {
  const configJson = JSON.stringify({
    endpoint: cfg.endpoint,
    feedbackLabel: cfg.feedbackLabel,
    enrichHook: cfg.enrichHook,
    registerSw: cfg.registerSw,
  });

  const tag = `<script src="/__observe__/observe.js"></script><script>window.__OBSERVE_CONFIG__ = ${configJson};</script>`;

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();

  const reader = response.body.getReader();
  let injected = false;

  (async () => {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!injected) {
        const str = new TextDecoder().decode(value);
        let modified;
        if (str.includes("</head>")) {
          modified = str.replace("</head>", tag + "</head>");
        } else if (str.includes("<body")) {
          modified = str.replace("<body", tag + "<body");
        } else {
          modified = tag + str;
        }
        injected = true;
        writer.write(encoder.encode(modified));
      } else {
        writer.write(value);
      }
    }
    writer.close();
  })();

  return new Response(readable, {
    status: response.status,
    headers: response.headers,
  });
}
