# Freya Bank statement services mock

Cloudflare Worker mock for the final case. The test fixture is copied from
`../Build the Builder - Final Case/test-environment/test-customers.json` to
`src/test-customers.json`. Responses are returned with the fixture's exact
HTTP status and body.

## Endpoints

- `GET /healthz`
- `POST /oauth2/token` (synthetic test token)
- `POST /voice/v1/cards.list`
- `POST /voice/v1/cards.balance`
- `POST /voice/v1/statement.week.get`
- `POST /voice/v1/statement.week.decide`
- `POST /voice/v1/statement.week.change`
- `POST /voice/v1/contact.email.get`
- `POST /voice/v1/statement.pdf.send`

Service requests use the `data` / `call` envelope from the final case service
contract. `call`, API headers, and token values are accepted but not validated,
as specified by the test environment. `delaySeconds` in a fixture is honored.

## Local development

```powershell
pnpm install
pnpm run dev
```

The local Worker listens on `http://localhost:8787`. Use `/healthz` to confirm
it starts.

## Deploy

```powershell
pnpm run deploy
```

For Cloudflare Dashboard Quick Edit, regenerate the self-contained source after
updating the fixture or Worker:

```powershell
python build-dashboard-worker.py
```

Then paste `dashboard-worker.js` into the Worker's `worker.js` editor and
deploy. The generated source embeds a gzip-compressed copy of the fixture so
Quick Edit does not need a second file.

Keep the Worker available through the benchmark period and place its
`workers.dev` URL in `submission.json`.
