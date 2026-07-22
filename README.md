# psi-crux-mcp

An MCP server + Python toolkit for **Google PageSpeed Insights** and the **Chrome UX Report (CrUX)** — lab audits, real-user Core Web Vitals, and CrUX history, exposed to any MCP client (Claude, Cursor, …) and to Prefect flows.

Built for the current **Lighthouse 13** audit vocabulary (verified against a live API response), with a projection layer that keeps results LLM-sized, a multi-key rotation ring, and optional persistence — all off one pure Python core.

## Status
Early development. The walking-skeleton path (`crux_query` — current CrUX field data) is landing first; PSI lab analysis, the insight/diagnostic parsers, and the persistence layer follow.

## Install
```bash
uvx psi-crux-mcp            # run the MCP server (stdio)
# or
pip install psi-crux-mcp
```

## Configure
Set one Google API key (with the **PageSpeed Insights API** and **Chrome UX Report API** enabled on its project):
```bash
export CRUX_API_KEYS="your-key"       # or key:project_id, comma-separated for a rotation ring
```
`psi-crux init` will guide key setup and print the exact MCP client config.

## Credit
The single-page lab-analysis approach is adapted in spirit from
[ruslanlap/pagespeed-insights-mcp](https://github.com/ruslanlap/pagespeed-insights-mcp) (MIT).
This project reimplements it in Python and extends it with CrUX History, LH13 insight audits,
key rotation, projection, and persistence.

## License
MIT
