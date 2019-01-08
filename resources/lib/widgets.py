#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import urllib

from .plex_api import API
from .plex_db import PlexDB
from . import json_rpc as js
from . import utils, variables as v

###############################################################################
LOG = getLogger('PLEX.widgets')

###############################################################################


def xml_to_dict(xml_element, section_id=None, metadatautils=None,
                append_show_title=False, append_sxxexx=False):
    """
    Meant to be consumed by metadatautils.kodidb.prepare_listitem, and then
    metadatautils.kodidb.create_listitem

    Do NOT set resumetime - otherwise Kodi always resumes at that time
    even if the user chose to start element from the beginning
    listitem.setProperty('resumetime', str(userdata['Resume']))

    The key 'file' needs to be set later with the item's path
    """
    try:
        api = API(xml_element)
        plex_type = api.plex_type()
        kodi_type = v.KODITYPE_FROM_PLEXTYPE[plex_type]
        with PlexDB() as plexdb:
            db_item = plexdb.item_by_id(api.plex_id(), plex_type)
        item = {}
        if db_item:
            item = js.item_details(db_item['kodi_id'], kodi_type)
            LOG.error('json item for %s is: %s', kodi_type, item)
        _, _, tvshowtitle, season_no, episode_no = api.episode_data()
        userdata = api.userdata()
        if not item:
            people = api.people()
            cast = [{
                'name': x[0],
                'thumbnail': x[1],
                'role': x[2],
                'order': x[3],
            } for x in api.people_list()['actor']]
            item = {
                'cast': cast,
                'country': api.country_list(),
                'dateadded': api.date_created(),  # e.g '2019-01-03 19:40:59'
                'director': people['Director'],  # list of [str]
                'duration': userdata['Runtime'],
                'episode': episode_no,
                'extraproperties': {},
                'file': '',  # e.g. 'videodb://tvshows/titles/20'
                'genre': api.genre_list(),
                'imdbnumber': '',  # e.g.'341663'
                'label': api.title(),  # e.g. '1x05. Category 55 Emergency Doomsday Crisis'
                'lastplayed': userdata['LastPlayedDate'],  # e.g. '2019-01-04 16:05:03'
                'mpaa': api.content_rating(),  # e.g. 'TV-MA'
                'originaltitle': '',  # e.g. 'Titans (2018)'
                'playcount': userdata['PlayCount'],  # [int]
                'plot': api.plot(),  # [str]
                'plotoutline': api.tagline(),
                'premiered': api.premiere_date(),  # '2018-10-12'
                'rating': api.audience_rating(),  # [float]
                'season': season_no,
                'sorttitle': api.sorttitle(),  # 'Titans (2018)'
                'studio': api.music_studio_list(),  # e.g. 'DC Universe'
                'tag': [],  # List of tags this item belongs to
                'tagline': api.tagline(),
                'thumbnail': '',  # e.g. 'image://https%3a%2f%2fassets.tv'
                'title': api.title(),  # 'Titans (2018)'
                'type': kodi_type,
                'trailer': api.trailer(),
                'tvshowtitle': tvshowtitle,
                'uniqueid': {'imdbnumber': api.provider('imdb') or '',
                             'tvdb_id': api.provider('tvdb') or ''},
                'votes': '0',  # [str]!
                'writer': people['Writer'],  # list of [str]
                'year': api.year(),  # [int]
            }

            if plex_type in (v.PLEX_TYPE_EPISODE, v.PLEX_TYPE_SEASON, v.PLEX_TYPE_SHOW):
                leaves = api.leave_count()
                if leaves:
                    item['extraproperties'] = leaves
            if db_item:
                item['%sid' % kodi_type] = db_item['kodi_id']
            # Add all the artwork we can
            item['art'] = api.artwork()
            # Add all info for e.g. video and audio streams
            item['streamdetails'] = api.mediastreams()
            # Cleanup required due to the way metadatautils works
            if not item['lastplayed']:
                del item['lastplayed']
            for stream in item['streamdetails']['video']:
                stream['height'] = utils.cast(int, stream['height'])
                stream['width'] = utils.cast(int, stream['width'])
                stream['aspect'] = utils.cast(float, stream['aspect'])
            item['streamdetails']['subtitle'] = [{'language': x} for x in item['streamdetails']['subtitle']]

        item['icon'] = v.ICON_FROM_PLEXTYPE[plex_type]
        # Some customization
        if plex_type not in (v.PLEX_TYPE_MOVIE,
                             v.PLEX_TYPE_EPISODE,
                             v.PLEX_TYPE_SONG,
                             v.PLEX_TYPE_CLIP):
            # item is not playable but a folder
            # 'isPlayable' will be set automatically
            item['isFolder'] = True
        if plex_type == v.PLEX_TYPE_EPISODE:
            # Prefix to the episode's title/label
            if season_no is not None and episode_no is not None:
                if append_sxxexx is True:
                    item['label'] = "S%.2dE%.2d - %s" % (season_no, episode_no, item['label'])
            if append_show_title is True:
                item['label'] = "%s - %s " % (tvshowtitle, item['label'])

        # Determine the path for this item
        if xml_element.tag == 'Directory':
            key = xml_element.get('fastKey', xml_element.get('key'))
            if not key.startswith('/'):
                key = '/library/sections/%s/%s' % (section_id, key)
            params = {
                'mode': "browseplex",
                'key': key,
                'plex_type': plex_type
            }
            if section_id:
                params['id'] = section_id
            url = api.directory_path(section_id=section_id)
        else:
            # Playable videos, clips, streams and songs
            resume = api.resume_point()
            if resume:
                item['resume'] = {
                    'position': resume,
                    'total': userdata['Runtime']
                }
            if (api.path_and_plex_id().startswith('/system/services') or
                    api.path_and_plex_id().startswith('http')):
                params = {
                    'mode': 'plex_node',
                    'key': xml_element.attrib.get('key'),
                    'offset': xml_element.attrib.get('viewOffset', '0'),
                }
                url = "plugin://%s?%s" % (v.ADDON_ID, urllib.urlencode(params))
            elif api.plex_type() == v.PLEX_TYPE_PHOTO:
                url = api.get_picture_path()
            else:
                url = api.path()
        item['file'] = url
        LOG.debug('item is: %s', item)
        return item
    except Exception:
        utils.ERROR(notify=True)
        LOG.error('xml_element: %s', xml_element.attrib)


def create_main_entry(item):
    '''helper to create a simple (directory) listitem'''
    return {
        'title': item[0],
        'label': item[0],
        'file': item[1],
        'icon': item[2],
        'art': {
            'thumb': 'special://home/addons/%s/icon.png' % v.ADDON_ID,
            'fanart': 'special://home/addons/%s/fanart.jpg' % v.ADDON_ID},
        'isFolder': True,
        'type': '',
        'IsPlayable': 'false'
    }
