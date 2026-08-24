import cv2

from rareiq.core.storage import storage

# Recognition parallelism is managed at the card-worker level. Letting every
# OpenCV operation create its own thread pool causes severe CPU oversubscription
# during mixed multi-card scans.
cv2.setNumThreads(1)
cv2.setUseOptimized(True)

storage.initialize()

from rareiq.web.server import run


if __name__ == "__main__":
    run()
