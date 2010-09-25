#!/usr/bin/env python
"""Originally "Hacker News" feed rewriter by Nirmal Patel.

Now: General purpose "page cleaner".  Given the *content* of a page, at a URL,
attempts to convert it into the smallest subset of markup that contains the
entire body of important content.

--------------------------------------------------------------------------------

Readability API - Clean up pages and feeds to be readable.
Copyright (C) 2010  Anthony Lieuallen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import HTMLParser
import logging
import re
import sys

from third_party import BeautifulSoup

import patterns
import util

EMBED_NAMES = set(('embed', 'object'))
TAG_NAMES_BLOCK = set(('blockquote', 'div', 'ol', 'p', 'pre', 'td', 'th', 'ul'))
TAG_NAMES_HEADER = set(('h1', 'h2', 'h3', 'h4', 'h5', 'h6'))


def ExtractFromUrl(url):
  url = url.encode('utf-8')
  try:
    html, _ = util.Fetch(url)
    return ExtractFromHtml(url, html)
  except IOError, e:
    logging.exception(e)
    return ''


def ExtractFromHtml(url, html):
  """Given a string of HTML, remove nasty bits, score and pick bit to keep."""
  if re.search(r'^http://(www\.)?reddit\.com/.*/comments/', url, re.I):
    strainer = BeautifulSoup.SoupStrainer(
        attrs={'class': re.compile(r'thing.*link')})
    soup = BeautifulSoup.BeautifulSoup(html, parseOnlyThese=strainer)
    return unicode(soup.find(attrs={'class': 'usertext-body'}))
  else:
    return _ExtractFromHtmlGeneric(html)


def _ExtractFromHtmlGeneric(html):
  try:
    soup = BeautifulSoup.BeautifulSoup(
        util.PreCleanHtml(html),
        convertEntities=BeautifulSoup.BeautifulStoneSoup.ALL_ENTITIES)
  except HTMLParser.HTMLParseError, e:
    logging.exception(e)
    return u''

  title = soup.find('title')
  title = title and title.text.lower() or ''

  patterns.Process(soup)
  _ScoreBlocks(soup)
  _ScoreImages(soup)
  _ScoreEmbeds(soup)

  # Get the highest scored nodes.
  scored_nodes = sorted(soup.findAll(attrs={'score': True}),
                        key=lambda x: x['score'])[-15:]
  if not scored_nodes:
    return u'<p>Scoring error.</p>'
  best_node = scored_nodes[-1]

  _TransformDivsToPs(soup)

  # If a header repeats the title, strip it and all preceding nodes.
  title_header = _FindTitleHeader(best_node, title)
  if title_header:
    _StripBefore(title_header)

  # For debugging ...
  if util.IS_DEV_APPSERVER:
    # Log scored nodes.
    for node in scored_nodes:
      logging.info('%10.2f %s', node['score'], util.SoupTagOnly(node)[0:69])

  return best_node


def _FindLeafBlocks(soup):
  for tag in soup.findAll(name=True, recursive=False):
    if tag.name in TAG_NAMES_BLOCK and not tag.find(name=TAG_NAMES_BLOCK):
      yield tag
    else:
      for child in _FindLeafBlocks(tag):
        yield child


def _FindTitleHeader(soup, title_text):
  headers = soup.findAll(TAG_NAMES_HEADER)
  for header in headers:
    header_text = header.text.lower()
    if len(header_text) < 10:
      continue  # avoid false positives thanks to short/empty headers
    if (title_text in header_text) or (header_text in title_text):
      return header


def _ScoreBlocks(soup):
  """Score up all leaf block nodes, based on the length of their text."""
  for leaf_block in _FindLeafBlocks(soup):
    # Length of stripped text, with all whitespace collapsed.
    block_text = leaf_block.text.strip()
    block_text = re.sub(r'[ \t]+', ' ', block_text)
    block_text = re.sub(r'&[^;]{2,6};', '', block_text)
    text_len = len(block_text)

    if text_len == 0:
      continue
    if (text_len < 20) and (leaf_block.name not in TAG_NAMES_HEADER):
      util.ApplyScore(leaf_block, -1.5, name='short_text')
    if text_len > 75:
      util.ApplyScore(leaf_block, 6, name='some_text')
    if text_len > 250:
      util.ApplyScore(leaf_block, 8, name='more_text')


def _ScoreEmbeds(soup):
  """Score up objects/embeds."""
  for tag in soup.findAll(EMBED_NAMES):
    if tag.findParent(EMBED_NAMES):
      continue
    util.ApplyScore(tag, 15, name='has_embed')


def _ScoreImages(soup):
  """Score up images."""
  for tag in soup.findAll('img'):
    util.ApplyScore(tag, 1, name='any_img')
    if tag.has_key('alt'):
      util.ApplyScore(tag, 3, name='img_alt')

    if not tag.has_key('width') or not tag.has_key('height'):
      continue
    try:
      size = int(tag['width']) * int(tag['height'])
    except ValueError:
      continue

    if size == 1:
      util.ApplyScore(tag, -3, name='tiny_img')
    if size >= 125000:
      util.ApplyScore(tag, 5, name='has_img')
    if size >= 500000:
      util.ApplyScore(tag, 10, name='big_img')


def _StripBefore(strip_tag):
  ancestors = strip_tag.findParents(True)
  for tag in strip_tag.findAllPrevious():
    if tag in ancestors:
      # Don't strip the tags that contain the strip_tag.
      continue
    tag.extract()
  strip_tag.extract()


def _TransformDivsToPs(soup):
  for tag in soup.findAll('div'):
    if not tag.find(TAG_NAMES_BLOCK):
      tag.name = 'p'


if __name__ == '__main__':
  # For debugging, assume file on command line.
  print ExtractFromHtml('http://www.example.com', open(sys.argv[1]).read())
