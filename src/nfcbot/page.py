"""
Objects representing various MediaWiki pages.

This module extends pywikibot.page.
"""
from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Iterable

import mwparserfromhell
import pywikibot
import pywikibot_extensions.page
from pywikibot.textlib import removeDisabledParts
from pywikibot_extensions.page import get_redirects

import nfcbot


@dataclass(frozen=True)
class NfccViolation:
    """Represents a NFCC violation."""

    file: NonFreeFilePage
    page: Page
    criterion: str


class Page(pywikibot_extensions.page.Page):
    """Represents a MediaWiki page."""

    @property
    def nfcc_usage_violations(self) -> list[NfccViolation]:
        """Return any NFCC usage violations on the page."""
        vios = []
        for file_page in self.imagelinks(content=True):
            with suppress(ValueError):
                file_page = NonFreeFilePage(file_page)
                for vio in file_page.nfcc_usage_violations:
                    if vio.page == self:
                        vios.append(vio)
        return vios

    @property
    def article_title_regex(self) -> str:
        """Return a regex to match the article title."""
        title = self.title(underscore=True)
        title = re.escape(title)
        title = title.replace("_", "[ _]+")
        char1 = title[:1]
        if char1.isalpha():
            # The first letter is not case sensative.
            char1 = f"[{char1}{char1.swapcase()}]"
            title = char1 + title[1:]
        return fr"(?:{title})"

    @property
    def article_titles_regex(self) -> str:
        """Return a regex to match article titles, including redirects."""
        redirects = get_redirects(frozenset([self]), namespaces=0)
        titles = [Page(r).article_title_regex for r in redirects]
        return fr"(?:{'|'.join(titles)})"


class NonFreeFilePage(pywikibot_extensions.page.FilePage, Page):
    """Represents a non-free file description page."""

    def __init__(
        self, source: pywikibot_extensions.page.PageSource, title: str = ""
    ) -> None:
        """Initialize."""
        super().__init__(source, title)
        if (
            pywikibot.Category(self.site, nfcbot.NONFREE_FILE_CAT)
            not in self.categories()
        ):
            raise ValueError(f"{self} is not a non-free file.")
        self._10c_articles: set[Page] = set()
        self._10c_wikitext = ""
        self._nfcc_file_violations: list[NfccViolation] = []
        self._nfcc_usage_violations: list[NfccViolation] = []

    @property
    def nfcc_file_violations(self) -> list[NfccViolation]:
        """Return NFCC file violations."""
        if self._nfcc_file_violations:
            return self._nfcc_file_violations
        if self.is_used:
            visible_file_revs = 0
            for file_rev in self.get_file_history().values():
                if not hasattr(file_rev, "filehidden"):
                    visible_file_revs += 1
                    if visible_file_revs > 1:
                        self._nfcc_file_violations.append(
                            NfccViolation(self, self, "7")
                        )
                        break
        else:
            self._nfcc_file_violations.append(NfccViolation(self, self, "7"))
        if (
            self.megapixels
            and self.megapixels > 0.1 * 1.05
            and not self.has_template(nfcbot.NONFREE_NO_REDUCE_TPL)
        ):
            self._nfcc_file_violations.append(NfccViolation(self, self, "3b"))
        return self._nfcc_file_violations

    def _10c_parse(self) -> tuple[set[Page], str]:
        """Return article wikilinks and wikitext without file ns templates."""
        if self._10c_articles or self._10c_wikitext:
            return self._10c_articles, self._10c_wikitext
        pywikibot.log(f"Parsing {self!r}")
        if not hasattr(self.site, "nfur_tpl"):
            # file_tpl_cat = pywikibot.Category(
            #     self.site, "File namespace templates"
            # )
            # file_tpl = file_tpl_cat.articles(recurse=True, namespaces=10)
            # self.site.file_tpl = get_redirects(frozenset(file_tpl))
            nfur_tpl_cat = pywikibot.Category(self.site, nfcbot.NFUR_TPL_CAT)
            nfur_tpl = nfur_tpl_cat.articles(recurse=True, namespaces=10)
            self.site.nfur_tpl = get_redirects(frozenset(nfur_tpl))
        links = set()
        text = removeDisabledParts(self.text, site=self.site)
        wikicode = mwparserfromhell.parse(text, skip_style_tags=True)
        for tpl in wikicode.ifilter_templates():
            try:
                template = Page.from_wikilink(tpl.name.strip(), self.site, 10)
            except ValueError:
                continue
            if template in self.site.nfur_tpl:
                for param in reversed(tpl.params):
                    if param.name.matches("Article"):
                        value = param.value.strip()
                        if "{" in value:
                            value = self.site.expand_text(
                                text=value,
                                title=self.title(),
                            )
                        with suppress(ValueError):
                            links.add(Page.from_wikilink(value, self.site))
                        break
                wikicode.remove(tpl)
            # elif template in self.site.file_tpl:
            #     wikicode.remove(tpl)
        for wikilink in wikicode.ifilter_wikilinks():
            with suppress(ValueError):
                links.add(Page.from_wikilink(wikilink, self.site))
                wikicode.remove(wikilink)
        self._10c_articles = self._get_articles(links)
        self._10c_wikitext = str(wikicode)
        return self._10c_articles, self._10c_wikitext

    @staticmethod
    def _get_articles(pages: Iterable[Page]) -> set[Page]:
        """Return articles from an iterable of pages."""
        articles = set()
        for page in pages:
            if page.namespace() < 0:
                continue
            with suppress(pywikibot.exceptions.Error):
                while page.isRedirectPage():
                    page = page.getRedirectTarget()
                page = Page(page)
            if not page.is_article:
                continue
            if page.section():
                page = Page(page.site, page.title(with_section=False))
            articles.add(page)
        return articles

    @property
    def nfcc_usage_violations(self) -> list[NfccViolation]:
        """Return NFCC usage violations."""
        if self._nfcc_usage_violations:
            return self._nfcc_usage_violations
        for page in self.usingPages():
            if page.is_article:
                article_links, text = self._10c_parse()
                if not (page in article_links or page.title() in text):
                    self._nfcc_usage_violations.append(
                        NfccViolation(self, page, "10c")
                    )
            else:
                self._nfcc_usage_violations.append(
                    NfccViolation(self, page, "9")
                )
        return self._nfcc_usage_violations

    @property
    def nfcc_violations(self) -> list[NfccViolation]:
        """Return NFCC violations."""
        return self.nfcc_file_violations + self.nfcc_usage_violations
