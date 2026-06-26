from observe.sink.sink import ErrorEvent, FeedbackEvent, Sink


class Router:
    def __init__(self) -> None:
        self._sinks: list[Sink] = []

    def register(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def push_error(self, event: ErrorEvent) -> None:
        for s in self._sinks:
            s.push_error(event)

    def push_feedback(self, event: FeedbackEvent) -> None:
        for s in self._sinks:
            s.push_feedback(event)


router = Router()
