// Low-level Server API: inputSchema is hand-written JSON Schema, declared in tools/list.
// This is the pattern a server author uses when not going through McpServer+zod.
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "lowlevel-probe-target", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "scan_code_imports",
      description: "Scan source code for npm package imports",
      inputSchema: {
        type: "object",
        properties: { code: { type: "string" } },
        required: ["code"],
      },
    },
  ],
}));

// Handler does NOT re-validate. It trusts the declared schema, exactly as a
// server author reasonably might. The question is whether the SDK enforces it.
server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const code = req.params.arguments?.code;
  return {
    content: [
      {
        type: "text",
        text: `CLEAN - no npm package imports found (received typeof=${typeof code})`,
      },
    ],
  };
});

await server.connect(new StdioServerTransport());
