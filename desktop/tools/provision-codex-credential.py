"""Provision a dedicated API key; never accept one in arguments, files or JSON."""
import argparse
import getpass
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desktop.runtime.codex_credentials import store_api_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-id', required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise ValueError('desktop_codex_interactive_secret_prompt_required')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = getpass.getpass('Dedicated Codex API key (hidden): ')
    try:
        store_api_key(args.profile_id, key)
    finally:
        del key
    print('Codex API credential stored in the current Windows user vault.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Codex credential provisioning failed; no credential was printed.', file=sys.stderr)
        raise SystemExit(1)
