from plexapi.myplex import PlexServer
from plexapi.exceptions import Unauthorized
from prometheus_client.core import Gauge, Info
from prometheus_client import start_http_server
from requests.exceptions import ConnectionError
from datetime import datetime
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

    __version__ = "v3.0.0"

    FAST_INTERVAL = 15
    SLOW_INTERVAL = 300

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

        last_slow_run = 0

        while True:
            self.collector._collect_clients()

            now = time.time()
            if now - last_slow_run >= self.SLOW_INTERVAL:
                try:
                    self.collector._collect_base()
                    self.collector._collect_libraries_genres()
                    self.collector._collect_total_played()
                except Exception as e:
                    logging.warning(f"Failed to run slow-tier collectors: {e}")
                last_slow_run = now

            time.sleep(self.FAST_INTERVAL)


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
        self.plex_session_metric = Gauge(
            "plex_sessions_total",
            "Total number of current sessions",
            labelnames=[
                "session_id",
                "session_type",
                "username",
                "title",
                "player",
                "state",
                "location",
                "server",
            ],
        )
        self.plex_total_played_duration_metric = Gauge(
            "plex_total_played_duration",
            "Total number of media played in milliseconds",
            labelnames=["server", "user"],
        )

        self._user_totals = {}
        self._last_history_check = None
        self._cached_users = {}

    def _collect_base(self):
        self.plex_base_metric.info(
            {
                "version": f"{self.plex.version}",
                "name": f"{self.plex.friendlyName}",
                "platform": f"{self.plex.platform}",
                "platform_version": f"{self.plex.platformVersion}",
                "my_plex_subscription": f"{self.plex.myPlexSubscription}",
            }
        )

    def _collect_clients(self):
        sessions = self.plex.sessions()
        self.plex_session_metric.clear()

        unique_clients = set()

        try:
            if sessions:
                for session in sessions:
                    if type(session).__name__ == "EpisodeSession":
                        title = f"{session.grandparentTitle} - {session.title}"
                    else:
                        title = session.title

                    if session.transcodeSessions:
                        session_type = "transcode"
                    else:
                        session_type = "direct"

                    session_key = str(session.sessionKey)
                    username = session.usernames[0]
                    client = session.player

                    self.plex_session_metric.labels(
                        session_key,
                        session_type,
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

    def _collect_libraries_genres(self):
        libraries = self.plex.library.sections()

        try:
            for section in libraries:
                if section.TYPE == "show":
                    episodes_total_size = self._get_episode_count(section)

                    self.plex_library_size_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalStorage)

                    self.plex_library_items_metric.labels(
                        section.title, self.plex.friendlyName, section.type
                    ).set(section.totalSize)

                    self.plex_library_items_metric.labels(
                        "Episodes", self.plex.friendlyName, "episode"
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

    def _get_episode_count(self, section):
        try:
            key = (
                f"/library/sections/{section.key}/all"
                "?type=4&X-Plex-Container-Start=0&X-Plex-Container-Size=0"
            )
            data = self.plex.query(key)
            return int(data.attrib.get("totalSize", data.attrib.get("size", 0)))
        except Exception as e:
            logging.warning(
                f"Failed to fetch lightweight episode count for '{section.title}', "
                f"falling back to full episode fetch: {e}"
            )
            return len(section.searchEpisodes())

    def _collect_total_played(self):
        self._cached_users = self._get_users()
        users_dict = self._cached_users

        if self._last_history_check is None:
            history = self.plex.history()
        else:
            history = self.plex.history(mindate=self._last_history_check)

        self._last_history_check = datetime.now()

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
                        self._user_totals.setdefault(username, 0)
                        self._user_totals[username] += media.duration
                    else:
                        logging.warning(f"User with ID {user_id} not found.")

            except Exception as e:
                logging.warning(f"Failed to scrape plex_total_played_duration_metric: {e}")

        for user, duration in self._user_totals.items():
            self.plex_total_played_duration_metric.labels(
                self.plex.friendlyName, user
            ).set(float(duration))

    def _get_users(self):
        users = self.plex.systemAccounts()
        user_list = {}
        for user in users:
            if user.name:
                user_list[user.id] = user.name
        return user_list