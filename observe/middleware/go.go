package observe

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

//go:embed ../shim/observe.js
var observeJS []byte

//go:embed ../shim/observe.sw.js
var observeSW []byte

type Config struct {
	Endpoint      string `json:"endpoint"`
	FeedbackLabel string `json:"feedbackLabel"`
	EnrichHook    string `json:"enrichHook"`
	RegisterSW    bool   `json:"registerSw"`
}

type Sink interface {
	PushError(event ErrorEvent)
	PushFeedback(event FeedbackEvent)
}

type ErrorEvent struct {
	Message   string         `json:"message"`
	Level     string         `json:"level"`
	Timestamp string         `json:"timestamp"`
	Context   map[string]any `json:"context"`
	TraceID   string         `json:"trace_id,omitempty"`
	SpanID    string         `json:"span_id,omitempty"`
}

type FeedbackEvent struct {
	Message   string            `json:"message"`
	Timestamp string            `json:"timestamp"`
	Context   map[string]any    `json:"context"`
	User      map[string]string `json:"user"`
}

type Router struct {
	sinks []Sink
}

func (r *Router) Register(s Sink) {
	r.sinks = append(r.sinks, s)
}

func (r *Router) PushError(e ErrorEvent) {
	for _, s := range r.sinks {
		s.PushError(e)
	}
}

func (r *Router) PushFeedback(e FeedbackEvent) {
	for _, s := range r.sinks {
		s.PushFeedback(e)
	}
}

type wrappedWriter struct {
	http.ResponseWriter
	status int
	body   *bytes.Buffer
}

func (w *wrappedWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}

func (w *wrappedWriter) Write(b []byte) (int, error) {
	w.body.Write(b)
	return len(b), nil
}

func Wrap(next http.Handler, cfg Config) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path

		switch {
		case path == "/__observe__/observe.js":
			w.Header().Set("Content-Type", "application/javascript")
			w.Write(observeJS)
			return
		case path == "/__observe__/observe.sw.js":
			w.Header().Set("Content-Type", "application/javascript")
			w.Write(observeSW)
			return
		case path == "/__observe__/config":
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(cfg)
			return
		case path == "/__observe__/feedback" && r.Method == "POST":
			handleFeedback(w, r)
			return
		case strings.HasPrefix(path, "/__observe__/otlp") && r.Method == "POST":
			handleOTLP(w, r)
			return
		}

		if !shouldInject(r) {
			next.ServeHTTP(w, r)
			return
		}

		ww := &wrappedWriter{
			ResponseWriter: w,
			status:         http.StatusOK,
			body:           &bytes.Buffer{},
		}
		next.ServeHTTP(ww, r)

		if ww.status >= 200 && ww.status < 300 {
			body := injectScript(ww.body.Bytes(), cfg)
			w.Header().Set("Content-Length", fmt.Sprintf("%d", len(body)))
			w.Write(body)
		} else {
			w.Write(ww.body.Bytes())
		}
	})
}

func shouldInject(r *http.Request) bool {
	ct := r.Header.Get("Accept")
	return strings.Contains(ct, "text/html") || strings.Contains(ct, "*/*")
}

func injectScript(body []byte, cfg Config) []byte {
	configJSON, _ := json.Marshal(cfg)
	tag := fmt.Sprintf(
		`<script src="/__observe__/observe.js"></script><script>window.__OBSERVE_CONFIG__ = %s;</script>`,
		string(configJSON),
	)
	headTag := []byte("</head>")
	if idx := bytes.Index(body, headTag); idx != -1 {
		result := make([]byte, 0, len(body)+len(tag))
		result = append(result, body[:idx]...)
		result = append(result, []byte(tag)...)
		result = append(result, body[idx:]...)
		return result
	}
	return append([]byte(tag), body...)
}

func handleFeedback(w http.ResponseWriter, r *http.Request) {
	var data map[string]any
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		data = map[string]any{}
	}
	// push via global router
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte("{}"))
}

func handleOTLP(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	_ = body // parse OTLP and push to router
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte("{}"))
}
