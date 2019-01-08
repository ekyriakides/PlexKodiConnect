#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import sys
from urllib import urlencode

import xbmcplugin
from xbmc import sleep
from xbmcgui import ListItem
from metadatautils import MetadataUtils

from . import utils
from . import path_ops
from .downloadutils import DownloadUtils as DU
from .plex_api import API
from .plex_db import PlexDB
from . import plex_functions as PF
from . import json_rpc as js
from . import variables as v
# Be careful - your using app in another Python instance!
from . import app, widgets

###############################################################################
LOG = getLogger('PLEX.entrypoint')

###############################################################################


def choose_pms_server():
    """
    Lets user choose from list of PMS
    """
    LOG.info("Choosing PMS server requested, starting")
    utils.plex_command('choose_pms_server')


def toggle_plex_tv_sign_in():
    """
    Signs out of Plex.tv if there was a token saved and thus deletes the token.
    Or signs in to plex.tv if the user was not logged in before.
    """
    LOG.info('Toggle of Plex.tv sign-in requested')
    utils.plex_command('toggle_plex_tv_sign_in')


def directory_item(label, path, folder=True):
    """
    Adds a xbmcplugin.addDirectoryItem() directory itemlistitem
    """
    listitem = ListItem(label, path=path)
    listitem.setThumbnailImage(
        "special://home/addons/plugin.video.plexkodiconnect/icon.png")
    listitem.setArt(
        {"fanart": "special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    listitem.setArt(
        {"landscape":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                url=path,
                                listitem=listitem,
                                isFolder=folder)


def show_main_menu(content_type=None):
    """
    Shows the main PKC menu listing with all libraries, Channel, settings, etc.
    """
    LOG.debug('Do main listing with content_type: %s', content_type)
    xbmcplugin.setContent(int(sys.argv[1]), 'files')
    # Get emby nodes from the window props
    plexprops = utils.window('Plex.nodes.total')
    if plexprops:
        totalnodes = int(plexprops)
        for i in range(totalnodes):
            path = utils.window('Plex.nodes.%s.index' % i)
            if not path:
                path = utils.window('Plex.nodes.%s.content' % i)
                if not path:
                    continue
            label = utils.window('Plex.nodes.%s.title' % i)
            node_type = utils.window('Plex.nodes.%s.type' % i)
            # because we do not use seperate entrypoints for each content type,
            # we need to figure out which items to show in each listing. for
            # now we just only show picture nodes in the picture library video
            # nodes in the video library and all nodes in any other window
            if node_type == 'photos' and content_type == 'image':
                directory_item(label, path)
            elif node_type == 'albums' and content_type == 'audio':
                directory_item(label, path)
            elif node_type in ('movies',
                               'tvshows',
                               'homevideos',
                               'musicvideos') and content_type == 'video':
                directory_item(label, path)
    # Playlists
    if content_type != 'image':
        directory_item(utils.lang(136),
                       ('plugin://%s?mode=playlists&content_type=%s'
                        % (v.ADDON_ID, content_type)))
    # Plex Hub
    directory_item('Plex Hub',
                   'plugin://%s?mode=hub&type=%s' % (v.ADDON_ID, content_type))
    # Plex Watch later
    if content_type not in ('image', 'audio'):
        directory_item(utils.lang(39211),
                       "plugin://%s?mode=watchlater" % v.ADDON_ID)
    # Plex Channels
    directory_item(utils.lang(30173), "plugin://%s?mode=channels" % v.ADDON_ID)
    # Plex user switch
    directory_item('%s%s' % (utils.lang(39200), utils.settings('username')),
                   "plugin://%s?mode=switchuser" % v.ADDON_ID)

    # some extra entries for settings and stuff
    directory_item(utils.lang(39201), "plugin://%s?mode=settings" % v.ADDON_ID)
    directory_item(utils.lang(39204),
                   "plugin://%s?mode=manualsync" % v.ADDON_ID)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def show_listing(xml, plex_type=None):
    """
    """
    LOG.debug('show_listing plex_type: %s: %s', plex_type, xml)
    if plex_type:
        xbmcplugin.setContent(int(sys.argv[1]),
                              v.MEDIATYPE_FROM_PLEX_TYPE[plex_type])
    else:
        xbmcplugin.setContent(int(sys.argv[1]), 'files')

    metadatautils = MetadataUtils()
    all_items = utils.process_method_on_list(widgets.xml_to_dict,
                                             xml)
    all_items = utils.process_method_on_list(metadatautils.kodidb.prepare_listitem,
                                             all_items)
    # fill that listing...
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED)
    all_items = utils.process_method_on_list(
        metadatautils.kodidb.create_listitem, all_items)
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), all_items, len(all_items))
    # end directory listing
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def switch_plex_user():
    """
    Signs out currently logged in user (if applicable). Triggers sign-in of a
    new user
    """
    # Guess these user avatars are a future feature. Skipping for now
    # Delete any userimages. Since there's always only 1 user: position = 0
    # position = 0
    # utils.window('EmbyAdditionalUserImage.%s' % position, clear=True)
    LOG.info("Plex home user switch requested")
    utils.plex_command('switch_plex_user')


def create_listitem(item, append_show_title=False, append_sxxexx=False):
    """
    Feed with a Kodi json item response to get a xbmcgui.ListItem() with
    everything set and ready.
    """
    title = item['title']
    listitem = ListItem(title)
    listitem.setProperty('IsPlayable', 'true')
    metadata = {
        'duration': str(item['runtime'] / 60),
        'Plot': item['plot'],
        'Playcount': item['playcount']
    }
    if 'episode' in item:
        episode = item['episode']
        metadata['Episode'] = episode
    if 'season' in item:
        season = item['season']
        metadata['Season'] = season
    if season and episode:
        listitem.setProperty('episodeno', 's%.2de%.2d' % (season, episode))
        if append_sxxexx is True:
            title = 'S%.2dE%.2d - %s' % (season, episode, title)
    if 'firstaired' in item:
        metadata['Premiered'] = item['firstaired']
    if 'showtitle' in item:
        metadata['TVshowTitle'] = item['showtitle']
        if append_show_title is True:
            title = item['showtitle'] + ' - ' + title
    if 'rating' in item:
        metadata['Rating'] = str(round(float(item['rating']), 1))
    if 'director' in item:
        metadata['Director'] = item['director']
    if 'writer' in item:
        metadata['Writer'] = item['writer']
    if 'cast' in item:
        cast = []
        castandrole = []
        for person in item['cast']:
            name = person['name']
            cast.append(name)
            castandrole.append((name, person['role']))
        metadata['Cast'] = cast
        metadata['CastAndRole'] = castandrole

    metadata['Title'] = title
    metadata['mediatype'] = 'episode'
    metadata['dbid'] = str(item['episodeid'])
    listitem.setLabel(title)
    listitem.setInfo(type='Video', infoLabels=metadata)

    listitem.setProperty('resumetime', str(item['resume']['position']))
    listitem.setProperty('totaltime', str(item['resume']['total']))
    listitem.setArt(item['art'])
    listitem.setThumbnailImage(item['art'].get('thumb', ''))
    listitem.setArt({'icon': 'DefaultTVShows.png'})
    listitem.setProperty('fanart_image', item['art'].get('tvshow.fanart', ''))
    try:
        listitem.addContextMenuItems([(utils.lang(30032),
                                       'XBMC.Action(Info)',)])
    except TypeError:
        # Kodi fuck-up
        pass
    for key, value in item['streamdetails'].iteritems():
        for stream in value:
            listitem.addStreamInfo(key, stream)
    return listitem


def next_up_episodes(tagname, limit):
    """
    List the next up episodes for tagname.
    """
    count = 0
    # if the addon is called with nextup parameter,
    # we return the nextepisodes list of the given tagname
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
    # First we get a list of all the TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]},
        'properties': ['title', 'studio', 'mpaa', 'file', 'art']
    }
    for item in js.get_tv_shows(params):
        if utils.settings('ignoreSpecialsNextEpisodes') == "true":
            params = {
                'tvshowid': item['tvshowid'],
                'sort': {'method': "episode"},
                'filter': {
                    'and': [
                        {'operator': "lessthan",
                         'field': "playcount",
                         'value': "1"},
                        {'operator': "greaterthan",
                         'field': "season",
                         'value': "0"}]},
                'properties': [
                    "title", "playcount", "season", "episode", "showtitle",
                    "plot", "file", "rating", "resume", "tvshowid", "art",
                    "streamdetails", "firstaired", "runtime", "writer",
                    "dateadded", "lastplayed"
                ],
                'limits': {"end": 1}
            }
        else:
            params = {
                'tvshowid': item['tvshowid'],
                'sort': {'method': "episode"},
                'filter': {
                    'operator': "lessthan",
                    'field': "playcount",
                    'value': "1"},
                'properties': [
                    "title", "playcount", "season", "episode", "showtitle",
                    "plot", "file", "rating", "resume", "tvshowid", "art",
                    "streamdetails", "firstaired", "runtime", "writer",
                    "dateadded", "lastplayed"
                ],
                'limits': {"end": 1}
            }
        for episode in js.get_episodes(params):
            LOG.error('episode: %s', episode)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                        url=episode['file'],
                                        listitem=create_listitem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def in_progress_episodes(tagname, limit):
    """
    List the episodes that are in progress for tagname
    """
    count = 0
    # if the addon is called with inprogressepisodes parameter,
    # we return the inprogressepisodes list of the given tagname
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
    # First we get a list of all the in-progress TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]},
        'properties': ['title', 'studio', 'mpaa', 'file', 'art']
    }
    for item in js.get_tv_shows(params):
        params = {
            'tvshowid': item['tvshowid'],
            'sort': {'method': "episode"},
            'filter': {
                'operator': "true",
                'field': "inprogress",
                'value': ""},
            'properties': ["title", "playcount", "season", "episode",
                           "showtitle", "plot", "file", "rating", "resume",
                           "tvshowid", "art", "cast", "streamdetails",
                           "firstaired", "runtime", "writer", "dateadded",
                           "lastplayed"]
        }
        for episode in js.get_episodes(params):
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                        url=episode['file'],
                                        listitem=create_listitem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def recent_episodes(mediatype, tagname, limit):
    """
    List the recently added episodes for tagname
    """
    count = 0
    # if the addon is called with recentepisodes parameter,
    # we return the recentepisodes list of the given tagname
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
    append_show_title = utils.settings('RecentTvAppendShow') == 'true'
    append_sxxexx = utils.settings('RecentTvAppendSeason') == 'true'
    # First we get a list of all the TV shows - filtered by tag
    show_ids = set()
    params = {
        'sort': {'order': "descending", 'method': "dateadded"},
        'filter': {'operator': "is", 'field': "tag", 'value': "%s" % tagname},
    }
    for tv_show in js.get_tv_shows(params):
        show_ids.add(tv_show['tvshowid'])
    params = {
        'sort': {'order': "descending", 'method': "dateadded"},
        'properties': ["title", "playcount", "season", "episode", "showtitle",
            "plot", "file", "rating", "resume", "tvshowid", "art",
            "streamdetails", "firstaired", "runtime", "cast", "writer",
            "dateadded", "lastplayed"],
        "limits": {"end": limit}
    }
    if utils.settings('TVShowWatched') == 'false':
        params['filter'] = {
            'operator': "lessthan",
            'field': "playcount",
            'value': "1"
        }
    for episode in js.get_episodes(params):
        LOG.debug('episode is: %s', episode)
        if episode['tvshowid'] in show_ids:
            listitem = create_listitem(episode,
                                       append_show_title=append_show_title,
                                       append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                        url=episode['file'],
                                        listitem=listitem)
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def get_video_files(plex_id, params):
    """
    GET VIDEO EXTRAS FOR LISTITEM

    returns the video files for the item as plugin listing, can be used for
    browsing the actual files or videoextras etc.
    """
    if plex_id is None:
        filename = params.get('filename')
        if filename is not None:
            filename = filename[0]
            import re
            regex = re.compile(r'''library/metadata/(\d+)''')
            filename = regex.findall(filename)
            try:
                plex_id = filename[0]
            except IndexError:
                pass

    if plex_id is None:
        LOG.info('No Plex ID found, abort getting Extras')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]))
    app.init(entrypoint=True)
    item = PF.GetPlexMetadata(plex_id)
    try:
        path = utils.try_decode(item[0][0][0].attrib['file'])
    except (TypeError, IndexError, AttributeError, KeyError):
        LOG.error('Could not get file path for item %s', plex_id)
        return xbmcplugin.endOfDirectory(int(sys.argv[1]))
    # Assign network protocol
    if path.startswith('\\\\'):
        path = path.replace('\\\\', 'smb://')
        path = path.replace('\\', '/')
    # Plex returns Windows paths as e.g. 'c:\slfkjelf\slfje\file.mkv'
    elif '\\' in path:
        path = path.replace('\\', '\\\\')
    # Directory only, get rid of filename
    path = path.replace(path_ops.path.basename(path), '')
    if path_ops.exists(path):
        for root, dirs, files in path_ops.walk(path):
            for directory in dirs:
                item_path = utils.try_encode(path_ops.path.join(root,
                                                                directory))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                            url=item_path,
                                            listitem=listitem,
                                            isFolder=True)
            for file in files:
                item_path = utils.try_encode(path_ops.path.join(root, file))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                            url=file,
                                            listitem=listitem)
            break
    else:
        LOG.error('Kodi cannot access folder %s', path)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


@utils.catch_exceptions(warnuser=False)
def extra_fanart(plex_id, plex_path):
    """
    Get extrafanart for listitem
    will be called by skinhelper script to get the extrafanart
    for tvshows we get the plex_id just from the path
    """
    LOG.debug('Called with plex_id: %s, plex_path: %s', plex_id, plex_path)
    if not plex_id:
        if "plugin.video.plexkodiconnect" in plex_path:
            plex_id = plex_path.split("/")[-2]
    if not plex_id:
        LOG.error('Could not get a plex_id, aborting')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]))

    # We need to store the images locally for this to work
    # because of the caching system in xbmc
    fanart_dir = path_ops.translate_path("special://thumbnails/plex/%s/"
                                         % plex_id)
    if not path_ops.exists(fanart_dir):
        # Download the images to the cache directory
        path_ops.makedirs(fanart_dir)
        app.init(entrypoint=True)
        xml = PF.GetPlexMetadata(plex_id)
        if xml is None:
            LOG.error('Could not download metadata for %s', plex_id)
            return xbmcplugin.endOfDirectory(int(sys.argv[1]))

        api = API(xml[0])
        backdrops = api.artwork()['Backdrop']
        for count, backdrop in enumerate(backdrops):
            # Same ordering as in artwork
            art_file = utils.try_encode(path_ops.path.join(
                fanart_dir, "fanart%.3d.jpg" % count))
            listitem = ListItem("%.3d" % count, path=art_file)
            xbmcplugin.addDirectoryItem(
                handle=int(sys.argv[1]),
                url=art_file,
                listitem=listitem)
            path_ops.copyfile(backdrop, utils.try_decode(art_file))
    else:
        LOG.info("Found cached backdrop.")
        # Use existing cached images
        fanart_dir = utils.try_decode(fanart_dir)
        for root, _, files in path_ops.walk(fanart_dir):
            root = utils.decode_path(root)
            for file in files:
                file = utils.decode_path(file)
                art_file = utils.try_encode(path_ops.path.join(root, file))
                listitem = ListItem(file, path=art_file)
                xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                            url=art_file,
                                            listitem=listitem)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def _wait_for_auth():
    """
    Call to be sure that PKC is authenticated, e.g. for widgets on Kodi
    startup. Will wait for at most 30s, then fail if not authenticated.

    Will set xbmcplugin.endOfDirectory(int(sys.argv[1]), False) if failed
    """
    counter = 0
    while utils.window('plex_authenticated') != 'true':
        counter += 1
        if counter == 300:
            LOG.error('Aborting view, we were not authenticated for PMS')
            xbmcplugin.endOfDirectory(int(sys.argv[1]), False)
            return False
        sleep(100)
    return True


def on_deck_episodes(viewid, tagname, limit):
    """
    Retrieves Plex On Deck items, currently only for TV shows

    Input:
        viewid:             Plex id of the library section, e.g. '1'
        tagname:            Name of the Plex library, e.g. "My Movies"
        limit:              Max. number of items to retrieve, e.g. 50
    """
    xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
    append_show_title = utils.settings('OnDeckTvAppendShow') == 'true'
    append_sxxexx = utils.settings('OnDeckTvAppendSeason') == 'true'
    if utils.settings('OnDeckTVextended') == 'false':
        # Chances are that this view is used on Kodi startup
        # Wait till we've connected to a PMS. At most 30s
        if not _wait_for_auth():
            return
        # We're using another python instance - need to load some vars
        app.init(entrypoint=True)
        xml = DU().downloadUrl('{server}/library/sections/%s/onDeck' % viewid)
        if xml in (None, 401):
            LOG.error('Could not download PMS xml for view %s', viewid)
            xbmcplugin.endOfDirectory(int(sys.argv[1]), False)
            return
        counter = 0
        for item in xml:
            api = API(item)
            listitem = api.create_listitem(
                append_show_title=append_show_title,
                append_sxxexx=append_sxxexx)
            if api.resume_point():
                listitem.setProperty('resumetime', str(api.resume_point()))
            path = api.path(force_first_media=True)
            xbmcplugin.addDirectoryItem(
                handle=int(sys.argv[1]),
                url=path,
                listitem=listitem)
            counter += 1
            if counter == limit:
                break
        xbmcplugin.endOfDirectory(
            handle=int(sys.argv[1]),
            cacheToDisc=utils.settings('enableTextureCache') == 'true')
        return

    # if the addon is called with nextup parameter,
    # we return the nextepisodes list of the given tagname
    # First we get a list of all the TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]}
    }
    items = js.get_tv_shows(params)
    if not items:
        # Now items retrieved - empty directory
        xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))
        return

    params = {
        'sort': {'method': "episode"},
        'limits': {"end": 1},
        'properties': [
            "title", "playcount", "season", "episode", "showtitle",
            "plot", "file", "rating", "resume", "tvshowid", "art",
            "streamdetails", "firstaired", "runtime", "cast", "writer",
            "dateadded", "lastplayed"
        ],
    }
    if utils.settings('ignoreSpecialsNextEpisodes') == "true":
        params['filter'] = {
            'and': [
                {'operator': "lessthan", 'field': "playcount", 'value': "1"},
                {'operator': "greaterthan", 'field': "season", 'value': "0"}
            ]
        }
    else:
        params['filter'] = {
            'or': [
                {'operator': "lessthan", 'field': "playcount", 'value': "1"},
                {'operator': "true", 'field': "inprogress", 'value': ""}
            ]
        }

    # Are there any episodes still in progress/not yet finished watching?!?
    # Then we should show this episode, NOT the "next up"
    inprog_params = {
        'sort': {'method': "episode"},
        'filter': {'operator': "true", 'field': "inprogress", 'value': ""},
        'properties': params['properties']
    }

    count = 0
    for item in items:
        inprog_params['tvshowid'] = item['tvshowid']
        episodes = js.get_episodes(inprog_params)
        if not episodes:
            # No, there are no episodes not yet finished. Get "next up"
            params['tvshowid'] = item['tvshowid']
            episodes = js.get_episodes(params)
            if not episodes:
                # Also no episodes currently coming up
                continue
        for episode in episodes:
            # There will always be only 1 episode ('limit=1')
            listitem = create_listitem(episode,
                                       append_show_title=append_show_title,
                                       append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                        url=episode['file'],
                                        listitem=listitem,
                                        isFolder=False)
        count += 1
        if count >= limit:
            break
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def playlists(content_type):
    """
    Lists all Plex playlists of the media type plex_playlist_type
    content_type: 'audio', 'video'
    """
    LOG.debug('Listing Plex %s playlists', content_type)
    if not _wait_for_auth():
        return
    xbmcplugin.setContent(int(sys.argv[1]), 'files')
    app.init(entrypoint=True)
    from .playlists.pms import all_playlists
    xml = all_playlists()
    if xml is None:
        return
    for item in xml:
        api = API(item)
        if not api.playlist_type() == content_type:
            continue
        listitem = ListItem(api.title())
        listitem.setArt({'thumb': api.one_artwork('composite')})
        url = "plugin://%s/" % v.ADDON_ID
        key = api.path_and_plex_id()
        params = {
            'mode': "browseplex",
            'key': key,
        }
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                    url="%s?%s" % (url, urlencode(params)),
                                    isFolder=True,
                                    listitem=listitem)
    xbmcplugin.endOfDirectory(
        handle=int(sys.argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def hub(content_type):
    """
    Plus hub endpoint pms:port/hubs. Need to separate Kodi types with
    content_type:
        audio, video, image
    """
    LOG.debug('Showing Plex Hub entries')
    app.init(entrypoint=True)
    # recent_episodes('episode', 'TV Shows', 5)
    xml = PF.get_plex_hub()
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not get Plex hub listing')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]), False)

    # We need to make sure that only entries that WORK are displayed
    all_items = []
    for entry in xml:
        api = API(entry)
        append = False
        if content_type == 'video' and api.plex_type() in v.PLEX_VIDEOTYPES:
            append = True
        elif content_type == 'audio' and api.plex_type() in v.PLEX_AUDIOTYPES:
            append = True
        elif content_type == 'image' and api.plex_type() == v.PLEX_TYPE_PHOTO:
            append = True
        elif content_type not in ('video', 'audio', 'image'):
            # Needed for widgets, where no content_type is provided
            append = True
        if append:
            all_items.append((api.title(),
                              api.directory_path(),
                              v.ICON_FROM_PLEXTYPE[api.plex_type()]))
    xbmcplugin.setContent(int(sys.argv[1]), 'files')
    metadatautils = MetadataUtils()
    LOG.debug('all_items: %s', all_items)
    all_items = utils.process_method_on_list(widgets.create_main_entry, all_items)
    all_items = utils.process_method_on_list(
        metadatautils.kodidb.prepare_listitem, all_items)
    # fill that listing...
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED)
    all_items = utils.process_method_on_list(
        metadatautils.kodidb.create_listitem, all_items)
    xbmcplugin.addDirectoryItems(int(sys.argv[1]), all_items, len(all_items))
    # end directory listing
    xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))


def watchlater():
    """
    Listing for plex.tv Watch Later section (if signed in to plex.tv)
    """
    if utils.window('plex_token') == '':
        LOG.error('No watch later - not signed in to plex.tv')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]), False)
    if utils.window('plex_restricteduser') == 'true':
        LOG.error('No watch later - restricted user')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]), False)

    app.init(entrypoint=True)
    xml = DU().downloadUrl('https://plex.tv/pms/playlists/queue/all',
                           authenticate=False,
                           headerOptions={'X-Plex-Token': utils.window('plex_token')})
    if xml in (None, 401):
        LOG.error('Could not download watch later list from plex.tv')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]), False)

    LOG.info('Displaying watch later plex.tv items')
    xbmcplugin.setContent(int(sys.argv[1]), 'movies')
    direct_paths = utils.settings('useDirectPaths') == '1'
    for item in xml:
        __build_item(item, direct_paths)
    xbmcplugin.endOfDirectory(
        handle=int(sys.argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def channels():
    """
    Listing for Plex Channels
    """
    app.init(entrypoint=True)
    xml = DU().downloadUrl('{server}/channels/all')
    try:
        xml[0].attrib
    except (ValueError, AttributeError, IndexError, TypeError):
        LOG.error('Could not download Plex Channels')
        return xbmcplugin.endOfDirectory(int(sys.argv[1]), False)

    LOG.info('Displaying Plex Channels')
    xbmcplugin.setContent(int(sys.argv[1]), 'files')
    for method in v.SORT_METHODS_DIRECTORY:
        xbmcplugin.addSortMethod(int(sys.argv[1]), getattr(xbmcplugin, method))
    for item in xml:
        __build_folder(item)
    xbmcplugin.endOfDirectory(
        handle=int(sys.argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def browse_plex(key=None, plex_type=None, plex_section_id=None):
    """
    Lists the content of a Plex folder, e.g. channels. Either pass in key (to
    be used directly for PMS url {server}<key>) or the plex_section_id
    """
    LOG.debug('Browsing to key %s, section %s, plex_type: %s',
              key, plex_section_id, plex_type)
    app.init(entrypoint=True)
    if key:
        xml = DU().downloadUrl('{server}%s' % key)
    else:
        xml = PF.GetPlexSectionResults(plex_section_id)
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not browse to key %s, section %s',
                  key, plex_section_id)
    show_listing(xml, plex_type)


def __build_folder(xml_element, plex_section_id=None):
    api = API(xml_element)
    key = xml_element.get('fastKey', xml_element.get('key'))
    if not key.startswith('/'):
        key = '/library/sections/%s/%s' % (plex_section_id, key)
    params = {
        'mode': 'browseplex',
        'key': key,
    }
    if plex_section_id:
        params['id'] = plex_section_id
    url = 'plugin://%s/?%s' % (v.ADDON_ID, urlencode(params))
    listitem = ListItem(label=xml_element.get('title'),
                        label2=None,
                        path=url)
    kodi_type = v.KODITYPE_FROM_PLEXTYPE[api.plex_type()]
    if kodi_type in (v.KODI_TYPE_SONG, v.KODI_TYPE_ALBUM, v.KODI_TYPE_ARTIST):
        nodetype = 'Music'
    else:
        nodetype = 'Video'
    infolabels = {
        'title': api.title(),
        # 'icon': item[2],
        'mediatype': kodi_type,
        'type': kodi_type,
        # 'art': api.artwork(),
    }
    extras = {
        'IsPlayable': 'false',
        'dbtype': kodi_type,
        'DBTYPE': kodi_type,
        'type': kodi_type,
        'path': url
    }
    with PlexDB() as plexdb:
        entry = plexdb.item_by_id(api.plex_id(), plex_type=api.plex_type())
    if entry:
        infolabels['dbid'] = entry['kodi_id']
        extras['DBID'] = unicode(entry['kodi_id'])
    overlay = api.unseen_leaves()
    if overlay:
        infolabels['overlay'] = unicode(overlay)
        extras['UnWatchedEpisodes'] = unicode(overlay)
    for key, value in extras.iteritems():
        listitem.setProperty(key, value)
    LOG.debug('infolabels: %s', infolabels)
    # 'extraproperties': {}
    listitem.setInfo(type=nodetype, infoLabels=infolabels)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                url=url,
                                isFolder=True,
                                listitem=listitem)


def __build_item(xml_element, direct_paths):
    api = API(xml_element)
    listitem = api.create_listitem()
    resume = api.resume_point()
    if resume:
        listitem.setProperty('resumetime', str(resume))
    if (api.path_and_plex_id().startswith('/system/services') or
            api.path_and_plex_id().startswith('http')):
        params = {
            'mode': 'plex_node',
            'key': xml_element.attrib.get('key'),
            'offset': xml_element.attrib.get('viewOffset', '0'),
        }
        url = "plugin://%s?%s" % (v.ADDON_ID, urlencode(params))
    elif api.plex_type() == v.PLEX_TYPE_PHOTO:
        url = api.get_picture_path()
    else:
        url = api.path(direct_paths=direct_paths)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                url=url,
                                listitem=listitem)


def extras(plex_id):
    """
    Lists all extras for plex_id
    """
    xbmcplugin.setContent(int(sys.argv[1]), 'movies')
    app.init(entrypoint=True)
    xml = PF.GetPlexMetadata(plex_id)
    try:
        xml[0].attrib
    except (TypeError, IndexError, KeyError):
        xbmcplugin.endOfDirectory(int(sys.argv[1]))
        return
    for item in API(xml[0]).extras():
        api = API(item)
        listitem = api.create_listitem()
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]),
                                    url=api.path(),
                                    listitem=listitem)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))


def create_new_pms():
    """
    Opens dialogs for the user the plug in the PMS details
    """
    LOG.info('Request to manually enter new PMS address')
    utils.plex_command('enter_new_pms_address')
