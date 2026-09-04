"""google-maps-reviews-scraper — public API."""
from .scraper import scrape
from .storage import Store
from .parser import parse_batch
from .dashboard import generate as generate_dashboard

__all__ = ["scrape", "Store", "parse_batch", "generate_dashboard"]
__version__ = "0.2.0"
