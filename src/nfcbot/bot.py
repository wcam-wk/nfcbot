"""
Bots for this package.

This module extends pywikibot.bot.
"""
from __future__ import annotations

import html
import re
from contextlib import suppress
from typing import Any, Iterable

import mwparserfromhell
import pywikibot
from mwparserfromhell.wikicode import Wikicode
from pywikibot.bot import ExistingPageBot, SingleSiteBot
from pywikibot.textlib import removeDisabledParts, replaceExcept
from pywikibot_extensions.page import FilePage, get_redirects
from pywikibot_extensions.textlib import FILE_LINK_REGEX, iterable_to_wikitext

import nfcbot
from nfcbot.cache import get_cache
from nfcbot.page import NfccViolation, NonFreeFilePage, Page


class NfcBot(SingleSiteBot, ExistingPageBot):
    """Base bot for this package."""

    EXCEPTIONS = ("comment", "nowiki", "pre", "syntaxhighlight")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        self.log_list: list[object] = []
        self.start_time = self.site.server_time()

    def init_page(self, item: object) -> NonFreeFilePage | Page:
        """Re-class the page."""
        page = super().init_page(item)
        try:
            return NonFreeFilePage(page)
        except ValueError:
            return Page(page)

    def log_issue(self, page: pywikibot.Page, issue: object) -> None:
        """
        Log to the logfile and add to self.log_list.

        :param page: Page the issue was encountered on
        :param issue: Issue encountered
        """
        if issue:
            pywikibot.log(f"{page!r}: {issue!r}")
            issue_s = html.escape(str(issue))
            issue_s = issue_s.replace("\n", r"\n")
            self.log_list.append(
                f"{page.title(as_link=True, textlink=True)}: "
                f"<code>{issue_s}</code>"
            )

    def check_disabled(self) -> None:
        """Check if the task is disabled. If so, quit."""
        class_name = self.__class__.__name__
        page = Page(
            self.site,
            f"User:{self.site.username()}/shutoff/{class_name}.json",
        )
        if page.exists():
            content = page.get(force=True).strip()
            if content:
                e = f"{class_name} disabled:\n{content}"
                self.log_issue(page, e)
                pywikibot.error(e)
                self.quit()

    def put_current(  # pylint: disable=arguments-differ
        self, new_text: str, **kwargs: Any
    ) -> bool:
        """Save the current page with the specified text."""
        kwargs.setdefault("asynchronous", False)
        kwargs.setdefault("callback", self.log_issue)
        kwargs.setdefault("minor", self.current_page.namespace() == 3)
        kwargs.setdefault("nocreate", True)
        try:
            return super().put_current(new_text, **kwargs)
        except pywikibot.exceptions.PageSaveRelatedError as e:
            self.log_issue(self.current_page, e)
            return False

    def remove_disabled_parts(self, text: str) -> str:
        """Remove disabled parts from wikitext."""
        return removeDisabledParts(text, tags=self.EXCEPTIONS, site=self.site)

    def teardown(self) -> None:
        """Log issues."""
        if not self.log_list:
            return
        page = Page(
            self.site,
            f"User:{self.site.username()}/log/{self.__class__.__name__}",
        )
        if not page.exists():
            return
        page.save(
            text=f"{iterable_to_wikitext(self.log_list).strip()}\n\n~~~~",
            summary=str(self.start_time),
            botflag=False,
            force=True,
            section="new",
        )

    def treat_page(self) -> None:
        """Process one page (abstract method)."""
        raise NotImplementedError(
            f"Method {self.__class__.__name__}.treat_page() not implemented."
        )


class NfurFixerBot(NfcBot):
    """Bot to fix NFUR disambiguation errors."""

    update_options = {
        "summary": "Update [[WP:NFUR|non-free use rationale]] per usage"
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        cache = get_cache(self.site)
        self.nfur_templates = {
            Page(self.site, t) for t in cache[nfcbot.NFUR_TPL_CAT]
        }

    def skip_page(self, page: Page) -> bool:
        """Sikp the page if it is not a non-free file."""
        if super().skip_page(page):
            return True
        if not isinstance(page, NonFreeFilePage):
            pywikibot.error(f"{page!r} is not a non-free file.")
            return True
        return False

    def handle_title(
        self, title: str
    ) -> tuple[Page | None, list[pywikibot.Page]]:
        """
        Return page and list of other possible pages.

        Returns None and an empty list if the title is not valid.

        :param title: Title of the page
        """
        other_pages: list[pywikibot.Page] = []
        try:
            page = Page.from_wikilink(title, self.site)
        except ValueError as e:
            self.log_issue(self.current_page, e)
            return None, other_pages
        moves = self.site.logevents(logtype="move", page=page)
        other_pages.extend(i.target_page for i in moves if i.target_ns == 0)
        if page.isRedirectPage():
            try:
                page = Page(page.getRedirectTarget())
            except pywikibot.exceptions.Error as e:
                self.log_issue(self.current_page, e)
                return None, other_pages
        if page.isDisambig():
            other_pages.extend(page.linkedPages(namespaces=0))
        return page, other_pages

    @staticmethod
    def get_new_title(
        article: Page,
        other_pages: list[pywikibot.Page],
        vios: Iterable[NfccViolation],
    ) -> str | None:
        """
        Return the new title or None.

        :param article: Article needing possible replacement
        :param other_pages: List of other pages
        :param vios: List of violations
        """
        dab_regex = re.compile(
            rf"""
            \s*
            (?:
                {article.article_titles_regex}(?:\ \(.+\)|, [^,]+)
                |
                {re.escape(article.title().rpartition(' (')[0])}\ \(.+\)
                |
                {re.escape(article.title().rpartition(', ')[0])},\ [^,]+
            )
            \s*
            """,
            flags=re.I | re.X,
        )
        for vio in vios:
            title: str = vio.page.title()
            if vio.page in other_pages or dab_regex.fullmatch(title):
                return title
        return None

    def treat_templates(
        self,
        wikicode: Wikicode,
        usage: Iterable[pywikibot.Page],
        vios: Iterable[NfccViolation],
    ) -> None:
        """Process the templates on the page."""
        for tpl in wikicode.ifilter_templates():
            with suppress(ValueError):
                template = Page.from_wikilink(tpl.name.strip(), self.site, 10)
                if template not in self.nfur_templates:
                    continue
                for param in reversed(tpl.params):
                    if not param.name.matches("Article"):
                        continue
                    article, other_pages = self.handle_title(str(param.value))
                    if article is None:
                        continue
                    if article in usage:
                        break
                    new_title = self.get_new_title(article, other_pages, vios)
                    if new_title:
                        tpl.add(param.name, new_title)

    def treat_headings(
        self,
        wikicode: Wikicode,
        usage: Iterable[pywikibot.Page],
        vios: Iterable[NfccViolation],
    ) -> None:
        """Process the headings on the page."""
        for heading in wikicode.ifilter_headings():
            for link in heading.title.ifilter_wikilinks():
                article, other_pages = self.handle_title(link.title.strip())
                if article is None:
                    continue
                if article in usage:
                    break
                new_title = self.get_new_title(article, other_pages, vios)
                if new_title:
                    link.title = new_title

    def treat_page(self) -> None:
        """Process one page."""
        self.check_disabled()
        vios = self.current_page.nfcc_usage_violations
        vios = [vio for vio in vios if vio.criterion == "10c"]
        if not vios:
            return
        usage = set(self.current_page.usingPages())
        wikicode = mwparserfromhell.parse(
            self.current_page.text, skip_style_tags=True
        )
        self.treat_templates(wikicode, usage, vios)
        if str(wikicode) == self.current_page.text:
            self.treat_headings(wikicode, usage, vios)
        self.put_current(str(wikicode), summary=self.opt.summary)


class OrphanTaggerBot(NfcBot):
    """Bot to tag orphaned non-free files or revisions."""

    update_options = {
        "mode": "",
        "summary": "Tag orphaned non-free file per [[WP:NFCC#7]]",
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        if self.opt.mode == "file":
            self.tpl = "di-orphaned non-free file"
        elif self.opt.mode == "revision":
            self.tpl = "orphaned non-free revisions"
        else:
            raise ValueError("Invalid mode.")
        self.add_text = f"{{{{subst:{self.tpl}}}}}\n"

    def skip_page(self, page: Page) -> bool:
        """
        Sikp the page if any of the below criteria are met.

            1) It is not a non-free file
            2) It is not orphaned
            3) It has the relevant template
        """
        if super().skip_page(page):
            return True
        if not isinstance(page, NonFreeFilePage):
            pywikibot.error(f"{page!r} is not a non-free file.")
            return True
        if (self.opt.mode == "file" and page.is_used) or (
            self.opt.mode == "revision" and not page.is_used
        ):
            return True
        vios = page.nfcc_file_violations
        vios = [vio for vio in vios if vio.criterion == "7"]
        if not vios:
            return True
        if page.has_template(self.tpl):
            pywikibot.output(f"{page!r} already has the template.")
            return True
        return False

    def treat_page(self) -> None:
        """Process one page."""
        self.check_disabled()
        self.put_current(
            self.add_text + self.current_page.text,
            summary=self.opt.summary,
        )


class ReduceTaggerBot(NfcBot):
    """Bot to tag non-free files for reduction."""

    update_options = {
        "summary": "Request reduction. See [[WP:IMAGERES]] for details."
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        self.add_text = f"{{{{{nfcbot.NONFREE_REDUCE_TPL[0]}}}}}\n"

    def skip_page(self, page: Page) -> bool:
        """
        Sikp the page if any of the below criteria are met.

            1) Not a non-free file
            2) Doesn't need reduction
            3) Has {{non-free reduce}}
            4) Has {{non-free no reduce}}
        """
        if super().skip_page(page):
            return True
        if not isinstance(page, NonFreeFilePage):
            pywikibot.error(f"{page!r} is not a non-free file.")
            return True
        vios = page.nfcc_file_violations
        vios = [vio for vio in vios if vio.criterion == "3b"]
        if not vios:
            return True
        if page.has_template(
            nfcbot.NONFREE_REDUCE_TPL + nfcbot.NONFREE_NO_REDUCE_TPL
        ):
            pywikibot.output(f"{page!r} already has a template.")
            return True
        return False

    def treat_page(self) -> None:
        """Process one page."""
        self.check_disabled()
        self.put_current(
            self.add_text + self.current_page.text,
            summary=self.opt.summary,
        )


class FileRemoverBot(NfcBot):
    """Bot to remove files from pages."""

    SUMMARIES = {
        "9": "Non-free files are only permitted in articles.",
        "10c": (
            "No valid [[WP:NFUR|non-free use rationale]] for this page. See"
            " [[WP:NFC#Implementation]]. Questions? [[WP:MCQ|Ask here]]."
        ),
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        self.file_link_regex = re.compile(
            FILE_LINK_REGEX.format("|".join(self.site.namespaces.FILE)),
            flags=re.I | re.X,
        )

    def remove_file_links(
        self, text: str, files: Iterable[NonFreeFilePage]
    ) -> str:
        """
        Remove file links.

        :param text: Page text
        :param files: Files to remove
        """
        if self.current_page.namespace() % 2 == 0:
            old_fmt = r" *{} *"
            new_fmt = ""
        else:
            old_fmt = r"{}"
            new_fmt = "[[:{}:{}]]"
        for match in self.file_link_regex.finditer(
            self.remove_disabled_parts(text)
        ):
            with suppress(ValueError):
                file_page = FilePage.from_wikilink(
                    match.group("filename"), self.site
                )
                if file_page in files:
                    text = replaceExcept(
                        text=text,
                        old=old_fmt.format(re.escape(match.group())),
                        new=new_fmt.format(
                            match.group("namespace"), match.group("filename")
                        ),
                        exceptions=self.EXCEPTIONS,
                        site=self.site,
                    )
        return text

    def remove_gallery_files(
        self, wikicode: Wikicode, files: Iterable[NonFreeFilePage]
    ) -> None:
        """
        Remove files from <gallery>.

        :param wikicode: Parsed wikitext
        :param files: Files to remove
        """
        for tag in wikicode.ifilter_tags():
            if tag.tag.lower() != "gallery" or not tag.contents.strip():
                continue
            lines = str(tag.contents).splitlines()
            for line in list(lines):
                title = self.remove_disabled_parts(line).partition("|")[0]
                with suppress(ValueError):
                    file_page = FilePage.from_wikilink(title, self.site)
                    if file_page in files:
                        lines.remove(line)
                    else:
                        try:
                            NonFreeFilePage(file_page)
                        except ValueError:
                            pass
                        else:
                            self.log_issue(self.current_page, "[[WP:NFG]]")
            tag.contents = "\n".join(lines) + "\n"
            if not tag.contents.strip():
                wikicode.remove(tag)

    def remove_imagemap_files(
        self, wikicode: Wikicode, files: Iterable[NonFreeFilePage]
    ) -> None:
        """
        Remove files from <imagemap>.

        :param wikicode: Parsed wikitext
        :param files: Files to remove
        """
        for tag in wikicode.ifilter_tags():
            if tag.tag.lower() != "imagemap" or not tag.contents.strip():
                continue
            for line in str(tag.contents).splitlines():
                line = line.strip()
                if not line or line[0] == "#":
                    # Ignore blank lines and comments.
                    continue
                title = self.remove_disabled_parts(line).partition("|")[0]
                with suppress(ValueError):
                    file_page = FilePage.from_wikilink(title, self.site)
                    if file_page in files:
                        wikicode.remove(tag)
                # Only the first logical line specifies the iamge.
                break

    def remove_template_files(
        self, wikicode: Wikicode, files: Iterable[NonFreeFilePage]
    ) -> None:
        """
        Remove files from template parameters.

        :param wikicode: Parsed wikitext
        :param files: Files to remove
        """
        for tpl in wikicode.ifilter_templates():
            for param in tpl.params:
                with suppress(ValueError):
                    file_page = FilePage.from_wikilink(
                        param.value.strip(), self.site
                    )
                    if file_page in files:
                        tpl.remove(param, keep_field=True)

    def treat_page(self) -> None:
        """Process one page."""
        self.check_disabled()
        vios = self.current_page.nfcc_usage_violations
        files = get_redirects(frozenset(vio.file for vio in vios))
        if not files:
            return
        text = new_text = self.current_page.text
        new_text = self.remove_file_links(new_text, files)
        wikicode = mwparserfromhell.parse(new_text, skip_style_tags=True)
        self.remove_gallery_files(wikicode, files)
        self.remove_imagemap_files(wikicode, files)
        self.remove_template_files(wikicode, files)
        new_text = str(wikicode)
        if text == new_text:
            self.log_issue(self.current_page, "Failed to remove file(s)")
            return
        summary = "Removed [[WP:NFCC]] violation(s). "
        if self.current_page.is_article:
            summary += self.SUMMARIES["10c"]
        else:
            summary += self.SUMMARIES["9"]
        self.put_current(new_text, summary=summary)
