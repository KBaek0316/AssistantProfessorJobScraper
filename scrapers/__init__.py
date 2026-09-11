from .base import JobPosting, BaseScraper
from .academickeys import AcademicKeysScraper
from .higheredjobs import HigherEdJobsScraper
from .chronicle import ChronicleScraper
from .linkedin import LinkedInScraper

__all__ = [
    "JobPosting",
    "BaseScraper",
    "AcademicKeysScraper",
    "HigherEdJobsScraper",
    "ChronicleScraper",
    "LinkedInScraper",
]
