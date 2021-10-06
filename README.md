[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/jjmc89-bot/nfcbot/main.svg)](https://results.pre-commit.ci/latest/github/jjmc89-bot/nfcbot/main) [![CI](https://github.com/jjmc89-bot/nfcbot/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/jjmc89-bot/nfcbot/actions?query=workflow%3ACI+branch%3Amain) [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# nfcbot
nfcbot manages [non-free media](https://enwp.org/WP:NFC) on the English Wikipedia.
* List some [policy](https://enwp.org/WP:NFCCP) violations: `nfcbot list-vios ...`
* Fix some non-free use rationales: `nfcbot nfur-fixer ...`
* Tag orphaned files for (revision) deletion: `nfcbot orphan-tagger ...`
* Tag large files for reduction: `nfcbot reduce-tagger ...`
* Remove some policy violations: `nfcbot remove-vios ...`

## Toolforge setup
```shell
$ git clone https://github.com/jjmc89-bot/nfcbot $HOME/repo
$ toolforge-jobs run setup-venv --command $HOME/repo/.toolforge/bin/setup-venv --image tf-python39 --wait
$ toolforge-jobs load $HOME/repo/.toolforge/cronjobs.yaml
```
