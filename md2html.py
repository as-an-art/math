#!/usr/bin/env python3
"""Convert markdown articles to HTML pages with sidenotes.

    python3 md2html.py call/index.md [more.md ...]

Each page is written next to its markdown file, with the same name and a
.html extension, and links to the stylesheets (css/landing.css, and
css/print.css for printing) and the icon (icon.ico) by paths relative to the
page.

A file starts with a YAML header giving the page's details:

    ---
    title: Math as an art
    author: Tyler Chen
    institution: Name of University
    email: name@example.org
    date: September 2026
    tldr: One sentence on what the post says, shown in lists of posts.
    description: One sentence for search engines and link previews.
    keywords: [mathematics, mathematical arts]
    ---

Only title is needed. Under the title the page shows the author, with the
date on the line below; the institution and email are not shown. Every field except title,
email and lang also becomes a <meta> tag. lang sets the page language
(default en).

The markdown itself is read by pandoc, which must be installed, so all of
standard markdown works. Footnotes ([^1] ... [^1]: text) become sidenotes.

A page can list other posts. A fenced div holding a bullet list of their
folders (or markdown files), relative to the page, is replaced by a list
showing each post's title, author, date and tldr, read from its header:

    ::: posts
    - a-future-of-math-as-an-art
    - triage
    :::

This script was written with Claude, Anthropic's AI model.
"""

import argparse
import html
import os
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAGE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
{meta}
  <meta name="viewport" content="width=device-width, initial-scale=1">

{css}
</head>
<body>
<div id="contentContainer">


{body}

</div>
</body>
</html>
"""

SIDENOTE = ('<input type="checkbox" id="sn-{n}" class="sidenote-toggle">'
            '<label for="sn-{n}" class="sidenote-ref"></label>')

STYLESHEET = Path(__file__).resolve().parent / 'css' / 'landing.css'
ICON = Path(__file__).resolve().parent / 'icon.ico'
NOTE_DEF = re.compile(r'^\[\^([^\]]+)\]:', re.M)
NOTE_REF = re.compile(r'\[\^([^\]]+)\](?!:)')


def pandoc(text, *args):
    if not shutil.which('pandoc'):
        sys.exit('error: pandoc is not installed (https://pandoc.org/installing.html)')
    done = subprocess.run(['pandoc', *args], input=text, capture_output=True,
                          encoding='utf-8')
    if done.returncode:
        sys.exit('error: pandoc failed: %s' % done.stderr.strip())
    return done.stdout


def plain(node):
    """The text of a piece of pandoc's document tree, without formatting."""
    if isinstance(node, list):
        return ''.join(plain(child) for child in node)
    if not isinstance(node, dict):
        return ''
    if node['t'] in ('Str', 'Code', 'Math'):
        return node['c'] if node['t'] == 'Str' else node['c'][1]
    if node['t'] in ('Space', 'SoftBreak', 'LineBreak'):
        return ' '
    return plain(node.get('c', []))


class Sidenotes:
    """Rewrites pandoc's document tree: footnotes become inline sidenotes,
    and a divider (***, escaped or not, or -.-) becomes a -.- paragraph, which
    the stylesheet draws as Vollkorn's ornament but which still copies as text."""

    def __init__(self):
        self.count = 0

    def walk(self, node):
        if isinstance(node, list):
            out = []
            for child in node:
                child = self.walk(child)
                out.extend(child) if isinstance(child, list) and child and \
                    isinstance(child[0], dict) and child[0].get('spliced') else \
                    out.append(child)
            for child in out:
                if isinstance(child, dict):
                    child.pop('spliced', None)
            return out
        if not isinstance(node, dict):
            return node
        if node.get('t') == 'Note':
            return self.sidenote(node['c'])
        if node.get('t') == 'HorizontalRule' or (
                node.get('t') == 'Para'
                and re.fullmatch(r'([*\-_] ?){3,}|-\.-', plain(node).strip())):
            return {'t': 'Div', 'c': [['', ['divider'], []],
                                      [{'t': 'Plain', 'c': [{'t': 'Str', 'c': '-.-'}]}]]}
        return {key: self.walk(value) for key, value in node.items()}

    def sidenote(self, blocks):
        self.count += 1
        inlines = []
        for block in blocks:
            if block['t'] not in ('Para', 'Plain'):
                sys.exit('error: footnote %d holds a %s; sidenotes can only '
                         'hold plain paragraphs' % (self.count, block['t']))
            if inlines:
                inlines += [{'t': 'LineBreak'}, {'t': 'LineBreak'}]
            inlines += self.walk(block['c'])
        return [{'t': 'RawInline', 'spliced': True,
                 'c': ['html', SIDENOTE.format(n=self.count)]},
                {'t': 'Span', 'c': [['', ['sidenote'], []], inlines]}]


POST = ('<li><a href="{href}" class="post-title">{title}</a>'
        '<span class="post-meta">{meta}</span>{tldr}</li>')


def post_list(block, base):
    """A ::: posts ::: div, listing posts by folder, as a raw HTML list."""
    items = []
    for inner in block['c'][1]:
        if inner['t'] != 'BulletList':
            sys.exit('error: a posts block may only hold a bullet list of folders')
        items += [plain(entry).strip() for entry in inner['c']]
    entries = []
    for item in items:
        path = base / item
        source = path if path.suffix == '.md' else path / 'index.md'
        if not source.exists():
            sys.exit('error: no post at %s (looked for %s)' % (item, source))
        fields, _ = front_matter(source.read_text(encoding='utf-8'))
        text = {key: ', '.join(v) if isinstance(v, list) else v
                for key, v in fields.items()}
        href = item if path.suffix == '.md' else item.rstrip('/') + '/'
        if path.suffix == '.md':
            href = str(Path(item).with_suffix('.html'))
        meta = ', '.join(html.escape(text[key]) for key in ('author', 'date') if text.get(key))
        tldr = text.get('tldr', '')
        entries.append(POST.format(
            href=html.escape(href), title=html.escape(text.get('title') or path.stem),
            meta=meta, tldr='<p class="post-tldr">%s</p>' % html.escape(tldr) if tldr else ''))
    return {'t': 'RawBlock', 'c': ['html', '<ul class="posts">\n%s\n</ul>' % '\n'.join(entries)]}


def scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    return value


def front_matter(markdown):
    """Split off a leading YAML header; return (fields, rest of the text).

    Handles the plain subset used for page details: `key: value` lines,
    inline lists `[a, b]` and block lists of `- item` lines.
    """
    m = re.match(r'\ufeff?---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|$)',
                 markdown, re.S)
    if not m:
        return {}, markdown

    fields, key = {}, None
    for number, line in enumerate(m.group(1).splitlines(), 2):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        item = re.fullmatch(r'\s*-\s+(.*)', line)
        pair = re.fullmatch(r'([A-Za-z][\w-]*):(?:\s+(.*))?', line.rstrip())
        if item and key and isinstance(fields[key], list):
            fields[key].append(scalar(item.group(1)))
        elif pair:
            key, value = pair.group(1).lower(), (pair.group(2) or '').strip()
            if not value:
                fields[key] = []
            elif value[0] == '[' and value[-1] == ']':
                fields[key] = [scalar(v) for v in value[1:-1].split(',') if v.strip()]
            else:
                fields[key] = scalar(value)
        else:
            sys.exit('error: line %d of the header is not `key: value`: %s'
                     % (number, line.strip()))
    return fields, markdown[m.end():]


def convert(markdown, title=None, base=Path('.')):
    """Return (title, body html) for a markdown article; base is the folder
    the article is in, which post lists are relative to."""
    defined = set(NOTE_DEF.findall(markdown))
    used = set(NOTE_REF.findall(markdown))
    for key in sorted(used - defined):
        sys.exit('error: footnote [^%s] has no definition' % key)
    for key in sorted(defined - used):
        print('warning: footnote [^%s] is defined but never used' % key, file=sys.stderr)

    doc = json.loads(pandoc(markdown, '--from=markdown', '--to=json'))
    blocks = doc['blocks']
    if blocks and blocks[0]['t'] == 'Header' and blocks[0]['c'][0] == 1:
        title = title or plain(blocks[0]['c'][2])
        blocks = blocks[1:]
    blocks = [post_list(block, base) if block['t'] == 'Div' and 'posts' in block['c'][0][1]
              else block for block in blocks]
    doc['blocks'] = Sidenotes().walk(blocks)
    doc['meta'] = {}

    body = pandoc(json.dumps(doc), '--from=json', '--to=html', '--wrap=none')
    return title, body.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('input', type=Path, nargs='+', help='markdown file')
    parser.add_argument('--title', help='page title (default: the title in '
                        'the header, a leading # heading, or the file name)')
    parser.add_argument('--css', type=Path, default=STYLESHEET,
                        help='stylesheet file (default: css/landing.css '
                        'next to this script)')
    args = parser.parse_args()

    # a page is written over <name>.html, so never take one as input
    for source in args.input:
        if source.suffix.lower() not in ('.md', '.markdown'):
            parser.error('%s is not a markdown file; pass the .md file and '
                         'the page is written next to it' % source)

    for source in args.input:
        fields, markdown = front_matter(source.read_text(encoding='utf-8'))
        title, body = convert(markdown, args.title or fields.get('title'), source.parent)
        if title is None:
            title = source.stem
        title = html.escape(title, quote=False)

        def text(key):
            value = fields.get(key, '')
            return ', '.join(value) if isinstance(value, list) else value

        fields.setdefault('description', text('tldr') or title)
        meta = ['  <meta name="%s" content="%s">' % (key, html.escape(text(key)))
                for key in fields
                if key not in ('title', 'email', 'lang', 'tldr') and text(key)]

        header = '<h1>%s</h1>' % title
        # the byline: the author, then the date below
        lines = ['<span class="%s">%s</span>' % (key, html.escape(text(key)))
                 for key in ('author', 'date') if text(key)]
        if lines:
            header += '\n<p class="byline">%s</p>' % ' '.join(lines)

        output = source.with_suffix('.html')
        # print.css, if there is one beside the stylesheet, is used for printing
        sheets = [(args.css, ''), (args.css.with_name('print.css'), ' media="print"')]
        css = '\n'.join(
            '  <link rel="stylesheet" href="%s"%s>'
            % (Path(os.path.relpath(sheet.resolve(), output.resolve().parent)).as_posix(), media)
            for sheet, media in sheets if sheet == args.css or sheet.exists())
        if ICON.exists():
            css = '  <link rel="icon" href="%s">\n%s' % (
                Path(os.path.relpath(ICON, output.resolve().parent)).as_posix(), css)
        output.write_text(PAGE.format(title=title, lang=text('lang') or 'en',
                                      meta='\n'.join(meta),
                                      css=css,
                                      body='%s\n%s' % (header, body)),
                          encoding='utf-8')
        print('wrote %s' % output)


if __name__ == '__main__':
    main()
