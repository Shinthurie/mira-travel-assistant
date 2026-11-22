// CopilotKit runtime (server side of the browser app).
// Browser -> this route -> AG-UI HttpAgent -> FastAPI /agent (LangGraph).
// The A2UI middleware turns tool results containing `a2ui_operations` into A2UI surfaces.
// injectA2UITool is false: Mira's surfaces come from our own graph (validated server-side), never
// from a model-generated render tool.
import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";

const backend = process.env.MIRA_BACKEND_URL || `http://127.0.0.1:${process.env.BACKEND_PORT || "8123"}`;

const runtime = new CopilotRuntime({
  agents: { mira: new HttpAgent({ url: `${backend}/agent` }) },
  a2ui: { injectA2UITool: false, agents: ["mira"] },
});

const handler = createCopilotRuntimeHandler({ runtime, basePath: "/api/copilotkit" });

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
