# Security

This project stores credentials in the operating system keychain via `keyring`.

## Safe usage

- do not commit exported health data
- do not commit SQLite databases or local config files
- avoid pasting real tokens into shell history
- treat leaked `apptoken` values as compromised and rotate them

## Reporting issues

If you find a vulnerability or a secret leak, do not publish the secret in a GitHub issue. Share only the minimum details needed to reproduce the issue.
