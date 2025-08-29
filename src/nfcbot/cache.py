from __future__ import annotations

import json
import os.path
from typing import cast

import pywikibot
from pywikibot_extensions.page import get_redirects

import nfcbot


def _get_cache_directory() -> str:
    loc = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.abspath(os.path.join(loc, "nfcbot"))


def build_cache(site: pywikibot.site.APISite) -> Store:
    pywikibot.output("Building cache ...")
    store = Store()
    for cat in (nfcbot.NFUR_TPL_CAT, nfcbot.FILE_TPL_CAT):
        cat_page = pywikibot.Category(site, cat)
        tpl = cat_page.articles(recurse=True, namespaces=10)
        # Exclude to review
        tpl = (p for p in tpl if p.title() != "Template:Information")
        tpl_redirects = get_redirects(frozenset(tpl), namespaces=10)
        tpl_titles = frozenset(p.title() for p in tpl_redirects)
        store[cat] = cast(frozenset[str], tpl_titles)
    pywikibot.output("Cache built.")
    return store


def clear_cache() -> None:
    Store().clear()
    pywikibot.output("Cache cleared.")


def get_cache(site: pywikibot.site.APISite) -> Store:
    return Store() or build_cache(site)


class Store(dict[str, frozenset[str]]):

    def __init__(self) -> None:
        super().__init__()
        directory = _get_cache_directory()
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        self._file = os.path.join(directory, "store.json")
        if os.path.exists(self._file):
            self._read()
        else:
            self._write()

    def __getitem__(self, key: str) -> frozenset[str]:
        self._read()
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: frozenset[str]) -> None:
        self._read()
        super().__setitem__(key, value)
        self._write()

    def clear(self) -> None:
        super().clear()
        self._write()

    def _read(self) -> None:
        super().clear()
        with open(self._file, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                v = cast(frozenset[str], frozenset(v))
                super().__setitem__(k, v)

    def _write(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(
                {k: list(v) for k, v in self.items()},
                f,
                indent=4,
                sort_keys=True,
            )
