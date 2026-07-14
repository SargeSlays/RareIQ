from rareiq.core.storage import storage

storage.initialize()

from rareiq.web.server import run


if __name__ == "__main__":
    run()
