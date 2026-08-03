package observe

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
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
	Sinks         []Sink `json:"-"`
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

// FileSink writes events as JSON lines to an append-only file.
type FileSink struct {
	mu sync.Mutex
	w  io.WriteCloser
}

func NewFileSink(path string) (*FileSink, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return nil, err
	}
	return &FileSink{w: f}, nil
}

func (s *FileSink) PushError(e ErrorEvent) {
	s.write(map[string]any{"type": "error", "event": e})
}

func (s *FileSink) PushFeedback(e FeedbackEvent) {
	s.write(map[string]any{"type": "feedback", "event": e})
}

func (s *FileSink) write(v any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.w.Write(append(b, '\n'))
}

// StderrSink logs events via the standard log package.
type StderrSink struct{}

func (StderrSink) PushError(e ErrorEvent) {
	b, _ := json.Marshal(e)
	log.Printf("observe error: %s", b)
}

func (StderrSink) PushFeedback(e FeedbackEvent) {
	b, _ := json.Marshal(e)
	log.Printf("observe feedback: %s", b)
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
	router := &Router{}
	for _, s := range cfg.Sinks {
		router.Register(s)
	}

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
			handleFeedback(w, r, router)
			return
		case strings.HasPrefix(path, "/__observe__/otlp") && r.Method == "POST":
			handleOTLP(w, r, router)
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

// shouldInject only injects the shim into full-page HTML loads.
// htmx partial swaps (HX-Request) and non-HTML Accepts pass through untouched.
func shouldInject(r *http.Request) bool {
	if r.Header.Get("HX-Request") == "true" {
		return false
	}
	return strings.Contains(r.Header.Get("Accept"), "text/html")
}

func injectScript(body []byte, cfg Config) []byte {
	headTag := []byte("</head>")
	idx := bytes.Index(body, headTag)
	if idx == -1 {
		return body
	}
	configJSON, _ := json.Marshal(cfg)
	tag := fmt.Sprintf(
		`<script src="/__observe__/observe.js"></script><script>window.__OBSERVE_CONFIG__ = %s;</script>`,
		string(configJSON),
	)
	result := make([]byte, 0, len(body)+len(tag))
	result = append(result, body[:idx]...)
	result = append(result, []byte(tag)...)
	result = append(result, body[idx:]...)
	return result
}

func handleFeedback(w http.ResponseWriter, r *http.Request, router *Router) {
	var data struct {
		Message   string            `json:"message"`
		Timestamp string            `json:"timestamp"`
		Context   map[string]any    `json:"context"`
		User      map[string]string `json:"user"`
	}
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		data = struct {
			Message   string            `json:"message"`
			Timestamp string            `json:"timestamp"`
			Context   map[string]any    `json:"context"`
			User      map[string]string `json:"user"`
		}{}
	}
	router.PushFeedback(FeedbackEvent{
		Message:   data.Message,
		Timestamp: data.Timestamp,
		Context:   data.Context,
		User:      data.User,
	})
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte("{}"))
}

func handleOTLP(w http.ResponseWriter, r *http.Request, router *Router) {
	body, err := io.ReadAll(r.Body)
	if err == nil {
		for _, ev := range otlpToErrors(body) {
			router.PushError(ev)
		}
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte("{}"))
}

// otlpToErrors converts an OTLP JSON payload into ErrorEvents, mirroring
// observe.receiver.otlp.span_to_error / log_to_error.
func otlpToErrors(body []byte) []ErrorEvent {
	var payload struct {
		ResourceSpans []struct {
			ScopeSpans []struct {
				Spans []struct {
					Name              string `json:"name"`
					TraceID           string `json:"traceId"`
					SpanID            string `json:"spanId"`
					StartTimeUnixNano string `json:"startTimeUnixNano"`
					Attributes        []attr `json:"attributes"`
				} `json:"spans"`
			} `json:"scopeSpans"`
		} `json:"resourceSpans"`
		ResourceLogs []struct {
			ScopeLogs []struct {
				LogRecords []struct {
					TimeUnixNano string `json:"timeUnixNano"`
					Body         struct {
						StringValue string `json:"stringValue"`
						JSONValue   any    `json:"jsonValue"`
					} `json:"body"`
					Attributes []attr `json:"attributes"`
				} `json:"logRecords"`
			} `json:"scopeLogs"`
		} `json:"resourceLogs"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil
	}

	var out []ErrorEvent
	for _, rs := range payload.ResourceSpans {
		for _, ss := range rs.ScopeSpans {
			for _, sp := range ss.Spans {
				attrs := extractAttrs(sp.Attributes)
				out = append(out, ErrorEvent{
					Message:   orDefault(sp.Name, "otel span"),
					Level:     popString(attrs, "level", "error"),
					Timestamp: sp.StartTimeUnixNano,
					Context:   attrs,
					TraceID:   sp.TraceID,
					SpanID:    sp.SpanID,
				})
			}
		}
	}
	for _, rl := range payload.ResourceLogs {
		for _, sl := range rl.ScopeLogs {
			for _, lr := range sl.LogRecords {
				attrs := extractAttrs(lr.Attributes)
				msg := lr.Body.StringValue
				if msg == "" {
					if s, ok := lr.Body.JSONValue.(string); ok {
						msg = s
					}
				}
				out = append(out, ErrorEvent{
					Message:   orDefault(msg, "otel log"),
					Level:     popString(attrs, "severity", "error"),
					Timestamp: lr.TimeUnixNano,
					Context:   attrs,
				})
			}
		}
	}
	return out
}

type attr struct {
	Key   string `json:"key"`
	Value struct {
		StringValue string `json:"stringValue"`
		IntValue    any    `json:"intValue"`
		DoubleValue any    `json:"doubleValue"`
		BoolValue   any    `json:"boolValue"`
	} `json:"value"`
}

func extractAttrs(items []attr) map[string]any {
	result := make(map[string]any, len(items))
	for _, a := range items {
		v := a.Value
		switch {
		case v.StringValue != "":
			result[a.Key] = v.StringValue
		case v.IntValue != nil:
			result[a.Key] = v.IntValue
		case v.DoubleValue != nil:
			result[a.Key] = v.DoubleValue
		case v.BoolValue != nil:
			result[a.Key] = v.BoolValue
		}
	}
	return result
}

func popString(m map[string]any, key, def string) string {
	v, ok := m[key]
	delete(m, key)
	if !ok {
		return def
	}
	if s, ok := v.(string); ok && s != "" {
		return s
	}
	return def
}

func orDefault(s, def string) string {
	if s == "" {
		return def
	}
	return s
}
