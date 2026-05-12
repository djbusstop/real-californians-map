// POST /api/chat
//
// Thin LLM proxy. Receives { messages, library_stats } from the chat
// UI, builds a system prompt from the PUMS catalog plus the library
// stats (calibration anchors), and orchestrates a tool-use loop with
// Claude. The one tool, `score_cohort`, proxies to the FastAPI /score
// endpoint exactly the same way page.tsx does. Returns
// { message, cohort } where `cohort` is the most recently scored
// cohort (if any) for the chat UI to hand to the map.
//
// Conversation memory: held by the client (Phase 3 stores in
// localStorage) and sent in full as `messages` per request. The route
// is stateless across requests.
//
// Env: ANTHROPIC_API_KEY required at runtime; COHORT_API_BASE optional
// (falls back to localhost:8000, same default as page.tsx).

import Anthropic from "@anthropic-ai/sdk";
import pumsFields from "@/lib/pums_fields.json";
import { COHORT_API_BASE } from "@/lib/constants";

const MODEL = "claude-sonnet-4-6";
const MAX_TOOL_ITERATIONS = 10;
const OPERATORS = [
  "eq",
  "in",
  "range",
  "gte",
  "lte",
  "occupation_soc_major",
  "industry_naics",
] as const;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatRequest {
  messages: ChatMessage[];
  library_stats: unknown[]; // shape from page.tsx; LLM reads as JSON
}

function buildSystemPrompt(libraryStats: unknown[]): string {
  const fmtField = (v: { name: string; topic?: string; description: string }) =>
    `  ${v.name}${v.topic ? ` (${v.topic})` : ""}: ${v.description}`;

  const personFields = pumsFields.person_vars.map(fmtField).join("\n");
  const housingFields = pumsFields.housing_vars.map(fmtField).join("\n");

  return `You help a user author a cultural cohort vector against ACS PUMS 2019-2023 5-Year data, score it, and discuss the result. You are the interpretive layer in a project that treats statistical machinery as descriptive and natural-language interpretation as the editorial layer above it.

Person-level PUMS fields:
${personFields}

Household-level PUMS fields:
${housingFields}

Operators: ${OPERATORS.join(", ")}.

When you have enough information to define a cohort, call score_cohort. The definition shape:
  {
    "name": string,
    "vibe": short editorial description,
    "threshold": number in (0, 1] (default 0.5),
    "tract_marginals": ACS table codes (e.g. "B11001_006E") — see library_stats below for examples,
    "vector": [{ "field", "op", "value", "weight", "required" (bool) }] (at least one required: true gate),
    "proxy_gap": optional string noting what the vector cannot capture
  }

Calibration anchors. Each library cohort below is an authored example with its computed stats. Use them as the comparison reference set when interpreting a new cohort ("concentrates like X", "broadly distributed like Y"). Do not invent magic-number thresholds:

${JSON.stringify(libraryStats, null, 2)}

Stay conversational. Ask one clarifying question at a time when something is missing. Never reveal the JSON vector to the user. Describe the cohort in plain language and discuss results by comparison against the library examples.`;
}

const SCORE_TOOL: Anthropic.Tool = {
  name: "score_cohort",
  description:
    "Score a cohort definition against PUMS data. Returns id, name, and statistical diagnostics (concentration_index, weighted_member_count, R², Moran's I residual, marginal_reliability_summary, etc.) used to interpret the cohort's geography.",
  input_schema: {
    type: "object",
    properties: {
      name: { type: "string" },
      vibe: { type: "string" },
      threshold: { type: "number", minimum: 0, maximum: 1 },
      tract_marginals: {
        type: "array",
        items: { type: "string" },
        minItems: 1,
        maxItems: 8,
      },
      vector: {
        type: "array",
        minItems: 1,
        items: {
          type: "object",
          properties: {
            field: { type: "string" },
            op: { type: "string", enum: [...OPERATORS] },
            value: {},
            weight: { type: "number", exclusiveMinimum: 0 },
            required: { type: "boolean" },
          },
          required: ["field", "op", "value", "weight"],
        },
      },
      proxy_gap: { type: "string" },
    },
    required: ["name", "vibe", "tract_marginals", "vector"],
  },
};

export async function POST(req: Request): Promise<Response> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return Response.json(
      { error: "ANTHROPIC_API_KEY not set in environment" },
      { status: 500 },
    );
  }

  let body: ChatRequest;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const client = new Anthropic({ apiKey });
  const system = buildSystemPrompt(body.library_stats ?? []);
  const conversation: Anthropic.MessageParam[] = body.messages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  // Most recent successful score_cohort result, returned to the chat
  // UI so the map can update without a second round-trip.
  let lastScoredCohort: unknown = null;

  for (let iter = 0; iter < MAX_TOOL_ITERATIONS; iter++) {
    const response = await client.messages.create({
      model: MODEL,
      max_tokens: 4096,
      system,
      tools: [SCORE_TOOL],
      messages: conversation,
    });

    if (response.stop_reason === "tool_use") {
      conversation.push({ role: "assistant", content: response.content });

      const toolResults: Anthropic.ToolResultBlockParam[] = [];
      for (const block of response.content) {
        if (block.type !== "tool_use" || block.name !== "score_cohort") continue;

        try {
          const scoreRes = await fetch(`${COHORT_API_BASE}/score`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(block.input),
          });
          const text = await scoreRes.text();
          if (!scoreRes.ok) {
            toolResults.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: text,
              is_error: true,
            });
            continue;
          }
          const data = JSON.parse(text);
          // Merge vibe from the tool input. The /score response carries
          // name but not vibe (vibe is presentation-only and is excluded
          // from canonical_cohort_hash). The chat client needs both to
          // label the current cohort, which can drift across iterations
          // even when the vector and therefore the hash stay the same.
          const input = block.input as { vibe?: string };
          lastScoredCohort = { ...data, vibe: input.vibe ?? null };
          // Send the LLM only id, name, and stats. tract_scores is the
          // map-rendering payload and would just consume context here.
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: JSON.stringify({
              id: data.id,
              name: data.name,
              stats: data.stats,
            }),
          });
        } catch (e) {
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: `score_cohort fetch failed: ${e instanceof Error ? e.message : String(e)}`,
            is_error: true,
          });
        }
      }
      conversation.push({ role: "user", content: toolResults });
      continue;
    }

    if (
      response.stop_reason === "end_turn" ||
      response.stop_reason === "stop_sequence"
    ) {
      const message = response.content
        .filter((b): b is Anthropic.TextBlock => b.type === "text")
        .map((b) => b.text)
        .join("\n");
      return Response.json({ message, cohort: lastScoredCohort });
    }

    return Response.json(
      { error: `unexpected stop_reason: ${response.stop_reason}` },
      { status: 500 },
    );
  }

  return Response.json(
    { error: "max tool iterations exceeded" },
    { status: 500 },
  );
}
