#!/usr/bin/env python
"""Cleaning wrapper.

Given a URL, first apply special cases.  Then try to fetch a feed of the
content, then try to directly handle the HTML.  Clean up all HTML where
appropriate.

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

import re
import urlparse

from third_party import BeautifulSoup
from third_party import hyphenate

import extract_content
import extract_feed
import util

RE_ALIGNED = re.compile(
    r'(?:_|\b)(?:align|float:\s*)?(left|right)(?:_|\b)', re.I)
RE_FEED_JUNK = re.compile(r'^https?://feed[^/]+/(~.{1,3}|1\.0)/', re.I)
RE_RELATED_HEADER = re.compile(
    r'\b(for more|related (posts?|articles?)|see also)\b', re.I)
STRIP_ATTRS = {
    'onblur': True,
    'onchange ': True,
    'onclick': True,
    'ondblclick': True,
    'onfocus': True,
    'onkeydown': True,
    'onkeypress': True,
    'onkeyup': True,
    'onload': True,
    'onmousedown': True,
    'onmousemove': True,
    'onmouseout': True,
    'onmouseover': True,
    'onmouseup': True,
    'onreset': True,
    'onselect': True,
    'onsubmit': True,
    'onunload': True,
    'style': True,
    }
if not util.IS_DEV_APPSERVER:
  STRIP_ATTRS.update({
      'class': util.IS_DEV_APPSERVER,
      'id': util.IS_DEV_APPSERVER,
      'score': util.IS_DEV_APPSERVER,
      })
STRIP_TAG_NAMES = set((
    'iframe',
    'link',
    'meta',
    'noscript',
    'script',
    'style',
    ))


def Clean(url):
  """Clean the contents of a given URL to only the "readable part".

  Handle special cases like YouTube, PDF, images directly.  Delegate out to
  either extract content from the site's feed, or parse and clean the HTML.

  Args:
    url: String, the URL to the interesting content.

  Returns:
    String: HTML representing the "readable part".
  """
  if re.search(r'^http://www\.youtube\.com/watch', url, re.I):
    video_id = url.split('v=')[1]
    return util.RenderTemplate('youtube.html', {'video_id': video_id})
  elif re.search(r'\.pdf(\?|$)', url, re.I):
    return util.RenderTemplate('pdf.html', {'url': url})
  elif re.search(r'\.(gif|jpe?g|png)(\?|$)', url, re.I):
    return util.RenderTemplate('image.html', {'url': url})

  match = re.search(r'^https?://docs.google.com.*docid=(.*?)(&|$)', url, re.I)
  if match:
    return util.RenderTemplate('google-docs.html', {'docid': match.group(1),
                                                    'url': url})

  html, final_url = util.Fetch(url)
  note = ''
  try:
    extractor = extract_feed.FeedExtractor(
        url=url, final_url=final_url, html=html)
    note = u'<!-- cleaned feed -->\n'
    soup = extractor.soup
  except extract_feed.RssError, e:
    note = u'<!-- cleaned content, %s, %s -->\n' % (e.__class__.__name__, e)
    soup = extract_content.ExtractFromHtml(url, html)

  _FixUrls(soup, final_url)
  return note + _Munge(soup)
if not util.IS_DEV_APPSERVER:
  Clean = util.Memoize('Clean_%s', 60*60*24)(Clean)  # pylint: disable-msg=C6409


def _FixUrls(parent, base_url):
  for tag in parent.findAll(href=True):
    tag['href'] = urlparse.urljoin(base_url, tag['href'])
  for tag in parent.findAll(src=True):
    tag['src'] = urlparse.urljoin(base_url, tag['src'])


def _Munge(soup):
  """Given a string of HTML content, munge it to be more pleasing."""
  # In certain failure cases, we'll still get a string.  Just use it.
  if isinstance(soup, basestring):
    return soup

  _MungeImages(soup)
  _MungeStripTags(soup)
  _MungeStripAttrs(soup)
  _MungeStripEmpties(soup)
  _MungeStripRelatedList(soup)
  _MungeHyphenate(soup)

  # Now that we've removed attributes, including style, put back clears
  # on aligned images.
  for img in soup.findAll('img', attrs={'align': True}):
    img['style'] = 'clear: both'

  # Serialize the soup, and apply full justification.
  return u"<div style='text-align: justify;'>%s</div>" % unicode(soup)


def _MungeHyphenate(soup):
  for text in soup.findAll(text=True):
    text_parts = re.split(r'(&[^;]{2,6};)', text)
    new_text = []
    for text_part in text_parts:
      if not text_part:
        continue
      if '&' == text_part[0]:
        new_text.append(text_part)
      else:
        words = re.split(r'\s+', text_part)
        words = ['&shy;'.join(hyphenate.hyphenate_word(word))
                 for word in words]
        new_text.append(' '.join(words))
    text.replaceWith(BeautifulSoup.NavigableString(''.join(new_text)))


def _MungeImages(soup):
  # For all images:
  #  * If they have a style or class that implies floating, apply alignment.
  #  * If they are at the beginning of a paragraph, with text, apply alignment.
  for img in soup.findAll('img'):
    if img.has_key('align'):
      continue

    if img.has_key('style'):
      match = RE_ALIGNED.search(img['style'])
      if match:
        img['align'] = match.group(1)
        continue

    if img.has_key('class'):
      match = RE_ALIGNED.search(img['class'])
      if match:
        img['align'] = match.group(1)
        continue

#    parent_p = img.findParent('p', limit=1)
#    if parent_p and not img.findPreviousSibling(name=True):
#      if parent_p.text or not parent_p.findPreviousSibling('p'):
#        img['align'] = 'left'


def _MungeStripAttrs(soup):
  for tag in soup.findAll(True):
    for attr in STRIP_ATTRS:
      del tag[attr]


def _MungeStripEmpties(soup):
  for tag in soup.findAll(('a', 'div', 'p', 'td', 'span')):
    if not tag.text.strip():
      if not tag.find(True):
        tag.extract()
      elif not tag.find(lambda tag: tag.name != 'br'):
        tag.extract()


def _MungeStripRelatedList(soup):
  for tag in soup.findAll(('ul', 'ol')):
    previous = tag.findPreviousSibling(True)
    if previous and RE_RELATED_HEADER.search(previous.text):
      _StripAfter(previous)
    elif tag.parent:
      parent_text = ' '.join(tag.parent.findAll(text=True))
      if RE_RELATED_HEADER.search(parent_text):
        _StripAfter(tag.parent)


def _MungeStripTags(soup):
  for tag in soup.findAll(STRIP_TAG_NAMES):
    tag.extract()

  for tag in soup.findAll(name='a', attrs={'href': RE_FEED_JUNK}):
    tag.extract()
  for tag in soup.findAll(name='img', attrs={'src': RE_FEED_JUNK}):
    tag.extract()

  extract_content.StripJunk(soup)


def _StripAfter(strip_tag):
  for tag in strip_tag.findAllNext():
    tag.extract()
  strip_tag.extract()
