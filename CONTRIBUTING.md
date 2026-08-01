# Contributing to Priors

Thanks for helping. Ground rules:

## Setup

```bash
make setup && make preview   # if the sample issue builds, you're good
```

## Before opening a PR

```bash
make lint && make test
```

CI runs the same two commands. Keep PRs focused — one feature or fix each.

## Principles

- **Boring tech.** One container, SQLite, no queues, no microservices. PRs adding heavy infrastructure will be declined.
- **Editorial rules are code.** Anything touching story composition must preserve: sourced takes only, prediction-market odds only (never model guesses), link validation before send.
- **Forker experience first.** Any new config must have a sensible default and a comment in `config.yaml`; any new secret must be documented in `.env.example` with a link to where the key is obtained.
