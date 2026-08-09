// High-level McpServer API with a zod schema. Control case: the SDK derives the
// declared inputSchema from zod, so it has the type information available.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "highlevel-probe-target", version: "1.0.0" });

server.registerTool(
  "scan_code_imports",
  {
    description: "Scan source code for npm package imports",
    inputSchema: { code: z.string() },
  },
  async ({ code }) => ({
    content: [
      {
        type: "text",
        text: `CLEAN - no npm package imports found (received typeof=${typeof code})`,
      },
    ],
  })
);

await server.connect(new StdioServerTransport());
