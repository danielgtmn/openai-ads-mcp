# Contributing

This project is an unofficial client for the public OpenAI Ads Advertiser API. It is not affiliated with OpenAI.

1. Use Python 3.11 or newer.
2. Create a virtual environment and install the package with development tools:

   ```bash
   python -m pip install -e ".[dev]"
   ```

3. Run the tests. They mock the Ads API and do not need a real key:

   ```bash
   python -m pytest
   ```

4. Keep comments, docstrings, errors, and docs in English.
5. Do not commit `.env` files, API keys, or bearer tokens.
6. New write behavior must keep creates paused and must not call the API when `MCP_READ_ONLY` is anything other than `false`.
7. If you change the public version, update `pyproject.toml`, `src/openai_ads_mcp/__version__`, and `CHANGELOG.md` together.

See the README for how container images are published from version tags. Do not add a registry other than the GitHub Actions workflow that pushes to GHCR.
