# Disclaimer

> **Read this before installing, running, or distributing this software.**

## 1. Not financial advice

TAO_2.0 produces machine-generated reports, scores, plans, and analyses
about the Bittensor (TAO) network and related markets. **None of its
output is financial advice, investment advice, tax advice, legal advice,
or any kind of professional advice.** Outputs are not endorsed by, and
have not been reviewed by, any qualified advisor.

You are solely responsible for any decision you make based on this
software's output, including but not limited to:

- buying, holding, or selling TAO or any other digital asset;
- registering, staking, unstaking, or delegating on any subnet;
- running miners, validators, or other on-chain infrastructure;
- exposing capital to volatile markets;
- entering or exiting positions on any exchange.

## 2. Cryptocurrency risk

TAO and other digital assets are highly volatile and may lose all of
their value. Smart contracts, on-chain protocols, exchanges, RPC
providers, and wallet software can fail, be hacked, be censored, or
contain bugs. Network conditions can change without notice. Past
performance is not predictive of future results.

The "live" data paths in this software read from public endpoints
(Bittensor finney, Subscan, CoinGecko, GitHub) that may be down,
rate-limited, fork their schemas, or return incorrect data. The
software falls back to mock fixtures in such cases — those fixtures
are **not** real market data and must not be used to make decisions.

## 3. No automated value movement

By design and by construction:

- The default wallet mode is `NO_WALLET` (no wallet attached).
- `WATCH_ONLY` mode accepts only public SS58 addresses.
- The software never asks for, stores, logs, or transmits seed
  phrases, mnemonics, or private keys.
- The orchestrator's `ApprovalGate` classifies every action as
  `SAFE`, `CAUTION`, or `DANGER` **before routing**. `DANGER`
  actions (`execute_trade`, `sign_transaction`, `stake`, `unstake`,
  `swap_coldkey`, `reveal_seed`, …) emit a **plan only** and are
  never executed automatically.

If you bypass these defaults — for example by passing
`safety_override=True`, by writing a plug-in that signs transactions,
or by integrating the software with a hot wallet — you do so at your
own risk and outside the scope of this disclaimer.

## 4. Read-only assumptions

The Bittensor SDK is started with `BT_READ_ONLY=1` set before import,
and the chain collector enforces a write-method denylist
(`add_stake`, `unstake`, `transfer`, `set_weights`, `register`, …).
These guards are best-effort and depend on the upstream SDK behaving
as documented. Future SDK changes could weaken the guarantee. The
software is provided "AS IS" — see the licence.

## 5. Local-only, no telemetry — but third-party endpoints exist

The software runs locally and does not phone home. However, the
"live" data paths make outbound HTTPS requests to:

- `entrypoint-finney.opentensor.ai` (Bittensor mainnet)
- `bittensor.api.subscan.io` (Subscan API for wallet data)
- `api.coingecko.com` (price/volume data)
- `api.github.com`, `raw.githubusercontent.com` (subnet repo metadata)

Those services have their own terms of service, privacy policies, and
rate limits. Your use of them is governed by **their** terms, not by
the licence of this repository.

## 6. No warranty

The Licensed Work is provided "AS IS", without warranty of any kind,
express or implied. To the fullest extent permitted by applicable law,
the Licensor disclaims all liability for any direct, indirect,
incidental, consequential, special, exemplary, or punitive damages
arising from your use of, or inability to use, the Licensed Work —
including but not limited to: lost profits, lost data, lost
opportunity, lost or stolen funds, regulatory penalties, tax
liabilities, or reputation damage.

This includes losses arising from:

- bugs, regressions, or design errors in the Licensed Work;
- bugs in upstream dependencies (Bittensor SDK, scalecodec, requests, …);
- incorrect or stale data returned by third-party endpoints;
- network outages, SSL failures, or other connectivity issues;
- decisions you make in reliance on the software's output;
- security vulnerabilities discovered after distribution;
- misuse of the software, including bypassing default safety modes.

## 7. Compliance

You are solely responsible for compliance with all laws, regulations,
licences, sanctions, and contractual obligations that apply to your
use of this software in your jurisdiction, including but not limited
to:

- securities, commodities, and digital-asset regulations;
- anti-money-laundering (AML) and know-your-customer (KYC) rules;
- tax reporting obligations;
- export-control and sanctions regimes;
- data-protection laws (GDPR, CCPA, etc.) for any personal data you
  collect or process;
- the terms of service of every third-party endpoint you connect to.

If your jurisdiction prohibits any of the activities the software
researches, plans, or describes, **do not run those parts of the
software**.

## 8. Production use

Production use, commercial use, and any deployment beyond the
Non-Production Use grant in `LICENSE` require a separate commercial
licence from the Licensor. Running this software in production
without such a licence is a breach of the Business Source License
1.1 and may also violate other terms.

## 9. Open-source dependencies

This project depends on a number of third-party open-source libraries
(see `requirements.txt`). Each carries its own licence and disclaimer.
Their inclusion does not extend their warranties to this project, and
this project's restrictions do not extend to them.

## 10. Updates to this disclaimer

The Licensor may update this disclaimer at any time. The version in
the repository at the time you obtain a copy of the Licensed Work is
the version that applies to that copy. By continuing to use, modify,
or distribute the Licensed Work after the disclaimer has been
updated, you accept the updated version.

---

If you do not accept any part of this disclaimer or the
accompanying `LICENSE`, do not install, run, or distribute this
software.
