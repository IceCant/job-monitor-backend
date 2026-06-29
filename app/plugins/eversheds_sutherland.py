from app.plugins.successfactors import SuccessFactorsPlugin


class EvershedsSutherlandPlugin(SuccessFactorsPlugin):
    plugin_name = "eversheds_sutherland"
    display_name = "Eversheds Sutherland"
    discoverable = True
    enabled = True
    careers_url = "https://esi-vacancies.eversheds-sutherland.com/search/"
    description = "Eversheds Sutherland SuccessFactors careers scraper"
    source_name = "eversheds_sutherland_successfactors_html"
    listing_style = "tiles"
    page_mode = "query"
    page_size = 25
    default_config = {
        "source_url": careers_url,
        "max_pages": 0,
        "safety_max_pages": 20,
        "fetch_detail_pages": False,
        "timeout": 60,
    }
