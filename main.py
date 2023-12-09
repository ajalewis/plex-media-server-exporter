# Plex Media Server Promtheus Exporter
# by alexanderashworthhomelewis@gmail.com

from exporter.exceptions import EnvInvalid
import requests.exceptions
import os
import logging
import argparse
from time import sleep
from exporter.plex_exporter import PlexExporter
from dotenv import load_dotenv

__version__ = "v1.0.0"

logging.basicConfig(
    level="INFO",
    format="[%(levelname)s] %(asctime)s: %(message)s",
    datefmt="%d-%m-%Y %H:%M:%S",
)

if __name__ == "__main__":
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Plex Media Server Prometheus exporter",
        prog="Plex Media Exporter",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-t", "--token", help="Plex token")
    parser.add_argument(
        "-s", "--server", help="Plex server baseurl", default="http://localhost:32400"
    )
    parser.add_argument(
        "-p", "--port", type=int, help="Metrics server port", default=9922
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args()

    token = os.environ.get("PLEX_TOKEN", args.token)
    server = os.environ.get("PLEX_SERVER", args.server)
    port = int(os.environ.get("METRICS_PORT", args.port))

    try:
        if token is None:
            raise EnvInvalid("Plex token has not been defined")

    except EnvInvalid as e:
        logging.error(f"{e}")
        exit(1)
    except TypeError as e:
        logging.error(f"{e}")
        exit(1)
    except ValueError as e:
        logging.error({e})
        exit(1)
    except AttributeError as e:
        pass

    while True:
        try:
            exporter = PlexExporter(token, server, port)
            exporter.run_collector()
            break
        except requests.exceptions.ConnectionError:
            logging.error("connection error. re-trying...")
            sleep(10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(e)
