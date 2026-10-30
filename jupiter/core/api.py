class JupiterAPI:
    """Stable facade for GUI, CLI, tests and future web clients."""

    def __init__(self, assistant):
        self.assistant = assistant

    def command(self, text: str):
        normalized = self.assistant._normalise_command(text)
        return self.assistant.dispatch_command(normalized)

    def health(self):
        from .health import HealthChecker
        return HealthChecker(self.assistant).check()

    def shutdown(self):
        return self.assistant.shutdown()
