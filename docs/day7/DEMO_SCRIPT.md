# MemTrace v0.1.0 demo scripts

Status: prepared for synthetic data only. Final screenshots and backup recording remain external ignored artifacts.

## Three-minute path

| Time | Action | Evidence to show |
|---|---|---|
| 0:00–0:20 | Open the login page and sign in with a prepared synthetic public account. | Public account identity, real Provider ready state and no shared demo selector. |
| 0:20–0:55 | Start a normal conversation: “以后给我 Python 示例时，请先给简短结论，再给代码。” | Real streamed answer, TTFT/latency/actual usage, no scenario selector. |
| 0:55–1:25 | Wait for background analysis and inspect the right memory sidebar. Confirm the extracted rule after checking content/type/scope. | Pending is not called learned; confirmed active rule is editable. |
| 1:25–1:55 | Ask a rewritten English follow-up that needs Python. | Applicability, injected memory receipt and answer following the concise-first preference. |
| 1:55–2:20 | Give an explicit one-turn override asking for detailed explanation. | Current instruction wins without permanently superseding the long-term rule. |
| 2:20–2:40 | Open Memory Center and show version Diff and usage/effect. | Immutable versions, controlled lifecycle and metadata-only evidence. |
| 2:40–3:00 | Open Evals and Settings. | Real model, 16/16 test, A/B, four baselines, quota and frozen security/tool diagnostics. |

## Five-minute path

Use the three-minute path, then add:

1. show `python_ast_check` on a Python fenced block and an ordinary non-code question where the model does not select the tool;
2. pause the memory, show a relevant turn no longer uses it, then resume it;
3. create a conflicting synthetic preference and demonstrate one conflict resolution path;
4. export a v2 Pack, preview it in the second synthetic account, verify import is paused, and show that local owner/memory IDs are absent;
5. switch accounts and attempt a known resource ID, showing uniform 404 and cleared UI state;
6. refresh the page and show snapshot plus event catch-up recovery.

## Capture rules

- Use only synthetic conversations and public test accounts created for the capture.
- Do not show or store passwords, Key, invitation code, recovery code, Cookie, CSRF token or raw Pack preview token.
- Crop screenshots to the browser viewport; exclude terminal environment and secret files.
- Save screenshots, Playwright traces and backup recording under `output/playwright/day7/` or another Git-ignored directory.
- Record browser name/version/user agent, candidate commit, model, time zone, console errors and network failures in a metadata-only manifest.
- If any response is not a real Provider call with actual usage, stop and repeat after fixing the gate; do not splice in Mock output.
