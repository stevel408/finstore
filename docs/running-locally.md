# Running finstore locally from source

This guide is for anyone running finstore from a cloned source checkout — whether you're evaluating it, contributing, or simply prefer pip-editable installs over pipx. If you installed via `pipx install 'finstore[local]'` and just want to use the CLI, the README quick-start is sufficient.

## Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or plain pip

## 1. Install from source

```bash
git clone https://github.com/you/finstore
cd finstore
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e ".[local,simplefin,snaptrade]"
```

`[local]` pulls in the dashboard and CLI. `[simplefin]` and `[snaptrade]` add the respective backend dependencies. Install only what you need — `[local,simplefin]` is fine if you don't have a SnapTrade account.

Verify:

```bash
finstore --help
```

## 2. Configuration

finstore reads configuration from a `.env` file in your working directory (or from environment variables directly). Create `.env` at the repo root:

```dotenv
# --- Data directory ---
# Where finstore stores account data. Defaults to the OS user data directory
# (~/.local/share/gnc-sfin-gateway/ on Linux, ~/Library/Application Support/gnc-sfin-gateway/ on macOS).
# Uncomment to use a local path during development:
# GNC_SFIN_CACHE_DIR=./data

# --- SimpleFIN (optional) ---
# Set by `finstore setup` automatically. Only set this manually if you want
# to override the saved credential file.
# SIMPLEFIN_ACCESS_URL=https://user:pass@bridge.simplefin.org/simplefin

# --- SnapTrade (optional) ---
# Partner credentials from your SnapTrade developer account.
# SNAPTRADE_CLIENT_ID=your-client-id
# SNAPTRADE_CONSUMER_KEY=your-consumer-key

# --- Dashboard ---
# HOST_BIND_ADDRESS=127.0.0.1
# HOST_PORT=8081
# WEB_SECRET_KEY=change-me-in-production  # used to sign session cookies
# WEB_ACCESS_CODE=optional-passphrase     # gate the dashboard behind a code
```

Most keys are optional. The minimal setup for SimpleFIN only is: nothing in `.env` before running `finstore setup` (step 3 below saves the credential for you).

## 3. SimpleFIN setup

SimpleFIN requires a one-time setup token to authorise access to your bank accounts. Get a token from [beta-bridge.simplefin.org](https://beta-bridge.simplefin.org/simplefin/create), then:

```bash
finstore setup <your-setup-token>
```

This exchanges the token for a permanent access URL and saves it to `{data_dir}/credentials/simplefin.bin` (mode 0600). You do not need to add it to `.env`.

To try finstore with fictional demo data (no account needed):

```bash
finstore setup --demo
```

## 4. SnapTrade setup

SnapTrade requires a developer account at [snaptrade.com](https://snaptrade.com). Once you have partner credentials, add them to `.env`:

```dotenv
SNAPTRADE_CLIENT_ID=your-client-id
SNAPTRADE_CONSUMER_KEY=your-consumer-key
```

Then register your local user and get a brokerage connection link:

```bash
finstore snaptrade setup
```

This registers a SnapTrade user on your behalf, saves the per-user secret to `{data_dir}/credentials/snaptrade.bin` (mode 0600), and prints an OAuth URL. Open the URL in a browser and connect your brokerage account(s). You only need to run `finstore snaptrade setup` once per machine. If you want to connect an additional brokerage later, run it again — it will reuse the existing registration and print a fresh OAuth link.

Check that your brokerage appears:

```bash
finstore snaptrade status
```

To remove the SnapTrade user entirely:

```bash
finstore snaptrade delete
```

## 5. Fetching data

Pull data from all configured backends:

```bash
finstore fetch --all
```

Or fetch a single backend:

```bash
finstore fetch --backend simplefin
finstore fetch --backend snaptrade
```

For a first-time backfill, supply a start date:

```bash
finstore fetch --all --start 2025-01-01
```

Subsequent runs without `--start` pick up from where the last fetch left off.

## 6. Other CLI commands

```bash
finstore accounts          # list cached accounts (cash and investment)
finstore accounts --json   # machine-readable output

finstore validate          # check all stored files for integrity violations

finstore cache reset                      # wipe the entire local cache
finstore cache reset --account <id>       # wipe a single account entry
```

After a schema upgrade (e.g. upgrading from a release that used schema v4 to one that requires v5), you must reset and re-fetch:

```bash
finstore cache reset --yes
finstore fetch --all --start 2025-01-01
```

## 7. Dashboard

Start the web dashboard:

```bash
finstore serve
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081) in a browser. The dashboard provides:

- **Accounts** — balance summary for all cash and investment accounts
- **Account detail** — transaction history for cash accounts; positions and investment transactions for brokerage accounts
- **Fetch** — trigger a fetch from the web UI and watch the result
- **Validate** — run the storage integrity check in-browser

To bind to a different address or port:

```bash
finstore serve --host 0.0.0.0 --port 9000
```

If `WEB_ACCESS_CODE` is set in `.env`, the dashboard prompts for that code before showing any data.

## 8. Using a separate env file

All commands accept `--env-file` to point at a `.env` other than the default:

```bash
finstore --env-file /path/to/staging.env fetch --all
finstore --env-file /path/to/staging.env serve
```

This is useful when running multiple local environments side by side (e.g. a demo environment vs. real data in different directories).
