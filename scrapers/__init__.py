from .base import JobPosting, BaseScraper
from .academickeys import AcademicKeysScraper
from .higheredjobs import HigherEdJobsScraper
from .chronicle import ChronicleScraper
from .linkedin import LinkedInScraper
from .jobsacuk import JobsAcUkScraper
from .manual import load_manual_jobs

__all__ = [
    "JobPosting",
    "BaseScraper",
    "AcademicKeysScraper",
    "HigherEdJobsScraper",
    "ChronicleScraper",
    "LinkedInScraper",
    "JobsAcUkScraper",
    "load_manual_jobs",
]

