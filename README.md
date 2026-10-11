# Freya Bank statement builder

A source-driven Freya workflow builder and the synthetic Cloudflare mock used for the final case.

## Build

Set `FREYA_API_KEY` and `FREYA_BANK_MOCK_URL`, then run:

```sh
python3 builder/final_case.py "<case_folder>"
```

The builder reads the case documents and service contract, updates one workflow in place, exports it to `submission/final.workflow.json`, and writes a run trace under `traces/`. It uses no model calls.

The submitted workflow was built from the final case pack. That source pack is not included in this public repository. The synthetic mock source is under `cloudflare-mock/`.
