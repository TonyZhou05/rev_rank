# Frontend agent brief

## Delivered

React + TypeScript + Vite working workspace under `frontend/`. The flow supports
URL or pasted-text import, clearly labeled synthetic examples, 2–3 candidate review
and correction, buyer budget/mileage/location/priorities, API-backed report generation,
print output, reset/new comparison, loading/error states, source/warning context,
and responsive layouts.

## Design decisions

The interface is a dense research workspace rather than a marketing landing page:
navy top bar, pale research surface, lime decision accent, structured cards, and
large readable comparison/report sections. It does not display made-up market graphs
or claim that user corrections independently verify seller claims. It uses relative
`/api` requests; Vite proxies to FastAPI during development.

## Run and verify

`npm --prefix frontend ci` then `npm --prefix frontend run build`.

The built app passed TypeScript and Vite production compilation. The backend should
be running at 127.0.0.1:8000 for imports and reports; otherwise the UI shows a clear
connection error. `scripts/dev.py` runs both processes together.

## Limitations

No browser visual QA was performed. Report history is available from the backend
contract but this first UI keeps the active report workflow focused. Candidate edits
are local React state until a report is generated. Arbitrary URLs remain subject to
backend source policy; pasted text is the universal fallback.
