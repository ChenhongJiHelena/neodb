from catalog.common import *
from catalog.models import *
import logging
import podcastparser
import urllib.request
from django.core.cache import cache
from catalog.podcast.models import PodcastEpisode
from datetime import datetime
from django.utils.timezone import make_aware
import bleach

_logger = logging.getLogger(__name__)


@SiteManager.register
class RSS(AbstractSite):
    SITE_NAME = SiteName.RSS
    ID_TYPE = IdType.RSS
    DEFAULT_MODEL = Podcast
    URL_PATTERNS = [r".+[./](rss|xml)"]

    @staticmethod
    def parse_feed_from_url(url):
        if not url:
            return None
        feed = cache.get(url)
        if feed:
            return feed
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "NeoDB/0.5")
        try:
            feed = podcastparser.parse(url, urllib.request.urlopen(req, timeout=3))
        except:
            return None
        cache.set(url, feed, timeout=300)
        return feed

    @classmethod
    def id_to_url(cls, id_value):
        return f"https://{id_value}"

    @classmethod
    def url_to_id(cls, url: str):
        return url.split("://")[1]

    @classmethod
    def validate_url_fallback(cls, url):
        return cls.parse_feed_from_url(url) is not None

    def scrape(self):
        feed = self.parse_feed_from_url(self.url)
        if not feed:
            return None
        pd = ResourceContent(
            metadata={
                "title": feed["title"],
                "brief": bleach.clean(feed["description"], strip=True),
                "hosts": [feed.get("itunes_author")]
                if feed.get("itunes_author")
                else [],
                "official_site": feed.get("link"),
                "cover_image_url": feed.get("cover_url"),
                "genre": feed.get("itunes_categories", [None])[0],
            }
        )
        pd.lookup_ids[IdType.RSS] = RSS.url_to_id(self.url)
        if pd.metadata["cover_image_url"]:
            imgdl = BasicImageDownloader(
                pd.metadata["cover_image_url"], feed.get("link") or self.url
            )
            try:
                pd.cover_image = imgdl.download().content
                pd.cover_image_extention = imgdl.extention
            except Exception:
                _logger.warn(
                    f'failed to download cover for {self.url} from {pd.metadata["cover_image_url"]}'
                )
        return pd

    def scrape_additional_data(self):
        item = self.get_item()
        feed = self.parse_feed_from_url(self.url)
        if not feed:
            return
        for episode in feed["episodes"]:
            PodcastEpisode.objects.get_or_create(
                program=item,
                guid=episode.get("guid"),
                defaults={
                    "title": episode["title"],
                    "brief": bleach.clean(episode.get("description"), strip=True),
                    "description_html": episode.get("description_html"),
                    "cover_url": episode.get("episode_art_url"),
                    "media_url": episode.get("enclosures")[0].get("url")
                    if episode.get("enclosures")
                    else None,
                    "pub_date": make_aware(
                        datetime.fromtimestamp(episode.get("published"))
                    ),
                    "duration": episode.get("duration"),
                    "link": episode.get("link"),
                },
            )
