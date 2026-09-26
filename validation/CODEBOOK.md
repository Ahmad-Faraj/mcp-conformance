# Codebook: replies to a wrong-typed tool call

Frozen on 2026-09-24, before any item was labeled. Changes after labeling starts
must be logged at the end of this file with a date and a reason.

## What the rater sees

Each item is one server's reply to a `tools/call` request whose arguments the
harness built to violate the tool's own declared `inputSchema` (for example, a
number where the schema asks for a string). The server returned a JSON-RPC
result, not a JSON-RPC error. The item shows the tool name, the arguments sent,
and the text of the result (cut at 600 characters).

The rater does not see the server name, the SDK, or any label the analysis
assigned.

## Labels

Pick exactly one.

**EXECUTED.** The tool ran on the bad input and returned an ordinary answer.
Data, a confirmation, a computed value, an empty list, or "no results" all
count. The reply gives no sign that the input was wrong.

**REJECTED.** The reply says the input is invalid, missing, of the wrong type,
or otherwise unacceptable. The error must be about the arguments.

**ENV-ERROR.** The reply is an error, but the cause is the environment and not
the arguments: a missing API key or token, no network, a missing file or
service, a rate limit, or a crash unrelated to input. The tool did not do its
job, and the reply does not show that the input was checked.

**UNCLEAR.** The text is too short, truncated, or ambiguous to decide. Use it
sparingly and write a one-line note.

## Decision rules

1. Judge what the reply says, not which words it contains. "Invalid" inside a
   returned document is not a rejection.
2. If the reply names the argument or its type as the problem, label REJECTED,
   even if other errors are mentioned too.
3. A generic "Error: something went wrong" with no cause: UNCLEAR, with a note.
4. "Not found" for the looked-up entity (for example, no user with id 12345) is
   EXECUTED: the tool used the bad value as a query.
5. Do not guess the server's code. Label only from the text shown.

## Output

One row per item: `item_id,label,note`. The note is required for UNCLEAR and
optional otherwise.

## Change log

(none)
