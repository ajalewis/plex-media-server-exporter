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
    Collect specific PMS related metrics and retuns them as a Prometheus metric.

    Parameters:
              server (str): Plex Media Server base URL (default http://localhost:32400).
              token (str): Plex token.
              port (int): Prometheus exporter port (default 9922).

    Attributes:
            port (int): 'The port in which the prometheus server is exposed on.'
            server (str): The base URL of the PMS.
            token (str): The relevant Plex token.
    """

    def __init__(self, token, server, port):
        self.token = token
        self.server = server
        self.port = port
        try:
            self.plex = PlexServer(baseurl=server, token=token)
            self.collector = PlexCollector(self.token, self.server)
        except Unauthorized:
            logging.error("Plex token is not valid")
            exit(1)
        except ConnectionError:
            logging.error(f"PMS '{server}' is unreachable")
            exit(1)
        except Exception as e:
            logging.error(e)
            exit(1)

    def run_collector(self):
        start_http_server(port=int(self.port))
        logging.info(f"serving metrics on port: {self.port}")

        while True:
            self.collector.collect_users()
            self.collector.collect_base()
            self.collector.collect_libraries
            self.collector.collect_clients()
            self.collector.collect_history()
            self.collector.collect_qualities()
            time.sleep(1)


class PlexCollector:
    def __init__(self, token, server) -> None:
        super().__init__()
        self.plex = PlexServer(server, token)
        self.plex_user_metric = Gauge(
            "plex_users", "Single user info", labelnames=["username", "id"]
        )
        self.plex_watch_history_metric = Gauge(
            "plex_watch_history_total", "Total watch history", labelnames=["id", "user"]
        )
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
        self.plex_session_metric = Gauge(
            "plex_sessions_total",
            "Total number of current sessions",
            labelnames=["session_id", "username", "title", "player", "state"],
        )
        self.plex_movie_quality = Gauge(
            "plex_movie_quality_total",
            "Total number of Movies by quality",
            labelnames=["quality"],
        )
        self.plex_show_quality = Gauge(
            "plex_show_quality_total",
            "Total number of TV Shows by quality",
            labelnames=["quality"],
        )

    def collect_users(self):
        self.plex_user_metric.clear()

        try:
            users = self.plex.systemAccounts()
            for user in users:
                if user.id:
                    self.plex_user_metric.labels(id=user.id, username=user.name).set(
                        1.0
                    )
        except Exception as e:
            logging.error(e)

    def collect_base(self):
        self.plex_base_metric.info(
            {
                "version": f"{self.plex.version}",
                "name": f"{self.plex.friendlyName}",
                "host_platform": f"{self.plex.platform}",
                "plexpass_subscription": f"{self.plex.myPlexSubscription}",
            }
        )

    def collect_history(self):
        users = self.plex.systemAccounts()
        history = self.plex.history()

        user_list = {}
        for user in users:
            if user.name:
                user_list[user.id] = user.name

        history_count = []
        for item in history:
            user_name = user_list.get(item.accountID, "unknown")
            history_count.append(f"{item.accountID}:{user_name}")

        final_count = Counter(history_count)

        for key, count in final_count.items():
            user_id, user_name = key.split(":")
            self.plex_watch_history_metric.labels(id=user_id, user=user_name).set(count)

    def collect_clients(self):
        sessions = self.plex.sessions()
        self.plex_session_metric.clear()

        unique_clients = set()

        for session in sessions:
            if session.librarySectionTitle == "TV Shows":
                title = session.grandparentTitle
            else:
                title = session.title

            session_key = str(session.sessionKey)
            username = session.usernames[0]
            client = session.player

            self.plex_session_metric.labels(
                session_key,
                username,
                str(f"{title} ({session.year})"),
                session.players[0].platform,
                session.players[0].state,
            ).set(1.0)

            if client.machineIdentifier not in unique_clients:
                self.plex_client_metric.labels(
                    client.device, client.product, client.platform
                ).set(1.0)

                unique_clients.add(client.machineIdentifier)

    def collect_qualities(self):
        self.plex_movie_quality.clear()
        self.plex_show_quality.clear()

        libraries = self.plex.library.sections()
        movies = []
        shows = []
        for library in libraries:
            if library.type in ["movie", "show"]:
                for item in library.all():
                    if item.type == "show":
                        for episode in item.episodes():
                            if episode.media:
                                for media_part in episode.media:
                                    video_resolution = media_part.videoResolution
                                    shows.append(video_resolution)
                    else:
                        if item.media:
                            for media_part in item.media:
                                video_resolution = media_part.videoResolution
                                video_resolution = media_part.videoResolution
                                movies.append(video_resolution)

        count_shows = Counter(shows)
        count_movies = Counter(movies)
        shows = dict(count_shows)
        movies = dict(count_movies)

        for quality, count in movies.items():
            self.plex_movie_quality.labels(quality).set(count)
        for quality, count in shows.items():
            self.plex_show_quality.labels(quality).set(count)

    def collect_libraries(self):
        libraries = self.plex.library.sections()

        for section in libraries:
            if section.TYPE == "show":
                totalSize = len(section.searchEpisodes())

                self.plex_library_size_metric.labels(
                    section.title, self.plex.friendlyName, section.type
                ).set(section.totalStorage)

                self.plex_library_items_metric.labels(
                    section.title, self.plex.friendlyName, section.type
                ).set(totalSize)

            else:
                self.plex_library_size_metric.labels(
                    section.title, self.plex.friendlyName, section.type
                ).set(section.totalStorage)

                self.plex_library_items_metric.labels(
                    section.title, self.plex.friendlyName, section.type
                ).set(section.totalSize)
