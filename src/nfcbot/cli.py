"""Command line interface."""
from __future__ import annotations

import argparse
import re
from typing import Iterable

import pywikibot
from pywikibot.bot import _GLOBAL_HELP
from pywikibot.pagegenerators import GeneratorFactory, parameterHelp

from nfcbot.bot import (
    FileRemoverBot,
    NfcBot,
    NfurFixerBot,
    OrphanTaggerBot,
    ReduceTaggerBot,
)
from nfcbot.cache import build_cache, clear_cache
from nfcbot.page import NonFreeFilePage, Page


CLASS_MAP: dict[str, type[NfcBot]] = {
    "nfur-fixer": NfurFixerBot,
    "orphan-tagger": OrphanTaggerBot,
    "reduce-tagger": ReduceTaggerBot,
    "remove-vios": FileRemoverBot,
}


def output_violations(
    page: Page, generator: Iterable[pywikibot.Page], limit: int | None = None
) -> None:
    """
    Write NFCC violations to a page.

    :param page: Page to output to
    :param generator: Pages to check
    :param limit: The maximum number of files to list
    """
    text = ""
    file_violation_count = 0
    for file_page in generator:
        try:
            file_page = NonFreeFilePage(file_page)
        except ValueError:
            pywikibot.exception(tb=True)
            continue
        vios = file_page.nfcc_usage_violations
        if not vios:
            continue
        pywikibot.log(f"{file_page!r} has violation(s).")
        file_violation_count += 1
        for vio in vios:
            text += (
                f"\n|-\n| {file_page.title(as_link=True, textlink=True)} "
                f"|| {vio.page.title(as_link=True, textlink=True)} "
                f"|| {vio.criterion}"
            )
        if limit and file_violation_count >= limit:
            break
    if text:
        caption = f"{file_violation_count} files"
        if limit:
            caption += f" (limit: {limit})"
        caption += "; Last updated: ~~~~~"
        text = (
            f'\n{{| class="wikitable sortable"\n|+ {caption}'
            f"\n! File !! Page !! Criterion{text}\n|}}"
        )
    else:
        text = "None"
    page.save_bot_start_end(text, summary="Updating NFCC violations report")


def parse_script_args(*args: str) -> argparse.Namespace:
    """Parse the CLI script arguments."""
    parser = argparse.ArgumentParser(
        description="NFC bot",
        epilog=parameterHelp
        + re.sub(
            r"\n\n?-help +.+?(\n\n-|\s*$)", r"\1", _GLOBAL_HELP, flags=re.S
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    always_parser = argparse.ArgumentParser(add_help=False)
    always_parser.add_argument(
        "--always",
        action="store_true",
        help="do not prompt to save changes",
    )
    summary_parser = argparse.ArgumentParser(add_help=False)
    summary_parser.add_argument(
        "--summary", help="edit aummary for the bot", default=argparse.SUPPRESS
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    description = "list NFCC violations"
    listvios_subparser = subparsers.add_parser(
        "list-vios",
        description=description,
        help=description,
        allow_abbrev=False,
    )
    listvios_subparser.add_argument(
        "page", help="page title to output the report to"
    )
    listvios_subparser.add_argument(
        "--limit",
        type=int,
        help="maximum number of files to list",
        metavar="N",
    )
    description = "fix NFURs based on current usage"
    subparsers.add_parser(
        "nfur-fixer",
        parents=[always_parser, summary_parser],
        description=description,
        help=description,
        allow_abbrev=False,
    )
    description = "tag orphan files or revisions"
    orphantagger_subparser = subparsers.add_parser(
        "orphan-tagger",
        parents=[always_parser, summary_parser],
        description=description,
        help=description,
        allow_abbrev=False,
    )
    orphantagger_subparser.add_argument(
        "mode", choices=("file", "revision"), help="mode for the bot"
    )
    description = "tag files for size reduction"
    subparsers.add_parser(
        "reduce-tagger",
        parents=[always_parser, summary_parser],
        description=description,
        help=description,
        allow_abbrev=False,
    )
    description = "remove NFCC violations"
    subparsers.add_parser(
        "remove-vios",
        parents=[always_parser],
        description=description,
        help=description,
        allow_abbrev=False,
    )
    description = "build or clear the cache"
    cache_subparser = subparsers.add_parser(
        "cache",
        description=description,
        help=description,
        allow_abbrev=False,
    )
    cache_subparser.add_argument("cache_action", choices=("build", "clear"))
    return parser.parse_args(args=args)


def cli(*args: str) -> int:
    """CLI for the package."""
    local_args = pywikibot.handle_args(args, do_help=False)
    site = pywikibot.Site()
    gen_factory = GeneratorFactory(site)
    script_args = gen_factory.handle_args(local_args)
    parsed_args = parse_script_args(*script_args)
    site.login()
    if parsed_args.action == "cache":
        if parsed_args.cache_action == "build":
            build_cache(site)
        elif parsed_args.cache_action == "clear":
            clear_cache()
        else:
            raise ValueError("Unknown cache action.")
        return 0
    if not gen_factory.gens:
        pywikibot.error(
            "Unable to execute because no generator was defined. "
            "Use --help for further information."
        )
        return 1
    gen = gen_factory.getCombinedGenerator(preload=True)
    if parsed_args.action == "list-vios":
        output_violations(Page(site, parsed_args.page), gen, parsed_args.limit)
    else:
        bot = CLASS_MAP[parsed_args.action]
        del parsed_args.action
        bot(generator=gen, site=site, **vars(parsed_args)).run()
    return 0
