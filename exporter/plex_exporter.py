from plexapi.myplex import PlexServer
from plexapi.exceptions import Unauthorized
from prometheus_client.core import Gauge, Info
from prometheus_client import start_http_server
from requests.exceptions import ConnectionError
from collections import Counter
import time
import logging


class PlexExporter:
    """
    Collect specific PMS related metrics and returns them as a Prometheus metric.

    Parameters:
              server (str): Plex Media Server base URL (default http://localhost:32400).
              token (str): Plex token.
              port (int): Prometheus exporter port (default 9922).

    Attributes:
            port (int): 'The port in which the prometheus server is exposed on.'
            server (str): The base URL of the PMS.
            token (str): The relevant Plex token.
    """

    __version__ = "v1.5.0"

    def __init__(self, token, server, port):
        self.token = token
        self.server = server
        self.port = port
        self._initialize()

    def _initialize(self):
        try:
            self.plex = PlexServer(baseurl=self.server, token=self.token, timeout=5)
            self.collector = PlexCollector(self.token, self.server)
            logging.info(f"** Plex Media Server Exporter {self.__version__} **")
            logging.info(f"successfully connected to {self.plex.friendlyName}")
        except Unauthorized:
            logging.error("Plex token is not valid")
            exit(1)
        except ConnectionError:
            logging.error(f"failed to initialise. PMS '{self.server}' is unreachable")
            exit(1)
        except Exception as e:
            logging.error(f"failed to initialise PMS connection: {e}")
            exit(1)

    def run_collector(self):
        start_http_server(port=int(self.port))
        logging.info(f"serving metrics on port: {self.port}")

        while True:
            self.collector._collect_base()
            self.collector._collect_libraries_genres()
            self.collector._collect_clients()
            self.collector._collect_total_played()
            self.collector._collect_qualities()
            time.sleep(15)


class PlexCollector:
    def __init__(self, token, server) -> None:
        super().__init__()
        self.plex = PlexServer(server, token)

        self.plex_client_metric = Gauge(
            "plex_clients_total",
            "Plex client information",
            labelnames=["platform", "product", "player"],
        )
        self.plex_base_metric = Info("plex", "General Plex information")
        self.plex_library_size_metric = Gauge(
            "plex_library_size_total",
            "Total size of a library in bytes",
            labelnames=["name", "server", "type"],
        )
        self.plex_library_items_metric = Gauge(
            "plex_library_items_total",
            "Total items in a library",
            labelnames=["name", "server", "type"],
        )
        self.plex_genres_metric = Gauge(
            "plex_genres_total",
            "Total genres for all media items",
            labelnames=["genre", "server"],
        )
        self.plex_session_metric = Gauge(
            "plex_sessions_total",
            "Total number of current sessions",
            labelnames=[
                "session_id",
                "username",
                "title",
                "player",
                "state",
                "location",
                "server",
            ],
        )
        self.plex_media_quality_metric = Gauge(
            "plex_media_quality_total",
            "Total number of media by quality",
            labelnames=["type", "quality", "server"],
        )
        self.plex_total_played_duration_metric = Gauge(
            "plex_total_played_duration",
            "Total number of media played in milliseconds",
            labelnames=["server", "user"],
        )

    def _collect_base(self):
        self.plex_base_metric.info(
            {
                "version": f"{self.plex.version}",
                "name": f"{self.plex.friendlyName}",
                "host_platform": f"{self.plex.platform}",
                "plexpass_subscription": f"{self.plex.myPlexSubscription}",
            }
        )

    def _collect_clients(self):
        sessions = self.plex.sessions()
        self.plex_session_metric.clear()

        unique_clients = set()

        try:
            for session in sessions:
                if type(session).__name__ == "EpisodeSession":
                    title = f"{session.grandparentTitle} - {session.title}"
                else:
                    title = session.title

                session_key = str(session.sessionKey)
                username = session.usernames[0]
                client = session.player

                self.plex_session_metric.labels(
                    session_key,
                    username,
                    title,
                    session.player.product,
                    session.player.state,
                    session.sessions[0].location,
                    self.plex.friendlyName,
                ).set(1.0)

                if client.machineIdentifier not in unique_clients:
                    self.plex_client_metric.labels(
                        client.device, client.product, client.platform
                    ).set(1.0)

                    unique_clients.add(client.machineIdentifier)
        except Exception as e:
            logging.warning(f"Failed to scrape plex_clients_metric: {e}")

    def _collect_qualities(self):
        self.plex_media_quality_metric.clear()

        payload = []
        medias = self.plex.library.sections()
        try:
            for media in medias:
                if media.TYPE == "movie":
                    for movie in self.plex.library.sectionByID(media.key).all():
                        media = movie.media[0] if movie.media else None
                        video_resolution = (
                            media.videoResolution
                            if media.videoResolution
                            else "undefined"
                        )  # Deals with Media not having videoResolution
                        payload.append(
                            {"type": movie.TYPE, "resolution": video_resolution}
                        )
                else:
                    for show in self.plex.library.sectionByID(media.key).all():
                        for episode in show.episodes():
                            media = episode.media[0] if episode.media else None
                            video_resolution = (
                                media.videoResolution
                                if media.videoResolution
                                else "undefined"
                            )  # Deals with Media not having videoResolution
                            payload.append(
                                {"type": episode.TYPE, "resolution": video_resolution}
                            )

                    payload = Counter(
                        (item["type"], item["resolution"]) for item in payload
                    )
                    for quality, count in payload.items():
                        self.plex_media_quality_metric.labels(
                            quality[0], quality[1], self.plex.friendlyName
                        ).set(count)
        except Exception as e:
            logging.warning(f"Failed to scrape plex_media_quality_metric: {e}")

    def _collect_libraries_genres(self):
        libraries = self.plex.library.sections()

        try:
            genres_lists = []
            for section in libraries:
                if section.TYPE == "show" or "movie":
                    media = section.all()
                    for media in media:
                        for genre in media.genres:
                            genres_lists.append(genre.tag)
            genre_count = Counter(genres_lists)
            genres = dict(genre_count)

            for genre, count in genres.items():
                self.plex_genres_metric.labels(genre, self.plex.friendlyName).set(count)

            for section in libraries:
                if section.TYPE == "show":
                    episodes_total_size = len(section.searchEpisodes())

                    self.plex_library_size_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalStorage)

                    self.plex_library_items_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalSize)

                    self.plex_library_items_metric.labels(
                        "Episodes", self.plex.friendlyName, section.type
                    ).set(episodes_total_size)

                else:
                    self.plex_library_size_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalStorage)

                    self.plex_library_items_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalSize)
        except Exception as e:
            logging.warning(
                f"Failed to scrape plex_library_items_metric, plex_library_size_metric: {e}"
            )

    def _collect_total_played(self):
        users_dict = self._get_users()
        total_playtime_by_user = {}
        history = self.plex.history()

        if history:
            try:
                keys = [history_item.key for history_item in history]
                keys_filtered = [x.split("/")[-1] for x in keys]
                search = "/library/metadata/" + ",".join(keys_filtered)
                media_items = self.plex.fetchItems(search)

                for history_item, media in zip(history, media_items):
                    user_id = history_item.accountID
                    username = users_dict.get(user_id)
                    if username:
                        total_playtime_by_user.setdefault(username, 0)
                        total_playtime_by_user[username] += media.duration
                    else:
                        logging.warning(f"User with ID {user_id} not found.")

                for user, duration in total_playtime_by_user.items():
                    self.plex_total_played_duration_metric.labels(
                        self.plex.friendlyName, user
                    ).set(float(duration))

            except Exception as e:
                logging.warning(
                    f"Failed to scrape plex_total_played_duration_metric: {e}"
                )

    def _get_users(self):
        users = self.plex.systemAccounts()
        user_list = {}
        for user in users:
            if user.name:
                user_list[user.id] = user.name
        return user_list