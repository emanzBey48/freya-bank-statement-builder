"""Build a self-contained Worker source for Cloudflare Dashboard Quick Edit."""

from __future__ import annotations

import base64
import gzip
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src" / "index.js"
FIXTURES = ROOT / "src" / "test-customers.json"
OUTPUT = ROOT / "dashboard-worker.js"

source = SOURCE.read_text(encoding="utf-8")
fixture_b64 = base64.b64encode(gzip.compress(FIXTURES.read_bytes(), compresslevel=9)).decode("ascii")

source = source.replace(
    'import fixture from "./test-customers.json";\n\nconst customers = fixture.customers;\n',
    f'''const FIXTURE_GZIP_B64 = "{fixture_b64}";
let fixturePromise;

async function loadFixture() {{
  if (!fixturePromise) {{
    fixturePromise = (async () => {{
      const binary = atob(FIXTURE_GZIP_B64);
      const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      return new Response(stream).json();
    }})();
  }}
  return fixturePromise;
}}
''',
)
source = source.replace(
    'async function serviceCall(service, request) {\n  const body = await readBody(request);',
    'async function serviceCall(service, request) {\n  const customers = (await loadFixture()).customers;\n  const body = await readBody(request);',
)

if 'import fixture from "./test-customers.json"' in source or 'fixture.customers' in source:
    raise SystemExit("Failed to make the dashboard source self-contained")

OUTPUT.write_text(source, encoding="utf-8", newline="\n")
print(f"Wrote {OUTPUT.name} ({OUTPUT.stat().st_size} bytes)")
