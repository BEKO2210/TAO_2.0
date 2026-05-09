# Disclaimer

> **Read this before installing, running, or distributing this software.**

## 1. Not financial advice

TAO_2.0 produces machine-generated reports, scores, plans, analyses,
and — when configured for it — automated trading actions on the
Bittensor (TAO) network. **None of its output is financial advice,
investment advice, tax advice, legal advice, or any kind of
professional advice.** Outputs are not endorsed by, and have not
been reviewed by, any qualified advisor.

You are solely responsible for any decision the software makes on
your behalf, including but not limited to:

- buying, holding, or selling TAO or any other digital asset;
- registering, staking, unstaking, or delegating on any subnet;
- running miners, validators, or other on-chain infrastructure;
- exposing capital to volatile markets;
- entering or exiting positions on any exchange.

## 2. Cryptocurrency risk

TAO and other digital assets are highly volatile and may lose all
of their value in hours. Smart contracts, on-chain protocols,
exchanges, RPC providers, and wallet software can fail, be hacked,
be censored, or contain bugs. Network conditions can change without
notice. Past performance is not predictive of future results.

The "live" data paths read from public endpoints (Bittensor finney,
Subscan, CoinGecko, GitHub) that may be down, rate-limited, fork
their schemas, or return incorrect data. Mock fixtures are **not**
real market data and must not be used to make decisions.

## 3. Operating modes

This software supports a layered set of operating modes. The default
is the safest one. **You opt in to higher-risk modes deliberately.**

- **`NO_WALLET`** (default) — no wallet attached, no signing
  capability, no value can move.
- **`WATCH_ONLY`** — accepts public SS58 addresses for read-only
  monitoring. Cannot sign anything.
- **`MANUAL_SIGNING`** — software prepares unsigned plans and hands
  them to you. You sign on a separate device. No automation.
- **`AUTO_TRADING`** — *opt-in*, *single-user*, *single-key* mode in
  which the software signs and submits transactions on your behalf
  using a hot key you provided. **This is the highest-risk mode.**
  See section 4.

The software never asks for, stores, logs, or transmits seed
phrases. A hot key used in `AUTO_TRADING` mode is the operator's
responsibility to provide and protect.

## 4. Auto-trading risks (read carefully if you enable `AUTO_TRADING`)

When configured for automated trading, the software signs and
submits on-chain transactions without further human approval,
within whatever limits you have set. By enabling this mode you
acknowledge:

- **Total loss is possible.** Strategy bugs, market dislocations,
  oracle failures, network outages, off-by-one errors, race
  conditions with other actors, and front-running can all destroy
  your position. Treat the funds in the hot key as **already lost**
  in a worst case.
- **The hot key is the single point of failure.** Anyone with
  access to the machine the bot runs on can read the key from
  memory or disk, transfer the funds, and you have no recourse.
  Use a separate hot key with a hard cap, not your main coldkey-
  funded account.
- **No kill-switch is foolproof.** The software ships with a file
  flag, an environment-variable kill, and a daily loss limit.
  These reduce risk; they do not eliminate it.
- **There is no broker, no insurance, no rollback.** Once a
  transaction is signed and broadcast, it cannot be reversed.
- **You are solely responsible for keeping the bot's behaviour
  legal in your jurisdiction.** See section 7.

The software's `AUTO_TRADING` mode is intended for use **only by
the Licensor** and any individual the Licensor has expressly
licensed in writing under a separate proprietary licence. Anyone
else who installs, runs, or modifies the software is acting
without a licence — see `LICENSE`.

## 5. Read-only and write-path guards

The Bittensor SDK is started with `BT_READ_ONLY=1` set before
import in the read-only collector path. The chain collector
enforces a write-method denylist (`add_stake`, `unstake`,
`transfer`, `set_weights`, `register`, …) on read paths. These
guards are best-effort and depend on the upstream SDK behaving as
documented.

When `AUTO_TRADING` is enabled, write-method calls go through a
**separate, audited execution path** with explicit position-size,
loss-limit, and kill-switch gates. Bypassing those gates (for
example by writing a plug-in that calls signing methods directly)
is your responsibility and your risk.

## 6. Local-only, no telemetry — but third-party endpoints exist

The software runs locally and does not phone home. However, the
"live" and `AUTO_TRADING` paths make outbound HTTPS / WSS requests
to:

- `entrypoint-finney.opentensor.ai` (Bittensor mainnet)
- `bittensor.api.subscan.io` (Subscan API for wallet data)
- `api.coingecko.com` (price/volume data)
- `api.github.com`, `raw.githubusercontent.com` (subnet repo metadata)

Those services have their own terms of service, privacy policies,
and rate limits. Your use of them is governed by **their** terms,
not by the licence of this repository.

## 7. Compliance is your responsibility

You are solely responsible for compliance with all laws,
regulations, licences, sanctions, and contractual obligations
that apply to your use of this software in your jurisdiction,
including but not limited to:

- securities, commodities, and digital-asset regulations;
- algorithmic-trading and market-abuse rules (e.g. MiFID II,
  WpHG §80 in Germany; equivalent rules elsewhere);
- anti-money-laundering (AML) and know-your-customer (KYC) rules;
- tax reporting obligations (every automated trade is a taxable
  event in many jurisdictions; the software generates many);
- export-control and sanctions regimes;
- data-protection laws (GDPR, CCPA, etc.) for any personal data
  you collect or process;
- the terms of service of every third-party endpoint you connect
  to, including the Bittensor network's own consensus rules.

If your jurisdiction prohibits any of the activities the software
researches, plans, or performs, **do not run those parts of the
software**.

## 8. No warranty

The Licensed Work is provided "AS IS", without warranty of any
kind, express or implied. To the fullest extent permitted by
applicable law, the Licensor disclaims all liability for any
direct, indirect, incidental, consequential, special, exemplary,
or punitive damages arising from your use of, or inability to use,
the Licensed Work — including but not limited to: lost profits,
lost data, lost opportunity, lost or stolen funds, regulatory
penalties, tax liabilities, or reputation damage.

This includes losses arising from:

- bugs, regressions, or design errors in the Licensed Work,
  including in the auto-trading and risk-management code paths;
- bugs in upstream dependencies (Bittensor SDK, scalecodec,
  requests, …);
- incorrect or stale data returned by third-party endpoints;
- network outages, SSL failures, or other connectivity issues
  during a live trading session;
- decisions the auto-trading mode makes on your behalf within
  the limits you configured;
- security vulnerabilities discovered after distribution;
- key-exfiltration or hot-wallet compromise on the operator's
  machine;
- misuse of the software, including bypassing default safety
  modes or removing kill-switch gates.

## 9. Open-source dependencies

This project depends on a number of third-party open-source
libraries (see `requirements.txt`). Each carries its own licence
and disclaimer. Their inclusion does not extend their warranties
to this project, and this project's restrictions do not extend
to them.

## 10. Updates to this disclaimer

The Licensor may update this disclaimer at any time. The version
in the repository at the time you obtain a copy of the Licensed
Work is the version that applies to that copy. By continuing to
use, modify, or distribute the Licensed Work after the disclaimer
has been updated, you accept the updated version.

---

If you do not accept any part of this disclaimer or the
accompanying `LICENSE`, do not install, run, or distribute this
software.
