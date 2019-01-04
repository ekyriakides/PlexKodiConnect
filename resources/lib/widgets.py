#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import sys
import random
import urlparse
try:
    from multiprocessing.pool import ThreadPool
    SUPPORTS_POOL = True
except Exception:
    SUPPORTS_POOL = False

import xbmcplugin
import xbmcaddon
import xbmc
import xbmcgui
from metadatautils import MetadataUtils

###############################################################################
LOG = getLogger('PLEX.widgets')

ADDON_ID = 'plugin.video.plexkodiconnect'
ADDON = xbmcaddon.Addon(ADDON_ID)

###############################################################################


def create_main_entry(item):
    '''helper to create a simple (directory) listitem'''
    if '//' in item[1]:
        filepath = item[1]
    else:
        filepath = 'plugin://%s/?action=%s' % (ADDON_ID, item[1])
    return {
        'label': item[0],
        'file': filepath,
        'icon': item[2],
        'art': {'fanart': 'special://home/addons/%s/fanart.jpg' % ADDON_ID,
                'thumb': 'special://home/addons/%s/icon.png' % ADDON_ID},
        'isFolder': True,
        'type': 'file',
        'IsPlayable': 'false'
    }


def process_method_on_list(method_to_run, items):
    '''helper method that processes a method on each listitem with pooling if the system supports it'''
    all_items = []
    if SUPPORTS_POOL:
        pool = ThreadPool()
        all_items = pool.map(method_to_run, items)
        pool.close()
        pool.join()
    else:
        all_items = [method_to_run(item) for item in items]
    all_items = filter(None, all_items)
    return all_items


def lang(stringid):
    """
    Central string retrieval from strings.po. If not found within PKC,
    standard XBMC/Kodi strings are retrieved.
    Will return unicode
    """
    return (ADDON.getLocalizedString(stringid) or
            xbmc.getLocalizedString(stringid))


def settings(setting, value=None):
    """
    Get or add addon setting. Returns unicode

    setting and value need to be unicode.
    """
    if value is not None:
        ADDON.setSetting(setting.encode('utf-8'), value.encode('utf-8'))
    else:
        return ADDON.getSetting(setting.encode('utf-8')).decode('utf-8')


class Entrypoint(object):
    '''Main entry path for our widget listing. Process the arguments and load
    correct class and module'''

    def __init__(self):
        ''' Initialization '''
        LOG.debug("Initializing Entrypoint")
        self.metadatautils = MetadataUtils()
        self.win = xbmcgui.Window(10000)
        self.addon_widget = xbmcaddon.Addon('script.skin.helper.widgets')
        self.options = self.get_options()
        LOG.debug('options are: %s', self.options)

        if 'section_id' in self.options and 'action' in self.options:
            self.pkc_widgets()
        elif 'section_id' in self.options:
            self.library_listing()
        elif "mediatype" not in self.options or "action" not in self.options:
            # we need both mediatype and action, so show the main listing
            self.mainlisting()
        else:
            # we have a mediatype and action so display the widget listing
            self.show_widget_listing()
        # Shutdown properly
        self.close()
        LOG.debug("Entrypoint exited")

    def show_widget_listing(self):
        '''display the listing for the provided action and mediatype'''
        media_type = self.options["mediatype"]
        action = self.options["action"]
        # set widget content type
        if media_type in ["favourites", "pvr", "media"]:
            xbmcplugin.setContent(int(sys.argv[1]), "files")
        else:
            xbmcplugin.setContent(int(sys.argv[1]), media_type)

        # try to get from cache first...
        all_items = []
        # alter cache_str depending on whether "tag" is available
        if self.options["action"] == "similar":
            # if action is similar, use imdbid
            cache_id = self.options.get("imdbid", "")
            # if similar was called without imdbid, skip cache
            if not cache_id:
                self.options["skipcache"] = "true"
        elif self.options["action"] == "playlist" and self.options["mediatype"] == "media":
            # if action is mixed playlist, use playlist labels
            cache_id = self.options.get("movie_label") + self.options.get("tv_label")
        else:
            # use tag otherwise
            cache_id = self.options.get("tag")
        # set cache_str
        cache_str = "PlexKodiConnect.Widgets.%s.%s.%s.%s.%s" % \
            (media_type,
             action,
             self.options["limit"],
             self.options.get("path"),
             cache_id)
        if not self.win.getProperty("widgetreload2"):
            # at startup we simply accept whatever is in the cache
            cache_checksum = None
        else:
            # we use a checksum based on the reloadparam to make sure we have the most recent data
            cache_checksum = self.options.get("reload", "")
        # only check cache if not "skipcache"
        if not self.options.get("skipcache") == "true":
            cache = self.metadatautils.cache.get(cache_str, checksum=cache_checksum)
            if cache:
                LOG.debug('MEDIATYPE: %s - ACTION: %s - PATH: %s - TAG: %s -- got items from cache - CHECKSUM: %s',
                          media_type, action, self.options.get("path"), self.options.get("tag"), cache_checksum)
                all_items = cache

        # Call the correct method to get the content from json when no cache
        if not all_items:
            LOG.debug('MEDIATYPE: %s - ACTION: %s - PATH: %s - TAG: %s -- no cache, quering kodi api to get items - CHECKSUM: %s',
                      media_type, action, self.options.get("path"), self.options.get("tag"), cache_checksum)

            # dynamically import and load the correct module, class and function
            try:
                media_module = __import__(media_type)
                media_class = getattr(
                    media_module,
                    media_type.capitalize())(ADDON, self.metadatautils, self.options)
                all_items = getattr(media_class, action)()
                del media_class
            except AttributeError:
                log_exception(__name__, "Incorrect widget action or type called")
            except Exception as exc:
                log_exception(__name__, exc)

            # randomize output if requested by skinner or user
            if self.options.get("randomize", "") == "true":
                all_items = sorted(all_items, key=lambda k: random.random())

            # prepare listitems and store in cache
            all_items = process_method_on_list(self.metadatautils.kodidb.prepare_listitem, all_items)
            self.metadatautils.cache.set(cache_str, all_items, checksum=cache_checksum)

        # fill that listing...
        xbmcplugin.addSortMethod(int(sys.sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED)
        all_items = process_method_on_list(self.metadatautils.kodidb.create_listitem, all_items)
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), all_items, len(all_items))

        # end directory listing
        xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))

    def get_options(self):
        '''get the options provided to the plugin path'''

        options = dict(urlparse.parse_qsl(sys.argv[2].replace('?', '').lower().decode("utf-8")))

        # set the widget settings as options
        options["hide_watched"] = self.addon_widget.getSetting("hide_watched") == "true"
        if self.addon_widget.getSetting("hide_watched_recent") == "true" and "recent" in options.get("action", ""):
            options["hide_watched"] = True
        # options["num_recent_similar"] = int(self.addon_widget.getSetting("num_recent_similar"))
        options["exp_recommended"] = self.addon_widget.getSetting("exp_recommended") == "true"
        options["hide_watched_similar"] = self.addon_widget.getSetting("hide_watched_similar") == "true"
        options["next_inprogress_only"] = self.addon_widget.getSetting("nextup_inprogressonly") == "true"
        options["episodes_enable_specials"] = self.addon_widget.getSetting("episodes_enable_specials") == "true"
        options["group_episodes"] = self.addon_widget.getSetting("episodes_grouping") == "true"
        if "limit" in options:
            options["limit"] = int(options["limit"])
        else:
            options["limit"] = int(self.addon_widget.getSetting("default_limit"))

        if "mediatype" not in options and "action" in options:
            # get the mediatype and action from the path (for backwards compatability with old style paths)
            for item in [
                    ("movies", "movies"),
                    ("shows", "tvshows"),
                    ("episode", "episodes"),
                    ("musicvideos", "musicvideos"),
                    ("pvr", "pvr"),
                    ("albums", "albums"),
                    ("songs", "songs"),
                    ("artists", "artists"),
                    ("media", "media"),
                    ("favourites", "favourites"),
                    ("favorites", "favourites")]:
                if item[0] in options["action"]:
                    options["mediatype"] = item[1]
                    options["action"] = options["action"].replace(item[1], "").replace(item[0], "")
                    break

        # prefer reload param for the mediatype
        if "mediatype" in options:
            alt_reload = self.win.getProperty("widgetreload-%s" % options["mediatype"])
            if options["mediatype"] == "favourites" or "favourite" in options["action"]:
                options["skipcache"] = "true"
            elif alt_reload:
                options["reload"] = alt_reload
            if not options.get("action") and options["mediatype"] == "favourites":
                options["action"] = "favourites"
            elif not options.get("action"):
                options["action"] = "listing"
            if "listing" in options["action"]:
                options["skipcache"] = "true"
            if options["action"] == "browsegenres" and options["mediatype"] == "randommovies":
                options["mediatype"] = "movies"
                options["random"] = True
            elif options["action"] == "browsegenres" and options["mediatype"] == "randomtvshows":
                options["mediatype"] = "tvshows"
                options["random"] = True

        return options

    def close(self):
        '''Cleanup Kodi Cpython instances'''
        self.metadatautils.close()
        del self.addon_widget

    def library_listing(self):
        '''main listing'''
        all_items = []
        xbmcplugin.setContent(int(sys.argv[1]), "files")
        node_str = 'Plex.nodes.%s' % self.options.get('section_id')
        for i in range(1, 15):
            win_path = '%s.%s' % (node_str, i)
            path = self.win.getProperty('%s.path' % win_path)
            LOG.debug('Testing: %s, %s', '%s.path' % win_path, path)
            if not path:
                continue
            label = self.win.getProperty('%s.title' % win_path)
            node_type = self.win.getProperty('%s.type' % win_path)
            LOG.debug('Plex.nodes.path: %s', path)
            LOG.debug('Plex.nodes.title: %s', label)
            LOG.debug('Plex.nodes.type: %s', node_type)
            if (node_type == 'photos' and
                    xbmc.getCondVisibility("Library.HasContent(images)")):
                all_items.append((label, path, 'DefaultPicture.png'))
            elif (node_type == 'albums' and
                  xbmc.getCondVisibility("Library.HasContent(music)")):
                all_items.append((label, path, 'DefaultMusicSongs.png'))
            elif (node_type in ('movies', 'homevideos', 'musicvideos') and
                  xbmc.getCondVisibility("Library.HasContent(movies)")):
                all_items.append((label, path, 'DefaultMovies.png'))
            elif (node_type == 'tvshows' and
                  xbmc.getCondVisibility("Library.HasContent(tvshows)")):
                all_items.append((label, path, 'DefaultTvShows.png'))

        LOG.debug('all_items: %s', all_items)
        # process the listitems and display listing
        all_items = process_method_on_list(create_main_entry, all_items)
        all_items = process_method_on_list(self.metadatautils.kodidb.prepare_listitem, all_items)
        all_items = process_method_on_list(self.metadatautils.kodidb.create_listitem, all_items)
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), all_items, len(all_items))
        xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))

    def mainlisting(self):
        '''main listing'''
        all_items = []
        xbmcplugin.setContent(int(sys.argv[1]), "files")

        plexprops = self.win.getProperty('Plex.nodes.total')
        if plexprops:
            totalnodes = int(plexprops)
            for i in range(totalnodes):
                path = self.win.getProperty('Plex.nodes.%s.index' % i)
                if not path:
                    path = self.win.getProperty('Plex.nodes.%s.content' % i)
                    if not path:
                        continue
                node_type = self.win.getProperty('Plex.nodes.%s.type' % i)
                label = self.win.getProperty('Plex.nodes.%s.title' % i)
                # because we do not use seperate entrypoints for each content type,
                # we need to figure out which items to show in each listing. for
                # now we just only show picture nodes in the picture library video
                # nodes in the video library and all nodes in any other window
                if (node_type == 'photos' and
                        xbmc.getCondVisibility("Library.HasContent(images)")):
                    all_items.append((label, path, 'DefaultPicture.png'))
                elif (node_type == 'albums' and
                      xbmc.getCondVisibility("Library.HasContent(music)")):
                    all_items.append((label, path, 'DefaultMusicSongs.png'))
                elif (node_type in ('movies', 'homevideos', 'musicvideos') and
                      xbmc.getCondVisibility("Library.HasContent(movies)")):
                    all_items.append((label, path, 'DefaultMovies.png'))
                elif (node_type == 'tvshows' and
                      xbmc.getCondVisibility("Library.HasContent(tvshows)")):
                    all_items.append((label, path, 'DefaultTvShows.png'))

        # Playlists
        if xbmc.getCondVisibility(
                'Library.HasContent(movies) | Library.HasContent(tvshows) | Library.HasContent(music)'):
            all_items.append((lang(136),
                              'plugin://%s?mode=playlists' % ADDON_ID,
                              'DefaultPlaylist.png'))
        # Plex Hub
        all_items.append(('Plex Hub',
                          'plugin://%s?mode=hub' % ADDON_ID,
                          'DefaultVideo.png'))
        # Plex Watch later
        if xbmc.getCondVisibility(
                'Library.HasContent(movies) | Library.HasContent(tvshows)'):
            all_items.append((lang(39211),
                              "plugin://%s?mode=watchlater" % ADDON_ID,
                              'DefaultVideo.png'))
        # Plex Channels
        all_items.append((lang(30173),
                          "plugin://%s?mode=channels" % ADDON_ID,
                          'DefaultAddonAlbumInfo.png'))
        # Plex user switch
        all_items.append(('%s%s' % (lang(39200), settings('username')),
                          "plugin://%s?mode=switchuser" % ADDON_ID,
                          'DefaultAddonAlbumInfo.png'))

        # some extra entries for settings and stuff
        all_items.append((lang(39201),
                          "plugin://%s?mode=settings" % ADDON_ID,
                          'DefaultAddonAlbumInfo.png'))
        all_items.append((lang(39204),
                          "plugin://%s?mode=manualsync" % ADDON_ID,
                          'DefaultAddonAlbumInfo.png'))
        LOG.debug('all_items: %s', all_items)
        # process the listitems and display listing
        all_items = process_method_on_list(create_main_entry, all_items)
        all_items = process_method_on_list(self.metadatautils.kodidb.prepare_listitem, all_items)
        all_items = process_method_on_list(self.metadatautils.kodidb.create_listitem, all_items)
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), all_items, len(all_items))
        xbmcplugin.endOfDirectory(handle=int(sys.argv[1]))
