"""ai-agent-{{name}} — FastAPI application."""
from platform_sdk import BaseAgentApp


class {{Name}}AgentApp(BaseAgentApp):
    service_name = "ai-agent-{{name}}"
    service_title = "ai-agent-{{name}}"
    mcp_servers = {}
    enable_telemetry = True

    def build_dependencies(self, *, bridges, checkpointer, store):
        return {"placeholder": True}

    def routes(self):
        return []


_agent = {{Name}}AgentApp()
app = _agent.create_app()
