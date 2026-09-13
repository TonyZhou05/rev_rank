# Implementation handoffs

The user requested two parallel implementation agents followed by an independent
crawler test agent. Each agent owns a brief describing its work and limitations.

| Track | Brief | Scope |
| --- | --- | --- |
| Frontend | [frontend.md](frontend.md) | React/TypeScript interaction and design |
| Data processing | [data-processing.md](data-processing.md) | FastAPI imports, extraction, aggregation, reports |
| Independent testing | [testing.md](testing.md) | Import behavior on major websites plus regression tests |

The parent agent owns the API contract, root tooling, integration, and overall docs.
A source-policy restriction, network block, or incomplete page must never be counted
as successful extraction. Synthetic tests must be labeled separately from live tests.
