"""Abstract detector interface. Replace only the detector when a new source is ready."""
from abc import ABC, abstractmethod

from ..risk.engine import Measurements


class Detector(ABC):
    @abstractmethod
    def read(self, frame=None):
        """Return Measurements from a frame and/or a sensor source."""
